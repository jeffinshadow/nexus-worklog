-- "Para empresas e instituições" (01/11/2026): opções globais do Admin, todas
-- desligadas por padrão (o padrão é o organizador pessoal), troca do próprio
-- e-mail com confirmação e o tour obrigatório no primeiro acesso.
-- Aditiva e idempotente (roda a cada inicialização): nada que já existe muda.

-- Visibilidade da equipe: 'self' = cada pessoa escolhe (users.viewers_allowed,
-- como sempre); 'managers' = quem tem o papel "Vê a equipe" vê todos. As
-- escolhas individuais continuam guardadas: voltar para 'self' as devolve.
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS team_visibility TEXT NOT NULL DEFAULT 'self'
    CHECK (team_visibility IN ('self', 'managers'));
-- Desde quando está em 'managers' (o aviso único de quem já usa compara com isto).
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS team_visibility_since TIMESTAMPTZ;
-- Nome e e-mail definidos pela administração (desligado: cada pessoa edita os seus).
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS identity_managed BOOLEAN NOT NULL DEFAULT false;
-- Tour obrigatório no primeiro acesso (sem "Pular" até concluir).
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS tour_required BOOLEAN NOT NULL DEFAULT false;

-- Quando a pessoa tocou "Entendi" no aviso de visibilidade (ou passou por ele no tour).
ALTER TABLE users ADD COLUMN IF NOT EXISTS visibility_notice_at TIMESTAMPTZ;

-- Conta que ainda não fez o primeiro tour. As contas que já existem nascem com
-- false (quem já usa nunca é forçado); daqui em diante, toda conta nova nasce
-- com true, e concluir o tour volta para false de vez.
ALTER TABLE users ADD COLUMN IF NOT EXISTS tour_first_access BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ALTER COLUMN tour_first_access SET DEFAULT true;
-- Convite ainda não aceito também é primeiro acesso (só muda quem nunca entrou).
UPDATE users SET tour_first_access = true
 WHERE invite_pending AND tour_done_at IS NULL AND NOT tour_first_access;

-- Troca do próprio e-mail: link de uso único mandado ao endereço NOVO; o
-- e-mail só muda quando a pessoa confirma por ele.
ALTER TABLE auth_links ADD COLUMN IF NOT EXISTS new_email TEXT;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'auth_links_kind_check'
                      AND pg_get_constraintdef(oid) LIKE '%email%') THEN
        ALTER TABLE auth_links DROP CONSTRAINT IF EXISTS auth_links_kind_check;
        ALTER TABLE auth_links ADD CONSTRAINT auth_links_kind_check
            CHECK (kind IN ('invite', 'reset', 'email'));
    END IF;
END $$;
