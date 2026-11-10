"""Проверки соответствия административных операций правилам сообщений."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase

from documents.models import (
    DocumentEntity, Revision, RevisionBuffer, State, StateCache,
    TemplateEntity, TemplateRevision,
)
from messages.models import (
    MessageEntity, Revision as MessageRevision,
    RevisionBuffer as MessageBuffer, State as MessageState,
    StateCache as MessageStateCache,
)


class AdminPermissionsTests(SimpleTestCase):
    """Сравнивает права и защищённые поля двух административных интерфейсов."""

    def setUp(self):
        """Готовит запрос администратора без обращения к базе."""
        self.request = RequestFactory().get("/admin/")
        self.request.user = get_user_model()(is_active=True, is_staff=True, is_superuser=True)

    def test_permissions_match_messages(self):
        """Разрешённые операции для общих сущностей совпадают с messages."""
        for document_model, message_model in (
            (DocumentEntity, MessageEntity), (Revision, MessageRevision),
            (RevisionBuffer, MessageBuffer), (State, MessageState),
            (StateCache, MessageStateCache),
        ):
            with self.subTest(model=document_model.__name__):
                document_admin = admin.site._registry[document_model]
                message_admin = admin.site._registry[message_model]
                for permission in ("add", "view", "change", "delete"):
                    method = f"has_{permission}_permission"
                    self.assertEqual(
                        getattr(document_admin, method)(self.request),
                        getattr(message_admin, method)(self.request),
                    )

    def test_append_only_fields(self):
        """Новые записи принимают данные, существующие полностью защищены."""
        for model in (DocumentEntity, Revision, State, TemplateEntity, TemplateRevision):
            with self.subTest(model=model.__name__):
                configuration = admin.site._registry[model]
                self.assertTrue(configuration.has_add_permission(self.request))
                expected = {"id", "created_at"}
                if model in (Revision, State, TemplateRevision):
                    expected.add("content_hash")
                self.assertEqual(set(configuration.get_readonly_fields(self.request)), expected)
                self.assertEqual(
                    set(configuration.get_readonly_fields(self.request, model())),
                    {field.name for field in model._meta.fields},
                )

    def test_buffer_fields_and_actions_match_messages(self):
        """Автор задаётся при создании, ключи защищены после сохранения."""
        configuration = admin.site._registry[RevisionBuffer]
        reference = admin.site._registry[MessageBuffer]
        self.assertEqual(
            configuration.get_readonly_fields(self.request),
            reference.get_readonly_fields(self.request),
        )
        self.assertEqual(
            configuration.get_readonly_fields(self.request, RevisionBuffer()),
            reference.get_readonly_fields(self.request, MessageBuffer()),
        )
        self.assertIn("commit_selected_buffers", configuration.get_actions(self.request))
