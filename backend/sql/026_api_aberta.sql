-- API aberta: idempotência em anotações e apontamentos e feed de mudanças.
-- Aditivo e idempotente.

-- external_ref como nas tarefas: a automação repete a chamada sem duplicar.
ALTER TABLE task_notes ADD COLUMN IF NOT EXISTS external_ref TEXT
    CHECK (external_ref IS NULL OR char_length(external_ref) BETWEEN 1 AND 120);
CREATE UNIQUE INDEX IF NOT EXISTS uq_task_notes_external_ref
    ON task_notes(user_id, external_ref) WHERE external_ref IS NOT NULL;

ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS external_ref TEXT
    CHECK (external_ref IS NULL OR char_length(external_ref) BETWEEN 1 AND 120);
CREATE UNIQUE INDEX IF NOT EXISTS uq_time_entries_external_ref
    ON time_entries(user_id, external_ref) WHERE external_ref IS NOT NULL;

-- Feed (GET /api/history?after=) e webhooks leem o histórico da pessoa pelo id.
CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_log(user_id, id);
