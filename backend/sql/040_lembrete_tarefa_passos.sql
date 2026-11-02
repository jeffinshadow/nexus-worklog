-- Lembrete com hora na tarefa ("me lembra às 15h de ligar para a Ana") e
-- passos opcionais na rotina (ronda com itens). Aditiva e idempotente (roda a
-- cada inicialização): nada que já existe muda.

-- Lembrar em: o instante em que o Nexus avisa (na tela, com o app aberto, e
-- pela notificação do aparelho). Disparado, o campo fica (histórico).
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS remind_at TIMESTAMPTZ;
-- "Adiar 10 min": até quando o aviso espera (vale em todos os aparelhos).
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS remind_snoozed_until TIMESTAMPTZ;
-- "Ok" no aviso: já visto, não toca mais (mudar o horário volta a valer).
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS remind_seen_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS worklog_tasks_remind_idx ON worklog_tasks (user_id, remind_at)
    WHERE remind_at IS NOT NULL AND status <> 'done';

-- Passos da rotina (até 12): marcar a rotina conta uma vez; os passos não
-- feitos entram como texto na evidência.
ALTER TABLE recurring_tasks ADD COLUMN IF NOT EXISTS steps TEXT[];
