-- Vencimentos compartilhados com uma equipe (pedido do dono, 02/11). Aditiva e
-- idempotente (roda a cada inicialização). Sem equipe (o padrão) nada muda;
-- equipe excluída = o vencimento volta a ser só de quem criou.
ALTER TABLE renewals ADD COLUMN IF NOT EXISTS team_id BIGINT REFERENCES teams(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_renewals_team ON renewals(team_id) WHERE team_id IS NOT NULL;
