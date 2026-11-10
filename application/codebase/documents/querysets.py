"""Пользовательские витрины документов с приоритетом личного буфера."""

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import BooleanField, Case, CharField, F, Func, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce, NullIf, Trim


class DocumentQuerySet(models.QuerySet):
    """Лента и карточка без чтения чужих буферов."""

    def for_user_feed(self, *, user_id, readiness_stage=None, search=None, include_details=False):
        """Возвращает актуальное содержимое и состояние документа."""
        from documents.models import Revision, RevisionBuffer, StateCache

        buffer = RevisionBuffer.objects.filter(entity_id=OuterRef("pk"), user_id=user_id)
        revision = Revision.objects.filter(entity_id=OuterRef("pk")).order_by("-created_at", "-pk")
        state = StateCache.objects.filter(entity_id=OuterRef("pk"))
        fields = ["topic", "out_number", "template_id", "user_id"]
        if include_details:
            fields += ["field_overrides", "message_bindings", "note", "details", "content_hash"]
        annotations = {
            "_buffer_id": Subquery(buffer.values("pk")[:1]),
            "_buffer_time": Subquery(buffer.values("updated_at")[:1]),
            "_revision_time": Subquery(revision.values("created_at")[:1]),
            "revision_id": Subquery(revision.values("pk")[:1]),
            "display_state": Subquery(state.values("readiness_stage")[:1]),
            "_is_deleted": Subquery(state.values("is_deleted")[:1]),
        }
        for field in fields:
            annotations[f"_buffer_{field}"] = Subquery(buffer.values(field)[:1])
            annotations[f"_revision_{field}"] = Subquery(revision.values(field)[:1])
        queryset = self.annotate(**annotations).annotate(
            display_datetime=Coalesce("_buffer_time", "_revision_time", "created_at"),
            display_topic=Coalesce("_buffer_topic", "_revision_topic", Value("")),
            display_template_id=Coalesce("_buffer_template_id", "_revision_template_id"),
            display_author_id=Coalesce("_buffer_user_id", "_revision_user_id", "user_id", output_field=get_user_model()._meta.pk),
            has_buffer=Case(When(_buffer_id__isnull=False, then=Value(True)), default=Value(False), output_field=BooleanField()),
            **{f"display_{field}": Case(When(_buffer_id__isnull=False, then=F(f"_buffer_{field}")), default=F(f"_revision_{field}")) for field in fields if field not in {"topic", "template_id", "user_id"}},
        )
        author = get_user_model().objects.filter(pk=OuterRef("display_author_id")).annotate(
            name=NullIf(Trim(Func(Value(" "), F("last_name"), F("first_name"), function="CONCAT_WS", output_field=CharField())), Value(""))
        ).values("name")[:1]
        queryset = queryset.annotate(display_author_name=Coalesce(Subquery(author), Value("Неизвестный автор"))).filter(Q(_is_deleted=False) | Q(_is_deleted__isnull=True))
        if readiness_stage:
            queryset = queryset.filter(display_state=readiness_stage)
        if search is not None:
            queryset = queryset.filter(Q(_buffer_id__isnull=False, _buffer_topic__icontains=search) | Q(_buffer_id__isnull=True, _revision_topic__icontains=search))
        return queryset.order_by("-display_datetime", "-pk")

    def for_user_detail(self, *, entity_id, user_id):
        """Возвращает полную карточку выбранного документа."""
        return self.for_user_feed(user_id=user_id, include_details=True).filter(pk=entity_id)


DocumentManager = models.Manager.from_queryset(DocumentQuerySet)
