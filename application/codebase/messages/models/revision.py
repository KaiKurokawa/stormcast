"""
Архив ревизий сообщений: messages.revisions.

Хранит историю зафиксированных версий текста и параметров сообщений.
Каждая ревизия представляет неизменяемый снимок содержимого сообщения
на момент фиксации.

PostgreSQL отвечает за генерацию идентификаторов и временных меток,
нативный тип перечисления, внешние ключи, ограничения целостности
и защиту записей от изменения и удаления.

Django описывает поля, связи, ограничения, индексы и метаданные модели.
Комментарии индексов и ограничений, внешние ключи и триггер неизменяемости
устанавливаются отдельными SQL-миграциями.
"""

from django.contrib.postgres.fields import DateTimeRangeField
from django.conf import settings
from django.db import models
from django.db.models.expressions import RawSQL

from messages.fields import PostgreSQLEnumField

from .common import (
    ContentHashModel,
    MessageType,
    PostgreSQLGinIndex,
    PostgreSQLGistIndex,
    PostgreSQLIndex,
    content_hash_length_constraint,
    parent_not_self_constraint,
)
from messages.hashing import revision_content_hash


class Revision(ContentHashModel):
    """
    Архив зафиксированных ревизий сообщения.

    Ревизия хранит снимок текста, типа события, периода действия,
    региона, комментария и дополнительных параметров сообщения.

    Связь entity указывает на сообщение, к которому относится ревизия.
    Связь parent указывает на сообщение, которое корректируется
    или отменяется данной ревизией. Связь user определяет автора ревизии.

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
        "stormcast_messages.MessageEntity",
        on_delete=models.CASCADE,
        db_column="entity_id",
        db_constraint=False,
        db_index=False,
        null=False,
        related_name="revisions",

        db_comment="Идентификатор сообщения.",
        verbose_name="Сообщение",
    )

    parent = models.ForeignKey(
        "stormcast_messages.MessageEntity",
        on_delete=models.SET_NULL,
        db_column="parent_id",
        db_constraint=False,
        db_index=False,
        null=True,
        blank=True,
        related_name="revision_children",

        db_comment=(
            "Идентификатор сообщения, к которому относится "
            "корректировка или отмена."
        ),

        verbose_name="Родительское сообщение",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        db_column="user_id",
        db_index=False,
        null=False,
        related_name="message_revisions",

        db_comment=(
            "Идентификатор пользователя, создавшего ревизию."
        ),

        verbose_name="Автор ревизии",
    )

    type = PostgreSQLEnumField(
        enum_type='"messages"."message_type"',
        max_length=100,
        choices=MessageType.choices,
        null=False,

        db_comment=(
            "Тип метеорологического события на момент создания ревизии."
        ),

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
            "Ориентировочный район/регион погодного явления "
            "на момент создания ревизии."
        ),

        verbose_name="Регион",
    )

    text = models.TextField(
        null=False,
        db_comment="Текст сообщения в данной ревизии.",
        verbose_name="Текст ревизии",
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
            "Контент-хэш снимка сообщения (BLAKE3). Вычисляется от "
            "канонической полезной нагрузки: type, period, region, text, "
            "note/details, если они значимы. Не включает технические поля: "
            "id, entity_id, user_id, created_at, сам хэш."
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
        managed = True
        db_table = '"messages"."revisions"'

        db_table_comment = (
            "История зафиксированных версий текста "
            "и параметров сообщений."
        )

        verbose_name = "Ревизия сообщения"
        verbose_name_plural = "Ревизии сообщений"

        constraints = [

            content_hash_length_constraint(
                name="check_revisions_content_hash_length",

                violation_error_message=(
                    "Проверяет, что контент-хэш содержимого ревизии "
                    "(BLAKE3) имеет длину 32 байта."
                ),
            ),

            parent_not_self_constraint(
                name="check_revisions_parent_not_self",

                violation_error_message=(
                    "Запрещает самопривязку, когда сообщение "
                    "ссылается само на себя."
                ),
            ),
        ]

        indexes = [

            # Оптимизирует получение последней ревизии сообщения.
            PostgreSQLIndex(
                fields=["entity", "-created_at", "-id"],
                name="index_messages_revisions_message_time",
            ),

            # Ускоряет поиск связанных сообщений (исправлений, отмен).
            PostgreSQLIndex(
                fields=["parent"],
                name="index_messages_revisions_parent",
            ),

            # Ускоряет поиск событий по времени действия.
            PostgreSQLGistIndex(
                fields=["period"],
                name="index_messages_revisions_period_gist",
            ),

            # Ускоряет поиск по тексту ревизий.
            PostgreSQLGinIndex(
                fields=["text"],
                name="index_messages_revisions_text_trigram",
                opclasses=["gin_trgm_ops"],
            ),

            # Ускоряет фильтрацию ревизий по типу метеорологического события.
            PostgreSQLIndex(
                fields=["type"],
                name="index_messages_revisions_type",
            ),

            # Ускоряет выборку ревизий по автору.
            PostgreSQLIndex(
                fields=["user"],
                name="index_messages_revisions_user_id",
            ),
        ]

    def calculate_content_hash(self):
        return revision_content_hash(
            message_type=self.type,
            period=self.period,
            region=self.region,
            text=self.text,
            note=self.note,
            details=self.details,
        )

    def __str__(self) -> str:
        """
        Возвращает строковое представление ревизии.
        """

        return (
            f"Ревизия {self.pk} "
            f"для сообщения {self.entity_id}"
        )
