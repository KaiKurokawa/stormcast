-- Метаданные #


-- Расширения #


-- Настройки сессии #

    -- Явная привязка к схеме documents для защиты от случайного развертывания в чужую схему

    SELECT pg_catalog.set_config('search_path', 'documents, public', FALSE);


-- Схемы #

    -- Создание изолированной схемы для документов

    CREATE SCHEMA IF NOT EXISTS documents;
    COMMENT ON SCHEMA documents IS 'Модуль выходных документов, шаблонов, реквизитов и их жизненного цикла.';


-- Типы данных #

    CREATE TYPE documents.readiness_stages AS ENUM (
        'draft',     -- документ формируется или дорабатывается
        'review',    -- документ передан на проверку
        'approved'   -- документ проверен и утвержден ответственным сотрудником
    );

    COMMENT ON TYPE documents.readiness_stages IS 'Перечень состояний, определяющих жизненный цикл выходного документа.';


-- Домены #


-- Функции #

    -- Фиксация ревизии из рабочего буфера пользователя @

        -- Переносит текущее содержимое рабочего буфера пользователя в архив ревизий.
        -- Если актуальная ревизия уже содержит такой же снимок по хэшу, новая ревизия не создаётся.
        -- Флаги is_archived и is_deleted сохраняются из текущего состояния документа,
        -- если вызывающая сторона не передала их явно.

        CREATE OR REPLACE FUNCTION documents.function_commit_revision_from_buffer(
            p_entity_id             UUID,
            p_user_id               UUID,
            p_state_content_hash    BYTEA,
            p_state_details         JSONB       DEFAULT '{}'::jsonb,
            p_is_archived           BOOLEAN     DEFAULT NULL,
            p_is_deleted            BOOLEAN     DEFAULT NULL
        )
        RETURNS UUID
        LANGUAGE plpgsql
        AS $$

        DECLARE
            buffer_record       RECORD;
            latest_revision     RECORD;
            current_state       RECORD;
            new_revision_id     UUID;

            v_is_archived       BOOLEAN;
            v_is_deleted        BOOLEAN;
            v_state_details     JSONB;

        BEGIN
            -- Проверка корректности хэша начального состояния
            IF p_state_content_hash IS NULL OR length(p_state_content_hash) <> 32 THEN
                RAISE EXCEPTION 'Не передан корректный хэш начального состояния ревизии документа.';
            END IF;

            v_state_details := COALESCE(p_state_details, '{}'::jsonb);

            -- Извлечение личного буфера с блокировкой строки от параллельных изменений
            SELECT *
            INTO buffer_record
            FROM documents.revision_buffer
            WHERE entity_id = p_entity_id
                AND user_id = p_user_id
            FOR UPDATE;

            -- Проверка существования буфера
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Рабочий буфер для документа % пользователя % не найден.',
                    p_entity_id,
                    p_user_id;
            END IF;

            -- Чтение текущих флагов состояния документа.
            -- Новые ревизии должны сохранять архивность и удалённость,
            -- если пользователь явно не передаёт другие значения.
            -- Блокировка строки предотвращает параллельное изменение состояния
            -- до завершения фиксации новой ревизии.
            SELECT
                is_archived,
                is_deleted
            INTO current_state
            FROM documents.state_cache
            WHERE entity_id = p_entity_id
            FOR UPDATE;

            IF FOUND THEN
                v_is_archived := COALESCE(p_is_archived, current_state.is_archived);
                v_is_deleted  := COALESCE(p_is_deleted, current_state.is_deleted);
            ELSE
                v_is_archived := COALESCE(p_is_archived, FALSE);
                v_is_deleted  := COALESCE(p_is_deleted, FALSE);
            END IF;

            -- Проверка актуальной ревизии, чтобы не создавать повтор текущего снимка
            SELECT
                id,
                content_hash
            INTO latest_revision
            FROM documents.revisions
            WHERE entity_id = p_entity_id
            ORDER BY created_at DESC, id DESC
            LIMIT 1;

            IF FOUND AND latest_revision.content_hash = buffer_record.content_hash THEN
                -- Если содержимое не изменилось относительно актуальной ревизии,
                -- буфер удаляется, а вызывающая сторона получает существующую ревизию.
                DELETE FROM documents.revision_buffer
                WHERE id = buffer_record.id;

                RETURN latest_revision.id;
            END IF;

            -- Перенос данных из буфера в архив неизменяемых ревизий
            INSERT INTO documents.revisions (
                entity_id,
                parent_id,
                template_id,
                user_id,
                out_number,
                topic,
                field_overrides,
                message_bindings,
                note,
                content_hash,
                details
            )
            VALUES (
                buffer_record.entity_id,
                buffer_record.parent_id,
                buffer_record.template_id,
                buffer_record.user_id,
                buffer_record.out_number,
                buffer_record.topic,
                buffer_record.field_overrides,
                buffer_record.message_bindings,
                buffer_record.note,
                buffer_record.content_hash,
                buffer_record.details
            )
            RETURNING id INTO new_revision_id;

            -- Фиксация начального состояния готовности для новой ревизии.
            -- Приложение передаёт хэш состояния, который соответствует:
            --
            -- {
            --     "readiness_stage": "draft",
            --     "is_archived": <итоговое значение>,
            --     "is_deleted": <итоговое значение>,
            --     "details": <p_state_details>
            -- }
            --
            -- Итоговые значения флагов могут быть явно заданы вызывающей стороной
            -- или унаследованы из текущего состояния документа.
            INSERT INTO documents.states (
                entity_id,
                revision_id,
                user_id,
                readiness_stage,
                is_archived,
                is_deleted,
                content_hash,
                details
            )
            VALUES (
                buffer_record.entity_id,
                new_revision_id,
                buffer_record.user_id,
                'draft',
                v_is_archived,
                v_is_deleted,
                p_state_content_hash,
                v_state_details
            );

            -- Обязательное удаление рабочего буфера после успешной фиксации ревизии.
            -- Удаление выполняется по техническому первичному ключу буфера.
            DELETE FROM documents.revision_buffer
            WHERE id = buffer_record.id;

            RETURN new_revision_id;
        END;
        $$;

        COMMENT ON FUNCTION documents.function_commit_revision_from_buffer(UUID, UUID, BYTEA, JSONB, BOOLEAN, BOOLEAN) IS 'Переносит содержимое рабочего буфера пользователя в архив ревизий документа, не создаёт повтор текущего снимка по хэшу, создаёт начальное состояние новой ревизии, сохраняет или явно устанавливает флаги is_archived и is_deleted, удаляет зафиксированный буфер и возвращает идентификатор ревизии.';


    -- Создание или обновление рабочего буфера пользователя @

        -- Безопасная точка входа для автосохранения черновика документа.
        -- Доменная пара (entity_id, user_id) остаётся уникальной, техническая запись получает суррогатный id.
        -- Функция возвращает технический первичный ключ буфера, удобный для Django, API и служебных операций.

        CREATE OR REPLACE FUNCTION documents.function_upsert_revision_buffer(
            p_entity_id         UUID,
            p_user_id           UUID,
            p_parent_id         UUID,
            p_template_id       UUID,
            p_out_number        VARCHAR(100),
            p_topic             VARCHAR(150),
            p_field_overrides   JSONB,
            p_message_bindings  JSONB,
            p_note              VARCHAR(255),
            p_content_hash      BYTEA,
            p_details           JSONB
        )
        RETURNS UUID
        LANGUAGE plpgsql
        AS $$

        DECLARE
            buffer_id       UUID;

        BEGIN
            INSERT INTO documents.revision_buffer (
                entity_id,
                parent_id,
                user_id,
                template_id,
                out_number,
                topic,
                field_overrides,
                message_bindings,
                note,
                content_hash,
                details
            )
            VALUES (
                p_entity_id,
                p_parent_id,
                p_user_id,
                p_template_id,
                p_out_number,
                p_topic,
                COALESCE(p_field_overrides, '{}'::jsonb),
                COALESCE(p_message_bindings, '[]'::jsonb),
                p_note,
                p_content_hash,
                COALESCE(p_details, '{}'::jsonb)
            )
            ON CONFLICT (entity_id, user_id) DO UPDATE SET
                parent_id           = EXCLUDED.parent_id,
                template_id         = EXCLUDED.template_id,
                out_number          = EXCLUDED.out_number,
                topic               = EXCLUDED.topic,
                field_overrides     = EXCLUDED.field_overrides,
                message_bindings    = EXCLUDED.message_bindings,
                note                = EXCLUDED.note,
                content_hash        = EXCLUDED.content_hash,
                details             = EXCLUDED.details
            RETURNING id INTO buffer_id;

            RETURN buffer_id;
        END;
        $$;

        COMMENT ON FUNCTION documents.function_upsert_revision_buffer(UUID, UUID, UUID, UUID, VARCHAR, VARCHAR, JSONB, JSONB, VARCHAR, BYTEA, JSONB) IS 'Создаёт или обновляет личный рабочий буфер пользователя для документа и возвращает технический идентификатор записи буфера.';


    -- Получение компактного списка документов (Feed) для интерфейса приложения @

        -- Формирует компактное представление списка документов для конкретного пользователя.
        -- Приоритет отображения: личный буфер пользователя > последняя ревизия > кэш состояний.
        -- Поддерживает опциональную фильтрацию по стадии и поиску в теме документа.
        -- Предназначена для индексной страницы со списком документов.

        CREATE OR REPLACE FUNCTION documents.function_get_user_document_feed(
            p_user_id   UUID,
            p_state     documents.readiness_stages    DEFAULT NULL,
            p_search    TEXT                          DEFAULT NULL
        )
        RETURNS TABLE (
            entity_id               UUID,
            display_datetime        TIMESTAMPTZ,
            display_state           documents.readiness_stages,
            display_topic           VARCHAR(150),
            display_out_number      VARCHAR(100),
            display_template_id     UUID,
            display_author_id       UUID,
            display_author_name     TEXT,
            has_buffer              BOOLEAN,
            revision_id             UUID
        )
        LANGUAGE plpgsql
        AS $$

        DECLARE
            v_search_pattern TEXT;

        BEGIN
            IF p_search IS NOT NULL THEN
                v_search_pattern := '%' || replace(replace(replace(p_search, '\', '\\'), '%', '\%'), '_', '\_') || '%';
            END IF;

            RETURN QUERY
            SELECT
                entities.id                                                                             AS entity_id,

                COALESCE(revision_buffer.updated_at, latest_revision.created_at, entities.created_at)  AS display_datetime,

                state_cache.readiness_stage                                                             AS display_state,

                COALESCE(revision_buffer.topic, latest_revision.topic, '')                              AS display_topic,

                CASE
                    WHEN revision_buffer.entity_id IS NOT NULL THEN revision_buffer.out_number
                    ELSE latest_revision.out_number
                END                                                                                     AS display_out_number,

                COALESCE(revision_buffer.template_id, latest_revision.template_id)                      AS display_template_id,

                COALESCE(revision_buffer.user_id, latest_revision.user_id, entities.user_id)            AS display_author_id,

                COALESCE(
                    NULLIF(
                        CONCAT_WS(' ',
                            author_users.last_name,
                            author_users.first_name,
                            author_users.middle_name
                        ),
                        ''
                    ),
                    'Неизвестный автор'
                )                                           AS display_author_name,

                (revision_buffer.entity_id IS NOT NULL)     AS has_buffer,
                latest_revision.revision_id                 AS revision_id

            FROM documents.entities AS entities

            -- Личный буфер текущего пользователя (гарантия изоляции буферов пользователей)
            LEFT JOIN documents.revision_buffer AS revision_buffer
                ON revision_buffer.entity_id = entities.id
                AND revision_buffer.user_id = p_user_id

            -- Последняя зафиксированная ревизия документа
            LEFT JOIN LATERAL (
                SELECT
                    revisions.id            AS revision_id,
                    revisions.template_id,
                    revisions.out_number,
                    revisions.topic,
                    revisions.created_at,
                    revisions.user_id
                FROM documents.revisions AS revisions
                WHERE revisions.entity_id = entities.id
                ORDER BY revisions.created_at DESC, revisions.id DESC
                LIMIT 1
            ) AS latest_revision ON TRUE

            -- Актуальный кэш состояния документа
            LEFT JOIN documents.state_cache AS state_cache
                ON state_cache.entity_id = entities.id

            -- Данные автора актуального содержимого
            LEFT JOIN identity.users AS author_users
                ON author_users.id = COALESCE(
                    revision_buffer.user_id,
                    latest_revision.user_id,
                    entities.user_id
                )

            WHERE
                -- Исключение удалённых документов
                (state_cache.is_deleted = FALSE OR state_cache.is_deleted IS NULL)

                -- Опциональная фильтрация по стадии готовности
                AND (p_state IS NULL OR state_cache.readiness_stage = p_state)

                -- Изолированный поиск по актуальной теме документа текущего пользователя
                AND (
                    p_search IS NULL
                    OR (
                        revision_buffer.entity_id IS NOT NULL
                        AND revision_buffer.topic ILIKE v_search_pattern
                    )
                    OR (
                        revision_buffer.entity_id IS NULL
                        AND latest_revision.topic ILIKE v_search_pattern
                    )
                )

            ORDER BY display_datetime DESC;
        END;
        $$;

        COMMENT ON FUNCTION documents.function_get_user_document_feed(UUID, documents.readiness_stages, TEXT) IS 'Возвращает компактный список документов для конкретного пользователя с приоритетом его личного буфера и строгой изоляцией от буферов других пользователей.';


    -- Получение полной обогащённой карточки документа (Detail)

        CREATE OR REPLACE FUNCTION documents.function_get_user_document_detail(
            p_entity_id     UUID,
            p_user_id       UUID
        )
        RETURNS TABLE (
            entity_id                   UUID,
            display_datetime            TIMESTAMPTZ,
            display_state               documents.readiness_stages,
            display_topic               VARCHAR(150),
            display_out_number          VARCHAR(100),
            display_template_id         UUID,
            display_field_overrides     JSONB,
            display_message_bindings    JSONB,
            display_note                VARCHAR(255),
            display_details             JSONB,
            display_content_hash        BYTEA,
            display_author_id           UUID,
            display_author_name         TEXT,
            has_buffer                  BOOLEAN,
            revision_id                 UUID,
            created_at                  TIMESTAMPTZ
        )
        LANGUAGE plpgsql
        AS $$

        BEGIN
            RETURN QUERY
            SELECT
                entities.id                                                                             AS entity_id,

                COALESCE(revision_buffer.updated_at, latest_revision.created_at, entities.created_at)   AS display_datetime,

                state_cache.readiness_stage                                                             AS display_state,

                COALESCE(revision_buffer.topic, latest_revision.topic, '')                              AS display_topic,

                CASE
                    WHEN revision_buffer.entity_id IS NOT NULL THEN revision_buffer.out_number
                    ELSE latest_revision.out_number
                END                                                                                     AS display_out_number,

                COALESCE(revision_buffer.template_id, latest_revision.template_id)                      AS display_template_id,

                CASE
                    WHEN revision_buffer.entity_id IS NOT NULL THEN revision_buffer.field_overrides
                    ELSE latest_revision.field_overrides
                END                                                                                     AS display_field_overrides,

                CASE
                    WHEN revision_buffer.entity_id IS NOT NULL THEN revision_buffer.message_bindings
                    ELSE latest_revision.message_bindings
                END                                                                                     AS display_message_bindings,

                CASE
                    WHEN revision_buffer.entity_id IS NOT NULL THEN revision_buffer.note
                    ELSE latest_revision.note
                END                                                                                     AS display_note,

                CASE
                    WHEN revision_buffer.entity_id IS NOT NULL THEN revision_buffer.details
                    ELSE latest_revision.details
                END                                                                                     AS display_details,

                CASE
                    WHEN revision_buffer.entity_id IS NOT NULL THEN revision_buffer.content_hash
                    ELSE latest_revision.content_hash
                END                                                                                     AS display_content_hash,

                COALESCE(revision_buffer.user_id, latest_revision.user_id, entities.user_id)            AS display_author_id,

                COALESCE(
                    NULLIF(
                        CONCAT_WS(' ',
                            author_users.last_name,
                            author_users.first_name,
                            author_users.middle_name
                        ),
                        ''
                    ),
                    'Неизвестный автор'
                )                                           AS display_author_name,

                (revision_buffer.entity_id IS NOT NULL)     AS has_buffer,
                latest_revision.revision_id                 AS revision_id,
                entities.created_at                         AS created_at

            FROM documents.entities AS entities

            -- Присоединение личного буфера текущего пользователя
            LEFT JOIN documents.revision_buffer AS revision_buffer
                ON revision_buffer.entity_id = entities.id
                AND revision_buffer.user_id = p_user_id

            -- Присоединение последней опубликованной ревизии
            LEFT JOIN LATERAL (
                SELECT
                    revisions.id            AS revision_id,
                    revisions.entity_id,
                    revisions.template_id,
                    revisions.out_number,
                    revisions.topic,
                    revisions.field_overrides,
                    revisions.message_bindings,
                    revisions.note,
                    revisions.content_hash,
                    revisions.details,
                    revisions.created_at,
                    revisions.user_id
                FROM documents.revisions AS revisions
                WHERE revisions.entity_id = entities.id
                ORDER BY revisions.created_at DESC, revisions.id DESC
                LIMIT 1
            ) AS latest_revision ON TRUE

            -- Присоединение кэша состояния
            LEFT JOIN documents.state_cache AS state_cache
                ON state_cache.entity_id = entities.id

            -- Данные автора изменений
            LEFT JOIN identity.users AS author_users
                ON author_users.id = COALESCE(
                    revision_buffer.user_id,
                    latest_revision.user_id,
                    entities.user_id
                )

            WHERE entities.id = p_entity_id
                AND (state_cache.is_deleted = FALSE OR state_cache.is_deleted IS NULL);
        END;
        $$;

        COMMENT ON FUNCTION documents.function_get_user_document_detail(UUID, UUID) IS 'Возвращает детальную карточку документа для пользователя с полным набором метаданных, приоритизируя личный буфер черновика.';


-- Процедуры #


-- Таблицы #

    -- Реестр документов @

        -- Хранит идентификаторы документов и связывает их версии и состояния

        -- Таблица #

            CREATE TABLE documents.entities (

                -- Ключи и связи #

                    id                      UUID                        PRIMARY KEY                                 DEFAULT uuid_generate_v7(),

                    user_id                 UUID                        REFERENCES identity.users(id)
                                                                        NOT NULL,


                -- Временные метки #

                    created_at              TIMESTAMPTZ                 NOT NULL                                    DEFAULT CURRENT_TIMESTAMP

            );


        -- Комментарии #

            COMMENT ON TABLE documents.entities IS 'Реестр документов. Хранит идентификаторы документов, для которых ведется история версий и состояний.';

            COMMENT ON COLUMN documents.entities.id IS 'Уникальный идентификатор документа.';
            COMMENT ON COLUMN documents.entities.user_id IS 'Идентификатор пользователя, создавшего документ.';
            COMMENT ON COLUMN documents.entities.created_at IS 'Дата и время создания документа.';


        -- Индексы #

            CREATE INDEX index_documents_entities_user_id
                ON documents.entities(user_id);

            COMMENT ON INDEX index_documents_entities_user_id IS 'Ускоряет выборку документов по их автору.';


            CREATE INDEX index_documents_entities_created_at
                ON documents.entities(created_at DESC);

            COMMENT ON INDEX index_documents_entities_created_at IS 'Оптимизирует сортировку документов по времени создания.';


        -- Обработчики событий #

            CREATE TRIGGER trigger_documents_entities_state_initialization
                AFTER INSERT ON documents.entities
                FOR EACH ROW
                EXECUTE FUNCTION common.function_initialize_state_log(
                    'documents.states',
                    'entity_id',
                    '{"readiness_stage": "draft", "is_archived": false, "is_deleted": false, "content_hash": "\\xf9266e4166ddff1969cff2f11b3e19f28f495c6236f07c32459e52f6d3f6062d"}'
                );

            COMMENT ON TRIGGER trigger_documents_entities_state_initialization ON documents.entities IS 'Создает начальную запись состояния документа в журнале.';


            CREATE TRIGGER trigger_documents_entities_immutability
                BEFORE UPDATE OR DELETE ON documents.entities
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_immutability();

            COMMENT ON TRIGGER trigger_documents_entities_immutability ON documents.entities IS 'Запрещает изменять или удалять созданный документ.';


    -- Реестр шаблонов @

        -- Хранит идентификаторы шаблонов документов и связывает их версии

        -- Таблица #

            CREATE TABLE documents.template_entities (

                -- Ключи и связи #

                    id                      UUID                        PRIMARY KEY                                 DEFAULT uuid_generate_v7(),

                    user_id                 UUID                        NOT NULL
                                                                        REFERENCES identity.users(id),


                -- Временные метки #

                    created_at              TIMESTAMPTZ                 NOT NULL                                    DEFAULT CURRENT_TIMESTAMP

            );


        -- Комментарии #

            COMMENT ON TABLE documents.template_entities IS 'Реестр шаблонов документов. Хранит идентификаторы шаблонов, для которых ведется история версий.';

            COMMENT ON COLUMN documents.template_entities.id IS 'Уникальный идентификатор шаблона документа.';
            COMMENT ON COLUMN documents.template_entities.user_id IS 'Идентификатор пользователя, создавшего шаблон.';
            COMMENT ON COLUMN documents.template_entities.created_at IS 'Дата и время создания шаблона.';


        -- Индексы #

            CREATE INDEX index_documents_template_entities_user_id
                ON documents.template_entities(user_id);

            COMMENT ON INDEX index_documents_template_entities_user_id IS 'Ускоряет выборку шаблонов по их автору.';


            CREATE INDEX index_documents_template_entities_created_at
                ON documents.template_entities(created_at DESC);

            COMMENT ON INDEX index_documents_template_entities_created_at IS 'Оптимизирует сортировку шаблонов по времени создания.';


        -- Обработчики событий #

            CREATE TRIGGER trigger_documents_template_entities_immutability
                BEFORE UPDATE OR DELETE ON documents.template_entities
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_immutability();

            COMMENT ON TRIGGER trigger_documents_template_entities_immutability ON documents.template_entities IS 'Запрещает изменять или удалять созданный шаблон.';


    -- Архив ревизий шаблонов @

        -- Хранит неизменяемые версии HTML-шаблонов с декларацией полей и значениями по умолчанию

        -- Таблица #

            CREATE TABLE documents.template_revisions (

                -- Ключи и связи #

                    id                      UUID                        PRIMARY KEY                                 DEFAULT uuid_generate_v7(),

                    template_entity_id      UUID                        NOT NULL
                                                                        REFERENCES documents.template_entities(id)
                                                                        ON DELETE CASCADE,

                    user_id                 UUID                        NOT NULL
                                                                        REFERENCES identity.users(id),


                -- Основное содержимое #

                    code                    VARCHAR(50)                 NOT NULL,
                    title                   VARCHAR(150)                NOT NULL,
                    description             VARCHAR(255),
                    body_html               TEXT                        NOT NULL,
                    field_schema            JSONB                       NOT NULL                                    DEFAULT '{}'::jsonb,
                    default_overrides       JSONB                       NOT NULL                                    DEFAULT '{}'::jsonb,
                    content_hash            BYTEA                       NOT NULL,


                -- Временные метки #

                    created_at              TIMESTAMPTZ                 NOT NULL                                    DEFAULT CURRENT_TIMESTAMP,


                -- Проверки целостности #

                    CONSTRAINT check_template_content_hash_length CHECK (length(content_hash) = 32)

            );


        -- Комментарии #

            COMMENT ON TABLE documents.template_revisions IS 'История неизменяемых версий HTML-шаблонов документов.';

            COMMENT ON COLUMN documents.template_revisions.id IS 'Уникальный идентификатор ревизии шаблона.';
            COMMENT ON COLUMN documents.template_revisions.template_entity_id IS 'Идентификатор родительского шаблона.';
            COMMENT ON COLUMN documents.template_revisions.user_id IS 'Идентификатор пользователя, создавшего эту ревизию шаблона.';
            COMMENT ON COLUMN documents.template_revisions.code IS 'Системный код шаблона для идентификации типа документа, например: ''storm_warning'', ''daily_bulletin''.';
            COMMENT ON COLUMN documents.template_revisions.title IS 'Человекочитаемое название шаблона.';
            COMMENT ON COLUMN documents.template_revisions.description IS 'Описание назначения и особенностей шаблона.';
            COMMENT ON COLUMN documents.template_revisions.body_html IS 'Исходный код HTML-шаблона в формате Django Templates.';
            COMMENT ON COLUMN documents.template_revisions.field_schema IS 'Декларация полей шаблона: типы, UI-контролы, требования, варианты выбора.';
            COMMENT ON COLUMN documents.template_revisions.default_overrides IS 'Значения по умолчанию для реквизитов формы, используемые в интерфейсе редактирования.';
            COMMENT ON COLUMN documents.template_revisions.content_hash IS 'Хеш содержимого шаблона (BLAKE3).';
            COMMENT ON COLUMN documents.template_revisions.created_at IS 'Дата и время создания ревизии шаблона.';

            COMMENT ON CONSTRAINT check_template_content_hash_length ON documents.template_revisions IS 'Проверяет, что хеш содержимого шаблона (BLAKE3) имеет длину 32 байта.';


        -- Индексы #

            CREATE INDEX index_documents_template_revisions_entity
                ON documents.template_revisions(template_entity_id, created_at DESC, id DESC);

            COMMENT ON INDEX index_documents_template_revisions_entity IS 'Ускоряет получение последней версии шаблона.';


            CREATE INDEX index_documents_template_revisions_user_id
                ON documents.template_revisions(user_id);

            COMMENT ON INDEX index_documents_template_revisions_user_id IS 'Ускоряет выборку ревизий шаблонов по автору.';


            CREATE INDEX index_documents_template_revisions_code
                ON documents.template_revisions(code);

            COMMENT ON INDEX index_documents_template_revisions_code IS 'Ускоряет поиск ревизий шаблонов по системному коду.';


            CREATE INDEX index_documents_template_revisions_created_at
                ON documents.template_revisions(created_at DESC);

            COMMENT ON INDEX index_documents_template_revisions_created_at IS 'Оптимизирует сортировку ревизий шаблонов по времени создания.';


            CREATE INDEX index_documents_template_revisions_field_schema
                ON documents.template_revisions
                USING gin(field_schema jsonb_path_ops);

            COMMENT ON INDEX index_documents_template_revisions_field_schema IS 'Ускоряет поиск по декларации полей шаблона в JSONB.';


            CREATE INDEX index_documents_template_revisions_default_overrides
                ON documents.template_revisions
                USING gin(default_overrides jsonb_path_ops);

            COMMENT ON INDEX index_documents_template_revisions_default_overrides IS 'Ускоряет поиск по значениям по умолчанию в JSONB.';


        -- Обработчики событий #

            CREATE TRIGGER trigger_documents_template_revisions_immutability
                BEFORE UPDATE OR DELETE ON documents.template_revisions
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_immutability();

            COMMENT ON TRIGGER trigger_documents_template_revisions_immutability ON documents.template_revisions IS 'Запрещает изменять или удалять зафиксированные ревизии шаблонов.';


    -- Буфер правок документов @

        -- Хранит текущие несохраненные изменения документа
        -- Каждый пользователь располагает собственным буфером для каждого документа
        -- Технический первичный ключ используется для совместимости с Django ORM,
        -- Django Admin и инструментами, работающими с одиночным первичным ключом.
        -- Доменная уникальность при этом сохраняется парой (entity_id, user_id).

        -- Таблица #

            CREATE TABLE documents.revision_buffer (

                -- Ключи и связи #

                    id                      UUID                        NOT NULL                                    DEFAULT uuid_generate_v7(),

                    entity_id               UUID                        NOT NULL
                                                                        REFERENCES documents.entities(id)
                                                                        ON DELETE CASCADE,

                    parent_id               UUID                        REFERENCES documents.entities(id)
                                                                        ON DELETE SET NULL,

                    template_id             UUID                        NOT NULL
                                                                        REFERENCES documents.template_revisions(id)
                                                                        ON DELETE RESTRICT,

                    user_id                 UUID                        NOT NULL
                                                                        REFERENCES identity.users(id),


                -- Основное содержимое #

                    out_number              VARCHAR(100),
                    topic                   VARCHAR(150)                NOT NULL,
                    field_overrides         JSONB                       NOT NULL                                    DEFAULT '{}'::jsonb,
                    message_bindings        JSONB                       NOT NULL                                    DEFAULT '[]'::jsonb,
                    note                    VARCHAR(255),
                    content_hash            BYTEA                       NOT NULL,


                -- Расширенные метаданные #

                    details                 JSONB                       NOT NULL                                    DEFAULT '{}'::jsonb,


                -- Временные метки #

                    updated_at              TIMESTAMPTZ                 NOT NULL                                    DEFAULT CURRENT_TIMESTAMP,


                -- Проверки целостности #

                    -- Исторический первичный ключ по документу.
                    -- Оставлен в комментарии для фиксации проектного решения:
                    -- прежняя версия рассматривала entity_id как единственный ключ буфера.
                    -- Теперь этот смысл сохранён в уникальном ограничении, а первичный ключ стал техническим.
                    -- PRIMARY KEY (entity_id),

                    CONSTRAINT documents_revision_buffer_pkey PRIMARY KEY (id),
                    CONSTRAINT documents_revision_buffer_entity_id_user_id_unique UNIQUE (entity_id, user_id),

                    CONSTRAINT check_revision_buffer_content_hash_length CHECK (length(content_hash) = 32),
                    CONSTRAINT check_revision_buffer_parent_not_self CHECK (parent_id IS DISTINCT FROM entity_id),
                    CONSTRAINT check_revision_buffer_message_bindings_is_array CHECK (jsonb_typeof(message_bindings) = 'array')

            );


        -- Комментарии #

            COMMENT ON TABLE documents.revision_buffer IS 'Буфер несохраненных изменений документов. Хранит текущее рабочее состояние для каждого пользователя и документа.';

            COMMENT ON COLUMN documents.revision_buffer.id IS 'Технический суррогатный идентификатор рабочего буфера. Добавлен для совместимости с Django ORM и другими инструментами, ожидающими один первичный ключ.';
            COMMENT ON COLUMN documents.revision_buffer.entity_id IS 'Идентификатор документа.';
            COMMENT ON COLUMN documents.revision_buffer.parent_id IS 'Идентификатор исходного документа для корректировки или отмены.';
            COMMENT ON COLUMN documents.revision_buffer.template_id IS 'Идентификатор ревизии шаблона печатной формы.';
            COMMENT ON COLUMN documents.revision_buffer.user_id IS 'Идентификатор пользователя, редактирующего документ.';
            COMMENT ON COLUMN documents.revision_buffer.out_number IS 'Проект исходящего номера документа.';
            COMMENT ON COLUMN documents.revision_buffer.topic IS 'Тема документа.';
            COMMENT ON COLUMN documents.revision_buffer.field_overrides IS 'Текущие значения реквизитов документа для формирования выходной формы.';
            COMMENT ON COLUMN documents.revision_buffer.message_bindings IS 'Черновые привязки сообщений к слотам шаблона. Хранится как массив объектов {slot_code, message_entity_id, message_revision_id}. message_entity_id используется для обратного поиска, message_revision_id — для точной фиксации снимка сообщения.';
            COMMENT ON COLUMN documents.revision_buffer.note IS 'Комментарий к документу.';
            COMMENT ON COLUMN documents.revision_buffer.content_hash IS 'Контент-хэш снимка документа (BLAKE3). Вычисляется от канонической полезной нагрузки: template_id, out_number, topic, field_overrides, значимой части message_bindings (slot_code, message_revision_id), note/details, если они значимы. Не включает технические поля: id, entity_id, user_id, created_at, updated_at, сам хэш.';
            COMMENT ON COLUMN documents.revision_buffer.details IS 'Дополнительные параметры документа в формате JSONB.';
            COMMENT ON COLUMN documents.revision_buffer.updated_at IS 'Дата и время последнего изменения буфера.';

            COMMENT ON CONSTRAINT documents_revision_buffer_pkey ON documents.revision_buffer IS 'Технический первичный ключ рабочего буфера. Нужен для однозначной идентификации записи в Django ORM, API и служебных операциях.';
            COMMENT ON CONSTRAINT documents_revision_buffer_entity_id_user_id_unique ON documents.revision_buffer IS 'Доменная уникальность рабочего буфера: один документ может иметь только один рабочий буфер для одного пользователя.';
            COMMENT ON CONSTRAINT check_revision_buffer_content_hash_length ON documents.revision_buffer IS 'Проверяет, что хеш содержимого документа (BLAKE3) имеет длину 32 байта.';
            COMMENT ON CONSTRAINT check_revision_buffer_parent_not_self ON documents.revision_buffer IS 'Запрещает самопривязку, когда документ ссылается сам на себя.';
            COMMENT ON CONSTRAINT check_revision_buffer_message_bindings_is_array ON documents.revision_buffer IS 'Проверяет, что привязки сообщений хранятся в виде JSON-массива.';


        -- Индексы #

            CREATE INDEX index_documents_revision_buffer_parent
                ON documents.revision_buffer(parent_id);

            COMMENT ON INDEX index_documents_revision_buffer_parent IS 'Ускоряет поиск документов, связанных с корректировками и отменами.';


            CREATE INDEX index_documents_revision_buffer_user_id
                ON documents.revision_buffer(user_id);

            COMMENT ON INDEX index_documents_revision_buffer_user_id IS 'Ускоряет выборку несохраненных документов пользователя.';


            CREATE INDEX index_documents_revision_buffer_topic_trigram
                ON documents.revision_buffer
                USING gin(topic gin_trgm_ops);

            COMMENT ON INDEX index_documents_revision_buffer_topic_trigram IS 'Ускоряет поиск по теме черновиков документов.';


            CREATE INDEX index_documents_revision_buffer_field_overrides
                ON documents.revision_buffer
                USING gin(field_overrides jsonb_path_ops);

            COMMENT ON INDEX index_documents_revision_buffer_field_overrides IS 'Ускоряет поиск по реквизитам документа в JSONB.';


            CREATE INDEX index_documents_revision_buffer_message_bindings
                ON documents.revision_buffer
                USING gin(message_bindings jsonb_path_ops);

            COMMENT ON INDEX index_documents_revision_buffer_message_bindings IS 'Ускоряет поиск по привязкам сообщений в черновиках, в том числе по message_entity_id и message_revision_id.';


            CREATE INDEX index_documents_revision_buffer_details
                ON documents.revision_buffer
                USING gin(details jsonb_path_ops);

            COMMENT ON INDEX index_documents_revision_buffer_details IS 'Ускоряет поиск по дополнительным параметрам документа в JSONB.';


            CREATE INDEX index_documents_revision_buffer_updated_at
                ON documents.revision_buffer(updated_at DESC);

            COMMENT ON INDEX index_documents_revision_buffer_updated_at IS 'Оптимизирует сортировку буферов по времени изменения.';


        -- Обработчики событий #

            CREATE TRIGGER trigger_documents_revision_buffer_identity
                BEFORE UPDATE OF id, entity_id, user_id ON documents.revision_buffer
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_revision_buffer_identity();

            COMMENT ON TRIGGER trigger_documents_revision_buffer_identity ON documents.revision_buffer IS 'Запрещает изменять суррогатный и доменный ключи рабочего буфера документа.';


            CREATE TRIGGER trigger_documents_revision_buffer_updated_at
                BEFORE UPDATE ON documents.revision_buffer
                FOR EACH ROW
                EXECUTE FUNCTION common.function_refresh_updated_at_column();

            COMMENT ON TRIGGER trigger_documents_revision_buffer_updated_at ON documents.revision_buffer IS 'Обновляет время последнего изменения буфера.';


    -- Архив ревизий документов @

        -- Хранит историю зафиксированных версий документов

        -- Таблица #

            CREATE TABLE documents.revisions (

                -- Ключи и связи #

                    id                      UUID                        PRIMARY KEY                                 DEFAULT uuid_generate_v7(),

                    entity_id               UUID                        NOT NULL
                                                                        REFERENCES documents.entities(id)
                                                                        ON DELETE CASCADE,

                    parent_id               UUID                        REFERENCES documents.entities(id)
                                                                        ON DELETE SET NULL,

                    template_id             UUID                        NOT NULL
                                                                        REFERENCES documents.template_revisions(id)
                                                                        ON DELETE RESTRICT,

                    user_id                 UUID                        NOT NULL
                                                                        REFERENCES identity.users(id),


                -- Основное содержимое #

                    out_number              VARCHAR(100),
                    topic                   VARCHAR(150)                NOT NULL,
                    field_overrides         JSONB                       NOT NULL                                    DEFAULT '{}'::jsonb,
                    message_bindings        JSONB                       NOT NULL                                    DEFAULT '[]'::jsonb,
                    note                    VARCHAR(255),
                    content_hash            BYTEA                       NOT NULL,


                -- Расширенные метаданные #

                    details                 JSONB                       NOT NULL                                    DEFAULT '{}'::jsonb,


                -- Временные метки #

                    created_at              TIMESTAMPTZ                 NOT NULL                                    DEFAULT CURRENT_TIMESTAMP,


                -- Проверки целостности #

                    CONSTRAINT check_revisions_content_hash_length CHECK (length(content_hash) = 32),
                    CONSTRAINT check_revisions_parent_not_self CHECK (parent_id IS DISTINCT FROM entity_id),
                    CONSTRAINT check_revisions_message_bindings_is_array CHECK (jsonb_typeof(message_bindings) = 'array')

            );


        -- Комментарии #

            COMMENT ON TABLE documents.revisions IS 'История зафиксированных версий документов.';

            COMMENT ON COLUMN documents.revisions.id IS 'Уникальный идентификатор ревизии.';
            COMMENT ON COLUMN documents.revisions.entity_id IS 'Идентификатор документа.';
            COMMENT ON COLUMN documents.revisions.parent_id IS 'Идентификатор исходного документа для корректировки или отмены.';
            COMMENT ON COLUMN documents.revisions.template_id IS 'Идентификатор ревизии шаблона печатной формы.';
            COMMENT ON COLUMN documents.revisions.user_id IS 'Идентификатор пользователя, зафиксировавшего ревизию.';
            COMMENT ON COLUMN documents.revisions.out_number IS 'Исходящий номер документа.';
            COMMENT ON COLUMN documents.revisions.topic IS 'Тема документа.';
            COMMENT ON COLUMN documents.revisions.field_overrides IS 'Значения реквизитов документа на момент фиксации ревизии.';
            COMMENT ON COLUMN documents.revisions.message_bindings IS 'Зафиксированные привязки сообщений к слотам шаблона. Хранится как массив объектов {slot_code, message_entity_id, message_revision_id}. message_entity_id используется для обратного поиска, message_revision_id — для точной фиксации снимка сообщения.';
            COMMENT ON COLUMN documents.revisions.note IS 'Комментарий к ревизии.';
            COMMENT ON COLUMN documents.revisions.content_hash IS 'Контент-хэш снимка документа (BLAKE3). Вычисляется от канонической полезной нагрузки: template_id, out_number, topic, field_overrides, значимой части message_bindings (slot_code, message_revision_id), note/details, если они значимы. Не включает технические поля: id, entity_id, user_id, created_at, сам хэш.';
            COMMENT ON COLUMN documents.revisions.details IS 'Дополнительные параметры документа в формате JSONB.';
            COMMENT ON COLUMN documents.revisions.created_at IS 'Дата и время создания ревизии.';

            COMMENT ON CONSTRAINT check_revisions_content_hash_length ON documents.revisions IS 'Проверяет, что хеш содержимого документа (BLAKE3) имеет длину 32 байта.';
            COMMENT ON CONSTRAINT check_revisions_parent_not_self ON documents.revisions IS 'Запрещает самопривязку, когда документ ссылается сам на себя.';
            COMMENT ON CONSTRAINT check_revisions_message_bindings_is_array ON documents.revisions IS 'Проверяет, что привязки сообщений хранятся в виде JSON-массива.';


        -- Индексы #

            CREATE INDEX index_documents_revisions_entity_time
                ON documents.revisions(entity_id, created_at DESC, id DESC);

            COMMENT ON INDEX index_documents_revisions_entity_time IS 'Оптимизирует получение последней ревизии документа.';


            CREATE INDEX index_documents_revisions_parent_id
                ON documents.revisions(parent_id);

            COMMENT ON INDEX index_documents_revisions_parent_id IS 'Ускоряет поиск документов, связанных с корректировками и отменами.';


            CREATE INDEX index_documents_revisions_template_id
                ON documents.revisions(template_id);

            COMMENT ON INDEX index_documents_revisions_template_id IS 'Ускоряет фильтрацию документов по шаблону.';


            CREATE INDEX index_documents_revisions_user_id
                ON documents.revisions(user_id);

            COMMENT ON INDEX index_documents_revisions_user_id IS 'Ускоряет выборку ревизий документов по автору.';


            CREATE INDEX index_documents_revisions_created_at
                ON documents.revisions(created_at DESC);

            COMMENT ON INDEX index_documents_revisions_created_at IS 'Оптимизирует сортировку ревизий документов по времени создания.';


            CREATE INDEX index_documents_revisions_out_number
                ON documents.revisions(out_number)
                WHERE (out_number IS NOT NULL);

            COMMENT ON INDEX index_documents_revisions_out_number IS 'Ускоряет поиск по исходящему номеру документа.';


            CREATE INDEX index_documents_revisions_topic_trigram
                ON documents.revisions USING gin(topic gin_trgm_ops);

            COMMENT ON INDEX index_documents_revisions_topic_trigram IS 'Ускоряет поиск по теме документа.';


            CREATE INDEX index_documents_revisions_field_overrides
                ON documents.revisions USING gin(field_overrides jsonb_path_ops);

            COMMENT ON INDEX index_documents_revisions_field_overrides IS 'Ускоряет поиск по реквизитам документа в JSONB.';


            CREATE INDEX index_documents_revisions_message_bindings
                ON documents.revisions USING gin(message_bindings jsonb_path_ops);

            COMMENT ON INDEX index_documents_revisions_message_bindings IS 'Ускоряет поиск документов по использованным ревизиям и идентификаторам сообщений внутри привязок.';


        -- Обработчики событий #

            CREATE TRIGGER trigger_documents_revisions_immutability
                BEFORE UPDATE OR DELETE ON documents.revisions
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_immutability();

            COMMENT ON TRIGGER trigger_documents_revisions_immutability ON documents.revisions IS 'Запрещает изменять или удалять зафиксированные ревизии.';


    -- Текущие состояния документов @

        -- Хранит текущее состояние документов для быстрого поиска и выборки
        -- Обновляется автоматически на основе журнала состояний

        -- Таблица #

            CREATE TABLE documents.state_cache (

                -- Ключи и связи #

                    entity_id               UUID                        PRIMARY KEY
                                                                        REFERENCES documents.entities(id)
                                                                        ON DELETE CASCADE,

                    revision_id             UUID                        REFERENCES documents.revisions(id)
                                                                        ON DELETE RESTRICT,

                    user_id                 UUID                        NOT NULL
                                                                        REFERENCES identity.users(id),


                -- Основное содержимое #

                    readiness_stage         documents.readiness_stages  NOT NULL                                    DEFAULT 'draft'::documents.readiness_stages,
                    is_archived             BOOLEAN                     NOT NULL                                    DEFAULT FALSE,
                    is_deleted              BOOLEAN                     NOT NULL                                    DEFAULT FALSE,
                    content_hash            BYTEA                       NOT NULL,


                -- Расширенные метаданные #

                    details                 JSONB                       NOT NULL                                    DEFAULT '{}'::jsonb,


                -- Временные метки #

                    updated_at              TIMESTAMPTZ                 NOT NULL                                    DEFAULT CURRENT_TIMESTAMP,


                -- Проверки целостности #

                    CONSTRAINT check_state_cache_content_hash_length CHECK (length(content_hash) = 32)

            );


        -- Комментарии #

            COMMENT ON TABLE documents.state_cache IS 'Текущие состояния документов. Обновляется автоматически на основе журнала documents.states.';

            COMMENT ON COLUMN documents.state_cache.entity_id IS 'Идентификатор документа.';
            COMMENT ON COLUMN documents.state_cache.revision_id IS 'Идентификатор ревизии, к которой относится текущее состояние готовности (если применимо).';
            COMMENT ON COLUMN documents.state_cache.user_id IS 'Идентификатор пользователя, последним изменившего состояние.';
            COMMENT ON COLUMN documents.state_cache.readiness_stage IS 'Текущее состояние документа.';
            COMMENT ON COLUMN documents.state_cache.is_archived IS 'Признак нахождения документа в архиве.';
            COMMENT ON COLUMN documents.state_cache.is_deleted IS 'Признак скрытия документа из рабочего списка пользователем.';
            COMMENT ON COLUMN documents.state_cache.content_hash IS 'Контент-хэш снимка состояния документа (BLAKE3). Вычисляется от полезной нагрузки состояния: readiness_stage, is_archived, is_deleted, details. Не включает контекст: id, entity_id, revision_id, user_id, updated_at.';
            COMMENT ON COLUMN documents.state_cache.details IS 'Дополнительные сведения о текущем состоянии.';
            COMMENT ON COLUMN documents.state_cache.updated_at IS 'Дата и время последнего изменения состояния.';

            COMMENT ON CONSTRAINT check_state_cache_content_hash_length ON documents.state_cache IS 'Проверяет, что хеш снимка состояния (BLAKE3) имеет длину 32 байта.';


        -- Индексы #

            CREATE INDEX index_documents_state_cache_entity_stage
                ON documents.state_cache(entity_id, readiness_stage);

            COMMENT ON INDEX index_documents_state_cache_entity_stage IS 'Ускоряет выборку документов по текущему состоянию.';


            CREATE INDEX index_documents_state_cache_active
                ON documents.state_cache(readiness_stage)
                WHERE (is_deleted = FALSE
                    AND is_archived = FALSE);

            COMMENT ON INDEX index_documents_state_cache_active IS 'Ускоряет выборку активных документов, не скрытых пользователем и не находящихся в архиве.';


            CREATE INDEX index_documents_state_cache_draft
                ON documents.state_cache(readiness_stage)
                WHERE (readiness_stage = 'draft'
                    AND is_deleted = FALSE);

            COMMENT ON INDEX index_documents_state_cache_draft IS 'Ускоряет выборку документов в состоянии draft.';


            CREATE INDEX index_documents_state_cache_details
                ON documents.state_cache
                USING gin(details jsonb_path_ops);

            COMMENT ON INDEX index_documents_state_cache_details IS 'Ускоряет поиск по дополнительным параметрам текущего состояния.';


            CREATE INDEX index_documents_state_cache_updated_at
                ON documents.state_cache(updated_at DESC);

            COMMENT ON INDEX index_documents_state_cache_updated_at IS 'Оптимизирует сортировку документов по времени изменения состояния.';


        -- Обработчики событий #

            CREATE TRIGGER trigger_documents_state_cache_updated_at
                BEFORE UPDATE ON documents.state_cache
                FOR EACH ROW
                EXECUTE FUNCTION common.function_refresh_updated_at_column();

            COMMENT ON TRIGGER trigger_documents_state_cache_updated_at ON documents.state_cache IS 'Обновляет время последнего изменения состояния.';


            CREATE TRIGGER trigger_documents_state_cache_revision_entity_consistency
                BEFORE INSERT OR UPDATE OF entity_id, revision_id ON documents.state_cache
                FOR EACH ROW
                EXECUTE FUNCTION common.function_validate_state_revision_entity();

            COMMENT ON TRIGGER trigger_documents_state_cache_revision_entity_consistency ON documents.state_cache IS 'Защищает от привязки кэша состояния к ревизии другого документа.';


    -- Журнал состояний документов @

        -- Хранит историю изменений состояний документов
        -- Каждая запись содержит состояние документа на момент изменения

        -- Таблица #

            CREATE TABLE documents.states (

                -- Ключи и связи #

                    id                      UUID                        PRIMARY KEY                                 DEFAULT uuid_generate_v7(),

                    entity_id               UUID                        NOT NULL
                                                                        REFERENCES documents.entities(id)
                                                                        ON DELETE CASCADE,

                    revision_id             UUID                        REFERENCES documents.revisions(id)
                                                                        ON DELETE RESTRICT,

                    user_id                 UUID                        NOT NULL
                                                                        REFERENCES identity.users(id),


                -- Основное содержимое #

                    readiness_stage         documents.readiness_stages  NOT NULL                                    DEFAULT 'draft'::documents.readiness_stages,
                    is_archived             BOOLEAN                     NOT NULL                                    DEFAULT FALSE,
                    is_deleted              BOOLEAN                     NOT NULL                                    DEFAULT FALSE,
                    content_hash            BYTEA                       NOT NULL,


                -- Расширенные метаданные #

                    details                 JSONB                       NOT NULL                                    DEFAULT '{}'::jsonb,


                -- Временные метки #

                    created_at              TIMESTAMPTZ                 NOT NULL                                    DEFAULT CURRENT_TIMESTAMP,


                -- Проверки целостности #

                    CONSTRAINT check_states_content_hash_length CHECK (length(content_hash) = 32)

            );


        -- Комментарии #

            COMMENT ON TABLE documents.states IS 'История изменений состояний документов. Каждая запись содержит состояние документа на момент изменения.';

            COMMENT ON COLUMN documents.states.id IS 'Уникальный идентификатор записи истории.';
            COMMENT ON COLUMN documents.states.entity_id IS 'Идентификатор документа.';
            COMMENT ON COLUMN documents.states.revision_id IS 'Идентификатор ревизии, к которой относится изменение состояния готовности (если применимо).';
            COMMENT ON COLUMN documents.states.user_id IS 'Идентификатор пользователя, изменившего состояние.';
            COMMENT ON COLUMN documents.states.readiness_stage IS 'Состояние документа, зафиксированное в записи.';
            COMMENT ON COLUMN documents.states.is_archived IS 'Признак нахождения документа в архиве на момент записи.';
            COMMENT ON COLUMN documents.states.is_deleted IS 'Признак скрытия документа из рабочего списка пользователем на момент записи.';
            COMMENT ON COLUMN documents.states.content_hash IS 'Контент-хэш снимка состояния документа (BLAKE3). Вычисляется от полезной нагрузки состояния: readiness_stage, is_archived, is_deleted, details. Не включает контекст: id, entity_id, revision_id, user_id, created_at.';
            COMMENT ON COLUMN documents.states.details IS 'Дополнительные сведения о переходе состояния.';
            COMMENT ON COLUMN documents.states.created_at IS 'Дата и время изменения состояния.';

            COMMENT ON CONSTRAINT check_states_content_hash_length ON documents.states IS 'Проверяет, что хеш снимка состояния (BLAKE3) имеет длину 32 байта.';


        -- Индексы #

            CREATE INDEX index_documents_states_chronology
                ON documents.states(entity_id, created_at ASC);

            COMMENT ON INDEX index_documents_states_chronology IS 'Ускоряет получение истории состояний документа.';


            CREATE INDEX index_documents_states_created_at
                ON documents.states(created_at DESC);

            COMMENT ON INDEX index_documents_states_created_at IS 'Оптимизирует выборку общего журнала изменений состояний.';


            CREATE INDEX index_documents_states_revision_id
                ON documents.states(revision_id);

            COMMENT ON INDEX index_documents_states_revision_id IS 'Ускоряет поиск состояний, связанных с конкретной ревизией документа.';


        -- Обработчики событий #

            CREATE TRIGGER trigger_documents_states_revision_entity_consistency
                BEFORE INSERT OR UPDATE OF entity_id, revision_id ON documents.states
                FOR EACH ROW
                EXECUTE FUNCTION common.function_validate_state_revision_entity();

            COMMENT ON TRIGGER trigger_documents_states_revision_entity_consistency ON documents.states IS 'Защищает от привязки состояния к ревизии другого документа.';


            CREATE TRIGGER trigger_documents_states_cache_sync
                AFTER INSERT ON documents.states
                FOR EACH ROW
                EXECUTE FUNCTION common.function_upsert_current_state('documents.state_cache', 'entity_id');

            COMMENT ON TRIGGER trigger_documents_states_cache_sync ON documents.states IS 'Обновляет текущее состояние документа на основе журнала.';


            CREATE TRIGGER trigger_documents_states_immutability
                BEFORE UPDATE OR DELETE ON documents.states
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_immutability();

            COMMENT ON TRIGGER trigger_documents_states_immutability ON documents.states IS 'Запрещает изменять или удалять записи истории состояний.';


-- Представления #


-- Материализованные представления #


-- Права доступа #
