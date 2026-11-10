"""Компоненты приложения документов."""
from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    """Представление данных документов."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "documents"
    label = "stormcast_documents"
    verbose_name = "Документы"
