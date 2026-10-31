-- Notificações do sistema (Web Push), por aparelho: rotina na hora, cobrança e
-- prazos de manhã, tarefa atribuída. Aditivo e idempotente.

-- Segredos gerados pelo próprio app no primeiro start (par de chaves VAPID):
-- quem instala não configura nada, e o backup do banco leva junto.
CREATE TABLE IF NOT EXISTS app_secrets (
    name       TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Um registro por aparelho/navegador que ligou as notificações. O endpoint é do
-- serviço de push do navegador (Google, Mozilla, Apple, Microsoft).
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint     TEXT NOT NULL UNIQUE CHECK (char_length(endpoint) <= 1000),
    p256dh       TEXT NOT NULL CHECK (char_length(p256dh) <= 200),
    auth         TEXT NOT NULL CHECK (char_length(auth) <= 100),
    label        TEXT CHECK (label IS NULL OR char_length(label) <= 60),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_ok_at   TIMESTAMPTZ,
    failures     SMALLINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user ON push_subscriptions(user_id);

-- O que cada pessoa quer receber (sem linha = o padrão: tudo ligado, às 8h).
CREATE TABLE IF NOT EXISTS push_prefs (
    user_id      BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    routine      BOOLEAN NOT NULL DEFAULT true,   -- rotina na hora (repete até marcar)
    follow_up    BOOLEAN NOT NULL DEFAULT true,   -- de manhã: bloqueadas para cobrar hoje
    deadline     BOOLEAN NOT NULL DEFAULT true,   -- de manhã: atrasadas e o que vence hoje
    assigned     BOOLEAN NOT NULL DEFAULT true,   -- tarefa atribuída a você
    morning_hour SMALLINT NOT NULL DEFAULT 8 CHECK (morning_hour BETWEEN 0 AND 23),
    hide_content BOOLEAN NOT NULL DEFAULT false,  -- tela bloqueada: só o tipo, sem nomes
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Cada disparo agendado sai uma vez só (gravado antes de enviar).
CREATE TABLE IF NOT EXISTS push_log (
    user_id  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind     TEXT NOT NULL,
    ref      TEXT NOT NULL,
    ref_date DATE NOT NULL,
    sent_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, kind, ref, ref_date)
);

-- "Adiar 10 min" de uma rotina (na notificação ou no aviso da tela).
CREATE TABLE IF NOT EXISTS push_snooze (
    user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recurring_id BIGINT NOT NULL REFERENCES recurring_tasks(id) ON DELETE CASCADE,
    day          DATE NOT NULL,
    until        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id, recurring_id, day)
);
