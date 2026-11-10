"""
Реестр документов: documents.entities.

Таблица хранит идентификаторы документов и связывает их версии и состояния.
Она представляет неизменяемую запись о существовании документа; версии и
состояния хранятся в связанных таблицах.

PostgreSQL отвечает за генерацию идентификаторов и времени создания,
ограничения целостности и выполнение триггеров. Django описывает структуру
таблицы, её поля, индексы и метаданные для ORM.

Комментарии индексов, определение внешнего ключа и триггеры задаются
отдельными SQL-миграциями.
"""

from django.conf import settings
from django.db import models
from django.db.models.expressions import RawSQL

from documents.querysets import DocumentManager

from .common import PostgreSQLIndex


class DocumentEntity(models.Model):
    """
    Реестр документов.

    Хранит идентификаторы документов, для которых ведется история версий
    и состояний.

    Первичный ключ и временная метка создания генерируются PostgreSQL.
    Автор документа определяется стандартной моделью пользователя Django.
    Неизменяемость записи и инициализация начального состояния
    обеспечиваются триггерами PostgreSQL.
    """

    objects = DocumentManager()

    id = models.UUIDField(
        primary_key=True,
        editable=False,

        db_default=RawSQL(
            "uuid_generate_v7()",
            [],
            output_field=models.UUIDField(),
        ),

        db_comment="Уникальный идентификатор документа.",
        verbose_name="Идентификатор документа",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        db_column="user_id",
        db_index=False,
        null=False,
        related_name="document_entities",

        db_comment=(
            "Идентификатор пользователя, создавшего документ."
        ),

        verbose_name="Автор документа",
    )

    created_at = models.DateTimeField(
        null=False,
        editable=False,

        db_default=RawSQL(
            "CURRENT_TIMESTAMP",
            [],
            output_field=models.DateTimeField(),
        ),

        db_comment="Дата и время создания документа.",
        verbose_name="Дата и время создания",
    )

    class Meta:
        """Описание полей и поведения записи."""
        managed = True
        db_table = '"documents"."entities"'

        db_table_comment = (
            "Реестр документов. Хранит идентификаторы документов, "
            "для которых ведется история версий и состояний."
        )

        verbose_name = "Реестр документов"
        verbose_name_plural = "Реестры документов"

        indexes = [

            # Ускоряет выборку документов по их автору.
            PostgreSQLIndex(
                fields=["user"],
                name="index_documents_entities_user_id",
            ),

            # Оптимизирует сортировку документов по времени создания.
            PostgreSQLIndex(
                fields=["-created_at"],
                name="index_documents_entities_created_at",
            ),
        ]

    def __str__(self) -> str:
        """
        Возвращает строковое представление записи реестра.
        """

        return f"Реестр документов {self.pk}"
