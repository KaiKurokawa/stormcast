"""Администрирование документов по правилам приложения сообщений."""

from django.contrib import admin, messages

from documents.models import (
    DocumentEntity,
    Revision,
    RevisionBuffer,
    State,
    StateCache,
    TemplateEntity,
    TemplateRevision,
)
from documents.services import commit_revision_buffer


class ReadOnlyModelAdmin(admin.ModelAdmin):
    """Разрешает только просмотр производных записей."""

    def has_add_permission(self, request):
        """Запрещает ручное создание производных записей."""
        return False

    def has_change_permission(self, request, obj=None):
        """Запрещает изменение производных записей."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Запрещает удаление производных записей."""
        return False


class AppendOnlyModelAdmin(admin.ModelAdmin):
    """Разрешает добавление и просмотр неизменяемых записей."""

    def has_change_permission(self, request, obj=None):
        """Существующие записи доступны только для просмотра."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Сохраняет неизменяемую историю."""
        return False

    def get_readonly_fields(self, request, obj=None):
        """При создании блокирует технические поля, при просмотре — все."""
        if obj is None:
            return tuple(
                field.name
                for field in self.model._meta.fields
                if field.name in {"id", "content_hash", "created_at"}
            )
        return tuple(field.name for field in self.model._meta.fields)


@admin.register(DocumentEntity)
class DocumentEntityAdmin(AppendOnlyModelAdmin):
    """Добавление документов и просмотр существующих записей реестра."""
    list_display = ("id", "user", "created_at")
    list_select_related = ("user",)
    ordering = ("-created_at",)


@admin.register(RevisionBuffer)
class RevisionBufferAdmin(admin.ModelAdmin):
    """Редактирование и фиксация буферов по правилам сообщений."""
    list_display = ("id", "entity", "user", "template", "topic", "updated_at")
    list_filter = ("template", "updated_at")
    search_fields = ("topic", "out_number", "note")
    list_select_related = ("entity", "template", "user")
    ordering = ("-updated_at",)
    readonly_fields = ("id", "user", "content_hash", "updated_at")
    fields = (
        "id",
        "entity",
        "parent",
        "template",
        "user",
        "out_number",
        "topic",
        "field_overrides",
        "message_bindings",
        "note",
        "content_hash",
        "details",
        "updated_at",
    )
    actions = ("commit_selected_buffers",)

    @admin.action(description="Зафиксировать выбранные буферы")
    def commit_selected_buffers(self, request, queryset):
        """Фиксирует выбранные буферы и сообщает число новых ревизий."""
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
        """Защищает идентичность буфера после его создания."""
        if obj is None:
            return ("id", "content_hash", "updated_at")
        return ("id", "entity", "user", "content_hash", "updated_at")


@admin.register(Revision)
class RevisionAdmin(AppendOnlyModelAdmin):
    """Добавление и просмотр неизменяемых ревизий документов."""
    list_display = ("id", "entity", "user", "template", "topic", "created_at")
    list_filter = ("template", "created_at")
    search_fields = ("topic", "out_number", "note")
    list_select_related = ("entity", "template", "user")
    ordering = ("-created_at",)


@admin.register(State)
class StateAdmin(AppendOnlyModelAdmin):
    """Добавление и просмотр записей журнала состояний."""
    list_display = ("id", "entity", "revision", "readiness_stage", "user", "created_at")
    list_filter = ("readiness_stage", "is_archived", "is_deleted")
    list_select_related = ("entity", "revision", "user")
    ordering = ("-created_at",)


@admin.register(StateCache)
class StateCacheAdmin(ReadOnlyModelAdmin):
    """Просмотр автоматически поддерживаемого кэша состояний."""
    list_display = ("entity", "revision", "readiness_stage", "is_archived", "is_deleted", "updated_at")
    list_filter = ("readiness_stage", "is_archived", "is_deleted")
    list_select_related = ("entity", "revision", "user")
    ordering = ("-updated_at",)
    readonly_fields = tuple(field.name for field in StateCache._meta.fields)


@admin.register(TemplateEntity)
class TemplateEntityAdmin(AppendOnlyModelAdmin):
    """Добавление и просмотр реестра шаблонов документов."""
    list_display = ("id", "user", "created_at")
    list_select_related = ("user",)
    ordering = ("-created_at",)


@admin.register(TemplateRevision)
class TemplateRevisionAdmin(AppendOnlyModelAdmin):
    """Добавление новых версий шаблонов и просмотр истории."""
    list_display = ("id", "template_entity", "user", "code", "title", "created_at")
    list_filter = ("created_at",)
    search_fields = ("code", "title", "description")
    list_select_related = ("template_entity", "user")
    ordering = ("-created_at",)
