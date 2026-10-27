"""
Текущие состояния сообщений: messages.state_cache.

Хранит актуальные состояния сообщений для быстрого поиска и выборки.
Заполняется автоматически триггерами на основе журнала состояний
messages.states.

PostgreSQL отвечает за генерацию временных меток, значения по умолчанию,
ограничения целостности, согласованность ревизии и автоматическое
обновление времени изменения. Django описывает структуру таблицы,
связи, индексы и метаданные для ORM.

Комментарии индексов, внешние ключи и триггеры устанавливаются
отдельной SQL-миграцией.
"""

from django.conf import settings
from django.db import models
from django.db.models.expressions import RawSQL

from messages.fields import PostgreSQLEnumField

from .common import (
    PostgreSQLGinIndex,
    PostgreSQLIndex,
    ReadinessStage,
    content_hash_length_constraint,
)


class StateCache(models.Model):
    """
    Текущее состояние сообщения для быстрого поиска и выборки.

    Каждому сообщению соответствует не более одной записи кэша.
    Запись обновляется автоматически на основе журнала messages.states.
    """

    entity = models.OneToOneField(
        "stormcast_messages.MessageEntity",
        primary_key=True,
        on_delete=models.CASCADE,
        db_column="entity_id",
        db_constraint=False,
        db_index=False,
        null=False,
        related_name="state_cache",

        db_comment="Идентификатор сообщения.",
        verbose_name="Сообщение",
    )

    revision = models.ForeignKey(
        "stormcast_messages.Revision",
        on_delete=models.RESTRICT,
        db_column="revision_id",
        db_constraint=False,
        db_index=False,
        null=True,
        blank=True,
        related_name="state_cache_entries",

        db_comment=(
            "Идентификатор ревизии, к которой относится текущее "
            "состояние готовности (если применимо)."
        ),

        verbose_name="Ревизия",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        db_column="user_id",
        db_index=False,
        null=False,
        related_name="message_state_caches",

        db_comment=(
            "Идентификатор пользователя, последним изменившего состояние."
        ),

        verbose_name="Автор изменения",
    )

    readiness_stage = PostgreSQLEnumField(
        enum_type='"messages"."readiness_stages"',
        max_length=50,
        choices=ReadinessStage.choices,
        null=False,

        db_default=RawSQL(
            "'draft'::messages.readiness_stages",
            [],
            output_field=models.CharField(max_length=50),
        ),

        db_comment="Стадия готовности сообщения.",
        verbose_name="Стадия готовности",
    )

    is_starred = models.BooleanField(
        db_default=False,
        null=False,

        db_comment=(
            "Признак отметки сообщения как важного."
        ),

        verbose_name="Важное",
    )

    is_archived = models.BooleanField(
        db_default=False,
        null=False,

        db_comment=(
            "Признак нахождения сообщения в архиве."
        ),

        verbose_name="В архиве",
    )

    is_deleted = models.BooleanField(
        db_default=False,
        null=False,

        db_comment=(
            "Признак логического удаления сообщения."
        ),

        verbose_name="Удалено",
    )

    content_hash = models.BinaryField(
        null=False,

        db_comment=(
            "Контент-хэш снимка состояния сообщения (BLAKE3). "
            "Вычисляется от полезной нагрузки состояния: readiness_stage, "
            "is_starred, is_archived, is_deleted, details. "
            "Не включает контекст: id, entity_id, revision_id, user_id, "
            "updated_at."
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
            "Дополнительные сведения о текущем состоянии."
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
            "Дата и время последнего изменения состояния."
        ),

        verbose_name="Дата и время изменения",
    )

    class Meta:
        managed = True

        db_table = '"messages"."state_cache"'

        db_table_comment = (
            "Текущие состояния сообщений. Обновляется автоматически "
            "на основе журнала messages.states."
        )

        verbose_name = "Кэш состояния сообщения"
        verbose_name_plural = "Кэш состояний сообщений"

        constraints = [

            content_hash_length_constraint(
                name="check_state_cache_content_hash_length",

                violation_error_message=(
                    "Проверяет, что контент-хэш снимка состояния "
                    "(BLAKE3) имеет длину 32 байта."
                ),
            ),
        ]

        indexes = [

            # Ускоряет выборку неудаленных сообщений по стадии готовности.
            PostgreSQLIndex(
                fields=["entity", "readiness_stage"],
                condition=models.Q(is_deleted=False),
                name="index_messages_state_cache_entity_stage_active",
            ),

            # Ускоряет выборку неархивированных сообщений по стадии готовности.
            PostgreSQLIndex(
                fields=["readiness_stage"],
                condition=models.Q(is_archived=False),
                name="index_messages_state_cache_stage_not_archived",
            ),

            # Оптимизирует выборку неудаленных черновиков.
            PostgreSQLIndex(
                fields=["readiness_stage"],

                condition=models.Q(
                    readiness_stage=ReadinessStage.DRAFT,
                    is_deleted=False,
                ),

                name="index_messages_state_cache_draft",
            ),

            # Ускоряет выборку неудаленных важных сообщений.
            PostgreSQLIndex(
                fields=["entity"],

                condition=models.Q(
                    is_starred=True,
                    is_deleted=False,
                ),

                name="index_messages_state_cache_starred",
            ),

            # Ускоряет поиск по структурированным данным в JSONB.
            PostgreSQLGinIndex(
                fields=["details"],
                name="index_messages_state_cache_details",
                opclasses=["jsonb_path_ops"],
            ),

            # Оптимизирует выборку сообщений по времени изменения состояния.
            PostgreSQLIndex(
                fields=["-updated_at"],
                name="index_messages_state_cache_updated_at",
            ),
        ]

    def __str__(self) -> str:
        """
        Возвращает краткое представление записи кэша.
        """

        return (
            f"Кэш состояния для сообщения {self.entity_id}"
        )
