-- Метаданные #


-- Расширения #

    CREATE EXTENSION IF NOT EXISTS pg_uuidv7;
    COMMENT ON EXTENSION pg_uuidv7 IS 'Генерация UUID версии 7 (time-ordered, RFC 9562). Обеспечивает естественную сортировку по времени создания.';


    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    COMMENT ON EXTENSION pg_trgm IS 'Расширение триграммного совпадения, используемое для ускорения полнотекстового поиска и поиска по подстрокам.';


-- Настройки сессии #

    -- Явная привязка к схеме common для защиты от случайного развертывания в чужую схему

    SELECT pg_catalog.set_config('search_path', 'common, public', false);


    -- Отключение тайм-аута на выполнение SQL-запросы (0 — выполнять без ограничений).

    SET statement_timeout = 0;


    -- Отключение тайм-аута на ожидание блокировок таблиц при изменении структуры.

    SET lock_timeout = 0;


    -- Отключение тайм-аута для открытых, но бездействующих транзакций.

    SET idle_in_transaction_session_timeout = 0;


    -- Установка кодировки UTF-8 для корректного отображения кириллицы в комментариях и данных.

    SET client_encoding = 'UTF8';


    -- Отключение экранирования символов обратного слэша (\), что защищает пути к файлам/строкам от искажения.

    SET standard_conforming_strings = on;


    -- Отключение проверки тела функций при создании (позволяет функциям ссылаться друг на друга).

    SET check_function_bodies = false;


    -- Настройка обработки XML-документов в режиме контента.

    SET xmloption = content;


    -- Подавление информационного шума в консоли, выводятся только важные предупреждения и ошибки.

    SET client_min_messages = warning;


    -- Отключение политик безопасности на уровне строк (RLS) на время накатки схемы.

    SET row_security = off;


-- Схемы #

    -- Создание изолированной схемы общего назначения

    CREATE SCHEMA IF NOT EXISTS common;
    COMMENT ON SCHEMA common IS 'Общие системные утилиты, инфраструктурные функции и универсальные бизнес-триггеры.';


-- Типы данных #


-- Домены #


