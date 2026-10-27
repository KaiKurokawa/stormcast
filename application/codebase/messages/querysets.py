from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import (
    BooleanField,
    Case,
    CharField,
    F,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
    Func,
)
from django.db.models.functions import Coalesce, NullIf, Trim


class MessageQuerySet(models.QuerySet):
    def for_user_feed(
        self,
        *,
        user_id,
        message_type=None,
        readiness_stage=None,
        search=None,
        include_details=False,
    ):
        from messages.models import (
            Revision,
            RevisionBuffer,
            StateCache,
        )

        user_buffer = RevisionBuffer.objects.filter(
            entity_id=OuterRef("pk"),
            user_id=user_id,
        )
        latest_revision = Revision.objects.filter(
            entity_id=OuterRef("pk"),
        ).order_by("-created_at", "-pk")
        current_state = StateCache.objects.filter(entity_id=OuterRef("pk"))

        queryset = self.annotate(
            _buffer_id=Subquery(user_buffer.values("id")[:1]),
            _buffer_type=Subquery(user_buffer.values("type")[:1]),
            _buffer_period=Subquery(user_buffer.values("period")[:1]),
            _buffer_region=Subquery(user_buffer.values("region")[:1]),
            _buffer_text=Subquery(user_buffer.values("text")[:1]),
            _buffer_updated_at=Subquery(user_buffer.values("updated_at")[:1]),
            _buffer_user_id=Subquery(user_buffer.values("user_id")[:1]),
            _revision_id=Subquery(latest_revision.values("id")[:1]),
            _revision_type=Subquery(latest_revision.values("type")[:1]),
            _revision_region=Subquery(latest_revision.values("region")[:1]),
            _revision_text=Subquery(latest_revision.values("text")[:1]),
            _revision_created_at=Subquery(latest_revision.values("created_at")[:1]),
            _revision_user_id=Subquery(latest_revision.values("user_id")[:1]),
            _readiness_stage=Subquery(current_state.values("readiness_stage")[:1]),
            _is_deleted=Subquery(current_state.values("is_deleted")[:1]),
        ).annotate(
            display_datetime=Coalesce(
                F("_buffer_updated_at"),
                F("_revision_created_at"),
                F("created_at"),
            ),
            display_type=Coalesce(F("_buffer_type"), F("_revision_type")),
            display_state=F("_readiness_stage"),
            display_text=Coalesce(F("_buffer_text"), F("_revision_text"), Value("")),
            display_author_id=Coalesce(
                F("_buffer_user_id"),
                F("_revision_user_id"),
                F("user_id"),
            ),
            has_buffer=Case(
                When(_buffer_id__isnull=False, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
            revision_id=F("_revision_id"),
        ).annotate(
            display_region=Case(
                When(_buffer_id__isnull=False, then=F("_buffer_region")),
                default=F("_revision_region"),
            ),
        )

        if include_details:
            queryset = queryset.annotate(
                _buffer_note=Subquery(user_buffer.values("note")[:1]),
                _buffer_details=Subquery(user_buffer.values("details")[:1]),
                _buffer_content_hash=Subquery(
                    user_buffer.values("content_hash")[:1]
                ),
                _revision_note=Subquery(latest_revision.values("note")[:1]),
                _revision_details=Subquery(
                    latest_revision.values("details")[:1]
                ),
                _revision_content_hash=Subquery(
                    latest_revision.values("content_hash")[:1]
                ),
                display_period=Case(
                    When(_buffer_id__isnull=False, then=F("_buffer_period")),
                    default=Subquery(latest_revision.values("period")[:1]),
                ),
                display_note=Case(
                    When(_buffer_id__isnull=False, then=F("_buffer_note")),
                    default=F("_revision_note"),
                ),
                display_details=Case(
                    When(_buffer_id__isnull=False, then=F("_buffer_details")),
                    default=F("_revision_details"),
                ),
                display_content_hash=Case(
                    When(_buffer_id__isnull=False, then=F("_buffer_content_hash")),
                    default=F("_revision_content_hash"),
                ),
            )

        author_name = (
            Func(
                Value(" "),
                F("last_name"),
                F("first_name"),
                function="CONCAT_WS",
                output_field=CharField(),
            )
        )
        author = (
            get_user_model().objects.filter(pk=OuterRef("display_author_id"))
            .annotate(
                _display_name=Coalesce(
                    NullIf(Trim(author_name), Value("")),
                    F("username"),
                    output_field=CharField(max_length=512),
                )
            )
            .values("_display_name")[:1]
        )
        queryset = queryset.annotate(
            display_author_name=Coalesce(
                Subquery(author),
                Value("Неизвестный автор"),
                output_field=CharField(max_length=512),
            )
        ).filter(Q(_is_deleted=False) | Q(_is_deleted__isnull=True))

        if message_type:
            queryset = queryset.filter(display_type=message_type)
        if readiness_stage:
            queryset = queryset.filter(display_state=readiness_stage)
        if search is not None:
            queryset = queryset.filter(
                Q(_buffer_id__isnull=False, _buffer_text__icontains=search)
                | Q(_buffer_id__isnull=True, _revision_text__icontains=search)
            )

        return queryset.order_by("-display_datetime")

    def for_user_detail(self, *, entity_id, user_id):
        return self.for_user_feed(
            user_id=user_id,
            include_details=True,
        ).filter(pk=entity_id)


MessageManager = models.Manager.from_queryset(MessageQuerySet)
