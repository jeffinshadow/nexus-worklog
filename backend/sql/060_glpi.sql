-- Integração com o GLPI (app/glpi.py): o chamado aberto no nome da pessoa vira
-- tarefa; a tarefa concluída vira a solução do chamado. Aditivo e idempotente.

-- Instância: onde fica o GLPI (só o admin define) e o App-Token do cliente de
-- API de lá (opcional; guardado cifrado, nunca devolvido pela API).
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS glpi_url TEXT
    CHECK (glpi_url IS NULL OR char_length(glpi_url) <= 300);
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS glpi_app_token TEXT;

-- Pessoa: o token dela no GLPI (cifrado com chave derivada do SECRET_KEY;
-- nunca devolvido) e o estado da sincronização. failures >= 5 = pausada.
CREATE TABLE IF NOT EXISTS glpi_accounts (
    user_id         BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    token           TEXT NOT NULL,
    glpi_name       TEXT,
    last_sync_at    TIMESTAMPTZ,
    failures        INT NOT NULL DEFAULT 0,
    last_error      TEXT,
    next_attempt_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Vínculo chamado -> tarefa, gravado SÓ pela sincronização (nunca pelo
-- external_ref que uma chave de API pode escolher): é ele que autoriza mandar a
-- solução. Chamado já importado não volta, mesmo com a tarefa excluída
-- (task_id nulo). sent_at = solução enviada (ou o chamado já estava solucionado).
CREATE TABLE IF NOT EXISTS glpi_tickets (
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticket_id  BIGINT NOT NULL,
    task_id    BIGINT REFERENCES worklog_tasks(id) ON DELETE SET NULL,
    sent_at    TIMESTAMPTZ,
    tries      INT NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, ticket_id)
);
CREATE INDEX IF NOT EXISTS idx_glpi_tickets_task ON glpi_tickets(task_id);
