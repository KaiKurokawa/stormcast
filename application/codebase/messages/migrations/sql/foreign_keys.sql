ALTER TABLE messages.revision_buffer
    ADD CONSTRAINT revision_buffer_entity_id_fkey
    FOREIGN KEY (entity_id) REFERENCES messages.entities(id) ON DELETE CASCADE;
ALTER TABLE messages.revision_buffer
    ADD CONSTRAINT revision_buffer_parent_id_fkey
    FOREIGN KEY (parent_id) REFERENCES messages.entities(id) ON DELETE SET NULL;
ALTER TABLE messages.revisions
    ADD CONSTRAINT revisions_entity_id_fkey
    FOREIGN KEY (entity_id) REFERENCES messages.entities(id) ON DELETE CASCADE;
ALTER TABLE messages.revisions
    ADD CONSTRAINT revisions_parent_id_fkey
    FOREIGN KEY (parent_id) REFERENCES messages.entities(id) ON DELETE SET NULL;
ALTER TABLE messages.state_cache
    ADD CONSTRAINT state_cache_entity_id_fkey
    FOREIGN KEY (entity_id) REFERENCES messages.entities(id) ON DELETE CASCADE;
ALTER TABLE messages.state_cache
    ADD CONSTRAINT state_cache_revision_id_fkey
    FOREIGN KEY (revision_id) REFERENCES messages.revisions(id) ON DELETE RESTRICT;
ALTER TABLE messages.states
    ADD CONSTRAINT states_entity_id_fkey
    FOREIGN KEY (entity_id) REFERENCES messages.entities(id) ON DELETE CASCADE;
ALTER TABLE messages.states
    ADD CONSTRAINT states_revision_id_fkey
    FOREIGN KEY (revision_id) REFERENCES messages.revisions(id) ON DELETE RESTRICT;
