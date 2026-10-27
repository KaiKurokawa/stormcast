"""
Реестр сообщений: messages.entities.

Таблица хранит идентификаторы сообщений и связывает их версии и состояния.
Она представляет неизменяемую запись о существовании сообщения; версии и
состояния хранятся в связанных таблицах.

PostgreSQL отвечает за генерацию идентификаторов и времени создания,
ограничения целостности и выполнение триггеров. Django описывает структуру
таблицы, её поля, индексы и метаданные для ORM.

Комментарии индексов, определение внешнего ключа и триггеры задаются
отдельными SQL-миграциями.
"""

from django.db import models
from django.db.models.expressions import RawSQL


class MessageEntity(models.Model):
    """
    Реестр сообщений.

    Хранит идентификаторы сообщений, для которых ведется история версий
    и состояний.

    Первичный ключ и временная метка создания генерируются PostgreSQL.
    Автор сообщения определяется внешним ключом на identity.users.
    Неизменяемость записи и инициализация начального состояния
    обеспечиваются триггерами PostgreSQL.
    """

    id = models.UUIDField(
        primary_key=True,
        editable=False,

        db_default=RawSQL(
            "uuid_generate_v7()",
            [],
            output_field=models.UUIDField(),
        ),

        db_comment="Уникальный идентификатор сообщения.",
        verbose_name="Идентификатор сообщения",
    )

    user = models.ForeignKey(
        "identity.User",
        on_delete=models.DO_NOTHING,
        db_column="user_id",
        db_constraint=False,
        db_index=False,
        null=False,
        related_name="message_entities",

        db_comment=(
            "Идентификатор пользователя, создавшего сообщение."
        ),

        verbose_name="Автор сообщения",
    )

    created_at = models.DateTimeField(
        null=False,
        editable=False,

        db_default=RawSQL(
            "CURRENT_TIMESTAMP",
            [],
            output_field=models.DateTimeField(),
        ),

        db_comment="Дата и время создания сообщения.",
        verbose_name="Дата и время создания",
    )

    class Meta:
        managed = True
        db_table = '"messages"."entities"'

        db_table_comment = (
            "Реестр сообщений. Хранит идентификаторы сообщений, "
            "для которых ведется история версий и состояний."
        )

        verbose_name = "Реестр сообщений"
        verbose_name_plural = "Реестры сообщений"

        indexes = [

            # Ускоряет фильтрацию сообщений по их автору.
            models.Index(
                fields=["user"],
                name="index_messages_entities_user_id",
            ),

            # Оптимизирует сортировку списков по времени создания.
            models.Index(
                fields=["-created_at"],
                name="index_messages_entities_created_at",
            ),
        ]

    def __str__(self) -> str:
        """
        Возвращает строковое представление записи реестра.
        """

        return f"Реестр сообщений {self.pk}"
