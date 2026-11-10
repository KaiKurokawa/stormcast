"""Настройка общих компонентов."""
from django.apps import AppConfig

class CommonConfig(AppConfig):
    """Общие механизмы PostgreSQL."""
    name = "common"
    verbose_name = "Общие компоненты"
