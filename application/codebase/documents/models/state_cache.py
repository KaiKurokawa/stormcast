"""
Текущие состояния документов: documents.state_cache.

Хранит актуальные состояния документов для быстрого поиска и выборки.
Заполняется автоматически триггерами на основе журнала состояний
documents.states.

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
    Текущее состояние документа для быстрого поиска и выборки.

    Каждому документу соответствует не более одной записи кэша.
    Запись обновляется автоматически на основе журнала documents.states.
    """

    entity = models.OneToOneField(
        "stormcast_documents.DocumentEntity",
        primary_key=True,
        on_delete=models.CASCADE,
        db_column="entity_id",
        db_constraint=False,
        db_index=False,
        null=False,
        related_name="state_cache",

        db_comment="Идентификатор документа.",
        verbose_name="Документ",
    )

    revision = models.ForeignKey(
        "stormcast_documents.Revision",
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
        related_name="document_state_caches",

        db_comment=(
            "Идентификатор пользователя, последним изменившего состояние."
        ),

        verbose_name="Автор изменения",
    )

    readiness_stage = PostgreSQLEnumField(
        enum_type='"documents"."readiness_stages"',
        max_length=50,
        choices=ReadinessStage.choices,
        null=False,

        db_default=RawSQL(
            "'draft'::documents.readiness_stages",
            [],
            output_field=models.CharField(max_length=50),
        ),

        db_comment="Текущее состояние документа.",
        verbose_name="Стадия готовности",
    )

    is_archived = models.BooleanField(
        db_default=False,
        null=False,

        db_comment=(
            "Признак нахождения документа в архиве."
        ),

        verbose_name="В архиве",
    )

    is_deleted = models.BooleanField(
        db_default=False,
        null=False,

        db_comment=(
            "Признак скрытия документа из рабочего списка пользователем."
        ),

        verbose_name="Удалено",
    )

    content_hash = models.BinaryField(
        null=False,

        db_comment=(
            "Контент-хэш снимка состояния документа (BLAKE3). "
            "Вычисляется от полезной нагрузки состояния: readiness_stage, "
            "is_archived, is_deleted, details. "
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

        db_table = '"documents"."state_cache"'

        db_table_comment = (
            "Текущие состояния документов. Обновляется автоматически "
            "на основе журнала documents.states."
        )

        verbose_name = "Кэш состояния документа"
        verbose_name_plural = "Кэш состояний документов"

        constraints = [

            content_hash_length_constraint(
                name="check_state_cache_content_hash_length",

                violation_error_message=(
                    "Проверяет, что хеш снимка состояния "
                    "(BLAKE3) имеет длину 32 байта."
                ),
            ),
        ]

        indexes = [

            # Ускоряет выборку документов по текущему состоянию.
            PostgreSQLIndex(
                fields=["entity", "readiness_stage"],
                name="index_documents_state_cache_entity_stage",
            ),

            # Ускоряет выборку активных документов, не скрытых пользователем и не находящихся в архиве.
            PostgreSQLIndex(
                fields=["readiness_stage"],

                condition=models.Q(
                    is_deleted=False,
                    is_archived=False,
                ),

                name="index_documents_state_cache_active",
            ),

            # Ускоряет выборку документов в состоянии draft.
            PostgreSQLIndex(
                fields=["readiness_stage"],

                condition=models.Q(
                    readiness_stage=ReadinessStage.DRAFT,
                    is_deleted=False,
                ),

                name="index_documents_state_cache_draft",
            ),

            # Ускоряет поиск по дополнительным параметрам текущего состояния.
            PostgreSQLGinIndex(
                fields=["details"],
                name="index_documents_state_cache_details",
                opclasses=["jsonb_path_ops"],
            ),

            # Оптимизирует сортировку документов по времени изменения состояния.
            PostgreSQLIndex(
                fields=["-updated_at"],
                name="index_documents_state_cache_updated_at",
            ),
        ]

    def __str__(self) -> str:
        """
        Возвращает краткое представление записи кэша.
        """

        return (
            f"Кэш состояния для документа {self.entity_id}"
        )
