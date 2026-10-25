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
