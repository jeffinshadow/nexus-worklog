-- Tarefa em mais de um projeto, projeto padrão e o tour guiado.
-- Aditivo e idempotente (roda a cada inicialização).

-- Projetos além do principal (worklog_tasks.project_id continua sendo o
-- principal). A tarefa aparece no filtro e no relatório de cada um, com o
-- tempo inteiro em cada um. Sem principal não há extras (a API garante).
CREATE TABLE IF NOT EXISTS worklog_task_projects (
    task_id    BIGINT NOT NULL REFERENCES worklog_tasks(id) ON DELETE CASCADE,
    project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, project_id)
);
CREATE INDEX IF NOT EXISTS idx_task_projects_project ON worklog_task_projects(project_id);

-- Projeto aplicado à tarefa criada sem projeto (app, API, IA, atribuição).
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_project_id BIGINT REFERENCES projects(id) ON DELETE SET NULL;

-- Tour guiado: NULL = ainda não viu (abre sozinho no primeiro acesso).
ALTER TABLE users ADD COLUMN IF NOT EXISTS tour_done_at TIMESTAMPTZ;
