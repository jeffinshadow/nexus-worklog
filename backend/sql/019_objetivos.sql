-- Objetivos do projeto: as demandas principais, em ordem de execução, com as
-- tarefas vinculadas (também em ordem). Aditivo e idempotente.

CREATE TABLE IF NOT EXISTS project_objectives (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id  BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
    description TEXT CHECK (description IS NULL OR char_length(description) <= 500),
    due_date    DATE,                          -- prazo opcional
    position    INT NOT NULL DEFAULT 0,        -- ordem de execução no projeto
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_objectives_project ON project_objectives(project_id, position);

-- A tarefa fica em um objetivo do seu projeto principal (ou em nenhum: "Sem
-- objetivo"). Excluir o objetivo não apaga a tarefa: ela volta para "Sem objetivo".
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS objective_id BIGINT
    REFERENCES project_objectives(id) ON DELETE SET NULL;
-- Ordem de execução dentro do objetivo (ou do "Sem objetivo" do projeto).
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS exec_position INT;
CREATE INDEX IF NOT EXISTS idx_worklog_objective ON worklog_tasks(objective_id);
