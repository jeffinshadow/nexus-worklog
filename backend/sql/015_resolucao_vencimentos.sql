-- Inovação (lote 5): como foi resolvido (base de conhecimento leve, entra na
-- busca) e vencimentos com antecedência (certificado, licença, domínio,
-- garantia). Aditivo e idempotente.
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS resolution TEXT
    CHECK (resolution IS NULL OR char_length(resolution) <= 1000);

CREATE TABLE IF NOT EXISTS renewals (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label      TEXT NOT NULL CHECK (char_length(label) BETWEEN 1 AND 120),
    expires_on DATE NOT NULL,
    warn_days  SMALLINT NOT NULL DEFAULT 30 CHECK (warn_days BETWEEN 1 AND 365),
    project_id BIGINT REFERENCES projects(id) ON DELETE SET NULL,
    note       TEXT CHECK (note IS NULL OR char_length(note) <= 200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_renewals_user_expires ON renewals(user_id, expires_on);
