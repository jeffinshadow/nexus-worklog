-- Projetos e objetivos criados pela IA (MCP): descrição do projeto e a chave
-- externa de idempotência (como a das tarefas). Aditivo e idempotente.

ALTER TABLE projects ADD COLUMN IF NOT EXISTS description TEXT
    CHECK (description IS NULL OR char_length(description) <= 500);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS external_ref TEXT
    CHECK (external_ref IS NULL OR char_length(external_ref) BETWEEN 1 AND 120);
CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_external_ref
    ON projects(user_id, external_ref) WHERE external_ref IS NOT NULL;

ALTER TABLE project_objectives ADD COLUMN IF NOT EXISTS external_ref TEXT
    CHECK (external_ref IS NULL OR char_length(external_ref) BETWEEN 1 AND 120);
CREATE UNIQUE INDEX IF NOT EXISTS uq_objectives_external_ref
    ON project_objectives(user_id, external_ref) WHERE external_ref IS NOT NULL;
