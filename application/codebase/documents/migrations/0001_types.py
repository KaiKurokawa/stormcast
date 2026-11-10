"""Создаёт схему и нативное перечисление до таблиц ORM."""
from django.db import migrations

class Migration(migrations.Migration):
    """Подготавливает зависимости стандартной миграции."""
    dependencies = [("common", "0001_shared_functions")]
    operations = [migrations.RunSQL(
        """CREATE SCHEMA IF NOT EXISTS documents;
        DO $$ BEGIN
          CREATE TYPE documents.readiness_stages AS ENUM ('draft', 'review', 'approved');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;""",
        reverse_sql="DROP TYPE documents.readiness_stages; DROP SCHEMA documents;",
    )]
