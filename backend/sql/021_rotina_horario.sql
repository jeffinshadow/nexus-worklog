-- Horário da rotina (opcional): a interface lembra perto dele e toca até a
-- rotina ser marcada. Só o horário do dia; a agenda continua a mesma.
-- Aditivo e idempotente.

ALTER TABLE recurring_tasks ADD COLUMN IF NOT EXISTS remind_at TIME;
