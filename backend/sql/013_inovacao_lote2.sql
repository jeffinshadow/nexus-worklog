-- Inovação (lote 2): rotina que exige evidência ao marcar (auditoria).
ALTER TABLE recurring_tasks ADD COLUMN IF NOT EXISTS require_note BOOLEAN NOT NULL DEFAULT false;
