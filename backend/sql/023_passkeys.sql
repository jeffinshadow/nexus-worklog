-- Entrar com passkey (WebAuthn): digital, rosto, Windows Hello ou chave física.
-- Só a chave pública fica aqui; a privada nunca sai do aparelho. Aditivo e idempotente.
CREATE TABLE IF NOT EXISTS webauthn_credentials (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_id BYTEA NOT NULL UNIQUE,
    public_key    BYTEA NOT NULL,
    sign_count    BIGINT NOT NULL DEFAULT 0,       -- contador do autenticador (detecta cópia)
    transports    TEXT,                            -- ex.: "internal,hybrid"
    name          TEXT CHECK (name IS NULL OR char_length(name) <= 60),
    backed_up     BOOLEAN NOT NULL DEFAULT false,  -- sincronizada (iCloud, Google, 1Password…)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_webauthn_credentials_user ON webauthn_credentials(user_id);

-- Desafio de uso único, por 5 minutos (cadastrar ou entrar).
CREATE TABLE IF NOT EXISTS webauthn_challenges (
    id         TEXT PRIMARY KEY,
    user_id    BIGINT REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('register', 'login')),
    challenge  BYTEA NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
