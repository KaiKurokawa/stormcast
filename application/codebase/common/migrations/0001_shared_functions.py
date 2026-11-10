"""Устанавливает общие функции PostgreSQL независимо от приложений."""
from pathlib import Path
import sqlparse
from django.db import migrations

class Migration(migrations.Migration):
    """Создаёт переиспользуемые функции без прикладных таблиц."""
    initial = True
    dependencies = [("stormcast_messages", "0003_fix_revision_validation")]
    operations = [migrations.RunSQL(
        sql=sqlparse.split((Path(__file__).parent / "sql" / "functions.sql").read_text()),
        reverse_sql=migrations.RunSQL.noop,
    )]
