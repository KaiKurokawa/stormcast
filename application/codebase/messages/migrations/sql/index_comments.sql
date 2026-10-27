COMMENT ON INDEX messages.index_messages_entities_user_id IS 'Ускоряет фильтрацию сообщений по их автору.';
COMMENT ON INDEX messages.index_messages_entities_created_at IS 'Оптимизирует сортировку списков по времени создания.';

COMMENT ON CONSTRAINT messages_revision_buffer_entity_id_user_id_unique
    ON messages.revision_buffer
    IS 'Доменная уникальность рабочего буфера: одно сообщение может иметь только один рабочий буфер для одного пользователя.';
COMMENT ON CONSTRAINT check_revision_buffer_content_hash_length
    ON messages.revision_buffer
    IS 'Проверяет, что контент-хэш содержимого сообщения (BLAKE3) имеет длину 32 байта.';
COMMENT ON CONSTRAINT check_revision_buffer_parent_not_self
    ON messages.revision_buffer
    IS 'Запрещает самопривязку, когда сообщение ссылается само на себя.';
COMMENT ON INDEX messages.index_messages_revision_buffer_parent IS 'Ускоряет поиск связанных сообщений (исправлений, отмен).';
COMMENT ON CONSTRAINT messages_revision_buffer_pkey
    ON messages.revision_buffer
    IS 'Технический первичный ключ рабочего буфера. Нужен для однозначной идентификации записи в Django ORM, API и служебных операциях.';
COMMENT ON INDEX messages.index_messages_revision_buffer_user_id IS 'Ускоряет поиск активных черновиков пользователя.';
COMMENT ON INDEX messages.index_messages_revision_buffer_text_trigram IS 'Ускоряет поиск по тексту черновиков.';
COMMENT ON INDEX messages.index_messages_revision_buffer_details IS 'Ускоряет поиск по параметрам черновиков в JSONB.';
COMMENT ON INDEX messages.index_messages_revision_buffer_updated_at IS 'Оптимизирует сортировку черновиков по времени изменения.';

COMMENT ON CONSTRAINT check_revisions_content_hash_length
    ON messages.revisions
    IS 'Проверяет, что контент-хэш содержимого ревизии (BLAKE3) имеет длину 32 байта.';
COMMENT ON CONSTRAINT check_revisions_parent_not_self
    ON messages.revisions
    IS 'Запрещает самопривязку, когда сообщение ссылается само на себя.';
COMMENT ON INDEX messages.index_messages_revisions_message_time IS 'Оптимизирует получение последней ревизии сообщения.';
COMMENT ON INDEX messages.index_messages_revisions_parent IS 'Ускоряет поиск связанных сообщений (исправлений, отмен).';
COMMENT ON INDEX messages.index_messages_revisions_period_gist IS 'Ускоряет поиск событий по времени действия.';
COMMENT ON INDEX messages.index_messages_revisions_text_trigram IS 'Ускоряет поиск по тексту ревизий.';
COMMENT ON INDEX messages.index_messages_revisions_type IS 'Ускоряет фильтрацию ревизий по типу метеорологического события.';
COMMENT ON INDEX messages.index_messages_revisions_user_id IS 'Ускоряет выборку ревизий по автору.';

COMMENT ON CONSTRAINT check_state_cache_content_hash_length
    ON messages.state_cache
    IS 'Проверяет, что контент-хэш снимка состояния (BLAKE3) имеет длину 32 байта.';
COMMENT ON INDEX messages.index_messages_state_cache_entity_stage_active IS 'Ускоряет выборку неудаленных сообщений по стадии готовности.';
COMMENT ON INDEX messages.index_messages_state_cache_stage_not_archived IS 'Ускоряет выборку неархивированных сообщений по стадии готовности.';
COMMENT ON INDEX messages.index_messages_state_cache_draft IS 'Оптимизирует выборку неудаленных черновиков.';
COMMENT ON INDEX messages.index_messages_state_cache_starred IS 'Ускоряет выборку неудаленных важных сообщений.';
COMMENT ON INDEX messages.index_messages_state_cache_details IS 'Ускоряет поиск по структурированным данным в JSONB.';
COMMENT ON INDEX messages.index_messages_state_cache_updated_at IS 'Оптимизирует выборку сообщений по времени изменения состояния.';

COMMENT ON CONSTRAINT check_states_content_hash_length
    ON messages.states
    IS 'Проверяет, что контент-хэш снимка состояния (BLAKE3) имеет длину 32 байта.';
COMMENT ON INDEX messages.index_messages_states_chronology IS 'Оптимизирует построение истории состояний сообщения.';
COMMENT ON INDEX messages.index_messages_states_created_at IS 'Оптимизирует построение общего журнала изменений состояний.';
COMMENT ON INDEX messages.index_messages_states_revision_id IS 'Ускоряет поиск состояний, связанных с конкретной ревизией сообщения.';
