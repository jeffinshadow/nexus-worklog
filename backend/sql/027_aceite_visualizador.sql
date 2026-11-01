-- Aceite do Visualizador: cada pessoa decide se quem tem o papel viewer vê o
-- registro dela (quadro, números, PDF, horas no CSV da equipe, fotos).
-- Aditivo e idempotente.
--
-- Contas que já existem ficam LIGADAS (quem usa Equipe hoje continua vendo);
-- contas criadas depois desta migração começam DESLIGADAS.
--
-- Tudo num bloco só, e só quando a coluna ainda não existe: ADD COLUMN com
-- DEFAULT true preenche as linhas atuais com true; logo em seguida o padrão
-- vira false para as próximas. Rodar de novo não entra no IF, então não
-- religa quem desligou nem as contas novas.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'users'
                      AND column_name = 'viewers_allowed') THEN
        ALTER TABLE users ADD COLUMN viewers_allowed BOOLEAN NOT NULL DEFAULT true;
        ALTER TABLE users ALTER COLUMN viewers_allowed SET DEFAULT false;
    END IF;
END $$;
