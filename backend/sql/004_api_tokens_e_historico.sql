-- Chaves de API pessoais e histórico de ações (com origem e desfazer).
-- Aditivo e idempotente: só cria tabelas/índices novos.

-- Chave de API: o valor bruto (nxs_...) é mostrado UMA vez; o banco guarda só
-- o HMAC (como as sessões). scope: 'read' (só leitura) ou 'write'.
CREATE TABLE IF NOT EXISTS api_tokens (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    prefix       TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    scope        TEXT NOT NULL CHECK (scope IN ('read', 'write')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_id);

-- Histórico: toda alteração de dados registra quem fez (web, api, mcp, admin),
-- por qual chave, e o estado antes/depois (JSON), para exibir e desfazer.
CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor      TEXT NOT NULL CHECK (actor IN ('web', 'api', 'mcp', 'admin')),
    token_id   BIGINT REFERENCES api_tokens(id) ON DELETE SET NULL,
    token_name TEXT,
    action     TEXT NOT NULL,
    entity     TEXT NOT NULL,
    entity_id  BIGINT,
    before     JSONB,
    after      JSONB,
    undone_at  TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(user_id, entity, entity_id, id DESC)
