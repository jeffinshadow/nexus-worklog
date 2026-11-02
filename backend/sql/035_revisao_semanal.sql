-- Revisão semanal guiada e aviso de tarefa aguardando parada (01/11/2026).
-- Aditiva e idempotente: nada muda nos dados que já existem.

-- Aguardando há N dias sem data para cobrar: o assistente do Hoje (e o aviso
-- da manhã) pergunta se a pessoa quer marcar quando cobrar. Padrão: 5 dias.
ALTER TABLE assistant_prefs ADD COLUMN IF NOT EXISTS stale_days SMALLINT NOT NULL DEFAULT 5
    CHECK (stale_days BETWEEN 1 AND 60);

-- Revisão da semana (domingo a sábado): feita, ou o convite do assistente
-- dispensado ("Agora não"). Só serve para o assistente não insistir.
CREATE TABLE IF NOT EXISTS week_reviews (
    user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    week_start   DATE NOT NULL,
    done_at      TIMESTAMPTZ,
    dismissed_at TIMESTAMPTZ,
    PRIMARY KEY (user_id, week_start)
);
