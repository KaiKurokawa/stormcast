CREATE TRIGGER trigger_documents_entities_state_initialization
                AFTER INSERT ON documents.entities
                FOR EACH ROW
                EXECUTE FUNCTION common.function_initialize_state_log(
                    'documents.states',
                    'entity_id',
                    '{"readiness_stage": "draft", "is_archived": false, "is_deleted": false, "content_hash": "\\x6b4eb78df2fb93cbe5a3034501862580d143d3d3d010055a12c44fba9e910f2b"}'
                );

CREATE TRIGGER trigger_documents_entities_immutability
                BEFORE UPDATE OR DELETE ON documents.entities
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_immutability();

CREATE TRIGGER trigger_documents_template_entities_immutability
                BEFORE UPDATE OR DELETE ON documents.template_entities
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_immutability();

CREATE TRIGGER trigger_documents_template_revisions_immutability
                BEFORE UPDATE OR DELETE ON documents.template_revisions
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_immutability();

CREATE TRIGGER trigger_documents_revision_buffer_identity
                BEFORE UPDATE OF id, entity_id, user_id ON documents.revision_buffer
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_revision_buffer_identity();

CREATE TRIGGER trigger_documents_revision_buffer_updated_at
                BEFORE UPDATE ON documents.revision_buffer
                FOR EACH ROW
                EXECUTE FUNCTION common.function_refresh_updated_at_column();

CREATE TRIGGER trigger_documents_revisions_immutability
                BEFORE UPDATE OR DELETE ON documents.revisions
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_immutability();

CREATE TRIGGER trigger_documents_state_cache_updated_at
                BEFORE UPDATE ON documents.state_cache
                FOR EACH ROW
                EXECUTE FUNCTION common.function_refresh_updated_at_column();

CREATE TRIGGER trigger_documents_state_cache_revision_entity_consistency
                BEFORE INSERT OR UPDATE OF entity_id, revision_id ON documents.state_cache
                FOR EACH ROW
                EXECUTE FUNCTION common.function_validate_state_revision_entity('documents.revisions');

CREATE TRIGGER trigger_documents_states_revision_entity_consistency
                BEFORE INSERT OR UPDATE OF entity_id, revision_id ON documents.states
                FOR EACH ROW
                EXECUTE FUNCTION common.function_validate_state_revision_entity('documents.revisions');

CREATE TRIGGER trigger_documents_states_cache_sync
                AFTER INSERT ON documents.states
                FOR EACH ROW
                EXECUTE FUNCTION common.function_upsert_current_state('documents.state_cache', 'entity_id');

CREATE TRIGGER trigger_documents_states_immutability
                BEFORE UPDATE OR DELETE ON documents.states
                FOR EACH ROW
                EXECUTE FUNCTION common.function_protect_immutability();
