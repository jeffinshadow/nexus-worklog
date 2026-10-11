-- Entrega 3: projetos/clientes, prioridade, anotações de progresso, checklist,
-- apontamento de tempo e recorrências flexíveis. Aditivo e idempotente:
-- só tabelas/colunas novas, com padrões que mantêm o comportamento atual.

CREATE TABLE IF NOT EXISTS projects (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    color      TEXT NOT NULL DEFAULT '#5294E2' CHECK (color ~ '^#[0-9A-Fa-f]{6}$'),
    archived   BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

-- Tarefa pontual: projeto (opcional) e prioridade 1 alta, 2 normal, 3 baixa.
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS project_id BIGINT REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS priority SMALLINT NOT NULL DEFAULT 2 CHECK (priority BETWEEN 1 AND 3);
CREATE INDEX IF NOT EXISTS idx_worklog_project ON worklog_tasks(project_id);

-- Anotações de progresso (linha do tempo da tarefa), com a origem.
CREATE TABLE IF NOT EXISTS task_notes (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id    BIGINT NOT NULL REFERENCES worklog_tasks(id) ON DELETE CASCADE,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body       TEXT NOT NULL CHECK (char_length(body) BETWEEN 1 AND 2000),
    actor      TEXT NOT NULL DEFAULT 'web',
    token_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notes_task ON task_notes(task_id, created_at);

-- Subtarefas (checklist dentro da tarefa pontual).
CREATE TABLE IF NOT EXISTS task_checklist (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id    BIGINT NOT NULL REFERENCES worklog_tasks(id) ON DELETE CASCADE,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label      TEXT NOT NULL CHECK (char_length(label) BETWEEN 1 AND 200),
    done       BOOLEAN NOT NULL DEFAULT false,
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_checklist_task ON task_checklist(task_id, position);

-- Apontamento de tempo por tarefa (minutos num dia).
CREATE TABLE IF NOT EXISTS time_entries (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id    BIGINT NOT NULL REFERENCES worklog_tasks(id) ON DELETE CASCADE,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    minutes    INTEGER NOT NULL CHECK (minutes BETWEEN 1 AND 1440),
    day        DATE NOT NULL,
    note       TEXT CHECK (note IS NULL OR char_length(note) <= 200),
    actor      TEXT NOT NULL DEFAULT 'web',
    token_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_time_user_day ON time_entries(user_id, day);
CREATE INDEX IF NOT EXISTS idx_time_task ON time_entries(task_id);

-- Recorrências flexíveis. Padrão 'daily' = comportamento atual (dias úteis do
-- dono). weekly: weekdays (máscara, domingo = bit 0). monthly: month_day
-- (31 = último dia do mês). interval: a cada interval_days dias, contando da
-- criação (created_at).
ALTER TABLE recurring_tasks ADD COLUMN IF NOT EXISTS freq TEXT NOT NULL DEFAULT 'daily'
    CHECK (freq IN ('daily', 'weekly', 'monthly', 'interval'));
ALTER TABLE recurring_tasks ADD COLUMN IF NOT EXISTS weekdays SMALLINT CHECK (weekdays BETWEEN 1 AND 127);
ALTER TABLE recurring_tasks ADD COLUMN IF NOT EXISTS month_day SMALLINT CHECK (month_day BETWEEN 1 AND 31);
ALTER TABLE recurring_tasks ADD COLUMN IF NOT EXISTS interval_days SMALLINT CHECK (interval_days BETWEEN 2 AND 365)
