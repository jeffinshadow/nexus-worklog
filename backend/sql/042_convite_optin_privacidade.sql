-- Gauntlet geral R6 (lote C1). Aditiva e idempotente (roda a cada inicialização).

-- "Solicitar convite" na tela de login passa a ser opt-in (decisão do dono, D1,
-- 02/11): desligado por padrão, inclusive nas instâncias que já existem, até o
-- admin ligar em Admin › Para empresas. A coluna antiga invite_request_off fica
-- no banco, sem uso.
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS invite_request_on BOOLEAN NOT NULL DEFAULT false;

-- Endereço da política de privacidade da instância (Admin › Para empresas):
-- link na tela de login, na Conta e no e-mail de convite. Vazio = sem link.
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS privacy_url TEXT;
