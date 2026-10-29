-- Resumo semanal por e-mail: o relatório em PDF anexado e uma cópia opcional
-- (gestor, cliente). Aditivo e idempotente; os dois começam desligados.
ALTER TABLE notification_prefs ADD COLUMN IF NOT EXISTS weekly_pdf BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE notification_prefs ADD COLUMN IF NOT EXISTS weekly_cc TEXT
    CHECK (weekly_cc IS NULL OR char_length(weekly_cc) BETWEEN 3 AND 254);
