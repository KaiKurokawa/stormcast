"""Устанавливает прикладные триггеры после таблиц и общих функций."""

from pathlib import Path
import sqlparse
from django.db import migrations


def statements(filename):
    """Читает SQL без разбиения тел функций по внутренним точкам с запятой."""
    return sqlparse.split((Path(__file__).parent / "sql" / filename).read_text())


class Migration(migrations.Migration):
    """Подключает защиту истории, синхронизацию кэша и временные метки."""
    dependencies = [("stormcast_documents", "0002_initial"), ("common", "0001_shared_functions")]
    operations = [migrations.RunSQL(statements("triggers.sql"), statements("drop_triggers.sql"))]
