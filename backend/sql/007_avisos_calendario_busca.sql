-- Entrega 4: avisos por e-mail, feed de calendário (ICS) e busca.
-- Aditivo e idempotente (roda a cada inicialização).

-- Avisos por e-mail: opt-in por usuário (tudo desligado por padrão).
CREATE TABLE IF NOT EXISTS notification_prefs (
    user_id        BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    morning        BOOLEAN NOT NULL DEFAULT false,          -- "seu dia": prazos e rotinas de hoje
    morning_hour   SMALLINT NOT NULL DEFAULT 8 CHECK (morning_hour BETWEEN 0 AND 23),
    evening        BOOLEAN NOT NULL DEFAULT false,          -- rotinas do dia ainda não feitas
    evening_hour   SMALLINT NOT NULL DEFAULT 17 CHECK (evening_hour BETWEEN 0 AND 23),
    weekly         BOOLEAN NOT NULL DEFAULT false,          -- resumo da semana anterior (segunda)
    weekly_hour    SMALLINT NOT NULL DEFAULT 8 CHECK (weekly_hour BETWEEN 0 AND 23),
    show_titles    BOOLEAN NOT NULL DEFAULT true,           -- false = só números no e-mail
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Um envio por (usuário, tipo, dia): o agendador grava antes de mandar e
-- nunca repete, mesmo reiniciando o backend.
CREATE TABLE IF NOT EXISTS notification_log (
    user_id   BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind      TEXT NOT NULL CHECK (kind IN ('morning', 'evening', 'weekly', 'test')),
    ref_date  DATE NOT NULL,
    sent_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    ok        BOOLEAN,
    error     TEXT,
    PRIMARY KEY (user_id, kind, ref_date)
);

-- Feed de calendário: um link secreto por usuário (só o hash fica no banco).
CREATE TABLE IF NOT EXISTS calendar_feeds (
    user_id            BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    token_hash         TEXT NOT NULL UNIQUE,
    prefix             TEXT NOT NULL,
    include_recurring  BOOLEAN NOT NULL DEFAULT true,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at       TIMESTAMPTZ
);

-- Busca sem acento e sem diferenciar maiúsculas, sem depender de extensão.
CREATE OR REPLACE FUNCTION nx_fold(t TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT translate(lower(coalesce(t, '')),
                     'áàâãäåéèêëíìîïóòôõöúùûüçñ',
                     'aaaaaaeeeeiiiiooooouuuucn')
$$;
