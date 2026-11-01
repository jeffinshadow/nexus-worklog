-- Foto com chave de idempotência: a fila do app (ou uma automação) que reenvia
-- depois de um timeout no 3G não grava a mesma evidência duas vezes.
-- Aditivo e idempotente.
ALTER TABLE photos ADD COLUMN IF NOT EXISTS external_ref TEXT
    CHECK (external_ref IS NULL OR char_length(external_ref) BETWEEN 1 AND 120);
CREATE UNIQUE INDEX IF NOT EXISTS uq_photos_external_ref
    ON photos(user_id, external_ref) WHERE external_ref IS NOT NULL;
