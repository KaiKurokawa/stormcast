"""
Общие перечисления и вспомогательные элементы для моделей документов.
"""

from django.contrib.postgres.indexes import GinIndex, GistIndex
from django.db import models
from django.db.models import F, Func, IntegerField, TextField, Value
from django.db.models.lookups import Exact


CONTENT_HASH_LENGTH = 32

# Максимальная длина идентификатора в PostgreSQL обычно составляет 63 байта.
POSTGRES_MAX_IDENTIFIER_LENGTH = 63


class ReadinessStage(models.TextChoices):
    """
    Стадии готовности документа.

    Соответствует нативному перечислению PostgreSQL:
    documents.readiness_stages.
    """

    DRAFT = "draft", "Черновик"
    REVIEW = "review", "На проверке"
    APPROVED = "approved", "Утверждено"


class CheckConstraint(models.CheckConstraint):
    """
    CHECK-ограничение с поддержкой длинных имён.

    Используется для сохранения полных осмысленных имён ограничений,
    соответствующих эталонной схеме PostgreSQL.
    """

    max_name_length = POSTGRES_MAX_IDENTIFIER_LENGTH


class UniqueConstraint(models.UniqueConstraint):
    """
    UNIQUE-ограничение с поддержкой длинных имён.

    Используется для сохранения полных осмысленных имён ограничений,
    соответствующих эталонной схеме PostgreSQL.
    """

    max_name_length = POSTGRES_MAX_IDENTIFIER_LENGTH


class PostgreSQLIndexNameLengthMixin:
    max_name_length = POSTGRES_MAX_IDENTIFIER_LENGTH


class PostgreSQLIndex(PostgreSQLIndexNameLengthMixin, models.Index):
    pass


class PostgreSQLGinIndex(PostgreSQLIndexNameLengthMixin, GinIndex):
    pass


class PostgreSQLGistIndex(PostgreSQLIndexNameLengthMixin, GistIndex):
    pass


class ContentHashModel(models.Model):
    """
    Абстрактная модель с автоматическим пересчётом контент-хэша.

    Перед сохранением записи вычисляет контент-хэш на основе
    полезной нагрузки модели и добавляет его в update_fields,
    если сохранение выполняется с ограничением по полям.
    """

    class Meta:
        abstract = True

    def calculate_content_hash(self):
        raise NotImplementedError

    def save(self, *args, **kwargs):
        self.content_hash = self.calculate_content_hash()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"content_hash"}
        return super().save(*args, **kwargs)


def content_hash_length_constraint(
    *,
    name: str,
    violation_error_message: str,
) -> CheckConstraint:
    """
    Возвращает CHECK-ограничение на длину контент-хэша.

    Контент-хэш ожидается как 32 байта, что соответствует
    необработанному результату BLAKE3.
    """

    return CheckConstraint(
        condition=Exact(
            Func(
                F("content_hash"),
                function="length",
                output_field=IntegerField(),
            ),
            Value(CONTENT_HASH_LENGTH),
        ),
        name=name,
        violation_error_message=violation_error_message,
    )


def parent_not_self_constraint(
    *,
    name: str,
    violation_error_message: str,
) -> CheckConstraint:
    """
    Возвращает CHECK-ограничение против ссылки на самого себя.

    Поведение эквивалентно проверке:

        parent_id IS DISTINCT FROM entity_id

    При этом NULL в parent_id считается допустимым значением.
    """

    return CheckConstraint(
        condition=(
            models.Q(parent__isnull=True)
            | ~models.Q(parent=F("entity"))
        ),
        name=name,
        violation_error_message=violation_error_message,
    )


def message_bindings_is_array_constraint(
    *,
    name: str,
    violation_error_message: str,
) -> CheckConstraint:
    """
    Возвращает CHECK-ограничение на тип JSON-значения привязок сообщений.

    Поведение эквивалентно проверке:

        jsonb_typeof(message_bindings) = 'array'
    """

    return CheckConstraint(
        condition=Exact(
            Func(
                F("message_bindings"),
                function="jsonb_typeof",
                output_field=TextField(),
            ),
            Value("array"),
        ),
        name=name,
        violation_error_message=violation_error_message,
    )
