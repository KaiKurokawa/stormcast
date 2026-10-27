CREATE OR REPLACE FUNCTION common.function_validate_state_revision_entity()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_revision_table_name TEXT := TG_ARGV[0];
    v_revision_entity_id UUID;
    v_revision_row_count BIGINT;
BEGIN
    IF v_revision_table_name IS NULL OR v_revision_table_name = '' THEN
        RAISE EXCEPTION 'Не задано имя таблицы ревизий для проверки состояния.';
    END IF;

    IF NEW.revision_id IS NULL THEN
        RETURN NEW;
    END IF;

    EXECUTE format(
        'SELECT entity_id FROM %s WHERE id = $1',
        v_revision_table_name
    )
    INTO v_revision_entity_id
    USING NEW.revision_id;
    GET DIAGNOSTICS v_revision_row_count = ROW_COUNT;

    IF v_revision_row_count = 0 THEN
        RAISE EXCEPTION 'Ревизия % не найдена.', NEW.revision_id;
    END IF;

    IF v_revision_entity_id IS DISTINCT FROM NEW.entity_id THEN
        RAISE EXCEPTION 'Ревизия % принадлежит другой сущности.', NEW.revision_id;
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION common.function_validate_state_revision_entity()
IS 'Универсальная проверка: состояние или кэш состояния ссылается на ревизию той же сущности. Имя таблицы ревизий передаётся аргументом триггера.';
