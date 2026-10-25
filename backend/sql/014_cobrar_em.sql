-- Inovação (lote 3): impedimento com data combinada para cobrar ("o fornecedor
-- retorna na quinta"). Aditivo e idempotente.
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS follow_up_on DATE;
