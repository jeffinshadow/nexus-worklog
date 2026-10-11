-- Identidade visual do app (lockup do menu e do login), editável pelo admin.
-- Uma única linha (id = 1). Sem logo enviado, o app usa o dragão padrão.
-- Aditivo e idempotente.
CREATE TABLE IF NOT EXISTS app_branding (
    id         SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    line1      TEXT NOT NULL DEFAULT 'nexus',
    line2      TEXT NOT NULL DEFAULT 'worklog',
    logo       BYTEA,
    logo_mime  TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by BIGINT REFERENCES users(id) ON DELETE SET NULL
);

INSERT INTO app_branding (id) VALUES (1) ON CONFLICT (id) DO NOTHING
