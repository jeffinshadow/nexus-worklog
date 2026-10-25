-- Inovação (lote 1): evidência na rotina, impedimento com motivo e aviso a
-- quem atribuiu. Aditivo e idempotente.

-- Evidência ao marcar a rotina ("backup OK, 2,1 TB"): vai para o relatório.
ALTER TABLE recurring_completions ADD COLUMN IF NOT EXISTS note TEXT
    CHECK (note IS NULL OR char_length(note) <= 200);

-- Tarefa bloqueada: o que se está aguardando e desde quando.
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS blocked_reason TEXT
    CHECK (blocked_reason IS NULL OR char_length(blocked_reason) <= 120);
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS blocked_at TIMESTAMPTZ;

-- Tarefa atribuída concluída: quem atribuiu é avisado uma vez.
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS assigner_notified_at TIMESTAMPTZ;

-- Já concluídas antes deste recurso: não avisar atrasado.
UPDATE worklog_tasks SET assigner_notified_at = COALESCE(completed_at, now())
 WHERE status = 'done' AND assigned_by IS NOT NULL AND assigner_notified_at IS NULL
   AND NOT EXISTS (SELECT 1 FROM schema_flags WHERE name = 'assigner_notified_v1');
INSERT INTO schema_flags (name) VALUES ('assigner_notified_v1') ON CONFLICT DO NOTHING;
