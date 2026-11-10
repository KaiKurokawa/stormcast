"""Интеграционные проверки документов на PostgreSQL."""

from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from documents.models import DocumentEntity, RevisionBuffer, State, StateCache, TemplateEntity, TemplateRevision
from documents.services import commit_revision_buffer, upsert_revision_buffer


class DocumentTests(TestCase):
    """Проверяет триггеры, изоляцию и фиксацию снимков."""

    def setUp(self):
        """Создаёт пользователей и неизменяемый шаблон."""
        self.user = get_user_model().objects.create_user(username="author")
        self.other = get_user_model().objects.create_user(username="other")
        template = TemplateEntity.objects.create(user=self.user)
        self.template = TemplateRevision.objects.create(template_entity=template, user=self.user, code="test", title="Тест", body_html="{{ topic }}", field_schema={}, default_overrides={})
        self.entity = DocumentEntity.objects.create(user=self.user)

    def buffer(self, user=None, **values):
        """Сохраняет личный черновик."""
        return upsert_revision_buffer(entity_id=self.entity.pk, user_id=(user or self.user).pk, values={"template": self.template, "topic": "Тема", "field_overrides": {}, "message_bindings": [], "details": {}, **values})[0]

    def test_initial_state(self):
        """Начальное состояние автоматически попадает в журнал и кэш."""
        state = State.objects.get(entity=self.entity)
        self.assertEqual(state.readiness_stage, "draft")
        self.assertEqual(bytes(state.content_hash), state.calculate_content_hash())
        self.assertEqual(StateCache.objects.get(entity=self.entity).content_hash, state.content_hash)

    def test_commit_and_deduplication(self):
        """Повтор текущего снимка не создаёт ревизию."""
        revision, created = commit_revision_buffer(buffer_id=self.buffer().pk, user_id=self.user.pk)
        self.assertTrue(created)
        self.assertFalse(RevisionBuffer.objects.exists())
        duplicate, created = commit_revision_buffer(buffer_id=self.buffer().pk, user_id=self.user.pk)
        self.assertFalse(created)
        self.assertEqual(duplicate.pk, revision.pk)
        self.assertEqual(StateCache.objects.get(entity=self.entity).revision_id, revision.pk)

    def test_private_buffer_feed(self):
        """Лента не раскрывает черновики другого пользователя."""
        self.buffer(self.other, topic="Секрет")
        item = DocumentEntity.objects.for_user_feed(user_id=self.user.pk).get()
        self.assertFalse(item.has_buffer)
        self.assertEqual(item.display_topic, "")
        self.assertFalse(DocumentEntity.objects.for_user_feed(user_id=self.user.pk, search="Секрет").exists())

    def test_immutable_entity(self):
        """Прямое изменение неизменяемой записи отклоняется базой."""
        with self.assertRaises(DatabaseError), transaction.atomic():
            DocumentEntity.objects.filter(pk=self.entity.pk).update(user=self.other)

    def test_api_permissions(self):
        """API требует вход и скрывает чужой буфер."""
        client = APIClient()
        self.assertIn(client.get("/api/v1/documents/", secure=True).status_code, (401, 403))
        buffer = self.buffer(self.other)
        client.force_authenticate(self.user)
        self.assertEqual(client.get(f"/api/v1/document-buffers/{buffer.pk}/", secure=True).status_code, 404)
        self.assertEqual(client.patch(f"/api/v1/documents/{self.entity.pk}/", {}, secure=True).status_code, 405)

    def test_nullable_buffer_value_has_priority(self):
        """NULL личного буфера не заменяется значением архивной ревизии."""
        commit_revision_buffer(buffer_id=self.buffer(out_number="123").pk, user_id=self.user.pk)
        self.buffer(out_number=None)
        item = DocumentEntity.objects.for_user_detail(entity_id=self.entity.pk, user_id=self.user.pk).get()
        self.assertIsNone(item.display_out_number)
        self.assertTrue(item.has_buffer)

    def test_cross_entity_revision_rejected(self):
        """Триггер запрещает состояние с ревизией другого документа."""
        revision, _ = commit_revision_buffer(buffer_id=self.buffer().pk, user_id=self.user.pk)
        other_entity = DocumentEntity.objects.create(user=self.user)
        with self.assertRaises(DatabaseError), transaction.atomic():
            State.objects.create(entity=other_entity, revision=revision, user=self.user)

    def test_buffer_identity_rejected(self):
        """Прямое изменение владельца буфера отклоняется PostgreSQL."""
        buffer = self.buffer()
        with self.assertRaises(DatabaseError), transaction.atomic():
            RevisionBuffer.objects.filter(pk=buffer.pk).update(user=self.other)

    def test_message_bindings_array_constraint(self):
        """Привязки сообщений должны оставаться JSON-массивом."""
        buffer = self.buffer()
        with self.assertRaises(DatabaseError), transaction.atomic():
            RevisionBuffer.objects.filter(pk=buffer.pk).update(message_bindings={})

    def test_buffer_api_create_update_commit(self):
        """API создаёт, изменяет и фиксирует личный буфер."""
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.post("/api/v1/document-buffers/", {"entity": str(self.entity.pk), "template": str(self.template.pk), "topic": "API"}, secure=True)
        self.assertEqual(response.status_code, 201, response.data)
        identifier = response.data["id"]
        response = client.patch(f"/api/v1/document-buffers/{identifier}/", {"topic": "Изменено"}, secure=True)
        self.assertEqual(response.status_code, 200, response.data)
        response = client.post(f"/api/v1/document-buffers/{identifier}/commit/", {}, secure=True)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["topic"], "Изменено")
        self.assertEqual(client.get("/api/v1/documents/", secure=True).status_code, 200)
        self.assertEqual(client.get(f"/api/v1/documents/{self.entity.pk}/", secure=True).status_code, 200)

    def test_template_api_default_payload(self):
        """Новая версия шаблона получает JSON по умолчанию и вычисленный хеш."""
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.post("/api/v1/document-template-revisions/", {"template_entity": str(self.template.template_entity_id), "code": "new", "title": "Новый", "body_html": "Текст"}, secure=True)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data["content_hash"]), 64)
        self.assertEqual(response.data["user"], self.user.pk)

    def test_admin_immutable_permissions(self):
        """Администратор может просматривать историю, но не менять её."""
        from django.contrib import admin
        from django.test import RequestFactory
        request = RequestFactory().get("/admin/")
        request.user = self.user
        configuration = admin.site._registry[DocumentEntity]
        self.assertFalse(configuration.has_change_permission(request, self.entity))
        self.assertFalse(configuration.has_delete_permission(request, self.entity))
        self.user.is_superuser = True
        self.assertTrue(configuration.has_add_permission(request))

    def test_state_flags_survive_commit(self):
        """Фиксация сохраняет архивность и сбрасывает готовность в draft."""
        from documents.services import record_state_change
        record_state_change(entity_id=self.entity.pk, user_id=self.user.pk, readiness_stage="approved", is_archived=True)
        commit_revision_buffer(buffer_id=self.buffer().pk, user_id=self.user.pk)
        state = StateCache.objects.get(entity=self.entity)
        self.assertTrue(state.is_archived)
        self.assertEqual(state.readiness_stage, "draft")

    def test_messages_service_regression(self):
        """Существующий сервис сообщений продолжает фиксировать ревизии."""
        from messages.models import MessageEntity, RevisionBuffer as MessageBuffer
        from messages.services import commit_revision_buffer as commit_message
        entity = MessageEntity.objects.create(user=self.user)
        buffer = MessageBuffer.objects.create(entity=entity, user=self.user, type="warning", period=None, region=None, text="Предупреждение", note=None, details={})
        revision, created = commit_message(buffer_id=buffer.pk, user_id=self.user.pk)
        self.assertTrue(created)
        self.assertEqual(revision.text, "Предупреждение")

    def test_database_metadata(self):
        """Установлены ENUM, все прикладные триггеры и действия удаления FK."""
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='documents' AND NOT t.tgisinternal")
            self.assertEqual(cursor.fetchone()[0], 12)
            cursor.execute("SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='documents' ORDER BY enumsortorder")
            self.assertEqual([row[0] for row in cursor.fetchall()], ["draft", "review", "approved"])
            cursor.execute("SELECT a.attname, c.confdeltype FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1] WHERE n.nspname='documents' AND c.contype='f'")
            actions = {"entity_id": "c", "template_entity_id": "c", "parent_id": "n", "template_id": "r", "revision_id": "r", "user_id": "a"}
            for column, action in cursor.fetchall():
                self.assertEqual(action, actions[column])

    def test_admin_create_entity(self):
        """Администратор создаёт документ с выбранным автором, как в messages."""
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        response = self.client.post(
            "/admin/stormcast_documents/documententity/add/",
            {"user": self.other.pk, "_save": "Сохранить"},
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        entity = DocumentEntity.objects.get(user=self.other)
        self.assertEqual(StateCache.objects.get(entity=entity).readiness_stage, "draft")

    def test_admin_commit_selected_buffers(self):
        """Действие Admin фиксирует выбранные буферы с сохранением их авторов."""
        from django.contrib import admin
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        buffer = self.buffer(self.other)
        request = RequestFactory().post("/admin/")
        request.user = self.user
        request.session = {}
        request._messages = FallbackStorage(request)
        configuration = admin.site._registry[RevisionBuffer]
        configuration.commit_selected_buffers(request, RevisionBuffer.objects.filter(pk=buffer.pk))
        self.assertFalse(RevisionBuffer.objects.filter(pk=buffer.pk).exists())
        self.assertEqual(self.entity.revisions.get().user_id, self.other.pk)
