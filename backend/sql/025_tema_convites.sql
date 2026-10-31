-- Tema da interface por conta e pedidos de convite. Aditivo e idempotente.

-- auto = segue o aparelho; light/dark = forçado (Configurações › Conta).
ALTER TABLE users ADD COLUMN IF NOT EXISTS theme TEXT NOT NULL DEFAULT 'auto'
    CHECK (theme IN ('auto', 'light', 'dark'));

-- "Solicitar convite ao administrador" na tela de login (só com e-mail
-- configurado). O admin vê em Admin e convida (o convite por link de sempre)
-- ou recusa. Um pedido aberto por e-mail.
CREATE TABLE IF NOT EXISTS invite_requests (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
    email       TEXT NOT NULL CHECK (char_length(email) <= 254),
    source      TEXT NOT NULL CHECK (source IN ('colega', 'site', 'github', 'outro')),
    source_note TEXT CHECK (source_note IS NULL OR char_length(source_note) <= 120),
    reason      TEXT NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 600),
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'invited', 'declined')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at  TIMESTAMPTZ,
    decided_by  BIGINT REFERENCES users(id) ON DELETE SET NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_invite_requests_pending
    ON invite_requests (lower(email)) WHERE status = 'pending';
