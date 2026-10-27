from psycopg.types.range import Range
from rest_framework import serializers

from messages.models import (
    MessageEntity,
    MessageType,
    ReadinessStage,
    Revision,
    RevisionBuffer,
    State,
)
from messages.services import record_state_change, upsert_revision_buffer


class DateTimeRangeSerializerField(serializers.Field):
    default_error_messages = {
        "invalid": "Период должен содержать нижнюю и верхнюю границы в формате даты и времени.",
        "bounds": "Границы периода должны быть одним из значений: [], [), (], ().",
    }

    def to_internal_value(self, value):
        if value is None:
            return None
        if not isinstance(value, dict):
            self.fail("invalid")
        if value.get("empty") is True:
            return Range(empty=True)

        lower_value = value.get("lower")
        upper_value = value.get("upper")
        date_time_field = serializers.DateTimeField()
        lower = (
            date_time_field.run_validation(lower_value)
            if lower_value is not None
            else None
        )
        upper = (
            date_time_field.run_validation(upper_value)
            if upper_value is not None
            else None
        )

        bounds = value.get("bounds", "[)")
        if bounds not in {"[]", "[)", "(]", "()"}:
            self.fail("bounds")
        return Range(lower, upper, bounds=bounds)

    def to_representation(self, value):
        if value is None:
            return None
        if getattr(value, "isempty", False):
            return {"empty": True}
        return {
            "lower": value.lower.isoformat() if value.lower is not None else None,
            "upper": value.upper.isoformat() if value.upper is not None else None,
            "bounds": value.bounds,
        }


class HexBinarySerializerField(serializers.Field):
    def to_representation(self, value):
        return bytes(value).hex() if value is not None else None


class MessageFeedSerializer(serializers.Serializer):
    entity_id = serializers.UUIDField(source="pk", read_only=True)
    display_datetime = serializers.DateTimeField(read_only=True)
    display_type = serializers.ChoiceField(
        choices=MessageType.choices,
        read_only=True,
        allow_null=True,
    )
    display_state = serializers.ChoiceField(
        choices=ReadinessStage.choices,
        read_only=True,
        allow_null=True,
    )
    display_region = serializers.CharField(read_only=True, allow_null=True)
    display_text = serializers.CharField(read_only=True)
    display_author_id = serializers.IntegerField(read_only=True)
    display_author_name = serializers.CharField(read_only=True)
    has_buffer = serializers.BooleanField(read_only=True)
    revision_id = serializers.UUIDField(read_only=True, allow_null=True)


class MessageDetailSerializer(MessageFeedSerializer):
    display_period = DateTimeRangeSerializerField(read_only=True, allow_null=True)
    display_note = serializers.CharField(read_only=True, allow_null=True)
    display_details = serializers.JSONField(read_only=True, allow_null=True)
    display_content_hash = HexBinarySerializerField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)


class MessageEntityCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageEntity
        fields = ("id", "created_at")
        read_only_fields = fields


class RevisionBufferSerializer(serializers.ModelSerializer):
    period = DateTimeRangeSerializerField(required=False, allow_null=True)
    user_id = serializers.IntegerField(read_only=True)
    content_hash = HexBinarySerializerField(read_only=True)
    details = serializers.JSONField(required=False, default=dict)

    class Meta:
        model = RevisionBuffer
        fields = (
            "id",
            "entity",
            "parent",
            "user_id",
            "type",
            "period",
            "region",
            "text",
            "note",
            "content_hash",
            "details",
            "updated_at",
        )
        read_only_fields = ("id", "user_id", "content_hash", "updated_at")

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None:
            fields["entity"].read_only = True
        return fields

    def create(self, validated_data):
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
        parent = validated_data.pop("parent", serializers.empty)
        if parent is not serializers.empty:
            validated_data["parent_id"] = parent.pk if parent else None
        for field_name, field_value in validated_data.items():
            setattr(instance, field_name, field_value)
        instance.save()
        instance.refresh_from_db(fields=("updated_at",))
        return instance


class RevisionSerializer(serializers.ModelSerializer):
    period = DateTimeRangeSerializerField(read_only=True, allow_null=True)
    user_id = serializers.IntegerField(read_only=True)
    content_hash = HexBinarySerializerField(read_only=True)

    class Meta:
        model = Revision
        fields = (
            "id",
            "entity",
            "parent",
            "user_id",
            "type",
            "period",
            "region",
            "text",
            "note",
            "content_hash",
            "details",
            "created_at",
        )
        read_only_fields = fields


class StateSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(read_only=True)
    content_hash = HexBinarySerializerField(read_only=True)
    readiness_stage = serializers.ChoiceField(
        choices=ReadinessStage.choices,
        required=False,
    )
    is_starred = serializers.BooleanField(required=False)
    is_archived = serializers.BooleanField(required=False)
    is_deleted = serializers.BooleanField(required=False)
    details = serializers.JSONField(required=False)

    class Meta:
        model = State
        fields = (
            "id",
            "entity",
            "revision",
            "user_id",
            "readiness_stage",
            "is_starred",
            "is_archived",
            "is_deleted",
            "content_hash",
            "details",
            "created_at",
        )
        read_only_fields = ("id", "user_id", "content_hash", "created_at")

    def validate(self, attributes):
        revision = attributes.get("revision")
        entity = attributes.get("entity")
        if revision and entity and revision.entity_id != entity.pk:
            raise serializers.ValidationError(
                {"revision": "Ревизия должна относиться к этому сообщению."}
            )
        return attributes

    def create(self, validated_data):
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
    details = serializers.JSONField(
        source="state_details",
        required=False,
        default=dict,
    )
    is_starred = serializers.BooleanField(required=False, allow_null=True)
    is_archived = serializers.BooleanField(required=False, allow_null=True)
    is_deleted = serializers.BooleanField(required=False, allow_null=True)
