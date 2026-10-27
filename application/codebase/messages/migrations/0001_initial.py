from pathlib import Path

import sqlparse
from django.conf import settings
from django.contrib.postgres.fields import DateTimeRangeField
from django.db import migrations, models
from django.db.models.expressions import RawSQL

from messages.fields import PostgreSQLEnumField
from messages.models.common import (
    PostgreSQLGinIndex,
    PostgreSQLGistIndex,
    PostgreSQLIndex,
    UniqueConstraint,
    content_hash_length_constraint,
    parent_not_self_constraint,
)


def sql_statements(file_name):
    sql_path = Path(__file__).resolve().parent / "sql" / file_name
    return sqlparse.split(sql_path.read_text(encoding="utf-8"))


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.RunSQL(
            sql=sql_statements("types.sql"),
            reverse_sql=[
                "DROP TYPE IF EXISTS messages.message_type",
                "DROP TYPE IF EXISTS messages.readiness_stages",
                "DROP SCHEMA IF EXISTS messages",
            ],
        ),
        migrations.CreateModel(
            name="MessageEntity",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        db_comment="Уникальный идентификатор сообщения.",
                        db_default=RawSQL(
                            "uuid_generate_v7()",
                            [],
                            output_field=models.UUIDField(),
                        ),
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        verbose_name="Идентификатор сообщения",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        db_comment="Дата и время создания сообщения.",
                        db_default=RawSQL(
                            "CURRENT_TIMESTAMP",
                            [],
                            output_field=models.DateTimeField(),
                        ),
                        editable=False,
                        verbose_name="Дата и время создания",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        db_column="user_id",
                        db_index=False,
                        db_comment="Идентификатор пользователя, создавшего сообщение.",
                        on_delete=models.DO_NOTHING,
                        related_name="message_entities",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Автор сообщения",
                    ),
                ),
            ],
            options={
                "db_table": '"messages"."entities"',
                "db_table_comment": (
                    "Реестр сообщений. Хранит идентификаторы сообщений, "
                    "для которых ведется история версий и состояний."
                ),
                "managed": True,
                "verbose_name": "Реестр сообщений",
                "verbose_name_plural": "Реестры сообщений",
                "indexes": [
                    PostgreSQLIndex(
                        fields=["user"],
                        name="index_messages_entities_user_id",
                    ),
                    PostgreSQLIndex(
                        fields=["-created_at"],
                        name="index_messages_entities_created_at",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="RevisionBuffer",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        db_comment=(
                            "Технический суррогатный идентификатор рабочего буфера. "
                            "Добавлен для совместимости с Django ORM и другими инструментами, "
                            "ожидающими один первичный ключ."
                        ),
                        db_default=RawSQL(
                            "uuid_generate_v7()",
                            [],
                            output_field=models.UUIDField(),
                        ),
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        verbose_name="Идентификатор буфера",
                    ),
                ),
                (
                    "type",
                    PostgreSQLEnumField(
                        choices=[
                            ("forecast", "Прогноз"),
                            ("observation", "Наблюдение"),
                            ("warning", "Предупреждение"),
                        ],
                        db_comment="Тип метеорологического события.",
                        enum_type='"messages"."message_type"',
                        max_length=100,
                        verbose_name="Тип события",
                    ),
                ),
                (
                    "period",
                    DateTimeRangeField(
                        blank=True,
                        db_comment="Период действия метеорологического явления.",
                        null=True,
                        verbose_name="Период действия",
                    ),
                ),
                (
                    "region",
                    models.TextField(
                        blank=True,
                        db_comment=(
                            "Ориентировочный район/регион погодного явления. "
                            "Свободное описание до введения отдельного географического справочника."
                        ),
                        null=True,
                        verbose_name="Регион",
                    ),
                ),
                (
                    "text",
                    models.TextField(
                        db_comment="Редактируемый текст сообщения.",
                        verbose_name="Текст сообщения",
                    ),
                ),
                (
                    "note",
                    models.CharField(
                        blank=True,
                        db_comment="Рабочий комментарий к сообщению.",
                        max_length=255,
                        null=True,
                        verbose_name="Комментарий",
                    ),
                ),
                (
                    "content_hash",
                    models.BinaryField(
                        db_comment=(
                            "Контент-хэш снимка сообщения (BLAKE3). Вычисляется от "
                            "канонической полезной нагрузки: type, period, region, text, "
                            "note/details, если они значимы. Не включает технические поля: "
                            "id, entity_id, user_id, created_at, updated_at, сам хэш."
                        ),
                        verbose_name="Контент-хэш",
                    ),
                ),
                (
                    "details",
                    models.JSONField(
                        db_comment="Дополнительные параметры сообщения в формате JSONB.",
                        db_default=RawSQL(
                            "'{}'::jsonb",
                            [],
                            output_field=models.JSONField(),
                        ),
                        verbose_name="Детали",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        db_comment="Дата и время последнего изменения буфера.",
                        db_default=RawSQL(
                            "CURRENT_TIMESTAMP",
                            [],
                            output_field=models.DateTimeField(),
                        ),
                        editable=False,
                        verbose_name="Дата и время изменения",
                    ),
                ),
                (
                    "entity",
                    models.ForeignKey(
                        db_column="entity_id",
                        db_constraint=False,
                        db_index=False,
                        db_comment="Идентификатор сообщения.",
                        on_delete=models.CASCADE,
                        related_name="revision_buffers",
                        to="stormcast_messages.messageentity",
                        verbose_name="Сообщение",
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        db_column="parent_id",
                        db_constraint=False,
                        db_index=False,
                        db_comment=(
                            "Идентификатор сообщения, к которому относится "
                            "корректировка или отмена."
                        ),
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name="revision_buffer_children",
                        to="stormcast_messages.messageentity",
                        verbose_name="Родительское сообщение",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        db_column="user_id",
                        db_index=False,
                        db_comment="Идентификатор пользователя, редактирующего сообщение.",
                        on_delete=models.DO_NOTHING,
                        related_name="message_revision_buffers",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Редактор",
                    ),
                ),
            ],
            options={
                "db_table": '"messages"."revision_buffer"',
                "db_table_comment": (
                    "Буфер несохраненных изменений сообщений. Хранит текущее "
                    "рабочее состояние для каждого пользователя и сообщения."
                ),
                "managed": True,
                "verbose_name": "Буфер правок сообщения",
                "verbose_name_plural": "Буферы правок сообщений",
                "constraints": [
                    UniqueConstraint(
                        fields=("entity", "user"),
                        name="messages_revision_buffer_entity_id_user_id_unique",
                        violation_error_message=(
                            "Доменная уникальность рабочего буфера: одно сообщение может "
                            "иметь только один рабочий буфер для одного пользователя."
                        ),
                    ),
                    content_hash_length_constraint(
                        name="check_revision_buffer_content_hash_length",
                        violation_error_message=(
                            "Проверяет, что контент-хэш содержимого сообщения "
                            "(BLAKE3) имеет длину 32 байта."
                        ),
                    ),
                    parent_not_self_constraint(
                        name="check_revision_buffer_parent_not_self",
                        violation_error_message=(
                            "Запрещает самопривязку, когда сообщение ссылается само на себя."
                        ),
                    ),
                ],
                "indexes": [
                    PostgreSQLIndex(
                        fields=["parent"],
                        name="index_messages_revision_buffer_parent",
                    ),
                    PostgreSQLIndex(
                        fields=["user"],
                        name="index_messages_revision_buffer_user_id",
                    ),
                    PostgreSQLGinIndex(
                        fields=["text"],
                        name="index_messages_revision_buffer_text_trigram",
                        opclasses=["gin_trgm_ops"],
                    ),
                    PostgreSQLGinIndex(
                        fields=["details"],
                        name="index_messages_revision_buffer_details",
                        opclasses=["jsonb_path_ops"],
                    ),
                    PostgreSQLIndex(
                        fields=["-updated_at"],
                        name="index_messages_revision_buffer_updated_at",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Revision",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        db_comment="Уникальный идентификатор ревизии.",
                        db_default=RawSQL(
                            "uuid_generate_v7()",
                            [],
                            output_field=models.UUIDField(),
                        ),
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        verbose_name="Идентификатор ревизии",
                    ),
                ),
                (
                    "type",
                    PostgreSQLEnumField(
                        choices=[
                            ("forecast", "Прогноз"),
                            ("observation", "Наблюдение"),
                            ("warning", "Предупреждение"),
                        ],
                        db_comment=(
                            "Тип метеорологического события на момент создания ревизии."
                        ),
                        enum_type='"messages"."message_type"',
                        max_length=100,
                        verbose_name="Тип события",
                    ),
                ),
                (
                    "period",
                    DateTimeRangeField(
                        blank=True,
                        db_comment="Период действия метеорологического явления.",
                        null=True,
                        verbose_name="Период действия",
                    ),
                ),
                (
                    "region",
                    models.TextField(
                        blank=True,
                        db_comment=(
                            "Ориентировочный район/регион погодного явления на момент создания ревизии."
                        ),
                        null=True,
                        verbose_name="Регион",
                    ),
                ),
                (
                    "text",
                    models.TextField(
                        db_comment="Текст сообщения в данной ревизии.",
                        verbose_name="Текст ревизии",
                    ),
                ),
                (
                    "note",
                    models.CharField(
                        blank=True,
                        db_comment="Комментарий к ревизии.",
                        max_length=255,
                        null=True,
                        verbose_name="Комментарий",
                    ),
                ),
                (
                    "content_hash",
                    models.BinaryField(
                        db_comment=(
                            "Контент-хэш снимка сообщения (BLAKE3). Вычисляется от "
                            "канонической полезной нагрузки: type, period, region, text, "
                            "note/details, если они значимы. Не включает технические поля: "
                            "id, entity_id, user_id, created_at, сам хэш."
                        ),
                        verbose_name="Контент-хэш",
                    ),
                ),
                (
                    "details",
                    models.JSONField(
                        db_comment="Дополнительные параметры сообщения в формате JSONB.",
                        db_default=RawSQL(
                            "'{}'::jsonb",
                            [],
                            output_field=models.JSONField(),
                        ),
                        verbose_name="Детали",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        db_comment="Дата и время создания ревизии.",
                        db_default=RawSQL(
                            "CURRENT_TIMESTAMP",
                            [],
                            output_field=models.DateTimeField(),
                        ),
                        editable=False,
                        verbose_name="Дата и время создания",
                    ),
                ),
                (
                    "entity",
                    models.ForeignKey(
                        db_column="entity_id",
                        db_constraint=False,
                        db_index=False,
                        db_comment="Идентификатор сообщения.",
                        on_delete=models.CASCADE,
                        related_name="revisions",
                        to="stormcast_messages.messageentity",
                        verbose_name="Сообщение",
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        db_column="parent_id",
                        db_constraint=False,
                        db_index=False,
                        db_comment=(
                            "Идентификатор сообщения, к которому относится "
                            "корректировка или отмена."
                        ),
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name="revision_children",
                        to="stormcast_messages.messageentity",
                        verbose_name="Родительское сообщение",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        db_column="user_id",
                        db_index=False,
                        db_comment="Идентификатор пользователя, создавшего ревизию.",
                        on_delete=models.DO_NOTHING,
                        related_name="message_revisions",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Автор ревизии",
                    ),
                ),
            ],
            options={
                "db_table": '"messages"."revisions"',
                "db_table_comment": (
                    "История зафиксированных версий текста и параметров сообщений."
                ),
                "managed": True,
                "verbose_name": "Ревизия сообщения",
                "verbose_name_plural": "Ревизии сообщений",
                "constraints": [
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
                            "Запрещает самопривязку, когда сообщение ссылается само на себя."
                        ),
                    ),
                ],
                "indexes": [
                    PostgreSQLIndex(
                        fields=["entity", "-created_at", "-id"],
                        name="index_messages_revisions_message_time",
                    ),
                    PostgreSQLIndex(
                        fields=["parent"],
                        name="index_messages_revisions_parent",
                    ),
                    PostgreSQLGistIndex(
                        fields=["period"],
                        name="index_messages_revisions_period_gist",
                    ),
                    PostgreSQLGinIndex(
                        fields=["text"],
                        name="index_messages_revisions_text_trigram",
                        opclasses=["gin_trgm_ops"],
                    ),
                    PostgreSQLIndex(
                        fields=["type"],
                        name="index_messages_revisions_type",
                    ),
                    PostgreSQLIndex(
                        fields=["user"],
                        name="index_messages_revisions_user_id",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="StateCache",
            fields=[
                (
                    "revision",
                    models.ForeignKey(
                        blank=True,
                        db_column="revision_id",
                        db_constraint=False,
                        db_index=False,
                        db_comment=(
                            "Идентификатор ревизии, к которой относится текущее "
                            "состояние готовности (если применимо)."
                        ),
                        null=True,
                        on_delete=models.RESTRICT,
                        related_name="state_cache_entries",
                        to="stormcast_messages.revision",
                        verbose_name="Ревизия",
                    ),
                ),
                (
                    "readiness_stage",
                    PostgreSQLEnumField(
                        choices=[
                            ("draft", "Черновик"),
                            ("review", "На проверке"),
                            ("approved", "Утверждено"),
                        ],
                        db_comment="Стадия готовности сообщения.",
                        db_default=RawSQL(
                            "'draft'::messages.readiness_stages",
                            [],
                            output_field=models.CharField(max_length=50),
                        ),
                        enum_type='"messages"."readiness_stages"',
                        max_length=50,
                        verbose_name="Стадия готовности",
                    ),
                ),
                (
                    "is_starred",
                    models.BooleanField(
                        db_comment="Признак отметки сообщения как важного.",
                        db_default=False,
                        verbose_name="Важное",
                    ),
                ),
                (
                    "is_archived",
                    models.BooleanField(
                        db_comment="Признак нахождения сообщения в архиве.",
                        db_default=False,
                        verbose_name="В архиве",
                    ),
                ),
                (
                    "is_deleted",
                    models.BooleanField(
                        db_comment="Признак логического удаления сообщения.",
                        db_default=False,
                        verbose_name="Удалено",
                    ),
                ),
                (
                    "content_hash",
                    models.BinaryField(
                        db_comment=(
                            "Контент-хэш снимка состояния сообщения (BLAKE3). "
                            "Вычисляется от полезной нагрузки состояния: readiness_stage, "
                            "is_starred, is_archived, is_deleted, details. Не включает "
                            "контекст: id, entity_id, revision_id, user_id, updated_at."
                        ),
                        verbose_name="Контент-хэш",
                    ),
                ),
                (
                    "details",
                    models.JSONField(
                        db_comment="Дополнительные сведения о текущем состоянии.",
                        db_default=RawSQL(
                            "'{}'::jsonb",
                            [],
                            output_field=models.JSONField(),
                        ),
                        verbose_name="Детали",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        db_comment="Дата и время последнего изменения состояния.",
                        db_default=RawSQL(
                            "CURRENT_TIMESTAMP",
                            [],
                            output_field=models.DateTimeField(),
                        ),
                        editable=False,
                        verbose_name="Дата и время изменения",
                    ),
                ),
                (
                    "entity",
                    models.OneToOneField(
                        db_column="entity_id",
                        db_constraint=False,
                        db_index=False,
                        db_comment="Идентификатор сообщения.",
                        on_delete=models.CASCADE,
                        primary_key=True,
                        related_name="state_cache",
                        serialize=False,
                        to="stormcast_messages.messageentity",
                        verbose_name="Сообщение",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        db_column="user_id",
                        db_index=False,
                        db_comment=(
                            "Идентификатор пользователя, последним изменившего состояние."
                        ),
                        on_delete=models.DO_NOTHING,
                        related_name="message_state_caches",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Автор изменения",
                    ),
                ),
            ],
            options={
                "db_table": '"messages"."state_cache"',
                "db_table_comment": (
                    "Текущие состояния сообщений. Обновляется автоматически "
                    "на основе журнала messages.states."
                ),
                "managed": True,
                "verbose_name": "Кэш состояния сообщения",
                "verbose_name_plural": "Кэш состояний сообщений",
                "constraints": [
                    content_hash_length_constraint(
                        name="check_state_cache_content_hash_length",
                        violation_error_message=(
                            "Проверяет, что контент-хэш снимка состояния "
                            "(BLAKE3) имеет длину 32 байта."
                        ),
                    ),
                ],
                "indexes": [
                    PostgreSQLIndex(
                        fields=["entity", "readiness_stage"],
                        condition=models.Q(is_deleted=False),
                        name="index_messages_state_cache_entity_stage_active",
                    ),
                    PostgreSQLIndex(
                        fields=["readiness_stage"],
                        condition=models.Q(is_archived=False),
                        name="index_messages_state_cache_stage_not_archived",
                    ),
                    PostgreSQLIndex(
                        fields=["readiness_stage"],
                        condition=models.Q(
                            readiness_stage="draft",
                            is_deleted=False,
                        ),
                        name="index_messages_state_cache_draft",
                    ),
                    PostgreSQLIndex(
                        fields=["entity"],
                        condition=models.Q(is_starred=True, is_deleted=False),
                        name="index_messages_state_cache_starred",
                    ),
                    PostgreSQLGinIndex(
                        fields=["details"],
                        name="index_messages_state_cache_details",
                        opclasses=["jsonb_path_ops"],
                    ),
                    PostgreSQLIndex(
                        fields=["-updated_at"],
                        name="index_messages_state_cache_updated_at",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="State",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        db_comment="Уникальный идентификатор записи истории.",
                        db_default=RawSQL(
                            "uuid_generate_v7()",
                            [],
                            output_field=models.UUIDField(),
                        ),
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        verbose_name="Идентификатор записи",
                    ),
                ),
                (
                    "readiness_stage",
                    PostgreSQLEnumField(
                        choices=[
                            ("draft", "Черновик"),
                            ("review", "На проверке"),
                            ("approved", "Утверждено"),
                        ],
                        db_comment="Стадия готовности сообщения на момент записи.",
                        db_default=RawSQL(
                            "'draft'::messages.readiness_stages",
                            [],
                            output_field=models.CharField(max_length=50),
                        ),
                        enum_type='"messages"."readiness_stages"',
                        max_length=50,
                        verbose_name="Стадия готовности",
                    ),
                ),
                (
                    "is_starred",
                    models.BooleanField(
                        db_comment=(
                            "Признак отметки сообщения как важного на момент записи."
                        ),
                        db_default=False,
                        verbose_name="Важное",
                    ),
                ),
                (
                    "is_archived",
                    models.BooleanField(
                        db_comment=(
                            "Признак нахождения сообщения в архиве на момент записи."
                        ),
                        db_default=False,
                        verbose_name="В архиве",
                    ),
                ),
                (
                    "is_deleted",
                    models.BooleanField(
                        db_comment=(
                            "Признак логического удаления сообщения на момент записи."
                        ),
                        db_default=False,
                        verbose_name="Удалено",
                    ),
                ),
                (
                    "content_hash",
                    models.BinaryField(
                        db_comment=(
                            "Контент-хэш снимка состояния сообщения (BLAKE3). Вычисляется "
                            "от полезной нагрузки состояния: readiness_stage, is_starred, "
                            "is_archived, is_deleted, details. Не включает контекст: id, "
                            "entity_id, revision_id, user_id, created_at."
                        ),
                        verbose_name="Контент-хэш",
                    ),
                ),
                (
                    "details",
                    models.JSONField(
                        db_comment=(
                            "Дополнительные сведения о событии изменения состояния."
                        ),
                        db_default=RawSQL(
                            "'{}'::jsonb",
                            [],
                            output_field=models.JSONField(),
                        ),
                        verbose_name="Детали",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        db_comment="Дата и время записи состояния.",
                        db_default=RawSQL(
                            "CURRENT_TIMESTAMP",
                            [],
                            output_field=models.DateTimeField(),
                        ),
                        editable=False,
                        verbose_name="Дата и время записи",
                    ),
                ),
                (
                    "entity",
                    models.ForeignKey(
                        db_column="entity_id",
                        db_constraint=False,
                        db_index=False,
                        db_comment="Идентификатор сообщения.",
                        on_delete=models.CASCADE,
                        related_name="states",
                        to="stormcast_messages.messageentity",
                        verbose_name="Сообщение",
                    ),
                ),
                (
                    "revision",
                    models.ForeignKey(
                        blank=True,
                        db_column="revision_id",
                        db_constraint=False,
                        db_index=False,
                        db_comment=(
                            "Идентификатор ревизии, к которой относится изменение "
                            "состояния готовности (если применимо)."
                        ),
                        null=True,
                        on_delete=models.RESTRICT,
                        related_name="states",
                        to="stormcast_messages.revision",
                        verbose_name="Ревизия",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        db_column="user_id",
                        db_index=False,
                        db_comment="Идентификатор пользователя, изменившего состояние.",
                        on_delete=models.DO_NOTHING,
                        related_name="message_states",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Автор изменения",
                    ),
                ),
            ],
            options={
                "db_table": '"messages"."states"',
                "db_table_comment": (
                    "История изменений состояний сообщений. Каждая запись "
                    "содержит полное состояние сообщения на момент изменения."
                ),
                "managed": True,
                "verbose_name": "Запись журнала состояний",
                "verbose_name_plural": "Журнал состояний сообщений",
                "constraints": [
                    content_hash_length_constraint(
                        name="check_states_content_hash_length",
                        violation_error_message=(
                            "Проверяет, что контент-хэш снимка состояния "
                            "(BLAKE3) имеет длину 32 байта."
                        ),
                    ),
                ],
                "indexes": [
                    PostgreSQLIndex(
                        fields=["entity", "created_at"],
                        name="index_messages_states_chronology",
                    ),
                    PostgreSQLIndex(
                        fields=["-created_at"],
                        name="index_messages_states_created_at",
                    ),
                    PostgreSQLIndex(
                        fields=["revision"],
                        name="index_messages_states_revision_id",
                    ),
                ],
            },
        ),
        migrations.RunSQL(
            sql=sql_statements("foreign_keys.sql"),
            reverse_sql=sql_statements("drop_foreign_keys.sql"),
        ),
        migrations.RunSQL(
            sql=sql_statements("constraint_names.sql"),
            reverse_sql=sql_statements("restore_constraint_names.sql"),
        ),
    ]
