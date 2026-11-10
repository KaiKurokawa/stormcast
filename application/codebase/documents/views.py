"""API документов с изолированными личными буферами."""

from django.db import DatabaseError
from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from documents.models import (
    DocumentEntity,
    ReadinessStage,
    Revision,
    RevisionBuffer,
    State,
    TemplateEntity,
    TemplateRevision,
)
from documents.serializers import (
    CommitRevisionSerializer,
    DocumentDetailSerializer,
    DocumentEntityCreateSerializer,
    DocumentFeedSerializer,
    RevisionBufferSerializer,
    RevisionSerializer,
    StateSerializer,
    TemplateEntitySerializer,
    TemplateRevisionSerializer,
)
from documents.services import commit_revision_buffer


def authenticated_user_id(request):
    """Получает идентификатор аутентифицированного пользователя Django."""
    if request.user.pk is None:
        raise ValidationError(
            {"user": "Для работы с документами требуется пользователь Django."}
        )
    return request.user.pk


class IntegrityErrorMixin:
    """Преобразует ожидаемые нарушения целостности в ошибку запроса."""

    def handle_exception(self, exception):
        """Не раскрывает SQL и внутренние имена ограничений клиенту."""
        if isinstance(exception, DatabaseError):
            sqlstate = getattr(exception.__cause__, "sqlstate", "") or ""
            if sqlstate.startswith(("22", "23")) or sqlstate == "P0001":
                exception = ValidationError({"errors": "Операция нарушает ограничения целостности документа."})
        return super().handle_exception(exception)


class DocumentEntityViewSet(
    IntegrityErrorMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Представление данных документов."""
    ordering_fields = ("display_datetime",)

    def get_queryset(self):
        """Возвращает доступные текущему пользователю записи."""
        user_id = authenticated_user_id(self.request)
        if self.action == "retrieve":
            return DocumentEntity.objects.for_user_detail(
                entity_id=self.kwargs.get(self.lookup_url_kwarg or self.lookup_field),
                user_id=user_id,
            )

        parameters = self.request.query_params
        readiness_stage = parameters.get("state")
        if readiness_stage and readiness_stage not in ReadinessStage.values:
            raise ValidationError({"state": "Неизвестная стадия готовности."})
        return DocumentEntity.objects.for_user_feed(
            user_id=user_id,
            readiness_stage=readiness_stage,
            search=parameters.get("search"),
        )

    def get_serializer_class(self):
        """Выбирает представление данных для текущей операции."""
        if self.action == "create":
            return DocumentEntityCreateSerializer
        if self.action == "list":
            return DocumentFeedSerializer
        return DocumentDetailSerializer

    def get_serializer_context(self):
        """Передаёт идентификатор текущего пользователя сериализатору."""
        context = super().get_serializer_context()
        context["user_id"] = authenticated_user_id(self.request)
        return context

    def perform_create(self, serializer):
        """Назначает автора из аутентифицированного запроса."""
        serializer.save(user_id=authenticated_user_id(self.request))


class RevisionBufferViewSet(IntegrityErrorMixin, viewsets.ModelViewSet):
    """Представление данных документов."""
    serializer_class = RevisionBufferSerializer
    filterset_fields = ("entity", "template")
    ordering_fields = ("updated_at",)
    search_fields = ("topic", "out_number", "note")

    def create(self, request, *args, **kwargs):
        """Создаёт запись через разрешённую предметную операцию."""
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
        """Возвращает доступные текущему пользователю записи."""
        return RevisionBuffer.objects.filter(
            user_id=authenticated_user_id(self.request)
        ).select_related("entity", "parent", "user")

    def get_serializer_context(self):
        """Передаёт идентификатор текущего пользователя сериализатору."""
        context = super().get_serializer_context()
        context["user_id"] = authenticated_user_id(self.request)
        return context

    @action(detail=True, methods=("post",))
    def commit(self, request, pk=None):
        """Фиксирует личный буфер и возвращает неизменяемую ревизию."""
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
    """Представление данных документов."""
    serializer_class = RevisionSerializer
    filterset_fields = ("entity", "template")
    ordering_fields = ("created_at",)
    search_fields = ("topic", "out_number", "note")

    def get_queryset(self):
        """Возвращает доступные текущему пользователю записи."""
        return Revision.objects.filter(
            Q(entity__state_cache__is_deleted=False)
            | Q(entity__state_cache__isnull=True)
        ).select_related("entity", "parent", "user")


class StateViewSet(
    IntegrityErrorMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Представление данных документов."""
    serializer_class = StateSerializer
    filterset_fields = ("entity", "revision", "readiness_stage")
    ordering_fields = ("created_at",)

    def get_queryset(self):
        """Возвращает доступные текущему пользователю записи."""
        return State.objects.filter(
            Q(entity__state_cache__is_deleted=False)
            | Q(entity__state_cache__isnull=True)
        ).select_related("entity", "revision", "user")

    def get_serializer_context(self):
        """Передаёт идентификатор текущего пользователя сериализатору."""
        context = super().get_serializer_context()
        context["user_id"] = authenticated_user_id(self.request)
        return context


class TemplateEntityViewSet(IntegrityErrorMixin, mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """Создание и просмотр реестра шаблонов без изменения истории."""
    queryset = TemplateEntity.objects.select_related("user").order_by("-created_at", "-pk")
    serializer_class = TemplateEntitySerializer
    ordering_fields = ("created_at",)

    def perform_create(self, serializer):
        """Назначает автора шаблона."""
        serializer.save(user_id=authenticated_user_id(self.request))


class TemplateRevisionViewSet(IntegrityErrorMixin, mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """Создание и просмотр неизменяемых версий шаблонов."""
    queryset = TemplateRevision.objects.select_related("user", "template_entity").order_by("-created_at", "-pk")
    serializer_class = TemplateRevisionSerializer
    filterset_fields = ("template_entity", "code")
    search_fields = ("code", "title", "description")
    ordering_fields = ("created_at", "code", "title")

    def perform_create(self, serializer):
        """Назначает автора новой версии шаблона."""
        serializer.save(user_id=authenticated_user_id(self.request))
