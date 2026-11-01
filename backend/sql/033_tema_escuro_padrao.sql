-- Escuro como tema padrão (decisão do dono, 01/11/2026): contas novas nascem no escuro e,
-- UMA vez, quem estava no "automático" (o padrão antigo) passa para o escuro. Quem quiser
-- o claro ou o automático escolhe de novo no tour ou em Configurações > Conta. Idempotente:
-- a troca só roda enquanto a marca não existe.
ALTER TABLE users ALTER COLUMN theme SET DEFAULT 'dark';
UPDATE users SET theme = 'dark'
 WHERE theme = 'auto'
   AND NOT EXISTS (SELECT 1 FROM schema_flags WHERE name = 'theme_dark_default_v1');
INSERT INTO schema_flags (name) VALUES ('theme_dark_default_v1') ON CONFLICT DO NOTHING;
