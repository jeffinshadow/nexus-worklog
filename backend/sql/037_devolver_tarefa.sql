-- Devolver tarefa atribuída e o aviso de quem atribui no Hoje (01/11/2026).
-- Aditiva e idempotente: nada muda nos dados que já existem.
--
-- A devolução em si não precisa de tabela: a tarefa sai da conta de quem
-- recebeu como uma exclusão (lápide worklog.delete, desfazível) e quem atribuiu
-- ganha "assign.returned" no próprio histórico, com o motivo. Aqui só fica até
-- quando quem atribui já viu o aviso do Hoje ("Das que você atribuiu: 2
-- concluídas, 1 devolvida"): o que chegar depois disso entra no próximo aviso.
ALTER TABLE users ADD COLUMN IF NOT EXISTS assign_news_seen_at TIMESTAMPTZ;
