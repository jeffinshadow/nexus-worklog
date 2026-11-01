-- Admin > Usuários > "Bloquear acesso": a conta fica com uma senha que ninguém
-- sabe, sem sessões, chaves, calendário e passkeys, e o "Esqueci a senha" não
-- manda link enquanto blocked_at estiver preenchido. "Redefinir senha" libera.
-- Os dados da pessoa ficam. Aditivo e idempotente.
ALTER TABLE users ADD COLUMN IF NOT EXISTS blocked_at TIMESTAMPTZ;
