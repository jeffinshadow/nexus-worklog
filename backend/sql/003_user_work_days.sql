-- Dias úteis de cada usuário, como máscara de bits com domingo = bit 0:
--   dom=1 seg=2 ter=4 qua=8 qui=16 sex=32 sáb=64.  Seg–sex = 62.
-- Recorrentes só geram "dia devido" nos dias úteis do dono; conclusões em dia
-- não útil continuam salvas e aparecem como "extra" (não inflam o devido).
-- Idempotente e aditivo: ADD COLUMN IF NOT EXISTS com DEFAULT preenche os
-- usuários existentes com seg–sex. O CHECK impede uma semana sem nenhum dia.
ALTER TABLE users ADD COLUMN IF NOT EXISTS work_days SMALLINT NOT NULL DEFAULT 62
    CHECK (work_days BETWEEN 1 AND 127)
