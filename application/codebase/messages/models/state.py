"""
Журнал состояний сообщений: messages.states.

Хранит историю изменений состояний сообщений. Каждая запись содержит
полное состояние сообщения на момент изменения.

Записи журнала неизменяемы. PostgreSQL отвечает за генерацию
идентификаторов и временных меток, внешние ключи, ограничения целостности,
проверку согласованности сообщения и ревизии, синхронизацию текущего
состояния и защиту истории от изменения и удаления.

Django описывает поля, связи, ограничения, индексы и метаданные модели.
Комментарии индексов и ограничений, внешние ключи и триггеры задаются
отдельными SQL-миграциями.
"""

from django.db import models
from django.db.models.expressions import RawSQL

from messages.fields import PostgreSQLEnumField

from .common import (
    ReadinessStage,
    content_hash_length_constraint,
)


class State(models.Model):
    """
    Запись истории состояния сообщения.

    Содержит полное состояние сообщения на момент изменения: стадию
    готовности, признаки важности, архивирования и логического удаления,
    а также дополнительные сведения.

    Связь entity определяет сообщение, состояние которого записано.
    Связь revision указывает на ревизию, к которой относится изменение
    состояния, если такая связь применима. Связь user определяет автора
    изменения.

    Каждая запись является неизменяемой. Триггеры PostgreSQL проверяют
    согласованность сообщения и ревизии, обновляют кэш текущего состояния
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
        "messages.MessageEntity",
        on_delete=models.CASCADE,
        db_column="entity_id",
        db_constraint=False,
        db_index=False,
        null=False,
        related_name="states",

        db_comment="Идентификатор сообщения.",
        verbose_name="Сообщение",
    )

    revision = models.ForeignKey(
        "messages.Revision",
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
        "identity.User",
        on_delete=models.DO_NOTHING,
        db_column="user_id",
        db_constraint=False,
        db_index=False,
        null=False,
        related_name="message_states",

        db_comment=(
            "Идентификатор пользователя, изменившего состояние."
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

        db_comment=(
            "Стадия готовности сообщения на момент записи."
        ),

        verbose_name="Стадия готовности",
    )

    is_starred = models.BooleanField(
        db_default=False,
        null=False,

        db_comment=(
            "Признак отметки сообщения как важного на момент записи."
        ),

        verbose_name="Важное",
    )

    is_archived = models.BooleanField(
        db_default=False,
        null=False,

        db_comment=(
            "Признак нахождения сообщения в архиве на момент записи."
        ),

        verbose_name="В архиве",
    )

    is_deleted = models.BooleanField(
        db_default=False,
        null=False,

        db_comment=(
            "Признак логического удаления сообщения на момент записи."
        ),

        verbose_name="Удалено",
    )

    content_hash = models.BinaryField(
        null=False,

        db_comment=(
            "Контент-хэш снимка состояния сообщения (BLAKE3). Вычисляется "
            "от полезной нагрузки состояния: readiness_stage, is_starred, "
            "is_archived, is_deleted, details. Не включает контекст: id, "
            "entity_id, revision_id, user_id, created_at."
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
            "Дополнительные сведения о событии изменения состояния."
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

        db_comment="Дата и время записи состояния.",
        verbose_name="Дата и время записи",
    )

    class Meta:
        managed = True
        db_table = '"messages"."states"'

        db_table_comment = (
            "История изменений состояний сообщений. Каждая запись содержит "
            "полное состояние сообщения на момент изменения."
        )

        verbose_name = "Запись журнала состояний"
        verbose_name_plural = "Журнал состояний сообщений"

        constraints = [

            content_hash_length_constraint(
                name="check_states_content_hash_length",

                violation_error_message=(
                    "Проверяет, что контент-хэш снимка состояния "
                    "(BLAKE3) имеет длину 32 байта."
                ),
            ),
        ]

        indexes = [

            # Оптимизирует построение истории состояний сообщения.
            models.Index(
                fields=["entity", "created_at"],
                name="index_messages_states_chronology",
            ),

            # Оптимизирует построение общего журнала изменений состояний.
            models.Index(
                fields=["-created_at"],
                name="index_messages_states_created_at",
            ),

            # Ускоряет поиск состояний, связанных с конкретной ревизией сообщения.
            models.Index(
                fields=["revision"],
                name="index_messages_states_revision_id",
            ),
        ]

    def __str__(self) -> str:
        """
        Возвращает строковое представление записи истории состояний.
        """

        return (
            f"Запись журнала состояний {self.pk} "
            f"(Сообщение: {self.entity_id})"
        )
