-- Chave "só registrar" e avisos de agenda no feed/webhooks. Aditivo e idempotente:
-- só alarga as listas aceitas (troca cada CHECK uma vez) e cria um índice.

-- api_tokens.scope 'append': cria, anota, aponta, marca e conclui; não altera
-- nem exclui (lista fechada de rotas em app/deps.py, APPEND_ROUTES).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'api_tokens_scope_check'
                      AND pg_get_constraintdef(oid) LIKE '%append%') THEN
        ALTER TABLE api_tokens DROP CONSTRAINT IF EXISTS api_tokens_scope_check;
        ALTER TABLE api_tokens ADD CONSTRAINT api_tokens_scope_check
            CHECK (scope IN ('read', 'write', 'append'));
    END IF;
END $$;

-- audit_log.actor 'system': avisos de agenda gravados pelo agendador
-- (followup.due, recurring.due, renewal.warning; app/agenda.py). Saem no feed
-- (GET /api/history?after=) e nos webhooks; a tela de Histórico não mostra.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'audit_log_actor_check'
                      AND pg_get_constraintdef(oid) LIKE '%system%') THEN
        ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_actor_check;
        ALTER TABLE audit_log ADD CONSTRAINT audit_log_actor_check
            CHECK (actor IN ('web', 'api', 'mcp', 'admin', 'system'));
    END IF;
END $$;

-- Uma vez por ocorrência (item + dia), mesmo com o backend reiniciando ou dois
-- processos juntos: o INSERT do agendador usa ON CONFLICT neste índice.
CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_agenda
    ON audit_log (user_id, action, entity_id, (after->>'occurrence'))
    WHERE actor = 'system';
