-- Perfil (nome de exibição e foto) e preferências do assistente.
-- Aditivo e idempotente (roda a cada inicialização).

-- Nome escolhido pelo próprio usuário. NULL = o app deriva do e-mail.
ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT
    CHECK (display_name IS NULL OR char_length(display_name) BETWEEN 1 AND 60);

-- Foto de perfil fora da tabela de usuários (não pesa nas consultas de sessão).
-- O navegador já manda recortada e reduzida; o backend confere o tipo real.
CREATE TABLE IF NOT EXISTS user_avatars (
    user_id    BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    image      BYTEA NOT NULL,
    mime       TEXT NOT NULL CHECK (mime IN ('image/png', 'image/jpeg', 'image/webp')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Assistente: as falas nas telas e o lembrete de "X minutos sem registro"
-- (os dois ligados por padrão; o lembrete só nos dias úteis e dentro da janela).
CREATE TABLE IF NOT EXISTS assistant_prefs (
    user_id      BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    enabled      BOOLEAN NOT NULL DEFAULT true,
    idle_on      BOOLEAN NOT NULL DEFAULT true,
    idle_minutes SMALLINT NOT NULL DEFAULT 30 CHECK (idle_minutes BETWEEN 5 AND 480),
    idle_start   SMALLINT NOT NULL DEFAULT 480  CHECK (idle_start BETWEEN 0 AND 1439),   -- minutos do dia (08:00)
    idle_end     SMALLINT NOT NULL DEFAULT 1080 CHECK (idle_end BETWEEN 1 AND 1440),     -- 18:00
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (idle_start < idle_end)
);

-- Lembrete ligado por padrão (bancos que já tinham a tabela com o padrão antigo).
ALTER TABLE assistant_prefs ALTER COLUMN idle_on SET DEFAULT true;
-- Fala fechada no X: volta sozinha depois de N minutos (ou só ao recarregar).
ALTER TABLE assistant_prefs ADD COLUMN IF NOT EXISTS reopen_on BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE assistant_prefs ADD COLUMN IF NOT EXISTS reopen_minutes SMALLINT NOT NULL DEFAULT 10
    CHECK (reopen_minutes BETWEEN 1 AND 240);
-- Resumo do dia: aparece com a primeira tarefa ou rotina concluída no dia; sem
-- nada concluído, a partir deste horário (minutos do dia; padrão 14:00).
ALTER TABLE assistant_prefs ADD COLUMN IF NOT EXISTS summary_from SMALLINT NOT NULL DEFAULT 840
    CHECK (summary_from BETWEEN 0 AND 1439);
