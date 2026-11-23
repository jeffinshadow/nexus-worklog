# p08-atribuir: atribuição e devolução

Branch `lab/p08-atribuir`. Arquivos: `backend/app/routers/assign.py`, `web/static/js/devolver.js`,
`backend/tests/test_aud_p08.py`. Sem migration (a 048 reservada não foi usada), sem dependência nova,
sem rota nova.

## O que mudou

- **Devolver, cancelar e alterar são tudo ou nada** (`return_task`, `cancel_sent`, `update_sent` em
  `db.transaction()`); e-mail e push saem depois do bloco.
- **Devolver com horas de outra pessoa: 409** ("esta tarefa guarda horas de quem a passou para você; conclua em
  vez de devolver"). A tarefa é travada (`FOR UPDATE`) no começo da transação.
- **Lápide da devolução** (`worklog.delete`, `before.children.time[]`): cada apontamento leva `user_id`
  (contrato com p03/p09).
- **Devolver com cronômetro rodando**: `stop_timer_of` antes de apagar, dentro da transação; o apontamento
  entra na lápide e volta com o desfazer.
- **`GET /api/assign/people`**: admin só é tratado como admin pelo app (`actor == "web"`); por chave de API
  vale a visão do papel Manda tarefas. Para quem não é admin, conta bloqueada ou com convite pendente não
  entra mais como `{"accepts": false}`.
- **`GET /api/assign/sent`**: com `same_team` falso, `description` e `blocked_reason` vêm `null`. Conta de
  destino excluída: `to_name` = "conta excluída", `to_email` = `null`, `ended.reason` = `null` (o `audit_log`
  não é reescrito). O mesmo em `open_returns()` (usado por "Precisa de atenção" em `viewer.py`).
- **`PATCH /api/assign/{id}`**: além do escopo, exige `can_receive`; aceite desligado ou conta bloqueada = 403
  (`NOT_RECEIVING_MSG`). O cancelar continua só com `in_scope`.
- **A mesma devolução só é decidida uma vez**: `assign` com `from_return` e `close_return` travam a linha
  `assign.returned` (`_lock_open_return`) e conferem de novo dentro da transação.
- **Limite**: 20 atribuições por par atribuidor+destinatário a cada 10 min; a 21ª responde 429 com
  `Retry-After`. Vale para app, chave e MCP (todos passam por `assign()`).
- **Log**: falha de e-mail de atribuição registra `token_hash(to)[:12]`, não o endereço.
- **Diálogo Devolver**: quando a tarefa tem tempo, diz "Os N min apontados saem do seu registro."

## Atenção para quem integra

- **O limite não usa `RateLimiter` em memória**, e sim uma contagem das linhas `assign.send` do histórico de
  quem atribui (`_limit` em `assign.py`). Motivo: `conftest.py` zera os limitadores por nome e não podia ser
  editado; uma instância nova ficaria acumulando entre testes (os ids se repetem) e derrubaria a suíte. A
  contagem no banco também sobrevive a reinício. Se o integrador preferir `RateLimiter`, precisa incluir a
  instância na lista do `_banco_limpo`.
- **p09 (history.py)**: o desfazer da devolução ainda não trava a linha `assign.returned`; a corrida "desfazer
  × atribuir de novo" (concorrência #5, T22) só fecha quando o desfazer fizer o mesmo
  `SELECT 1 FROM audit_log WHERE id = <assign.returned> FOR UPDATE` e conferir `return_resolved` de novo.
- **p03 (worklog.py)**: o 409 de horas alheias vale aqui só para o devolver; a exclusão comum é do p03.
- **openapi**: nenhuma rota ou parâmetro novo; a docstring de `/assign/people` e `/assign/sent` mudou
  (se o `openapi.json` guarda descrições, regerar).
- **Docs para o dono atualizar** (não toquei): README (o que fica após excluir a conta), `docs/API.md` se
  cita o comportamento de `/assign/sent`, 429 em `POST /api/assign`.

## Não feito / limites conhecidos

- `/assign/sent` continua marcando `editable: true` para quem desligou o aceite (o `cancelable` deriva dele);
  a tela oferece "Alterar" e recebe o 403 com a explicação. Separar os dois campos mexeria em `atribuir.js`.
- Em devolução resolvida como "atribuída de novo a X", o nome de X (`ended.resolved.to`) continua vindo do
  histórico mesmo que X tenha excluído a conta.
- `web/static/js/atribuir.js` não precisou mudar.
