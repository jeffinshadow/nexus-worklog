-- Inovação (lote 6): vencimento que se repete (certificado anual, licença de 3
-- anos): "Renovei" já sugere a próxima data. Aditivo e idempotente.
ALTER TABLE renewals ADD COLUMN IF NOT EXISTS renew_months SMALLINT
    CHECK (renew_months IS NULL OR renew_months BETWEEN 1 AND 120);
