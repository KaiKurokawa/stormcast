"""Сериализация документов и проверка допустимых изменений."""

from rest_framework import serializers
from messages.serializers import HexBinarySerializerField
from documents.models import DocumentEntity, ReadinessStage, Revision, RevisionBuffer, State, TemplateEntity, TemplateRevision
from documents.services import record_state_change, upsert_revision_buffer


class DocumentFeedSerializer(serializers.Serializer):
    """Компактная пользовательская лента документов."""
    entity_id = serializers.UUIDField(source="pk", read_only=True)
    display_datetime = serializers.DateTimeField(read_only=True)
    display_state = serializers.ChoiceField(
        choices=ReadinessStage.choices,
        read_only=True,
        allow_null=True,
    )
    display_topic = serializers.CharField(read_only=True)
    display_out_number = serializers.CharField(read_only=True, allow_null=True)
    display_template_id = serializers.UUIDField(read_only=True, allow_null=True)
    display_author_id = serializers.IntegerField(read_only=True)
    display_author_name = serializers.CharField(read_only=True)
    has_buffer = serializers.BooleanField(read_only=True)
    revision_id = serializers.UUIDField(read_only=True, allow_null=True)


class DocumentDetailSerializer(DocumentFeedSerializer):
    """Полная карточка с содержимым актуального снимка."""
    display_field_overrides = serializers.JSONField(read_only=True, allow_null=True)
    display_message_bindings = serializers.JSONField(read_only=True, allow_null=True)
    display_note = serializers.CharField(read_only=True, allow_null=True)
    display_details = serializers.JSONField(read_only=True, allow_null=True)
    display_content_hash = HexBinarySerializerField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)


class DocumentEntityCreateSerializer(serializers.ModelSerializer):
    """Создание документа с идентификатором и временем от базы данных."""
    class Meta:
        """Описание полей и поведения записи."""
        model = DocumentEntity
        fields = ("id", "created_at")
        read_only_fields = fields


class RevisionBufferSerializer(serializers.ModelSerializer):
    """Допустимые изменения личного буфера документа."""
    user_id = serializers.IntegerField(read_only=True)
    content_hash = HexBinarySerializerField(read_only=True)
    details = serializers.JSONField(required=False, default=dict)

    class Meta:
        """Описание полей и поведения записи."""
        model = RevisionBuffer
        fields = (
            "id",
            "entity",
            "parent",
            "user_id",
            "template",
            "out_number",
            "topic",
            "field_overrides",
            "message_bindings",
            "note",
            "content_hash",
            "details",
            "updated_at",
        )
        read_only_fields = ("id", "user_id", "content_hash", "updated_at")

    def get_fields(self):
        """Исключает изменение документа существующего буфера."""
        fields = super().get_fields()
        if self.instance is not None:
            fields["entity"].read_only = True
        return fields

    def validate(self, attributes):
        """Проверяет запрет самоссылок и тип привязок сообщений."""
        entity = attributes.get("entity", getattr(self.instance, "entity", None))
        parent = attributes.get("parent", getattr(self.instance, "parent", None))
        if entity and parent and entity.pk == parent.pk:
            raise serializers.ValidationError({"parent": "Документ не может ссылаться на себя."})
        if "message_bindings" in attributes and not isinstance(attributes["message_bindings"], list):
            raise serializers.ValidationError({"message_bindings": "Ожидается массив."})
        return attributes

    def create(self, validated_data):
        """Создаёт запись через разрешённую предметную операцию."""
        user_id = self.context["user_id"]
        entity = validated_data.pop("entity")
        parent = validated_data.pop("parent", None)
        values = {
            **validated_data,
            "parent_id": parent.pk if parent else None,
        }
        buffer, created = upsert_revision_buffer(
            entity_id=entity.pk,
            user_id=user_id,
            values=values,
        )
        self.context["created"] = created
        return buffer

    def update(self, instance, validated_data):
        """Сохраняет допустимые изменения личного буфера."""
        parent = validated_data.pop("parent", serializers.empty)
        if parent is not serializers.empty:
            validated_data["parent_id"] = parent.pk if parent else None
        for field_name, field_value in validated_data.items():
            setattr(instance, field_name, field_value)
        instance.save()
        instance.refresh_from_db(fields=("updated_at",))
        return instance


class RevisionSerializer(serializers.ModelSerializer):
    """Неизменяемый снимок документа для чтения."""
    user_id = serializers.IntegerField(read_only=True)
    content_hash = HexBinarySerializerField(read_only=True)

    class Meta:
        """Описание полей и поведения записи."""
        model = Revision
        fields = (
            "id",
            "entity",
            "parent",
            "user_id",
            "template",
            "out_number",
            "topic",
            "field_overrides",
            "message_bindings",
            "note",
            "content_hash",
            "details",
            "created_at",
        )
        read_only_fields = fields


class StateSerializer(serializers.ModelSerializer):
    """Добавление записи в журнал состояний документа."""
    user_id = serializers.IntegerField(read_only=True)
    content_hash = HexBinarySerializerField(read_only=True)
    readiness_stage = serializers.ChoiceField(
        choices=ReadinessStage.choices,
        required=False,
    )
    is_archived = serializers.BooleanField(required=False)
    is_deleted = serializers.BooleanField(required=False)
    details = serializers.JSONField(required=False)

    class Meta:
        """Описание полей и поведения записи."""
        model = State
        fields = (
            "id",
            "entity",
            "revision",
            "user_id",
            "readiness_stage",
            "is_archived",
            "is_deleted",
            "content_hash",
            "details",
            "created_at",
        )
        read_only_fields = ("id", "user_id", "content_hash", "created_at")

    def validate(self, attributes):
        """Проверяет согласованность связанных объектов."""
        revision = attributes.get("revision")
        entity = attributes.get("entity")
        if revision and entity and revision.entity_id != entity.pk:
            raise serializers.ValidationError(
                {"revision": "Ревизия должна относиться к этому документу."}
            )
        return attributes

    def create(self, validated_data):
        """Создаёт запись через разрешённую предметную операцию."""
        entity = validated_data.pop("entity")
        revision = validated_data.pop("revision", serializers.empty)
        if revision is not serializers.empty:
            validated_data["revision_id"] = revision.pk if revision else None
        return record_state_change(
            entity_id=entity.pk,
            user_id=self.context["user_id"],
            **validated_data,
        )


class CommitRevisionSerializer(serializers.Serializer):
    """Необязательные флаги состояния при фиксации ревизии."""
    details = serializers.JSONField(
        source="state_details",
        required=False,
        default=dict,
    )
    is_archived = serializers.BooleanField(required=False, allow_null=True)
    is_deleted = serializers.BooleanField(required=False, allow_null=True)


class TemplateEntitySerializer(serializers.ModelSerializer):
    """Создаёт идентификатор шаблона с техническими полями только для чтения."""
    class Meta:
        """Поля реестра шаблонов."""
        model = TemplateEntity
        fields = ("id", "user", "created_at")
        read_only_fields = fields


class TemplateRevisionSerializer(serializers.ModelSerializer):
    """Принимает новый неизменяемый снимок шаблона."""
    content_hash = HexBinarySerializerField(read_only=True)

    class Meta:
        """Поля версии шаблона."""
        model = TemplateRevision
        fields = ("id", "template_entity", "user", "code", "title", "description", "body_html", "field_schema", "default_overrides", "content_hash", "created_at")
        read_only_fields = ("id", "user", "content_hash", "created_at")