-- Функции #

    -- Универсальная функция обновления времени в поле 'updated_at'

        CREATE OR REPLACE FUNCTION common.function_refresh_updated_at_column()
        RETURNS TRIGGER AS $$

        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;

        END;
        $$ LANGUAGE plpgsql;

        COMMENT ON FUNCTION common.function_refresh_updated_at_column() IS 'Инфраструктурная автоматизация: гарантирует актуализацию поля updated_at при любых изменениях строки.';


    -- Универсальная функция инициализации стартовой записи в журнале состояний (Event Sourcing)

        -- Аргументы: (имя таблицы журнала, имя поля связи, JSONB-снимок начального состояния)

        CREATE OR REPLACE FUNCTION common.function_initialize_state_log()
        RETURNS TRIGGER AS $$

        DECLARE
            target_log_table_name       text := TG_ARGV[0];
            foreign_key_column_name     text := TG_ARGV[1];
            initial_state_jsonb         jsonb := TG_ARGV[2]::jsonb;

            new_record_jsonb            jsonb := to_jsonb(NEW);
            entity_identifier_uuid      uuid  := (new_record_jsonb ->> 'id')::uuid;
            user_identifier_uuid        uuid  := (new_record_jsonb ->> 'user_id')::uuid;

            column_names                text := '';
            column_values               text := '';
            field_name                  text;
            field_value                 jsonb;
            field_type                  text;
            literal_value               text;
            sql_statement               text;

        BEGIN
            -- Формирование перечня полей и значений из снимка начального состояния
            FOR field_name IN
                SELECT key FROM jsonb_each(initial_state_jsonb)

            LOOP
                field_value := initial_state_jsonb -> field_name;
                field_type  := jsonb_typeof(field_value);

                IF field_type = 'boolean' THEN
                    literal_value := field_value #>> '{}';
                ELSIF field_type = 'string' THEN
                    literal_value := quote_literal(field_value #>> '{}');
                ELSIF field_type = 'null' THEN
                    literal_value := 'NULL';
                ELSE
                    literal_value := field_value::text;
                END IF;

                IF column_names != '' THEN
                    column_names  := column_names || ', ';
                    column_values := column_values || ', ';
                END IF;

                column_names  := column_names || quote_ident(field_name);
                column_values := column_values || literal_value;

            END LOOP;

            sql_statement := format(
                'INSERT INTO %s (%I, user_id, %s, details) VALUES ($1, $2, %s, $3)',
                target_log_table_name,
                foreign_key_column_name,
                column_names,
                column_values
            );

            EXECUTE sql_statement USING entity_identifier_uuid, user_identifier_uuid, '{}'::jsonb;

            RETURN NEW;

        END;
        $$ LANGUAGE plpgsql;

        COMMENT ON FUNCTION common.function_initialize_state_log() IS 'Аппаратная защита: гарантирует обязательное создание первоначальной записи в журнале состояний (Event Sourcing) для любой новой сущности. Третий аргумент принимает JSONB-снимок начального состояния.';


    -- Универсальная функция трансляции событий из журнала в оперативный кэш текущих состояний

        -- Копирует все поля снимка состояния из записи журнала в кэш, исключая служебные поля

        CREATE OR REPLACE FUNCTION common.function_upsert_current_state()
        RETURNS TRIGGER AS $$

        DECLARE
            target_cache_table_name     text := TG_ARGV[0];
            foreign_key_column_name     text := TG_ARGV[1];

            new_log_record_jsonb        jsonb := to_jsonb(NEW);
            entity_identifier_uuid      uuid  := (new_log_record_jsonb ->> foreign_key_column_name)::uuid;
            user_identifier_uuid        uuid  := (new_log_record_jsonb ->> 'user_id')::uuid;
            details_jsonb               jsonb := COALESCE(new_log_record_jsonb -> 'details', '{}'::jsonb);

            insert_columns              text := '';
            insert_values               text := '';
            update_set                  text := '';
            field_name                  text;
            field_value                 jsonb;
            field_type                  text;
            literal_value               text;
            sql_statement               text;

        BEGIN
            -- Формирование перечня полей снимка состояния (служебные поля исключаются)
            FOR field_name IN
                SELECT key FROM jsonb_each(new_log_record_jsonb)
                WHERE key NOT IN ('id', foreign_key_column_name, 'user_id', 'details', 'created_at')

            LOOP
                field_value := new_log_record_jsonb -> field_name;
                field_type  := jsonb_typeof(field_value);

                IF field_type = 'boolean' THEN
                    literal_value := field_value #>> '{}';
                ELSIF field_type = 'string' THEN
                    literal_value := quote_literal(field_value #>> '{}');
                ELSIF field_type = 'null' THEN
                    literal_value := 'NULL';
                ELSE
                    literal_value := field_value::text;
                END IF;

                IF insert_columns != '' THEN
                    insert_columns := insert_columns || ', ';
                    insert_values  := insert_values || ', ';
                    update_set     := update_set || ', ';
                END IF;

                insert_columns := insert_columns || quote_ident(field_name);
                insert_values  := insert_values || literal_value;
                update_set     := update_set || quote_ident(field_name) || ' = EXCLUDED.' || quote_ident(field_name);

            END LOOP;

            sql_statement := format(
                'INSERT INTO %s (%I, user_id, %s, details, updated_at) ' ||
                'VALUES ($1, $2, %s, $3, CURRENT_TIMESTAMP) ' ||
                'ON CONFLICT (%I) DO UPDATE SET ' ||
                'user_id = EXCLUDED.user_id, %s, details = EXCLUDED.details, updated_at = CURRENT_TIMESTAMP',
                target_cache_table_name,
                foreign_key_column_name,
                insert_columns,
                insert_values,
                foreign_key_column_name,
                update_set
            );

            EXECUTE sql_statement USING entity_identifier_uuid, user_identifier_uuid, details_jsonb;

            RETURN NEW;

        END;
        $$ LANGUAGE plpgsql;

        COMMENT ON FUNCTION common.function_upsert_current_state() IS 'Универсальная синхронизация: копирует все поля снимка состояния из записи журнала в оперативный кэш, исключая служебные поля.';


    -- Универсальная функция защиты таблиц журналов (запрет UPDATE и DELETE)

        CREATE OR REPLACE FUNCTION common.function_protect_immutability()
        RETURNS TRIGGER AS $$

        BEGIN
            RAISE EXCEPTION 'Таблица % работает в режиме append-only. Изменение или удаление записей запрещено.', TG_TABLE_NAME;
            RETURN NULL;

        END;
        $$ LANGUAGE plpgsql;

        COMMENT ON FUNCTION common.function_protect_immutability() IS 'Аппаратная защита: делает целевую таблицу неизменяемой (append-only), блокируя UPDATE и DELETE.';


    -- Универсальная функция защиты идентичности рабочего буфера @

        -- Суррогатный ключ и доменная привязка буфера не должны изменяться после создания записи.

        CREATE OR REPLACE FUNCTION common.function_protect_revision_buffer_identity()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$

        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id THEN
                RAISE EXCEPTION 'Идентификатор рабочего буфера изменению не подлежит.';
            END IF;

            IF NEW.entity_id IS DISTINCT FROM OLD.entity_id THEN
                RAISE EXCEPTION 'Привязка рабочего буфера к сущности изменению не подлежит.';
            END IF;

            IF NEW.user_id IS DISTINCT FROM OLD.user_id THEN
                RAISE EXCEPTION 'Пользователь рабочего буфера изменению не подлежит.';
            END IF;

            RETURN NEW;
        END;
        $$;

        COMMENT ON FUNCTION common.function_protect_revision_buffer_identity() IS 'Запрещает изменять суррогатный и доменный ключи рабочего буфера.';


    -- Универсальная проверка согласованности состояния и ревизии @

        -- Проверяет, что запись состояния или кэша состояния ссылается
        -- на ревизию той же самой сущности.
        -- Имя таблицы ревизий передаётся как аргумент триггера, например:
        -- 'messages.revisions' или 'documents.revisions'.

        CREATE OR REPLACE FUNCTION common.function_validate_state_revision_entity()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$

        DECLARE
            v_revision_table_name TEXT := TG_ARGV[0];
            v_revision_entity_id  UUID;

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

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Ревизия % не найдена.', NEW.revision_id;
            END IF;

            IF v_revision_entity_id IS DISTINCT FROM NEW.entity_id THEN
                RAISE EXCEPTION 'Ревизия % принадлежит другой сущности.', NEW.revision_id;
            END IF;

            RETURN NEW;
        END;
        $$;

        COMMENT ON FUNCTION common.function_validate_state_revision_entity() IS 'Универсальная проверка: состояние или кэш состояния ссылается на ревизию той же сущности. Имя таблицы ревизий передаётся аргументом триггера.';


-- Процедуры #


-- Таблицы #


-- Представления #


-- Материализованные представления #


-- Права доступа #
