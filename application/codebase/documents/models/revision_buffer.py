"""
Буфер правок документов: documents.revision_buffer.

Хранит текущие несохраненные изменения документов. Каждый пользователь
располагает собственным буфером для каждого документа.

Технический первичный ключ используется для совместимости с Django ORM,
Django Admin и инструментами, работающими с одиночным первичным ключом.
Доменная уникальность сохраняется ограничением UNIQUE по паре
(entity_id, user_id).

PostgreSQL отвечает за генерацию идентификаторов, значения по умолчанию,
целостность связей и ограничений, обновление временной метки и защиту
идентичности буфера триггерами.

Django описывает поля, связи, ограничения, индексы и метаданные модели.
Комментарии индексов и ограничений, внешние ключи и триггеры задаются
отдельными SQL-миграциями.
"""

from django.conf import settings
from django.db import models
from django.db.models.expressions import RawSQL

from documents.hashing import document_revision_content_hash

from .common import (
    ContentHashModel,
    PostgreSQLGinIndex,
    PostgreSQLIndex,
    UniqueConstraint,
    content_hash_length_constraint,
    message_bindings_is_array_constraint,
    parent_not_self_constraint,
)


class RevisionBuffer(ContentHashModel):
    """
    Буфер несохраненных изменений документа.

    Хранит текущее рабочее состояние документа для конкретного пользователя.
    Один пользователь может иметь не более одного буфера для одного документа.

    Поля entity, parent, template и user описывают связи с документом,
    исходным документом, шаблоном и автором.
    Поля содержимого сохраняют текущую редакцию реквизитов и параметров.

    Идентификаторы id, entity_id и user_id неизменяемы после создания записи.
    Содержимое буфера можно редактировать, при этом PostgreSQL обновляет
    временную метку updated_at автоматически.

    Технический первичный ключ отделен от доменного ограничения уникальности
    пары (entity_id, user_id).
    """

    id = models.UUIDField(
        primary_key=True,
        editable=False,

        db_default=RawSQL(
            "uuid_generate_v7()",
            [],
            output_field=models.UUIDField(),
        ),

        db_comment=(
            "Технический суррогатный идентификатор рабочего буфера. "
            "Добавлен для совместимости с Django ORM и другими инструментами, "
            "ожидающими один первичный ключ."
        ),

        verbose_name="Идентификатор буфера",
    )

    entity = models.ForeignKey(
        "stormcast_documents.DocumentEntity",
        on_delete=models.CASCADE,
        db_column="entity_id",
        db_constraint=False,
        db_index=False,
        null=False,
        related_name="revision_buffers",

        db_comment="Идентификатор документа.",
        verbose_name="Документ",
    )

    parent = models.ForeignKey(
        "stormcast_documents.DocumentEntity",
        on_delete=models.SET_NULL,
        db_column="parent_id",
        db_constraint=False,
        db_index=False,
        null=True,
        blank=True,
        related_name="revision_buffer_children",

        db_comment=(
            "Идентификатор исходного документа для корректировки или отмены."
        ),

        verbose_name="Родительский документ",
    )

    template = models.ForeignKey(
        "stormcast_documents.TemplateRevision",
        on_delete=models.RESTRICT,
        db_column="template_id",
        db_constraint=False,
        db_index=False,
        null=False,
        related_name="document_revision_buffers",

        db_comment="Идентификатор ревизии шаблона печатной формы.",
        verbose_name="Ревизия шаблона",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        db_column="user_id",
        db_index=False,
        null=False,
        related_name="document_revision_buffers",

        db_comment=(
            "Идентификатор пользователя, редактирующего документ."
        ),

        verbose_name="Редактор",
    )

    out_number = models.CharField(
        max_length=100,
        null=True,
        blank=True,

        db_comment="Проект исходящего номера документа.",
        verbose_name="Исходящий номер",
    )

    topic = models.CharField(
        max_length=150,
        null=False,

        db_comment="Тема документа.",
        verbose_name="Тема",
    )

    field_overrides = models.JSONField(
        null=False,

        db_default=RawSQL(
            "'{}'::jsonb",
            [],
            output_field=models.JSONField(),
        ),

        db_comment=(
            "Текущие значения реквизитов документа для формирования "
            "выходной формы."
        ),

        verbose_name="Значения реквизитов",
    )

    message_bindings = models.JSONField(
        null=False,

        db_default=RawSQL(
            "'[]'::jsonb",
            [],
            output_field=models.JSONField(),
        ),

        db_comment=(
            "Черновые привязки сообщений к слотам шаблона. "
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

        db_comment="Комментарий к документу.",
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
            "created_at, updated_at, сам хэш."
        ),

        verbose_name="Контент-хэш",
    )

    details = models.JSONField(
        null=False,

        db_default=RawSQL(
            "'{}'::jsonb",
            [],
            output_field=models.JSONField(),
        ),

        db_comment="Дополнительные параметры документа в формате JSONB.",
        verbose_name="Детали",
    )

    updated_at = models.DateTimeField(
        null=False,
        editable=False,

        db_default=RawSQL(
            "CURRENT_TIMESTAMP",
            [],
            output_field=models.DateTimeField(),
        ),

        db_comment="Дата и время последнего изменения буфера.",
        verbose_name="Дата и время изменения",
    )

    class Meta:
        managed = True
        db_table = '"documents"."revision_buffer"'

        db_table_comment = (
            "Буфер несохраненных изменений документов. Хранит текущее рабочее "
            "состояние для каждого пользователя и документа."
        )

        verbose_name = "Буфер правок документа"
        verbose_name_plural = "Буферы правок документов"

        constraints = [

            UniqueConstraint(
                fields=["entity", "user"],
                name="documents_revision_buffer_entity_id_user_id_unique",

                violation_error_message=(
                    "Доменная уникальность рабочего буфера: один документ может "
                    "иметь только один рабочий буфер для одного пользователя."
                ),
            ),

            content_hash_length_constraint(
                name="check_revision_buffer_content_hash_length",

                violation_error_message=(
                    "Проверяет, что хеш содержимого документа "
                    "(BLAKE3) имеет длину 32 байта."
                ),
            ),

            parent_not_self_constraint(
                name="check_revision_buffer_parent_not_self",

                violation_error_message=(
                    "Запрещает самопривязку, когда документ "
                    "ссылается сам на себя."
                ),
            ),

            message_bindings_is_array_constraint(
                name="check_revision_buffer_message_bindings_is_array",

                violation_error_message=(
                    "Проверяет, что привязки сообщений хранятся "
                    "в виде JSON-массива."
                ),
            ),
        ]

        indexes = [

            # Ускоряет поиск документов, связанных с корректировками и отменами.
            PostgreSQLIndex(
                fields=["parent"],
                name="index_documents_revision_buffer_parent",
            ),

            # Ускоряет выборку несохраненных документов пользователя.
            PostgreSQLIndex(
                fields=["user"],
                name="index_documents_revision_buffer_user_id",
            ),

            # Ускоряет поиск по теме черновиков документов.
            PostgreSQLGinIndex(
                fields=["topic"],
                name="index_documents_revision_buffer_topic_trigram",
                opclasses=["gin_trgm_ops"],
            ),

            # Ускоряет поиск по реквизитам документа в JSONB.
            PostgreSQLGinIndex(
                fields=["field_overrides"],
                name="index_documents_revision_buffer_field_overrides",
                opclasses=["jsonb_path_ops"],
            ),

            # Ускоряет поиск по привязкам сообщений в черновиках.
            PostgreSQLGinIndex(
                fields=["message_bindings"],
                name="index_documents_revision_buffer_message_bindings",
                opclasses=["jsonb_path_ops"],
            ),

            # Ускоряет поиск по дополнительным параметрам документа в JSONB.
            PostgreSQLGinIndex(
                fields=["details"],
                name="index_documents_revision_buffer_details",
                opclasses=["jsonb_path_ops"],
            ),

            # Оптимизирует сортировку буферов по времени изменения.
            PostgreSQLIndex(
                fields=["-updated_at"],
                name="index_documents_revision_buffer_updated_at",
            ),
        ]

    def calculate_content_hash(self):
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
        Возвращает строковое представление рабочего буфера.
        """

        return (
            f"Буфер правок {self.pk} "
            f"(Документ: {self.entity_id})"
        )
