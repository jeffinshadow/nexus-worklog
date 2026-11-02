-- Pequenas faltas do Admin (01/11/2026): último acesso das contas, aviso de
-- papel novo, pedido de convite que o admin desliga e origens genéricas no
-- formulário de pedido. Aditiva e idempotente (roda a cada inicialização).

-- Último acesso (login ou uso do app), gravado no máximo a cada 5 minutos.
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;

-- Papéis que a pessoa ganhou/perdeu e ainda não viu (aviso único no próximo
-- acesso, com "Entendi"): {"added": [...], "removed": [...]} ou NULL.
ALTER TABLE users ADD COLUMN IF NOT EXISTS role_notice JSONB;

-- Admin › Para empresas: tirar o "Solicitar convite" da tela de login.
-- Desligado (padrão) = como sempre: aparece quando há e-mail configurado.
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS invite_request_off BOOLEAN NOT NULL DEFAULT false;

-- Origens do pedido de convite sem nomes de fora ("site da ShadowTec", "GitHub"):
-- colega, empresa, internet, outro. As antigas continuam válidas nos pedidos
-- já guardados (saem sozinhos em até 180 dias).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'invite_requests_source_check'
                      AND pg_get_constraintdef(oid) LIKE '%internet%') THEN
        ALTER TABLE invite_requests DROP CONSTRAINT IF EXISTS invite_requests_source_check;
        ALTER TABLE invite_requests ADD CONSTRAINT invite_requests_source_check
            CHECK (source IN ('colega', 'empresa', 'internet', 'outro', 'site', 'github'));
    END IF;
END $$;

-- Endereço do sistema de chamados da instância (Admin › Para empresas). Vazio
-- (padrão) = cada pessoa usa o seu (users.ticket_url, como sempre); preenchido =
-- vale para todos e a Conta mostra o campo travado. Os endereços de cada um
-- ficam guardados e voltam a valer se o admin esvaziar. Nasce vazio: nada muda.
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS ticket_url TEXT
    CHECK (ticket_url IS NULL OR char_length(ticket_url) <= 300);
