from django.contrib import admin, messages

from messages.models import MessageEntity, Revision, RevisionBuffer, State, StateCache
from messages.services import commit_revision_buffer


class ReadOnlyModelAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AppendOnlyModelAdmin(admin.ModelAdmin):
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MessageEntity)
class MessageEntityAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "created_at")
    list_select_related = ("user",)
    ordering = ("-created_at",)

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ("id", "created_at")
        return tuple(field.name for field in MessageEntity._meta.fields)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RevisionBuffer)
class RevisionBufferAdmin(admin.ModelAdmin):
    list_display = ("id", "entity", "user", "type", "updated_at")
    list_filter = ("type", "updated_at")
    search_fields = ("text", "region", "note")
    list_select_related = ("entity", "user")
    ordering = ("-updated_at",)
    readonly_fields = ("id", "user", "content_hash", "updated_at")
    fields = (
        "id",
        "entity",
        "parent",
        "user",
        "type",
        "period",
        "region",
        "text",
        "note",
        "content_hash",
        "details",
        "updated_at",
    )
    actions = ("commit_selected_buffers",)

    @admin.action(description="Зафиксировать выбранные буферы")
    def commit_selected_buffers(self, request, queryset):
        created_count = 0
        unchanged_count = 0

        for buffer_id, user_id in queryset.values_list("pk", "user_id"):
            _revision, created = commit_revision_buffer(
                buffer_id=buffer_id,
                user_id=user_id,
            )
            if created:
                created_count += 1
            else:
                unchanged_count += 1

        self.message_user(
            request,
            (
                f"Создано ревизий: {created_count}. "
                f"Буферов без изменений: {unchanged_count}."
            ),
            level=messages.SUCCESS,
        )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ("id", "content_hash", "updated_at")
        return (
            "id",
            "entity",
            "user",
            "content_hash",
            "updated_at",
        )


@admin.register(Revision)
class RevisionAdmin(AppendOnlyModelAdmin):
    list_display = ("id", "entity", "user", "type", "created_at")
    list_filter = ("type", "created_at")
    search_fields = ("text", "region", "note")
    list_select_related = ("entity", "user")
    ordering = ("-created_at",)

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ("id", "content_hash", "created_at")
        return tuple(field.name for field in Revision._meta.fields)


@admin.register(State)
class StateAdmin(AppendOnlyModelAdmin):
    list_display = (
        "id",
        "entity",
        "revision",
        "readiness_stage",
        "user",
        "created_at",
    )
    list_filter = ("readiness_stage", "is_starred", "is_archived", "is_deleted")
    list_select_related = ("entity", "revision", "user")
    ordering = ("-created_at",)
    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ("id", "content_hash", "created_at")
        return tuple(field.name for field in State._meta.fields)


@admin.register(StateCache)
class StateCacheAdmin(ReadOnlyModelAdmin):
    list_display = (
        "entity",
        "revision",
        "readiness_stage",
        "is_starred",
        "is_archived",
        "is_deleted",
        "updated_at",
    )
    list_filter = ("readiness_stage", "is_starred", "is_archived", "is_deleted")
    list_select_related = ("entity", "revision", "user")
    ordering = ("-updated_at",)
    readonly_fields = tuple(field.name for field in StateCache._meta.fields)
