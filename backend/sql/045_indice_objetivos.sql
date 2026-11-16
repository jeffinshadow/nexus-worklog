-- Gauntlet loop (16/11/2026): a lista de projetos lê os objetivos da pessoa (services._STATS_SQL)
-- e só havia índice por projeto: a consulta varria os objetivos de todas as contas.
-- Só um índice novo: aditiva e idempotente (roda a cada inicialização).
CREATE INDEX IF NOT EXISTS idx_objectives_user ON project_objectives(user_id)
