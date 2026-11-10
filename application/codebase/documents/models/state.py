"""
Журнал состояний документов: documents.states.

Хранит историю изменений состояний документов. Каждая запись содержит
полное состояние документа на момент изменения.

Записи журнала неизменяемы. PostgreSQL отвечает за генерацию
идентификаторов и временных меток, внешние ключи, ограничения целостности,
проверку согласованности документа и ревизии, синхронизацию текущего
состояния и защиту истории от изменения и удаления.

Django описывает поля, связи, ограничения, индексы и метаданные модели.
Комментарии индексов и ограничений, внешние ключи и триггеры задаются
отдельными SQL-миграциями.
"""

from django.conf import settings
from django.db import models
from django.db.models.expressions import RawSQL

from documents.fields import PostgreSQLEnumField
from documents.hashing import state_content_hash

from .common import (
    ContentHashModel,
    PostgreSQLIndex,
    ReadinessStage,
    content_hash_length_constraint,
)


class State(ContentHashModel):
    """
    Запись истории состояния документа.

    Содержит полное состояние документа на момент изменения: стадию
    готовности, признаки архивирования и скрытия из рабочего списка,
    а также дополнительные сведения.

    Связь entity определяет документ, состояние которого записано.
    Связь revision указывает на ревизию, к которой относится изменение
    состояния, если такая связь применима. Связь user определяет автора
    изменения.

    Каждая запись является неизменяемой. Триггеры PostgreSQL проверяют
    согласованность документа и ревизии, обновляют кэш текущего состояния
    после вставки и запрещают изменение или удаление записи.
    """

    id = models.UUIDField(
        primary_key=True,
        editable=False,

        db_default=RawSQL(
            "uuid_generate_v7()",
            [],
            output_field=models.UUIDField(),
        ),

        db_comment="Уникальный идентификатор записи истории.",
        verbose_name="Идентификатор записи",
    )

    entity = models.ForeignKey(
        "stormcast_documents.DocumentEntity",
        on_delete=models.CASCADE,
        db_column="entity_id",
        db_constraint=False,
        db_index=False,
        null=False,
        related_name="states",

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
        related_name="states",

        db_comment=(
            "Идентификатор ревизии, к которой относится изменение "
            "состояния готовности (если применимо)."
        ),

        verbose_name="Ревизия",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        db_column="user_id",
        db_index=False,
        null=False,
        related_name="document_states",

        db_comment=(
            "Идентификатор пользователя, изменившего состояние."
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

        db_comment=(
            "Состояние документа, зафиксированное в записи."
        ),

        verbose_name="Стадия готовности",
    )

    is_archived = models.BooleanField(
        db_default=False,
        null=False,

        db_comment=(
            "Признак нахождения документа в архиве на момент записи."
        ),

        verbose_name="В архиве",
    )

    is_deleted = models.BooleanField(
        db_default=False,
        null=False,

        db_comment=(
            "Признак скрытия документа из рабочего списка пользователем "
            "на момент записи."
        ),

        verbose_name="Удалено",
    )

    content_hash = models.BinaryField(
        null=False,

        db_comment=(
            "Контент-хэш снимка состояния документа (BLAKE3). Вычисляется "
            "от полезной нагрузки состояния: readiness_stage, is_archived, "
            "is_deleted, details. Не включает контекст: id, entity_id, "
            "revision_id, user_id, created_at."
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
            "Дополнительные сведения о переходе состояния."
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

        db_comment="Дата и время изменения состояния.",
        verbose_name="Дата и время записи",
    )

    class Meta:
        managed = True
        db_table = '"documents"."states"'

        db_table_comment = (
            "История изменений состояний документов. Каждая запись содержит "
            "состояние документа на момент изменения."
        )

        verbose_name = "Запись журнала состояний"
        verbose_name_plural = "Журнал состояний документов"

        constraints = [

            content_hash_length_constraint(
                name="check_states_content_hash_length",

                violation_error_message=(
                    "Проверяет, что хеш снимка состояния "
                    "(BLAKE3) имеет длину 32 байта."
                ),
            ),
        ]

        indexes = [

            # Ускоряет получение истории состояний документа.
            PostgreSQLIndex(
                fields=["entity", "created_at"],
                name="index_documents_states_chronology",
            ),

            # Оптимизирует выборку общего журнала изменений состояний.
            PostgreSQLIndex(
                fields=["-created_at"],
                name="index_documents_states_created_at",
            ),

            # Ускоряет поиск состояний, связанных с конкретной ревизией документа.
            PostgreSQLIndex(
                fields=["revision"],
                name="index_documents_states_revision_id",
            ),
        ]

    def calculate_content_hash(self):
        return state_content_hash(
            readiness_stage=self.readiness_stage,
            is_archived=self.is_archived,
            is_deleted=self.is_deleted,
            details=self.details,
        )

    def __str__(self) -> str:
        """
        Возвращает строковое представление записи истории состояний.
        """

        return (
            f"Запись журнала состояний {self.pk} "
            f"(Документ: {self.entity_id})"
        )
