"""
Буфер правок сообщений: messages.revision_buffer.

Хранит текущие несохраненные изменения сообщений. Каждый пользователь
располагает собственным буфером для каждого сообщения.

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

from django.contrib.postgres.fields import DateTimeRangeField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.expressions import RawSQL

from messages.fields import PostgreSQLEnumField

from .common import (
    UniqueConstraint,
    MessageType,
    content_hash_length_constraint,
    parent_not_self_constraint,
)


class RevisionBuffer(models.Model):
    """
    Буфер несохраненных изменений сообщения.

    Хранит текущее рабочее состояние сообщения для конкретного пользователя.
    Один пользователь может иметь не более одного буфера для одного сообщения.

    Поля entity, parent и user описывают связи с сообщениями и автором.
    Поля содержимого сохраняют текущую редакцию текста и параметров.

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
        "messages.MessageEntity",
        on_delete=models.CASCADE,
        db_column="entity_id",
        db_constraint=False,
        db_index=False,
        null=False,
        related_name="revision_buffers",

        db_comment="Идентификатор сообщения.",
        verbose_name="Сообщение",
    )

    parent = models.ForeignKey(
        "messages.MessageEntity",
        on_delete=models.SET_NULL,
        db_column="parent_id",
        db_constraint=False,
        db_index=False,
        null=True,
        blank=True,
        related_name="revision_buffer_children",

        db_comment=(
            "Идентификатор сообщения, к которому относится "
            "корректировка или отмена."
        ),

        verbose_name="Родительское сообщение",
    )

    user = models.ForeignKey(
        "identity.User",
        on_delete=models.DO_NOTHING,
        db_column="user_id",
        db_constraint=False,
        db_index=False,
        null=False,
        related_name="message_revision_buffers",

        db_comment=(
            "Идентификатор пользователя, редактирующего сообщение."
        ),

        verbose_name="Редактор",
    )

    type = PostgreSQLEnumField(
        enum_type='"messages"."message_type"',
        max_length=100,
        choices=MessageType.choices,
        null=False,

        db_comment="Тип метеорологического события.",
        verbose_name="Тип события",
    )

    period = DateTimeRangeField(
        null=True,
        blank=True,

        db_comment=(
            "Период действия метеорологического явления."
        ),

        verbose_name="Период действия",
    )

    region = models.TextField(
        null=True,
        blank=True,

        db_comment=(
            "Ориентировочный район/регион погодного явления. "
            "Свободное описание до введения отдельного географического "
            "справочника."
        ),

        verbose_name="Регион",
    )

    text = models.TextField(
        null=False,

        db_comment="Редактируемый текст сообщения.",
        verbose_name="Текст сообщения",
    )

    note = models.CharField(
        max_length=255,
        null=True,
        blank=True,

        db_comment="Рабочий комментарий к сообщению.",
        verbose_name="Комментарий",
    )

    content_hash = models.BinaryField(
        null=False,

        db_comment=(
            "Контент-хэш снимка сообщения (BLAKE3). Вычисляется от "
            "канонической полезной нагрузки: type, period, region, text, "
            "note/details, если они значимы. Не включает технические поля: "
            "id, entity_id, user_id, created_at, updated_at, сам хэш."
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

        db_comment=(
            "Дополнительные параметры сообщения в формате JSONB."
        ),

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

        db_comment=(
            "Дата и время последнего изменения буфера."
        ),

        verbose_name="Дата и время изменения",
    )

    class Meta:
        managed = True
        db_table = '"messages"."revision_buffer"'

        db_table_comment = (
            "Буфер несохраненных изменений сообщений. Хранит текущее рабочее "
            "состояние для каждого пользователя и сообщения."
        )

        verbose_name = "Буфер правок сообщения"
        verbose_name_plural = "Буферы правок сообщений"

        constraints = [

            UniqueConstraint(
                fields=["entity", "user"],
                name="messages_revision_buffer_entity_id_user_id_unique",

                violation_error_message=(
                    "Доменная уникальность рабочего буфера: одно сообщение может "
                    "иметь только один рабочий буфер для одного пользователя."
                ),
            ),

            content_hash_length_constraint(
                name="check_revision_buffer_content_hash_length",

                violation_error_message=(
                    "Проверяет, что контент-хэш содержимого сообщения "
                    "(BLAKE3) имеет длину 32 байта."
                ),
            ),

            parent_not_self_constraint(
                name="check_revision_buffer_parent_not_self",

                violation_error_message=(
                    "Запрещает самопривязку, когда сообщение "
                    "ссылается само на себя."
                ),
            ),
        ]

        indexes = [

            # Ускоряет поиск связанных сообщений (исправлений, отмен).
            models.Index(
                fields=["parent"],
                name="index_messages_revision_buffer_parent",
            ),

            # Ускоряет поиск активных черновиков пользователя.
            models.Index(
                fields=["user"],
                name="index_messages_revision_buffer_user_id",
            ),

            # Ускоряет поиск по тексту черновиков.
            GinIndex(
                fields=["text"],
                name="index_messages_revision_buffer_text_trigram",
                opclasses=["gin_trgm_ops"],
            ),

            # Ускоряет поиск по параметрам черновиков в JSONB.
            GinIndex(
                fields=["details"],
                name="index_messages_revision_buffer_details",
                opclasses=["jsonb_path_ops"],
            ),

            # Оптимизирует сортировку черновиков по времени изменения.
            models.Index(
                fields=["-updated_at"],
                name="index_messages_revision_buffer_updated_at",
            ),
        ]

    def __str__(self) -> str:
        """
        Возвращает строковое представление рабочего буфера.
        """

        return (
            f"Буфер правок {self.pk} "
            f"(Сообщение: {self.entity_id})"
        )
