-- Метаданные #


-- Расширения #


-- Настройки сессии #

    -- Явная привязка к схеме messages для защиты от случайного развертывания в чужую схему

    SELECT pg_catalog.set_config('search_path', 'messages, public', FALSE);


-- Схемы #

    -- Создание изолированной схемы для ядра сообщений

    CREATE SCHEMA IF NOT EXISTS messages;
    COMMENT ON SCHEMA messages IS 'Ядро системы оповещений: хранение метеорологических событий, предупреждений и прогнозов (без привязки к выходным формам/документам).';


-- Типы данных #

    CREATE TYPE messages.readiness_stages AS ENUM (
        'draft',        -- сообщение формируется или дорабатывается
        'review',       -- сообщение передано на проверку
        'approved'      -- сообщение проверено и утверждено ответственным сотрудником
    );

    COMMENT ON TYPE messages.readiness_stages IS 'Состояние готовности содержимого.';


    CREATE TYPE messages.message_type AS ENUM (
        'forecast',     -- прогноз погоды
        'observation',  -- фактическое наблюдение
        'warning'       -- штормовое / экстренное предупреждение
    );

    COMMENT ON TYPE messages.message_type IS 'Категоризация метеорологических событий.';


-- Домены #


-- Функции #

    -- Фиксация ревизии из рабочего буфера пользователя @

        -- Переносит текущее содержимое рабочего буфера пользователя в архив ревизий.
        -- Если актуальная ревизия уже содержит такой же снимок по хэшу, новая ревизия не создаётся.
        -- Флаги is_starred, is_archived и is_deleted сохраняются из текущего состояния сообщения,
        -- если вызывающая сторона не передала их явно.

        CREATE OR REPLACE FUNCTION messages.function_commit_revision_from_buffer(
            p_entity_id             UUID,
            p_user_id               UUID,
            p_state_content_hash    BYTEA,
            p_state_details         JSONB       DEFAULT '{}'::jsonb,
            p_is_starred            BOOLEAN     DEFAULT NULL,
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

            v_is_starred        BOOLEAN;
            v_is_archived       BOOLEAN;
            v_is_deleted        BOOLEAN;
            v_state_details     JSONB;

        BEGIN
            -- Проверка корректности хэша начального состояния
            IF p_state_content_hash IS NULL OR length(p_state_content_hash) <> 32 THEN
                RAISE EXCEPTION 'Не передан корректный хэш начального состояния ревизии сообщения.';
            END IF;

            v_state_details := COALESCE(p_state_details, '{}'::jsonb);

            -- Извлечение личного буфера с блокировкой строки от параллельных изменений
            SELECT *
            INTO buffer_record
            FROM messages.revision_buffer
            WHERE entity_id = p_entity_id
                AND user_id = p_user_id
            FOR UPDATE;

            -- Проверка существования буфера
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Рабочий буфер для сообщения % пользователя % не найден.',
                    p_entity_id,
                    p_user_id;
            END IF;

            -- Чтение текущих флагов состояния сообщения.
            -- Новые ревизии должны сохранять флаги, если пользователь явно не передал другие значения.
            -- Блокировка строки предотвращает параллельное изменение состояния
            -- до завершения фиксации новой ревизии.
            SELECT
                is_starred,
                is_archived,
                is_deleted
            INTO current_state
            FROM messages.state_cache
            WHERE entity_id = p_entity_id
            FOR UPDATE;

            IF FOUND THEN
                v_is_starred  := COALESCE(p_is_starred, current_state.is_starred);
                v_is_archived := COALESCE(p_is_archived, current_state.is_archived);
                v_is_deleted  := COALESCE(p_is_deleted, current_state.is_deleted);
            ELSE
                v_is_starred  := COALESCE(p_is_starred, FALSE);
                v_is_archived := COALESCE(p_is_archived, FALSE);
                v_is_deleted  := COALESCE(p_is_deleted, FALSE);
            END IF;

            -- Проверка актуальной ревизии, чтобы не создавать повтор текущего снимка
            SELECT
                id,
                content_hash
            INTO latest_revision
            FROM messages.revisions
            WHERE entity_id = p_entity_id
            ORDER BY created_at DESC, id DESC
            LIMIT 1;

            IF FOUND AND latest_revision.content_hash = buffer_record.content_hash THEN
                -- Если содержимое не изменилось относительно актуальной ревизии,
                -- буфер удаляется, а вызывающая сторона получает существующую ревизию.
                DELETE FROM messages.revision_buffer
                WHERE id = buffer_record.id;

                RETURN latest_revision.id;
            END IF;

            -- Перенос данных из буфера в архив неизменяемых ревизий
            INSERT INTO messages.revisions (
                entity_id,
                parent_id,
                user_id,
                type,
                period,
                region,
                content_hash,
                text,
                note,
                details
            )
            VALUES (
                buffer_record.entity_id,
                buffer_record.parent_id,
                buffer_record.user_id,
                buffer_record.type,
                buffer_record.period,
                buffer_record.region,
                buffer_record.content_hash,
                buffer_record.text,
                buffer_record.note,
                buffer_record.details
            )
            RETURNING id INTO new_revision_id;

            -- Фиксация начального состояния готовности для новой ревизии.
            -- Приложение передаёт хэш состояния, который соответствует:
            --
            -- {
            --     "readiness_stage": "draft",
            --     "is_starred": <итоговое значение>,
            --     "is_archived": <итоговое значение>,
            --     "is_deleted": <итоговое значение>,
            --     "details": <p_state_details>
            -- }
            --
            -- Итоговые значения флагов могут быть явно заданы вызывающей стороной
            -- или унаследованы из текущего состояния сообщения.
            INSERT INTO messages.states (
                entity_id,
                revision_id,
                user_id,
                readiness_stage,
                is_starred,
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
                v_is_starred,
                v_is_archived,
                v_is_deleted,
                p_state_content_hash,
                v_state_details
            );

            -- Обязательное удаление рабочего буфера после успешной фиксации ревизии.
            -- Удаление выполняется по техническому первичному ключу буфера.
            DELETE FROM messages.revision_buffer
            WHERE id = buffer_record.id;

            RETURN new_revision_id;
        END;
        $$;

        COMMENT ON FUNCTION messages.function_commit_revision_from_buffer(UUID, UUID, BYTEA, JSONB, BOOLEAN, BOOLEAN, BOOLEAN) IS 'Переносит содержимое рабочего буфера пользователя в архив ревизий сообщения, не создаёт повтор текущего снимка по хэшу, создаёт начальное состояние новой ревизии, сохраняет или явно устанавливает флаги is_starred, is_archived и is_deleted, удаляет зафиксированный буфер и возвращает идентификатор ревизии.';


    -- Создание или обновление рабочего буфера пользователя @

        -- Безопасная точка входа для автосохранения черновика.
        -- Доменная пара (entity_id, user_id) остаётся уникальной, техническая запись получает суррогатный id.
        -- Функция возвращает технический первичный ключ буфера, удобный для Django, API и служебных операций.

        CREATE OR REPLACE FUNCTION messages.function_upsert_revision_buffer(
            p_entity_id       UUID,
            p_user_id         UUID,
            p_parent_id       UUID,
            p_type            messages.message_type,
            p_period          TSTZRANGE,
            p_region          TEXT,
            p_text            TEXT,
            p_note            VARCHAR(255),
            p_content_hash    BYTEA,
            p_details         JSONB
        )
        RETURNS UUID
        LANGUAGE plpgsql
        AS $$

        DECLARE
            buffer_id       UUID;

        BEGIN
            INSERT INTO messages.revision_buffer (
                entity_id,
                parent_id,
                user_id,
                type,
                period,
                region,
                text,
                note,
                content_hash,
                details
            )
            VALUES (
                p_entity_id,
                p_parent_id,
                p_user_id,
                p_type,
                p_period,
                p_region,
                p_text,
                p_note,
                p_content_hash,
                COALESCE(p_details, '{}'::jsonb)
            )
            ON CONFLICT (entity_id, user_id) DO UPDATE SET
                parent_id       = EXCLUDED.parent_id,
                type            = EXCLUDED.type,
                period          = EXCLUDED.period,
                region          = EXCLUDED.region,
                text            = EXCLUDED.text,
                note            = EXCLUDED.note,
                content_hash    = EXCLUDED.content_hash,
                details         = EXCLUDED.details
            RETURNING id INTO buffer_id;

            RETURN buffer_id;
        END;
        $$;

        COMMENT ON FUNCTION messages.function_upsert_revision_buffer(UUID, UUID, UUID, messages.message_type, TSTZRANGE, TEXT, TEXT, VARCHAR, BYTEA, JSONB) IS 'Создаёт или обновляет личный рабочий буфер пользователя и возвращает технический идентификатор записи буфера.';


    -- Получение компактного списка сообщений (Feed) для интерфейса приложения @

        -- Формирует компактное представление списка сообщений для конкретного пользователя.
        -- Приоритет отображения: личный буфер пользователя > последняя ревизия > кэш состояний.
        -- Поддерживает опциональную фильтрацию по типу, стадии и поиску в тексте.
        -- Предназначена для индексной страницы со списком сообщений.

        CREATE OR REPLACE FUNCTION messages.function_get_user_message_feed(
            p_user_id   UUID,
            p_msg_type  messages.message_type       DEFAULT NULL,
            p_state     messages.readiness_stages   DEFAULT NULL,
            p_search    TEXT                        DEFAULT NULL
        )
        RETURNS TABLE (
            entity_id               UUID,
            display_datetime        TIMESTAMPTZ,
            display_type            messages.message_type,
            display_state           messages.readiness_stages,
            display_region          TEXT,
            display_text            TEXT,
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
                COALESCE(revision_buffer.type, latest_revision.type)                                   AS display_type,

                state_cache.readiness_stage                                                             AS display_state,

                CASE
                    WHEN revision_buffer.entity_id IS NOT NULL THEN revision_buffer.region
                    ELSE latest_revision.region
                END                                                                                     AS display_region,

                COALESCE(revision_buffer.text, latest_revision.text, '')                               AS display_text,
                COALESCE(revision_buffer.user_id, latest_revision.user_id, entities.user_id)           AS display_author_id,

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

            FROM messages.entities AS entities

            -- Личный буфер текущего пользователя (гарантия изоляции буферов пользователей)
            LEFT JOIN messages.revision_buffer AS revision_buffer
                ON revision_buffer.entity_id = entities.id
                AND revision_buffer.user_id = p_user_id

            -- Последняя зафиксированная ревизия сообщения
            LEFT JOIN LATERAL (
                SELECT
                    revisions.id            AS revision_id,
                    revisions.type,
                    revisions.region,
                    revisions.text,
                    revisions.created_at,
                    revisions.user_id
                FROM messages.revisions AS revisions
                WHERE revisions.entity_id = entities.id
                ORDER BY revisions.created_at DESC, revisions.id DESC
                LIMIT 1
            ) AS latest_revision ON TRUE

            -- Актуальный кэш состояния сообщения
            LEFT JOIN messages.state_cache AS state_cache
                ON state_cache.entity_id = entities.id

            -- Данные автора актуального содержимого
            LEFT JOIN identity.users AS author_users
                ON author_users.id = COALESCE(
                    revision_buffer.user_id,
                    latest_revision.user_id,
                    entities.user_id
                )

            WHERE
                -- Исключение удалённых сообщений
                (state_cache.is_deleted = FALSE OR state_cache.is_deleted IS NULL)

                -- Опциональная фильтрация по типу сообщения
                AND (p_msg_type IS NULL OR COALESCE(revision_buffer.type, latest_revision.type) = p_msg_type)

                -- Опциональная фильтрация по стадии готовности
                AND (p_state IS NULL OR state_cache.readiness_stage = p_state)

                -- Изолированный поиск по актуальному отображаемому тексту текущего пользователя
                AND (
                    p_search IS NULL
                    OR (
                        revision_buffer.entity_id IS NOT NULL
                        AND revision_buffer.text ILIKE v_search_pattern
                    )
                    OR (
                        revision_buffer.entity_id IS NULL
                        AND latest_revision.text ILIKE v_search_pattern
                    )
                )

            ORDER BY display_datetime DESC;
        END;
        $$;

        COMMENT ON FUNCTION messages.function_get_user_message_feed(UUID, messages.message_type, messages.readiness_stages, TEXT) IS 'Возвращает компактный список сообщений для конкретного пользователя с приоритетом его личного буфера и строгой изоляцией от буферов других пользователей.';


    -- Получение полной обогащённой карточки сообщения (Detail)

        CREATE OR REPLACE FUNCTION messages.function_get_user_message_detail(
            p_entity_id UUID,
            p_user_id   UUID
        )
        RETURNS TABLE (
            entity_id               UUID,
            display_datetime        TIMESTAMPTZ,
            display_type            messages.message_type,
            display_state           messages.readiness_stages,
            display_text            TEXT,
            display_period          TSTZRANGE,
            display_region          TEXT,
            display_note            VARCHAR(255),
            display_details         JSONB,
            display_content_hash    BYTEA,
            display_author_id       UUID,
            display_author_name     TEXT,
            has_buffer              BOOLEAN,
            revision_id             UUID,
            created_at              TIMESTAMPTZ
        )
        LANGUAGE plpgsql
        AS $$

        BEGIN
            RETURN QUERY
            SELECT
                entities.id                                                                             AS entity_id,

                COALESCE(revision_buffer.updated_at, latest_revision.created_at, entities.created_at)   AS display_datetime,
                COALESCE(revision_buffer.type, latest_revision.type)                                    AS display_type,

                state_cache.readiness_stage                                                             AS display_state,

                COALESCE(revision_buffer.text, latest_revision.text, '')                                AS display_text,
                COALESCE(revision_buffer.period, latest_revision.period)                                AS display_period,

                CASE
                    WHEN revision_buffer.entity_id IS NOT NULL THEN revision_buffer.region
                    ELSE latest_revision.region
                END                                                                                     AS display_region,

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

            FROM messages.entities AS entities

            -- Присоединение личного буфера текущего пользователя
            LEFT JOIN messages.revision_buffer AS revision_buffer
                ON revision_buffer.entity_id = entities.id
                AND revision_buffer.user_id = p_user_id

            -- Присоединение последней опубликованной ревизии
            LEFT JOIN LATERAL (
                SELECT
                    revisions.id            AS revision_id,
                    revisions.entity_id,
                    revisions.type,
                    revisions.period,
                    revisions.region,
                    revisions.content_hash,
                    revisions.text,
                    revisions.note,
                    revisions.details,
                    revisions.created_at,
                    revisions.user_id
                FROM messages.revisions AS revisions
                WHERE revisions.entity_id = entities.id
                ORDER BY revisions.created_at DESC, revisions.id DESC
                LIMIT 1
            ) AS latest_revision ON TRUE

            -- Присоединение кэша состояния
            LEFT JOIN messages.state_cache AS state_cache
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

        COMMENT ON FUNCTION messages.function_get_user_message_detail(UUID, UUID) IS 'Возвращает детальную карточку сообщения для пользователя с полным набором метаданных, приоритизируя личный буфер черновика.';


-- Процедуры #


-- Таблицы #

    -- Реестр сообщений @

        -- Хранит идентификаторы сообщений и связывает их версии и состояния

        -- Таблица #

            CREATE TABLE messages.entities (

                -- Ключи и связи #

                    id                      UUID                        PRIMARY KEY                                 DEFAULT uuid_generate_v7(),

                    user_id                 UUID                        REFERENCES identity.users(id)
                                                                        NOT NULL,


                -- Временные метки #

                    created_at              TIMESTAMPTZ                 NOT NULL                                    DEFAULT CURRENT_TIMESTAMP

            );


        -- Комментарии #

            COMMENT ON TABLE messages.entities IS 'Реестр сообщений. Хранит идентификаторы сообщений, для которых ведется история версий и состояний.';

            COMMENT ON COLUMN messages.entities.id IS 'Уникальный идентификатор сообщения.';
            COMMENT ON COLUMN messages.entities.user_id IS 'Идентификатор пользователя, создавшего сообщение.';
            COMMENT ON COLUMN messages.entities.created_at IS 'Дата и время создания сообщения.';


        -- Индексы #

            CREATE INDEX index_messages_entities_user_id
                ON messages.entities(user_id);

            COMMENT ON INDEX index_messages_entities_user_id IS 'Ускоряет фильтрацию сообщений по их автору.';


            CREATE INDEX index_messages_entities_created_at
                ON messages.entities(created_at DESC);

            COMMENT ON INDEX index_messages_entities_created_at IS 'Оптимизирует сортировку списков по времени создания.';


        -- Обработчики событий #

            CREATE TRIGGER trigger_messages_entities_state_initialization
                AFTER INSERT ON messages.entities
                FOR EACH ROW
                EXECUTE FUNCTION common.function_initialize_state_log(
                    'messages.states',
                    'entity_id',
                    '{"readiness_stage": "draft", "is_starred": false, "is_archived": false, "is_deleted": false, "content_hash": "\\x3cb4a196aff1cb6bd02952e048432d857bf9bbd597c26e3a7aec0537baaae54e"}'
                );

            COMMENT ON TRIGGER trigger_messages_entities_state_initialization ON messages.entities IS 'Создает начальную запись состояния сообщения в журнале.';


            CREATE TRIGGER trigger_messages_entities_immutability
                BEFORE UPDATE OR DELETE ON messages.entities
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_immutability();

            COMMENT ON TRIGGER trigger_messages_entities_immutability ON messages.entities IS 'Запрещает изменять или удалять созданное сообщение.';


    -- Буфер правок сообщений @

        -- Хранит текущие несохраненные изменения
        -- Каждый пользователь располагает собственным буфером для каждого сообщения
        -- Технический первичный ключ используется для совместимости с Django ORM,
        -- Django Admin и инструментами, работающими с одиночным первичным ключом.
        -- Доменная уникальность при этом сохраняется парой (entity_id, user_id).

        -- Таблица #

            CREATE TABLE messages.revision_buffer (

                -- Ключи и связи #

                    id                      UUID                        NOT NULL                                    DEFAULT uuid_generate_v7(),

                    entity_id               UUID                        NOT NULL
                                                                        REFERENCES messages.entities(id)
                                                                        ON DELETE CASCADE,

                    parent_id               UUID                        REFERENCES messages.entities(id)
                                                                        ON DELETE SET NULL,

                    user_id                 UUID                        NOT NULL
                                                                        REFERENCES identity.users(id),


                -- Основное содержимое #

                    type                    messages.message_type       NOT NULL,
                    period                  TSTZRANGE,
                    region                  TEXT,
                    text                    TEXT                        NOT NULL,
                    note                    VARCHAR(255),
                    content_hash            BYTEA                       NOT NULL,


                -- Расширенные метаданные #

                    details                 JSONB                       NOT NULL                                    DEFAULT '{}'::jsonb,


                -- Временные метки #

                    updated_at              TIMESTAMPTZ                 NOT NULL                                    DEFAULT CURRENT_TIMESTAMP,


                -- Проверки целостности #

                    -- Исторический доменный первичный ключ.
                    -- Оставлен в комментарии для фиксации проектного решения:
                    -- прежняя версия рассматривала пару (entity_id, user_id) как единственный ключ буфера.
                    -- Теперь этот смысл сохранён в уникальном ограничении, а первичный ключ стал техническим.
                    -- PRIMARY KEY (entity_id, user_id),

                    CONSTRAINT messages_revision_buffer_pkey PRIMARY KEY (id),
                    CONSTRAINT messages_revision_buffer_entity_id_user_id_unique UNIQUE (entity_id, user_id),

                    CONSTRAINT check_revision_buffer_content_hash_length CHECK (length(content_hash) = 32),
                    CONSTRAINT check_revision_buffer_parent_not_self CHECK (parent_id IS DISTINCT FROM entity_id)

            );


        -- Комментарии #

            COMMENT ON TABLE messages.revision_buffer IS 'Буфер несохраненных изменений сообщений. Хранит текущее рабочее состояние для каждого пользователя и сообщения.';

            COMMENT ON COLUMN messages.revision_buffer.id IS 'Технический суррогатный идентификатор рабочего буфера. Добавлен для совместимости с Django ORM и другими инструментами, ожидающими один первичный ключ.';
            COMMENT ON COLUMN messages.revision_buffer.entity_id IS 'Идентификатор сообщения.';
            COMMENT ON COLUMN messages.revision_buffer.parent_id IS 'Идентификатор сообщения, к которому относится корректировка или отмена.';
            COMMENT ON COLUMN messages.revision_buffer.user_id IS 'Идентификатор пользователя, редактирующего сообщение.';
            COMMENT ON COLUMN messages.revision_buffer.type IS 'Тип метеорологического события.';
            COMMENT ON COLUMN messages.revision_buffer.period IS 'Период действия метеорологического явления.';
            COMMENT ON COLUMN messages.revision_buffer.region IS 'Ориентировочный район/регион погодного явления. Свободное описание до введения отдельного географического справочника.';
            COMMENT ON COLUMN messages.revision_buffer.text IS 'Редактируемый текст сообщения.';
            COMMENT ON COLUMN messages.revision_buffer.note IS 'Рабочий комментарий к сообщению.';
            COMMENT ON COLUMN messages.revision_buffer.content_hash IS 'Контент-хэш снимка сообщения (BLAKE3). Вычисляется от канонической полезной нагрузки: type, period, region, text, note/details, если они значимы. Не включает технические поля: id, entity_id, user_id, created_at, updated_at, сам хэш.';
            COMMENT ON COLUMN messages.revision_buffer.details IS 'Дополнительные параметры сообщения в формате JSONB.';
            COMMENT ON COLUMN messages.revision_buffer.updated_at IS 'Дата и время последнего изменения буфера.';

            COMMENT ON CONSTRAINT messages_revision_buffer_pkey ON messages.revision_buffer IS 'Технический первичный ключ рабочего буфера. Нужен для однозначной идентификации записи в Django ORM, API и служебных операциях.';
            COMMENT ON CONSTRAINT messages_revision_buffer_entity_id_user_id_unique ON messages.revision_buffer IS 'Доменная уникальность рабочего буфера: одно сообщение может иметь только один рабочий буфер для одного пользователя.';
            COMMENT ON CONSTRAINT check_revision_buffer_content_hash_length ON messages.revision_buffer IS 'Проверяет, что контент-хэш содержимого сообщения (BLAKE3) имеет длину 32 байта.';
            COMMENT ON CONSTRAINT check_revision_buffer_parent_not_self ON messages.revision_buffer IS 'Запрещает самопривязку, когда сообщение ссылается само на себя.';


        -- Индексы #

            CREATE INDEX index_messages_revision_buffer_parent
                ON messages.revision_buffer(parent_id);

            COMMENT ON INDEX index_messages_revision_buffer_parent IS 'Ускоряет поиск связанных сообщений (исправлений, отмен).';


            CREATE INDEX index_messages_revision_buffer_user_id
                ON messages.revision_buffer(user_id);

            COMMENT ON INDEX index_messages_revision_buffer_user_id IS 'Ускоряет поиск активных черновиков пользователя.';


            CREATE INDEX index_messages_revision_buffer_text_trigram
                ON messages.revision_buffer
                USING gin(text gin_trgm_ops);

            COMMENT ON INDEX index_messages_revision_buffer_text_trigram IS 'Ускоряет поиск по тексту черновиков.';


            CREATE INDEX index_messages_revision_buffer_details
                ON messages.revision_buffer
                USING gin(details jsonb_path_ops);

            COMMENT ON INDEX index_messages_revision_buffer_details IS 'Ускоряет поиск по параметрам черновиков в JSONB.';


            CREATE INDEX index_messages_revision_buffer_updated_at
                ON messages.revision_buffer(updated_at DESC);

            COMMENT ON INDEX index_messages_revision_buffer_updated_at IS 'Оптимизирует сортировку черновиков по времени изменения.';


        -- Обработчики событий #

            CREATE TRIGGER trigger_messages_revision_buffer_identity
                BEFORE UPDATE OF id, entity_id, user_id ON messages.revision_buffer
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_revision_buffer_identity();

            COMMENT ON TRIGGER trigger_messages_revision_buffer_identity ON messages.revision_buffer IS 'Запрещает изменять суррогатный и доменный ключи рабочего буфера.';


            CREATE TRIGGER trigger_messages_revision_buffer_updated_at
                BEFORE UPDATE ON messages.revision_buffer
                FOR EACH ROW
                EXECUTE FUNCTION common.function_refresh_updated_at_column();

            COMMENT ON TRIGGER trigger_messages_revision_buffer_updated_at ON messages.revision_buffer IS 'Обновляет время последнего изменения буфера.';


    -- Архив ревизий сообщений @

        -- Хранит историю зафиксированных версий текста и параметров сообщений

        -- Таблица #

            CREATE TABLE messages.revisions (

                -- Ключи и связи #

                    id                      UUID                        PRIMARY KEY                                 DEFAULT uuid_generate_v7(),

                    entity_id               UUID                        NOT NULL
                                                                        REFERENCES messages.entities(id)
                                                                        ON DELETE CASCADE,

                    parent_id               UUID                        REFERENCES messages.entities(id)
                                                                        ON DELETE SET NULL,

                    user_id                 UUID                        NOT NULL
                                                                        REFERENCES identity.users(id),


                -- Основное содержимое #

                    type                    messages.message_type       NOT NULL,
                    period                  TSTZRANGE,
                    region                  TEXT,
                    text                    TEXT                        NOT NULL,
                    note                    VARCHAR(255),
                    content_hash            BYTEA                       NOT NULL,


                -- Расширенные метаданные #

                    details                 JSONB                       NOT NULL                                    DEFAULT '{}'::jsonb,


                -- Временные метки #

                    created_at              TIMESTAMPTZ                 NOT NULL                                    DEFAULT CURRENT_TIMESTAMP,


                -- Проверки целостности #

                    CONSTRAINT check_revisions_content_hash_length CHECK (length(content_hash) = 32),
                    CONSTRAINT check_revisions_parent_not_self CHECK (parent_id IS DISTINCT FROM entity_id)

            );


        -- Комментарии #

            COMMENT ON TABLE messages.revisions IS 'История зафиксированных версий текста и параметров сообщений.';

            COMMENT ON COLUMN messages.revisions.id IS 'Уникальный идентификатор ревизии.';
            COMMENT ON COLUMN messages.revisions.entity_id IS 'Идентификатор сообщения.';
            COMMENT ON COLUMN messages.revisions.parent_id IS 'Идентификатор сообщения, к которому относится корректировка или отмена.';
            COMMENT ON COLUMN messages.revisions.user_id IS 'Идентификатор пользователя, создавшего ревизию.';
            COMMENT ON COLUMN messages.revisions.type IS 'Тип метеорологического события на момент создания ревизии.';
            COMMENT ON COLUMN messages.revisions.period IS 'Период действия метеорологического явления.';
            COMMENT ON COLUMN messages.revisions.region IS 'Ориентировочный район/регион погодного явления на момент создания ревизии.';
            COMMENT ON COLUMN messages.revisions.text IS 'Текст сообщения в данной ревизии.';
            COMMENT ON COLUMN messages.revisions.note IS 'Комментарий к ревизии.';
            COMMENT ON COLUMN messages.revisions.content_hash IS 'Контент-хэш снимка сообщения (BLAKE3). Вычисляется от канонической полезной нагрузки: type, period, region, text, note/details, если они значимы. Не включает технические поля: id, entity_id, user_id, created_at, сам хэш.';
            COMMENT ON COLUMN messages.revisions.details IS 'Дополнительные параметры сообщения в формате JSONB.';
            COMMENT ON COLUMN messages.revisions.created_at IS 'Дата и время создания ревизии.';

            COMMENT ON CONSTRAINT check_revisions_content_hash_length ON messages.revisions IS 'Проверяет, что контент-хэш содержимого ревизии (BLAKE3) имеет длину 32 байта.';
            COMMENT ON CONSTRAINT check_revisions_parent_not_self ON messages.revisions IS 'Запрещает самопривязку, когда сообщение ссылается само на себя.';


        -- Индексы #

            CREATE INDEX index_messages_revisions_message_time
                ON messages.revisions(entity_id, created_at DESC, id DESC);

            COMMENT ON INDEX index_messages_revisions_message_time IS 'Оптимизирует получение последней ревизии сообщения.';


            CREATE INDEX index_messages_revisions_parent
                ON messages.revisions(parent_id);

            COMMENT ON INDEX index_messages_revisions_parent IS 'Ускоряет поиск связанных сообщений (исправлений, отмен).';


            CREATE INDEX index_messages_revisions_period_gist
                ON messages.revisions
                USING gist(period);

            COMMENT ON INDEX index_messages_revisions_period_gist IS 'Ускоряет поиск событий по времени действия.';


            CREATE INDEX index_messages_revisions_text_trigram
                ON messages.revisions
                USING gin(text gin_trgm_ops);

            COMMENT ON INDEX index_messages_revisions_text_trigram IS 'Ускоряет поиск по тексту ревизий.';


            CREATE INDEX index_messages_revisions_type
                ON messages.revisions(type);

            COMMENT ON INDEX index_messages_revisions_type IS 'Ускоряет фильтрацию ревизий по типу метеорологического события.';


            CREATE INDEX index_messages_revisions_user_id
                ON messages.revisions(user_id);

            COMMENT ON INDEX index_messages_revisions_user_id IS 'Ускоряет выборку ревизий по автору.';


        -- Обработчики событий #

            CREATE TRIGGER trigger_messages_revisions_immutability
                BEFORE UPDATE OR DELETE ON messages.revisions
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_immutability();

            COMMENT ON TRIGGER trigger_messages_revisions_immutability ON messages.revisions IS 'Запрещает изменять или удалять сохраненные ревизии.';


    -- Текущие состояния сообщений @

        -- Хранит актуальные состояния сообщений для быстрого поиска и выборки
        -- Заполняется автоматически на основе журнала состояний

        -- Таблица #

            CREATE TABLE messages.state_cache (

                -- Ключи и связи #

                    entity_id               UUID                        PRIMARY KEY
                                                                        REFERENCES messages.entities(id)
                                                                        ON DELETE CASCADE,

                    revision_id             UUID                        REFERENCES messages.revisions(id)
                                                                        ON DELETE RESTRICT,

                    user_id                 UUID                        REFERENCES identity.users(id)
                                                                        NOT NULL,


                -- Основное содержимое #

                    readiness_stage         messages.readiness_stages   NOT NULL                                    DEFAULT 'draft'::messages.readiness_stages,
                    is_starred              BOOLEAN                     NOT NULL                                    DEFAULT FALSE,
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

            COMMENT ON TABLE messages.state_cache IS 'Текущие состояния сообщений. Обновляется автоматически на основе журнала messages.states.';

            COMMENT ON COLUMN messages.state_cache.entity_id IS 'Идентификатор сообщения.';
            COMMENT ON COLUMN messages.state_cache.revision_id IS 'Идентификатор ревизии, к которой относится текущее состояние готовности (если применимо).';
            COMMENT ON COLUMN messages.state_cache.user_id IS 'Идентификатор пользователя, последним изменившего состояние.';
            COMMENT ON COLUMN messages.state_cache.readiness_stage IS 'Стадия готовности сообщения.';
            COMMENT ON COLUMN messages.state_cache.is_starred IS 'Признак отметки сообщения как важного.';
            COMMENT ON COLUMN messages.state_cache.is_archived IS 'Признак нахождения сообщения в архиве.';
            COMMENT ON COLUMN messages.state_cache.is_deleted IS 'Признак логического удаления сообщения.';
            COMMENT ON COLUMN messages.state_cache.content_hash IS 'Контент-хэш снимка состояния сообщения (BLAKE3). Вычисляется от полезной нагрузки состояния: readiness_stage, is_starred, is_archived, is_deleted, details. Не включает контекст: id, entity_id, revision_id, user_id, updated_at.';
            COMMENT ON COLUMN messages.state_cache.details IS 'Дополнительные сведения о текущем состоянии.';
            COMMENT ON COLUMN messages.state_cache.updated_at IS 'Дата и время последнего изменения состояния.';

            COMMENT ON CONSTRAINT check_state_cache_content_hash_length ON messages.state_cache IS 'Проверяет, что контент-хэш снимка состояния (BLAKE3) имеет длину 32 байта.';


        -- Индексы #

            CREATE INDEX index_messages_state_cache_entity_stage_active
                ON messages.state_cache(entity_id, readiness_stage)
                WHERE (is_deleted = FALSE);

            COMMENT ON INDEX index_messages_state_cache_entity_stage_active IS 'Ускоряет выборку неудаленных сообщений по стадии готовности.';


            CREATE INDEX index_messages_state_cache_stage_not_archived
                ON messages.state_cache(readiness_stage)
                WHERE (is_archived = FALSE);

            COMMENT ON INDEX index_messages_state_cache_stage_not_archived IS 'Ускоряет выборку неархивированных сообщений по стадии готовности.';


            CREATE INDEX index_messages_state_cache_draft
                ON messages.state_cache(readiness_stage)
                WHERE (readiness_stage = 'draft'
                    AND is_deleted = FALSE);

            COMMENT ON INDEX index_messages_state_cache_draft IS 'Оптимизирует выборку неудаленных черновиков.';


            CREATE INDEX index_messages_state_cache_starred
                ON messages.state_cache(entity_id)
                WHERE (is_starred = TRUE
                    AND is_deleted = FALSE);

            COMMENT ON INDEX index_messages_state_cache_starred IS 'Ускоряет выборку неудаленных важных сообщений.';


            CREATE INDEX index_messages_state_cache_details
                ON messages.state_cache
                USING gin(details jsonb_path_ops);

            COMMENT ON INDEX index_messages_state_cache_details IS 'Ускоряет поиск по структурированным данным в JSONB.';


            CREATE INDEX index_messages_state_cache_updated_at
                ON messages.state_cache(updated_at DESC);

            COMMENT ON INDEX index_messages_state_cache_updated_at IS 'Оптимизирует выборку сообщений по времени изменения состояния.';


        -- Обработчики событий #

            CREATE TRIGGER trigger_messages_state_cache_updated_at
                BEFORE UPDATE ON messages.state_cache
                FOR EACH ROW
                EXECUTE FUNCTION common.function_refresh_updated_at_column();

            COMMENT ON TRIGGER trigger_messages_state_cache_updated_at ON messages.state_cache IS 'Обновляет время последнего изменения состояния.';


            CREATE TRIGGER trigger_messages_state_cache_revision_entity_consistency
                BEFORE INSERT OR UPDATE OF entity_id, revision_id ON messages.state_cache
                FOR EACH ROW
                EXECUTE FUNCTION common.function_validate_state_revision_entity('messages.revisions');

            COMMENT ON TRIGGER trigger_messages_state_cache_revision_entity_consistency ON messages.state_cache IS 'Защищает от привязки кэша состояния к ревизии другого сообщения.';


    -- Журнал состояний сообщений @

        -- Хранит историю изменений состояний сообщений
        -- Каждая запись содержит полное состояние сообщения на момент изменения

        -- Таблица #

            CREATE TABLE messages.states (

                -- Ключи и связи #

                    id                      UUID                        PRIMARY KEY                                 DEFAULT uuid_generate_v7(),

                    entity_id               UUID                        NOT NULL
                                                                        REFERENCES messages.entities(id)
                                                                        ON DELETE CASCADE,

                    revision_id             UUID                        REFERENCES messages.revisions(id)
                                                                        ON DELETE RESTRICT,

                    user_id                 UUID                        NOT NULL
                                                                        REFERENCES identity.users(id),


                -- Основное содержимое #

                    readiness_stage         messages.readiness_stages   NOT NULL                                    DEFAULT 'draft'::messages.readiness_stages,
                    is_starred              BOOLEAN                     NOT NULL                                    DEFAULT FALSE,
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

            COMMENT ON TABLE messages.states IS 'История изменений состояний сообщений. Каждая запись содержит полное состояние сообщения на момент изменения.';

            COMMENT ON COLUMN messages.states.id IS 'Уникальный идентификатор записи истории.';
            COMMENT ON COLUMN messages.states.entity_id IS 'Идентификатор сообщения.';
            COMMENT ON COLUMN messages.states.revision_id IS 'Идентификатор ревизии, к которой относится изменение состояния готовности (если применимо).';
            COMMENT ON COLUMN messages.states.user_id IS 'Идентификатор пользователя, изменившего состояние.';
            COMMENT ON COLUMN messages.states.readiness_stage IS 'Стадия готовности сообщения на момент записи.';
            COMMENT ON COLUMN messages.states.is_starred IS 'Признак отметки сообщения как важного на момент записи.';
            COMMENT ON COLUMN messages.states.is_archived IS 'Признак нахождения сообщения в архиве на момент записи.';
            COMMENT ON COLUMN messages.states.is_deleted IS 'Признак логического удаления сообщения на момент записи.';
            COMMENT ON COLUMN messages.states.content_hash IS 'Контент-хэш снимка состояния сообщения (BLAKE3). Вычисляется от полезной нагрузки состояния: readiness_stage, is_starred, is_archived, is_deleted, details. Не включает контекст: id, entity_id, revision_id, user_id, created_at.';
            COMMENT ON COLUMN messages.states.details IS 'Дополнительные сведения о событии изменения состояния.';
            COMMENT ON COLUMN messages.states.created_at IS 'Дата и время записи состояния.';

            COMMENT ON CONSTRAINT check_states_content_hash_length ON messages.states IS 'Проверяет, что контент-хэш снимка состояния (BLAKE3) имеет длину 32 байта.';


        -- Индексы #

            CREATE INDEX index_messages_states_chronology
                ON messages.states(entity_id, created_at ASC);

            COMMENT ON INDEX index_messages_states_chronology IS 'Оптимизирует построение истории состояний сообщения.';


            CREATE INDEX index_messages_states_created_at
                ON messages.states(created_at DESC);

            COMMENT ON INDEX index_messages_states_created_at IS 'Оптимизирует построение общего журнала изменений состояний.';


            CREATE INDEX index_messages_states_revision_id
                ON messages.states(revision_id);

            COMMENT ON INDEX index_messages_states_revision_id IS 'Ускоряет поиск состояний, связанных с конкретной ревизией сообщения.';


        -- Обработчики событий #

            CREATE TRIGGER trigger_messages_states_revision_entity_consistency
                BEFORE INSERT OR UPDATE OF entity_id, revision_id ON messages.states
                FOR EACH ROW
                EXECUTE FUNCTION common.function_validate_state_revision_entity('messages.revisions');

            COMMENT ON TRIGGER trigger_messages_states_revision_entity_consistency ON messages.states IS 'Защищает от привязки состояния к ревизии другого сообщения.';


            CREATE TRIGGER trigger_messages_states_cache_sync
                AFTER INSERT ON messages.states
                FOR EACH ROW
                EXECUTE FUNCTION common.function_upsert_current_state('messages.state_cache', 'entity_id');

            COMMENT ON TRIGGER trigger_messages_states_cache_sync ON messages.states IS 'Обновляет текущие состояния сообщений на основе журнала.';


            CREATE TRIGGER trigger_messages_states_immutability
                BEFORE UPDATE OR DELETE ON messages.states
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_immutability();

            COMMENT ON TRIGGER trigger_messages_states_immutability ON messages.states IS 'Запрещает изменять или удалять записи истории состояний.';


-- Представления #


-- Материализованные представления #


-- Права доступа #
