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

-- Webhooks de saída (app/webhooks.py): até 5 por pessoa. O segredo não fica
-- aqui: é derivado do SECRET_KEY com o sal. last_event_id = cursor no
-- audit_log; 5 falhas seguidas preenchem disabled_at.
CREATE TABLE IF NOT EXISTS webhooks (
    id                BIGSERIAL PRIMARY KEY,
    user_id           BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    url               TEXT NOT NULL CHECK (char_length(url) BETWEEN 9 AND 500),
    events            TEXT[] NOT NULL DEFAULT '{*}',
    secret_salt       TEXT NOT NULL,
    last_event_id     BIGINT NOT NULL DEFAULT 0,
    failures          INT NOT NULL DEFAULT 0,
    last_error        TEXT,
    next_attempt_at   TIMESTAMPTZ,
    last_delivered_at TIMESTAMPTZ,
    disabled_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_webhooks_user ON webhooks(user_id);
