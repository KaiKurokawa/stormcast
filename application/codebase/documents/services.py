"""Транзакционные операции с буферами и состояниями документов."""

from django.db import transaction

from documents.models import DocumentEntity, Revision, RevisionBuffer, State, StateCache


_UNSET = object()


@transaction.atomic
def upsert_revision_buffer(*, entity_id, user_id, values):
    """Атомарно создаёт или обновляет личный рабочий буфер."""
    DocumentEntity.objects.select_for_update().get(pk=entity_id)
    buffer, created = RevisionBuffer.objects.update_or_create(
        entity_id=entity_id,
        user_id=user_id,
        defaults=values,
    )
    if not created:
        buffer.refresh_from_db(fields=("updated_at",))
    return buffer, created


@transaction.atomic
def commit_revision_buffer(
    *,
    buffer_id,
    user_id,
    state_details=None,
    is_archived=None,
    is_deleted=None,
):
    """Фиксирует снимок и состояние, исключая повтор последней ревизии."""
    entity_id = RevisionBuffer.objects.values_list("entity_id", flat=True).get(pk=buffer_id, user_id=user_id)
    DocumentEntity.objects.select_for_update().get(pk=entity_id)
    buffer = RevisionBuffer.objects.select_for_update().get(
        pk=buffer_id,
        user_id=user_id,
    )
    current_state = (
        StateCache.objects.select_for_update()
        .filter(entity_id=buffer.entity_id)
        .first()
    )
    latest_revision = (
        Revision.objects.filter(entity_id=buffer.entity_id)
        .order_by("-created_at", "-pk")
        .first()
    )

    if latest_revision and latest_revision.content_hash == buffer.content_hash:
        buffer.delete()
        return latest_revision, False

    revision = Revision.objects.create(
        entity_id=buffer.entity_id,
        parent_id=buffer.parent_id,
        user_id=buffer.user_id,
        template_id=buffer.template_id,
        out_number=buffer.out_number,
        topic=buffer.topic,
        field_overrides=buffer.field_overrides,
        message_bindings=buffer.message_bindings,
        note=buffer.note,
        details=buffer.details,
    )

    State.objects.create(
        entity_id=buffer.entity_id,
        revision_id=revision.pk,
        user_id=buffer.user_id,
        readiness_stage="draft",
        is_archived=(
            is_archived
            if is_archived is not None
            else current_state.is_archived if current_state else False
        ),
        is_deleted=(
            is_deleted
            if is_deleted is not None
            else current_state.is_deleted if current_state else False
        ),
        details={} if state_details is None else state_details,
    )

    buffer.delete()
    return revision, True


@transaction.atomic
def record_state_change(
    *,
    entity_id,
    user_id,
    revision_id=_UNSET,
    readiness_stage=None,
    is_archived=None,
    is_deleted=None,
    details=None,
):
    """Добавляет состояние в журнал, сохраняя неуказанные значения."""
    DocumentEntity.objects.select_for_update().get(pk=entity_id)
    current_state = (
        StateCache.objects.select_for_update()
        .filter(entity_id=entity_id)
        .first()
    )

    if revision_id is _UNSET:
        revision_id = current_state.revision_id if current_state else None

    return State.objects.create(
        entity_id=entity_id,
        revision_id=revision_id,
        user_id=user_id,
        readiness_stage=(
            readiness_stage
            or (current_state.readiness_stage if current_state else "draft")
        ),
        is_archived=(
            is_archived
            if is_archived is not None
            else current_state.is_archived if current_state else False
        ),
        is_deleted=(
            is_deleted
            if is_deleted is not None
            else current_state.is_deleted if current_state else False
        ),
        details=(
            details
            if details is not None
            else current_state.details if current_state else {}
        ),
    )
