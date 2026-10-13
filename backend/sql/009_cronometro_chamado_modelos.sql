-- Entrega 6: cronômetro, número do chamado, plantão e modelos de tarefa.
-- Aditivo e idempotente (roda a cada inicialização).

-- Número do chamado no sistema da equipe (GLPI, TomTicket...) e plantão:
-- o tempo de uma tarefa de plantão sai separado no relatório.
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS ticket TEXT
    CHECK (ticket IS NULL OR char_length(ticket) BETWEEN 1 AND 40);
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS after_hours BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_worklog_ticket ON worklog_tasks(user_id, ticket) WHERE ticket IS NOT NULL;

-- Endereço do sistema de chamados de cada pessoa; {id} vira o número.
ALTER TABLE users ADD COLUMN IF NOT EXISTS ticket_url TEXT
    CHECK (ticket_url IS NULL OR char_length(ticket_url) <= 300);

-- Cronômetro: no máximo um rodando por pessoa (vale em qualquer aparelho).
-- Ao parar, vira um apontamento comum em time_entries.
CREATE TABLE IF NOT EXISTS task_timers (
    user_id    BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    task_id    BIGINT NOT NULL REFERENCES worklog_tasks(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Modelos de tarefa: procedimentos que se repetem, com checklist pronto.
CREATE TABLE IF NOT EXISTS task_templates (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 60),
    title       TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    description TEXT CHECK (description IS NULL OR char_length(description) <= 300),
    priority    SMALLINT NOT NULL DEFAULT 2 CHECK (priority BETWEEN 1 AND 3),
    project_id  BIGINT REFERENCES projects(id) ON DELETE SET NULL,
    after_hours BOOLEAN NOT NULL DEFAULT false,
    checklist   JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);
