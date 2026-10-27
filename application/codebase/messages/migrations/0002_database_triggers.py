from pathlib import Path

import sqlparse
from django.db import migrations


def sql_statements(file_name):
    sql_path = Path(__file__).resolve().parent / "sql" / file_name
    return sqlparse.split(sql_path.read_text(encoding="utf-8"))


class Migration(migrations.Migration):
    dependencies = [("stormcast_messages", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql=sql_statements("index_comments.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=sql_statements("common_functions.sql"),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=sql_statements("messages_triggers.sql"),
            reverse_sql=sql_statements("drop_messages_triggers.sql"),
        ),
    ]
