-- Convite por link e recuperação de senha por e-mail (só com SMTP configurado).
-- Aditivo e idempotente (roda a cada inicialização).

-- Links de uso único. Guardamos só o hash (HMAC com a SECRET_KEY), como nas
-- sessões: quem lê o banco não consegue usar um link.
CREATE TABLE IF NOT EXISTS auth_links (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('invite', 'reset')),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at    TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_auth_links_user ON auth_links(user_id, kind);

-- Convidada por link e ainda sem senha própria (o admin vê "convite pendente").
ALTER TABLE users ADD COLUMN IF NOT EXISTS invite_pending BOOLEAN NOT NULL DEFAULT false;
