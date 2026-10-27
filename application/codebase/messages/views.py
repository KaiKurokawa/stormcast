from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from messages.models import (
    MessageEntity,
    MessageType,
    ReadinessStage,
    Revision,
    RevisionBuffer,
    State,
)
from messages.serializers import (
    CommitRevisionSerializer,
    MessageDetailSerializer,
    MessageEntityCreateSerializer,
    MessageFeedSerializer,
    RevisionBufferSerializer,
    RevisionSerializer,
    StateSerializer,
)
from messages.services import commit_revision_buffer


def authenticated_user_id(request):
    if request.user.pk is None:
        raise ValidationError(
            {"user": "Для работы с сообщениями требуется пользователь Django."}
        )
    return request.user.pk


class MessageEntityViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    ordering_fields = ("display_datetime",)

    def get_queryset(self):
        user_id = authenticated_user_id(self.request)
        if self.action == "retrieve":
            return MessageEntity.objects.for_user_detail(
                entity_id=self.kwargs.get(self.lookup_url_kwarg or self.lookup_field),
                user_id=user_id,
            )

        parameters = self.request.query_params
        message_type = parameters.get("type")
        readiness_stage = parameters.get("state")
        if message_type and message_type not in MessageType.values:
            raise ValidationError({"type": "Неизвестный тип сообщения."})
        if readiness_stage and readiness_stage not in ReadinessStage.values:
            raise ValidationError({"state": "Неизвестная стадия готовности."})
        return MessageEntity.objects.for_user_feed(
            user_id=user_id,
            message_type=message_type,
            readiness_stage=readiness_stage,
            search=parameters.get("search"),
        )

    def get_serializer_class(self):
        if self.action == "create":
            return MessageEntityCreateSerializer
        if self.action == "list":
            return MessageFeedSerializer
        return MessageDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["user_id"] = authenticated_user_id(self.request)
        return context

    def perform_create(self, serializer):
        serializer.save(user_id=authenticated_user_id(self.request))


class RevisionBufferViewSet(viewsets.ModelViewSet):
    serializer_class = RevisionBufferSerializer
    filterset_fields = ("entity", "type")
    ordering_fields = ("updated_at",)
    search_fields = ("text", "region", "note")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        response_status = (
            status.HTTP_201_CREATED
            if serializer.context.get("created", True)
            else status.HTTP_200_OK
        )
        return Response(serializer.data, status=response_status)

    def get_queryset(self):
        return RevisionBuffer.objects.filter(
            user_id=authenticated_user_id(self.request)
        ).select_related("entity", "parent", "user")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["user_id"] = authenticated_user_id(self.request)
        return context

    @action(detail=True, methods=("post",))
    def commit(self, request, pk=None):
        buffer = self.get_object()
        serializer = CommitRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        revision, created = commit_revision_buffer(
            buffer_id=buffer.pk,
            user_id=authenticated_user_id(request),
            **serializer.validated_data,
        )
        response_serializer = RevisionSerializer(
            revision,
            context=self.get_serializer_context(),
        )
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class RevisionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RevisionSerializer
    filterset_fields = ("entity", "type")
    ordering_fields = ("created_at",)
    search_fields = ("text", "region", "note")

    def get_queryset(self):
        return Revision.objects.filter(
            Q(entity__state_cache__is_deleted=False)
            | Q(entity__state_cache__isnull=True)
        ).select_related("entity", "parent", "user")


class StateViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = StateSerializer
    filterset_fields = ("entity", "revision", "readiness_stage")
    ordering_fields = ("created_at",)

    def get_queryset(self):
        return State.objects.filter(
            Q(entity__state_cache__is_deleted=False)
            | Q(entity__state_cache__isnull=True)
        ).select_related("entity", "revision", "user")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["user_id"] = authenticated_user_id(self.request)
        return context
