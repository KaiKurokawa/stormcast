"""
Архив ревизий шаблонов документов: documents.template_revisions.

Хранит неизменяемые версии HTML-шаблонов с декларацией полей и значениями
по умолчанию. Каждая ревизия представляет неизменяемый снимок шаблона
на момент фиксации.

PostgreSQL отвечает за генерацию идентификаторов и временных меток,
внешние ключи, ограничения целостности и защиту записей от изменения
и удаления.

Django описывает поля, связи, ограничения, индексы и метаданные модели.
Комментарии индексов и ограничений, внешние ключи и триггер неизменяемости
устанавливаются отдельными SQL-миграциями.
"""

from django.conf import settings
from django.db import models
from django.db.models.expressions import RawSQL

from documents.fields import PostgreSQLEnumField
from documents.hashing import template_revision_content_hash

from .common import (
    ContentHashModel,
    PostgreSQLGinIndex,
    PostgreSQLIndex,
    content_hash_length_constraint,
)


class TemplateRevision(ContentHashModel):
    """
    Архив зафиксированных ревизий шаблона документа.

    Ревизия хранит снимок кода шаблона, названия, описания, HTML-тела,
    декларации полей и значений по умолчанию.

    Связь template_entity указывает на родительский шаблон.
    Связь user определяет автора ревизии шаблона.

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

        db_comment="Уникальный идентификатор ревизии шаблона.",
        verbose_name="Идентификатор ревизии шаблона",
    )

    template_entity = models.ForeignKey(
        "stormcast_documents.TemplateEntity",
        on_delete=models.CASCADE,
        db_column="template_entity_id",
        db_index=False,
        null=False,
        related_name="template_revisions",

        db_comment="Идентификатор родительского шаблона.",
        verbose_name="Шаблон документа",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        db_column="user_id",
        db_index=False,
        null=False,
        related_name="document_template_revisions",

        db_comment=(
            "Идентификатор пользователя, создавшего эту ревизию шаблона."
        ),

        verbose_name="Автор ревизии шаблона",
    )

    code = models.CharField(
        max_length=50,
        null=False,

        db_comment=(
            "Системный код шаблона для идентификации типа документа, "
            "например: 'storm_warning', 'daily_bulletin'."
        ),

        verbose_name="Код шаблона",
    )

    title = models.CharField(
        max_length=150,
        null=False,

        db_comment="Человекочитаемое название шаблона.",
        verbose_name="Название шаблона",
    )

    description = models.CharField(
        max_length=255,
        null=True,
        blank=True,

        db_comment="Описание назначения и особенностей шаблона.",
        verbose_name="Описание шаблона",
    )

    body_html = models.TextField(
        null=False,

        db_comment=(
            "Исходный код HTML-шаблона в формате Django Templates."
        ),

        verbose_name="HTML-шаблон",
    )

    field_schema = models.JSONField(
        default=dict,
        null=False,

        db_default=RawSQL(
            "'{}'::jsonb",
            [],
            output_field=models.JSONField(),
        ),

        db_comment=(
            "Декларация полей шаблона: типы, UI-контролы, требования, "
            "варианты выбора."
        ),

        verbose_name="Схема полей",
    )

    default_overrides = models.JSONField(
        default=dict,
        null=False,

        db_default=RawSQL(
            "'{}'::jsonb",
            [],
            output_field=models.JSONField(),
        ),

        db_comment=(
            "Значения по умолчанию для реквизитов формы, используемые "
            "в интерфейсе редактирования."
        ),

        verbose_name="Значения по умолчанию",
    )

    content_hash = models.BinaryField(
        null=False,

        db_comment="Хеш содержимого шаблона (BLAKE3).",
        verbose_name="Контент-хэш",
    )

    created_at = models.DateTimeField(
        null=False,
        editable=False,

        db_default=RawSQL(
            "CURRENT_TIMESTAMP",
            [],
            output_field=models.DateTimeField(),
        ),

        db_comment="Дата и время создания ревизии шаблона.",
        verbose_name="Дата и время создания",
    )

    class Meta:
        """Описание полей и поведения записи."""
        managed = True
        db_table = '"documents"."template_revisions"'

        db_table_comment = (
            "История неизменяемых версий HTML-шаблонов документов."
        )

        verbose_name = "Ревизия шаблона документа"
        verbose_name_plural = "Ревизии шаблонов документов"

        constraints = [

            content_hash_length_constraint(
                name="check_documents_template_content_hash_length",

                violation_error_message=(
                    "Проверяет, что хеш содержимого шаблона "
                    "(BLAKE3) имеет длину 32 байта."
                ),
            ),
        ]

        indexes = [

            # Ускоряет получение последней версии шаблона.
            PostgreSQLIndex(
                fields=["template_entity", "-created_at", "-id"],
                name="index_documents_template_revisions_entity",
            ),

            # Ускоряет выборку ревизий шаблонов по автору.
            PostgreSQLIndex(
                fields=["user"],
                name="index_documents_template_revisions_user_id",
            ),

            # Ускоряет поиск ревизий шаблонов по системному коду.
            PostgreSQLIndex(
                fields=["code"],
                name="index_documents_template_revisions_code",
            ),

            # Оптимизирует сортировку ревизий шаблонов по времени создания.
            PostgreSQLIndex(
                fields=["-created_at"],
                name="index_documents_template_revisions_created_at",
            ),

            # Ускоряет поиск по декларации полей шаблона в JSONB.
            PostgreSQLGinIndex(
                fields=["field_schema"],
                name="index_documents_template_revisions_field_schema",
                opclasses=["jsonb_path_ops"],
            ),

            # Ускоряет поиск по значениям по умолчанию в JSONB.
            PostgreSQLGinIndex(
                fields=["default_overrides"],
                name="index_documents_template_revisions_default_overrides",
                opclasses=["jsonb_path_ops"],
            ),
        ]

    def calculate_content_hash(self):
        """Вычисляет хеш полезной нагрузки снимка."""
        return template_revision_content_hash(
            code=self.code,
            title=self.title,
            description=self.description,
            body_html=self.body_html,
            field_schema=self.field_schema,
            default_overrides=self.default_overrides,
        )

    def __str__(self) -> str:
        """
        Возвращает строковое представление ревизии шаблона.
        """

        return (
            f"Ревизия шаблона {self.pk} "
            f"для шаблона {self.template_entity_id}"
        )
