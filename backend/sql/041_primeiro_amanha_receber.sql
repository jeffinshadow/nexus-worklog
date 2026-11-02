-- "Primeiro amanhã" (até 3 tarefas para começar o próximo dia útil) e a opção
-- "Receber tarefas atribuídas" em Admin › Para empresas e instituições.
-- Aditiva e idempotente (roda a cada inicialização): nada que já existe muda.

-- Primeiro amanhã: o dia em que a tarefa abre o Hoje (no topo das abertas,
-- com um selo). Passado esse dia, a marca para de valer sozinha (nada apaga).
ALTER TABLE worklog_tasks ADD COLUMN IF NOT EXISTS first_on DATE;
CREATE INDEX IF NOT EXISTS worklog_tasks_first_on_idx ON worklog_tasks (user_id, first_on)
    WHERE first_on IS NOT NULL;

-- Receber tarefas atribuídas: 'self' = cada pessoa escolhe (users.accepts_assignments_at,
-- como sempre); 'all' = todo Usuário recebe de quem tem o papel "Manda tarefas",
-- sem poder desligar. As escolhas individuais continuam guardadas: voltar para
-- 'self' as devolve.
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS assign_receive TEXT NOT NULL DEFAULT 'self'
    CHECK (assign_receive IN ('self', 'all'));
-- Desde quando está em 'all' (o aviso único de quem já usa compara com isto).
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS assign_receive_since TIMESTAMPTZ;
-- Quando a pessoa tocou "Entendi" no aviso (ou passou por ele no tour).
ALTER TABLE users ADD COLUMN IF NOT EXISTS assign_notice_at TIMESTAMPTZ;
