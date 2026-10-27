from pathlib import Path

import sqlparse
from django.db import migrations


def sql_statements(file_name):
    sql_path = Path(__file__).resolve().parent / "sql" / file_name
    return sqlparse.split(sql_path.read_text(encoding="utf-8"))


class Migration(migrations.Migration):
    dependencies = [("stormcast_messages", "0002_database_triggers")]

    operations = [
        migrations.RunSQL(
            sql=sql_statements("validate_state_revision_entity.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
