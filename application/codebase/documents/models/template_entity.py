"""
Реестр шаблонов документов: documents.template_entities.

Таблица хранит идентификаторы шаблонов документов и связывает их версии.
Она представляет неизменяемую запись о существовании шаблона; версии
хранятся в связанной таблице ревизий шаблонов.

PostgreSQL отвечает за генерацию идентификаторов и времени создания,
ограничения целостности и выполнение триггеров. Django описывает структуру
таблицы, её поля, индексы и метаданные для ORM.

Комментарии индексов, определение внешнего ключа и триггеры задаются
отдельными SQL-миграциями.
"""

from django.conf import settings
from django.db import models
from django.db.models.expressions import RawSQL

from .common import PostgreSQLIndex


class TemplateEntity(models.Model):
    """
    Реестр шаблонов документов.

    Хранит идентификаторы шаблонов, для которых ведется история версий.

    Первичный ключ и временная метка создания генерируются PostgreSQL.
    Автор шаблона определяется стандартной моделью пользователя Django.
    Неизменяемость записи обеспечивается триггерами PostgreSQL.
    """

    id = models.UUIDField(
        primary_key=True,
        editable=False,

        db_default=RawSQL(
            "uuid_generate_v7()",
            [],
            output_field=models.UUIDField(),
        ),

        db_comment="Уникальный идентификатор шаблона документа.",
        verbose_name="Идентификатор шаблона",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        db_column="user_id",
        db_index=False,
        null=False,
        related_name="document_template_entities",

        db_comment=(
            "Идентификатор пользователя, создавшего шаблон."
        ),

        verbose_name="Автор шаблона",
    )

    created_at = models.DateTimeField(
        null=False,
        editable=False,

        db_default=RawSQL(
            "CURRENT_TIMESTAMP",
            [],
            output_field=models.DateTimeField(),
        ),

        db_comment="Дата и время создания шаблона.",
        verbose_name="Дата и время создания",
    )

    class Meta:
        """Описание полей и поведения записи."""
        managed = True
        db_table = '"documents"."template_entities"'

        db_table_comment = (
            "Реестр шаблонов документов. Хранит идентификаторы шаблонов, "
            "для которых ведется история версий."
        )

        verbose_name = "Реестр шаблонов документов"
        verbose_name_plural = "Реестры шаблонов документов"

        indexes = [

            # Ускоряет выборку шаблонов по их автору.
            PostgreSQLIndex(
                fields=["user"],
                name="index_documents_template_entities_user_id",
            ),

            # Оптимизирует сортировку шаблонов по времени создания.
            PostgreSQLIndex(
                fields=["-created_at"],
                name="index_documents_template_entities_created_at",
            ),
        ]

    def __str__(self) -> str:
        """
        Возвращает строковое представление записи реестра шаблонов.
        """

        return f"Реестр шаблонов документов {self.pk}"
