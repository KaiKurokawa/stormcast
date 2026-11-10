"""Дополняет ORM-схему действиями удаления FK и комментариями индексов."""

from pathlib import Path
import sqlparse
from django.db import migrations


FORWARD = """
DO $$
DECLARE relation record; action text; definition text;
BEGIN
  FOR relation IN
    SELECT c.oid, c.conname, c.conrelid::regclass AS table_name,
           a.attname AS column_name
    FROM pg_constraint c
    JOIN pg_namespace n ON n.oid = c.connamespace
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
    WHERE n.nspname = 'documents' AND c.contype = 'f'
      AND a.attname IN ('entity_id', 'parent_id', 'revision_id', 'template_id', 'template_entity_id')
  LOOP
    action := CASE relation.column_name
      WHEN 'parent_id' THEN 'SET NULL'
      WHEN 'revision_id' THEN 'RESTRICT'
      WHEN 'template_id' THEN 'RESTRICT'
      ELSE 'CASCADE' END;
    definition := pg_get_constraintdef(relation.oid);
    definition := regexp_replace(definition, ' ON DELETE (CASCADE|SET NULL|RESTRICT|NO ACTION)', '');
    definition := regexp_replace(definition, ' DEFERRABLE', ' ON DELETE ' || action || ' DEFERRABLE');
    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I, ADD CONSTRAINT %I %s',
                   relation.table_name, relation.conname, relation.conname, definition);
  END LOOP;
END $$;
"""

REVERSE = """
DO $$
DECLARE relation record; definition text;
BEGIN
  FOR relation IN
    SELECT c.oid, c.conname, c.conrelid::regclass AS table_name
    FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
    WHERE n.nspname = 'documents' AND c.contype = 'f' AND c.confdeltype != 'a'
  LOOP
    definition := regexp_replace(pg_get_constraintdef(relation.oid), ' ON DELETE (CASCADE|SET NULL|RESTRICT)', '');
    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I, ADD CONSTRAINT %I %s',
                   relation.table_name, relation.conname, relation.conname, definition);
  END LOOP;
END $$;
"""


class Migration(migrations.Migration):
    """Изменяет существующие FK без добавления дублирующих связей."""
    dependencies = [("stormcast_documents", "0004_alter_revision_details_and_more")]
    operations = [
        migrations.RunSQL(FORWARD, REVERSE),
        migrations.RunSQL(
            sqlparse.split((Path(__file__).parent / "sql" / "index_comments.sql").read_text()),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
