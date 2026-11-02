-- Equipes e admin master (pedido do dono, 02/11). Aditiva e idempotente (roda a cada inicialização).

-- Equipes cadastradas no Admin. Uma pessoa pode estar em várias; todo mundo
-- começa sem equipe. Arquivada = não conta para nada (nem escopo, nem "Para
-- empresas"), mas guarda os membros para voltar.
CREATE TABLE IF NOT EXISTS teams (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_teams_name_ci ON teams (lower(name));

CREATE TABLE IF NOT EXISTS team_members (
    team_id    BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_team_members_user ON team_members(user_id);

-- Admin master: sempre exatamente um (uma coluna numa linha só: a troca é uma
-- gravação). Sem master (instância antiga ou o master perdeu o papel por fora),
-- o admin mais antigo assume, aqui e em main.seed_admin.
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS master_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;
UPDATE app_settings s
   SET master_user_id = (SELECT u.id FROM users u
                          WHERE EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'admin')
                          ORDER BY u.created_at, u.id LIMIT 1)
 WHERE s.id = 1
   AND (s.master_user_id IS NULL
        OR NOT EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = s.master_user_id AND r.role = 'admin'));

-- Código de uso único para transferir o papel de master (MFA por e-mail):
-- tabela de links existente, kind 'master', com quem recebe e as tentativas.
ALTER TABLE auth_links ADD COLUMN IF NOT EXISTS target_user_id BIGINT REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE auth_links ADD COLUMN IF NOT EXISTS attempts INT NOT NULL DEFAULT 0;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'auth_links_kind_check'
                      AND pg_get_constraintdef(oid) LIKE '%master%') THEN
        ALTER TABLE auth_links DROP CONSTRAINT IF EXISTS auth_links_kind_check;
        ALTER TABLE auth_links ADD CONSTRAINT auth_links_kind_check
            CHECK (kind IN ('invite', 'reset', 'email', 'master'));
    END IF;
END $$;
