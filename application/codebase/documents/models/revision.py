"""
Архив ревизий документов: documents.revisions.

Хранит историю зафиксированных версий документов. Каждая ревизия
представляет неизменяемый снимок содержимого документа на момент фиксации.

PostgreSQL отвечает за генерацию идентификаторов и временных меток,
внешние ключи, ограничения целостности и защиту записей от изменения
и удаления.

Django описывает поля, связи, ограничения, индексы и метаданные модели.
Комментарии индексов и ограничений, внешние ключи и триггер неизменяемости
устанавливаются отдельными SQL-миграциями.
"""

from django.conf import settings
from django.db import models
from django.db.models.expressions import RawSQL

from documents.hashing import document_revision_content_hash

from .common import (
    ContentHashModel,
    PostgreSQLGinIndex,
    PostgreSQLIndex,
    content_hash_length_constraint,
    message_bindings_is_array_constraint,
    parent_not_self_constraint,
)


class Revision(ContentHashModel):
    """
    Архив зафиксированных ревизий документа.

    Ревизия хранит снимок исходящего номера, темы, значений реквизитов,
    привязок сообщений, комментария и дополнительных параметров документа.

    Связь entity указывает на документ, к которому относится ревизия.
    Связь parent указывает на исходный документ, который корректируется
    или отменяется данной ревизией.
    Связь template определяет ревизию шаблона печатной формы.
    Связь user определяет автора ревизии.

    Записи создаются как новые версии, а сохранённые ревизии нельзя
    изменять или удалять. Неизменяемость обеспечивается триггером PostgreSQL.
    """

    id = models.UUIDField(
        primary_key=True,
        editable=False,

        db_default=RawSQL(
            "uuid_generate_v7()",
            [],
            output_field=models.UUIDField(),
        ),

        db_comment="Уникальный идентификатор ревизии.",
        verbose_name="Идентификатор ревизии",
    )

    entity = models.ForeignKey(
        "stormcast_documents.DocumentEntity",
        on_delete=models.CASCADE,
        db_column="entity_id",
        db_index=False,
        null=False,
        related_name="revisions",

        db_comment="Идентификатор документа.",
        verbose_name="Документ",
    )

    parent = models.ForeignKey(
        "stormcast_documents.DocumentEntity",
        on_delete=models.SET_NULL,
        db_column="parent_id",
        db_index=False,
        null=True,
        blank=True,
        related_name="revision_children",

        db_comment=(
            "Идентификатор исходного документа для корректировки или отмены."
        ),

        verbose_name="Родительский документ",
    )

    template = models.ForeignKey(
        "stormcast_documents.TemplateRevision",
        on_delete=models.RESTRICT,
        db_column="template_id",
        db_index=False,
        null=False,
        related_name="document_revisions",

        db_comment="Идентификатор ревизии шаблона печатной формы.",
        verbose_name="Ревизия шаблона",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        db_column="user_id",
        db_index=False,
        null=False,
        related_name="document_revisions",

        db_comment=(
            "Идентификатор пользователя, зафиксировавшего ревизию."
        ),

        verbose_name="Автор ревизии",
    )

    out_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,

        db_comment="Исходящий номер документа.",
        verbose_name="Исходящий номер",
    )

    topic = models.CharField(
        max_length=150,
        null=False,

        db_comment="Тема документа.",
        verbose_name="Тема",
    )

    field_overrides = models.JSONField(
        default=dict,
        null=False,

        db_default=RawSQL(
            "'{}'::jsonb",
            [],
            output_field=models.JSONField(),
        ),

        db_comment=(
            "Значения реквизитов документа на момент фиксации ревизии."
        ),

        verbose_name="Значения реквизитов",
    )

    message_bindings = models.JSONField(
        default=list,
        null=False,

        db_default=RawSQL(
            "'[]'::jsonb",
            [],
            output_field=models.JSONField(),
        ),

        db_comment=(
            "Зафиксированные привязки сообщений к слотам шаблона. "
            "Хранится как массив объектов "
            "{slot_code, message_entity_id, message_revision_id}. "
            "message_entity_id используется для обратного поиска, "
            "message_revision_id — для точной фиксации снимка сообщения."
        ),

        verbose_name="Привязки сообщений",
    )

    note = models.CharField(
        max_length=255,
        null=True,
        blank=True,

        db_comment="Комментарий к ревизии.",
        verbose_name="Комментарий",
    )

    content_hash = models.BinaryField(
        null=False,

        db_comment=(
            "Контент-хэш снимка документа (BLAKE3). Вычисляется от "
            "канонической полезной нагрузки: template_id, out_number, topic, "
            "field_overrides, значимой части message_bindings "
            "(slot_code, message_revision_id), note/details, если они значимы. "
            "Не включает технические поля: id, entity_id, user_id, "
            "created_at, сам хэш."
        ),

        verbose_name="Контент-хэш",
    )

    details = models.JSONField(
        default=dict,
        null=False,

        db_default=RawSQL(
            "'{}'::jsonb",
            [],
            output_field=models.JSONField(),
        ),

        db_comment="Дополнительные параметры документа в формате JSONB.",
        verbose_name="Детали",
    )

    created_at = models.DateTimeField(
        null=False,
        editable=False,

        db_default=RawSQL(
            "CURRENT_TIMESTAMP",
            [],
            output_field=models.DateTimeField(),
        ),

        db_comment="Дата и время создания ревизии.",
        verbose_name="Дата и время создания",
    )

    class Meta:
        """Описание полей и поведения записи."""
        managed = True
        db_table = '"documents"."revisions"'

        db_table_comment = (
            "История зафиксированных версий документов."
        )

        verbose_name = "Ревизия документа"
        verbose_name_plural = "Ревизии документов"

        constraints = [

            content_hash_length_constraint(
                name="check_documents_revisions_content_hash_length",

                violation_error_message=(
                    "Проверяет, что хеш содержимого документа "
                    "(BLAKE3) имеет длину 32 байта."
                ),
            ),

            parent_not_self_constraint(
                name="check_documents_revisions_parent_not_self",

                violation_error_message=(
                    "Запрещает самопривязку, когда документ "
                    "ссылается сам на себя."
                ),
            ),

            message_bindings_is_array_constraint(
                name="check_documents_revisions_message_bindings_is_array",

                violation_error_message=(
                    "Проверяет, что привязки сообщений хранятся "
                    "в виде JSON-массива."
                ),
            ),
        ]

        indexes = [

            # Оптимизирует получение последней ревизии документа.
            PostgreSQLIndex(
                fields=["entity", "-created_at", "-id"],
                name="index_documents_revisions_entity_time",
            ),

            # Ускоряет поиск документов, связанных с корректировками и отменами.
            PostgreSQLIndex(
                fields=["parent"],
                name="index_documents_revisions_parent_id",
            ),

            # Ускоряет фильтрацию документов по шаблону.
            PostgreSQLIndex(
                fields=["template"],
                name="index_documents_revisions_template_id",
            ),

            # Ускоряет выборку ревизий документов по автору.
            PostgreSQLIndex(
                fields=["user"],
                name="index_documents_revisions_user_id",
            ),

            # Оптимизирует сортировку ревизий документов по времени создания.
            PostgreSQLIndex(
                fields=["-created_at"],
                name="index_documents_revisions_created_at",
            ),

            # Ускоряет поиск по исходящему номеру документа.
            PostgreSQLIndex(
                fields=["out_number"],
                condition=models.Q(out_number__isnull=False),
                name="index_documents_revisions_out_number",
            ),

            # Ускоряет поиск по теме документа.
            PostgreSQLGinIndex(
                fields=["topic"],
                name="index_documents_revisions_topic_trigram",
                opclasses=["gin_trgm_ops"],
            ),

            # Ускоряет поиск по реквизитам документа в JSONB.
            PostgreSQLGinIndex(
                fields=["field_overrides"],
                name="index_documents_revisions_field_overrides",
                opclasses=["jsonb_path_ops"],
            ),

            # Ускоряет поиск документов по использованным ревизиям и идентификаторам сообщений внутри привязок.
            PostgreSQLGinIndex(
                fields=["message_bindings"],
                name="index_documents_revisions_message_bindings",
                opclasses=["jsonb_path_ops"],
            ),
        ]

    def calculate_content_hash(self):
        """Вычисляет хеш полезной нагрузки снимка."""
        return document_revision_content_hash(
            template_id=self.template_id,
            out_number=self.out_number,
            topic=self.topic,
            field_overrides=self.field_overrides,
            message_bindings=self.message_bindings,
            note=self.note,
            details=self.details,
        )

    def __str__(self) -> str:
        """
        Возвращает строковое представление ревизии документа.
        """

        return (
            f"Ревизия {self.pk} "
            f"для документа {self.entity_id}"
        )
