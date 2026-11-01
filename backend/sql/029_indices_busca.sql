-- Busca: anotações e checklist filtrados pela pessoa (antes, a busca varria
-- as de todas as contas). Só índices novos: aditivo e idempotente.
CREATE INDEX IF NOT EXISTS idx_notes_user ON task_notes(user_id);
CREATE INDEX IF NOT EXISTS idx_checklist_user ON task_checklist(user_id);
