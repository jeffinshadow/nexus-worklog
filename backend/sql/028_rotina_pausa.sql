-- Rotinas: pausa (férias, folga, prédio fechado) e "a cada N dias depois da
-- última vez". Aditivo e idempotente.

-- freq 'after': devida quando hoje >= última marcação + interval_days (sem
-- marcação: desde a criação). Só alarga a lista aceita; troca o CHECK uma vez.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'recurring_tasks_freq_check'
                      AND pg_get_constraintdef(oid) LIKE '%after%') THEN
        ALTER TABLE recurring_tasks DROP CONSTRAINT IF EXISTS recurring_tasks_freq_check;
        ALTER TABLE recurring_tasks ADD CONSTRAINT recurring_tasks_freq_check
            CHECK (freq IN ('daily', 'weekly', 'monthly', 'interval', 'after'));
    END IF;
END $$;

-- Períodos de pausa [start_d, end_d] (inclusive, no fuso da app). Nos dias
-- pausados a rotina não é devida (marcar = extra). A pausa começa no dia em
-- que é pedida e nunca reescreve o passado; "Retomar agora" encerra o período
-- na véspera (end_d < start_d = período vazio, ignorado). Um período por
-- pausa: as antigas ficam, e os números dos meses já fechados não mudam.
CREATE TABLE IF NOT EXISTS recurring_pauses (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recurring_id BIGINT NOT NULL REFERENCES recurring_tasks(id) ON DELETE CASCADE,
    start_d      DATE NOT NULL,
    end_d        DATE NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_recurring_pauses ON recurring_pauses(recurring_id, start_d);
