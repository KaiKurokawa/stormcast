DROP TRIGGER IF EXISTS trigger_messages_entities_state_initialization ON messages.entities;
CREATE TRIGGER trigger_messages_entities_state_initialization
    AFTER INSERT ON messages.entities
    FOR EACH ROW
    EXECUTE FUNCTION common.function_initialize_state_log(
        'messages.states',
        'entity_id',
        '{"readiness_stage": "draft", "is_starred": false, "is_archived": false, "is_deleted": false, "content_hash": "\\x3cb4a196aff1cb6bd02952e048432d857bf9bbd597c26e3a7aec0537baaae54e"}'
    );
COMMENT ON TRIGGER trigger_messages_entities_state_initialization ON messages.entities
    IS 'Создает начальную запись состояния сообщения в журнале.';

DROP TRIGGER IF EXISTS trigger_messages_entities_immutability ON messages.entities;
CREATE TRIGGER trigger_messages_entities_immutability
    BEFORE UPDATE OR DELETE ON messages.entities
    FOR EACH ROW
    EXECUTE FUNCTION common.function_protect_immutability();
COMMENT ON TRIGGER trigger_messages_entities_immutability ON messages.entities
    IS 'Запрещает изменять или удалять созданное сообщение.';

DROP TRIGGER IF EXISTS trigger_messages_revision_buffer_identity ON messages.revision_buffer;
CREATE TRIGGER trigger_messages_revision_buffer_identity
    BEFORE UPDATE OF id, entity_id, user_id ON messages.revision_buffer
    FOR EACH ROW
    EXECUTE FUNCTION common.function_protect_revision_buffer_identity();
COMMENT ON TRIGGER trigger_messages_revision_buffer_identity ON messages.revision_buffer
    IS 'Запрещает изменять суррогатный и доменный ключи рабочего буфера.';

DROP TRIGGER IF EXISTS trigger_messages_revision_buffer_updated_at ON messages.revision_buffer;
CREATE TRIGGER trigger_messages_revision_buffer_updated_at
    BEFORE UPDATE ON messages.revision_buffer
    FOR EACH ROW
    EXECUTE FUNCTION common.function_refresh_updated_at_column();
COMMENT ON TRIGGER trigger_messages_revision_buffer_updated_at ON messages.revision_buffer
    IS 'Обновляет время последнего изменения буфера.';

DROP TRIGGER IF EXISTS trigger_messages_revisions_immutability ON messages.revisions;
CREATE TRIGGER trigger_messages_revisions_immutability
    BEFORE UPDATE OR DELETE ON messages.revisions
    FOR EACH ROW
    EXECUTE FUNCTION common.function_protect_immutability();
COMMENT ON TRIGGER trigger_messages_revisions_immutability ON messages.revisions
    IS 'Запрещает изменять или удалять сохраненные ревизии.';

DROP TRIGGER IF EXISTS trigger_messages_state_cache_updated_at ON messages.state_cache;
CREATE TRIGGER trigger_messages_state_cache_updated_at
    BEFORE UPDATE ON messages.state_cache
    FOR EACH ROW
    EXECUTE FUNCTION common.function_refresh_updated_at_column();
COMMENT ON TRIGGER trigger_messages_state_cache_updated_at ON messages.state_cache
    IS 'Обновляет время последнего изменения состояния.';

DROP TRIGGER IF EXISTS trigger_messages_state_cache_revision_entity_consistency ON messages.state_cache;
CREATE TRIGGER trigger_messages_state_cache_revision_entity_consistency
    BEFORE INSERT OR UPDATE OF entity_id, revision_id ON messages.state_cache
    FOR EACH ROW
    EXECUTE FUNCTION common.function_validate_state_revision_entity('messages.revisions');
COMMENT ON TRIGGER trigger_messages_state_cache_revision_entity_consistency ON messages.state_cache
    IS 'Защищает от привязки кэша состояния к ревизии другого сообщения.';

DROP TRIGGER IF EXISTS trigger_messages_states_revision_entity_consistency ON messages.states;
CREATE TRIGGER trigger_messages_states_revision_entity_consistency
    BEFORE INSERT OR UPDATE OF entity_id, revision_id ON messages.states
    FOR EACH ROW
    EXECUTE FUNCTION common.function_validate_state_revision_entity('messages.revisions');
COMMENT ON TRIGGER trigger_messages_states_revision_entity_consistency ON messages.states
    IS 'Защищает от привязки состояния к ревизии другого сообщения.';

DROP TRIGGER IF EXISTS trigger_messages_states_cache_sync ON messages.states;
CREATE TRIGGER trigger_messages_states_cache_sync
    AFTER INSERT ON messages.states
    FOR EACH ROW
    EXECUTE FUNCTION common.function_upsert_current_state('messages.state_cache', 'entity_id');
COMMENT ON TRIGGER trigger_messages_states_cache_sync ON messages.states
    IS 'Обновляет текущие состояния сообщений на основе журнала.';

DROP TRIGGER IF EXISTS trigger_messages_states_immutability ON messages.states;
CREATE TRIGGER trigger_messages_states_immutability
    BEFORE UPDATE OR DELETE ON messages.states
    FOR EACH ROW
    EXECUTE FUNCTION common.function_protect_immutability();
COMMENT ON TRIGGER trigger_messages_states_immutability ON messages.states
    IS 'Запрещает изменять или удалять записи истории состояний.';
