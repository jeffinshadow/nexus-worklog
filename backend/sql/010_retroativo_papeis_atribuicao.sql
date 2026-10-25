-- Entrega 7: lançamento retroativo, papéis acumuláveis e atribuição de tarefas.
-- Aditivo e idempotente (roda a cada inicialização).

-- Chave de idempotência de quem cria por API/IA: repetida, devolve a tarefa
-- que já existe em vez de duplicar. Única por usuário.
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS external_ref TEXT
    CHECK (external_ref IS NULL OR char_length(external_ref) BETWEEN 1 AND 120);
CREATE UNIQUE INDEX IF NOT EXISTS uq_worklog_external_ref
    ON worklog_tasks(user_id, external_ref) WHERE external_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_worklog_user_created ON worklog_tasks(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_worklog_user_completed
    ON worklog_tasks(user_id, completed_at) WHERE completed_at IS NOT NULL;

-- Tarefa atribuída: quem mandou (o dono continua sendo quem recebeu).
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS assigned_by BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_worklog_assigned_by ON worklog_tasks(assigned_by) WHERE assigned_by IS NOT NULL;

-- Consentimento para receber tarefas de um atribuidor (NULL = não aceita).
ALTER TABLE users ADD COLUMN IF NOT EXISTS accepts_assignments_at TIMESTAMPTZ;

-- Configurações gerais, editáveis pelo admin. retro_days: até quantos dias
-- para trás uma tarefa pode ser criada ou concluída (rotinas seguem com 7).
CREATE TABLE IF NOT EXISTS app_settings (
    id         SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    retro_days SMALLINT NOT NULL DEFAULT 60 CHECK (retro_days BETWEEN 1 AND 366),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO app_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Papéis acumuláveis: user (tem o próprio registro), admin (contas, permissões,
-- configurações), assigner (atribui tarefas) e viewer (vê os registros e tira
-- relatórios de todos). users.role fica só por compatibilidade: espelha admin.
CREATE TABLE IF NOT EXISTS user_roles (
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('user', 'admin', 'assigner', 'viewer')),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role)
);

-- Migrações de dados que rodam uma vez só (o arquivo roda a cada inicialização).
CREATE TABLE IF NOT EXISTS schema_flags (
    name       TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ninguém perde o que tinha: todos viram Usuário; admins, também Admin e
-- Visualizador (ver registros e relatórios saiu do admin).
INSERT INTO user_roles (user_id, role)
SELECT u.id, r.role
  FROM users u
  CROSS JOIN (VALUES ('user'), ('admin'), ('viewer')) AS r(role)
 WHERE (r.role = 'user' OR u.role = 'admin')
   AND NOT EXISTS (SELECT 1 FROM schema_flags WHERE name = 'roles_v1')
ON CONFLICT DO NOTHING;
INSERT INTO schema_flags (name) VALUES ('roles_v1') ON CONFLICT DO NOTHING;
