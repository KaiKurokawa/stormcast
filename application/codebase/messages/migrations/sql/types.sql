CREATE EXTENSION IF NOT EXISTS pg_uuidv7;
COMMENT ON EXTENSION pg_uuidv7
    IS 'Генерация UUID версии 7 (time-ordered, RFC 9562).';
CREATE EXTENSION IF NOT EXISTS pg_trgm;
COMMENT ON EXTENSION pg_trgm
    IS 'Триграммное совпадение для полнотекстового поиска и поиска по подстрокам.';
CREATE SCHEMA IF NOT EXISTS messages;
COMMENT ON SCHEMA messages
    IS 'Ядро системы оповещений: хранение метеорологических событий, предупреждений и прогнозов.';

DO $$
BEGIN
    CREATE TYPE messages.readiness_stages AS ENUM ('draft', 'review', 'approved');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END;
$$;
COMMENT ON TYPE messages.readiness_stages IS 'Состояние готовности содержимого.';

DO $$
BEGIN
    CREATE TYPE messages.message_type AS ENUM ('forecast', 'observation', 'warning');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END;
$$;
COMMENT ON TYPE messages.message_type IS 'Категоризация метеорологических событий.';
