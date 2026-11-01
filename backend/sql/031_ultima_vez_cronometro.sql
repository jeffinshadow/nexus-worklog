-- Rodada 3 do gauntlet. Aditivo e idempotente.
--
-- Rotina "N dias depois da última vez" (freq after): trocar a agenda cria uma
-- rotina nova a partir de hoje; after_from guarda a última marcação da antiga,
-- para a próxima data seguir contando dela (última + N novo), e não da troca.
ALTER TABLE recurring_tasks ADD COLUMN IF NOT EXISTS after_from DATE;

-- Apontamento feito pelo cronômetro: o intervalo de verdade (início e fim).
-- Um início enviado depois (sem sinal, ou pela IA com `at`) não pode cair em
-- cima de tempo de cronômetro já apontado. Apontamento à mão: os dois nulos.
ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_time_user_ended ON time_entries(user_id, ended_at) WHERE ended_at IS NOT NULL;
