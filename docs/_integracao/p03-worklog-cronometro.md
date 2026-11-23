# p03-worklog-cronometro: notas para a integração

Branch `lab/p03-worklog-cronometro`. Arquivos: `backend/app/routers/worklog.py`, `backend/app/routers/timer.py`,
`backend/app/audit.py`, `backend/tests/test_aud_p03.py`. Sem migration (a 047 reservada não foi usada), sem
dependência nova, nada em `web/`.

**Fora da lista de arquivos do pacote (uma linha):** `backend/tests/test_entrega7_retroativo.py:97` comparava a
resposta de `external_ref` repetido com `{"id", "existing"}` exato; o item do `external_ref` pede o campo `status` nessa
resposta, então a comparação ganhou `"status": "todo"`. Se outro pacote mexer na mesma linha, vale a versão com `status`.

## Linhas para o CHANGELOG

- Excluir uma tarefa que veio de outra pessoa (transferência) e guarda horas dela agora é recusado (409, "esta tarefa
  guarda horas de quem a passou para você; conclua em vez de excluir"): antes as horas sumiam do relatório de quem saiu.
  Excluir tarefa só com tempo próprio continua igual.
- A cópia da tarefa excluída (histórico, para o desfazer) guarda de quem é cada apontamento (`user_id`).
- Concluir (`POST /api/worklog/{id}/finish` e `PATCH` com `status: done`) devolve `stopped`, no mesmo formato de
  `POST /api/timer/stop`: o apontamento do cronômetro que rodava na tarefa, `null`, ou `needs_review` quando o
  cronômetro estava esquecido há mais de 12 h (parou sem apontar).
- Concluir de novo com a mesma solução ou a mesma data não grava outro evento nem avisa de novo (`existing: true`),
  também para a chave "só registrar" (antes: 403 na repetição). Toques simultâneos geram um evento só.
- Excluir a tarefa com o cronômetro rodando nela para e aponta o tempo antes (o tempo volta no desfazer).
- Iniciar o cronômetro ao mesmo tempo em que a tarefa é concluída em outro aparelho não deixa mais a tarefa "em
  andamento" com data de conclusão.
- Cronômetro: meio minuto exato arredonda para cima (150 s = 3 min).
- Chave "só registrar": `at` com mais de 5 min de atraso em `POST /api/timer/start` e `/stop` é recusado (403); parar
  com `at` igual ao início transformava horas em 1 min.
- Duas edições da mesma tarefa no mesmo instante gravam o antes/depois certo no histórico.
- `created_at`/`completed_at` no ano 1 com fuso (ex.: `0001-01-01T00:00+14:00`) respondem 400 em vez de 500.
- Mensagem do limite de 60 dias na criação diz o caminho: criar com a data de hoje e apontar o tempo no dia certo.
- `POST /api/worklog` com `external_ref` já usado devolve também o `status` da tarefa; com `status: done` no corpo e a
  existente aberta, conclui (regra do finish, permitido à chave "só registrar") e devolve `stopped`. Sem `status` no
  corpo, nada muda. Não reabre.

## Contratos com outros pacotes

- **p13 (front):** `stopped` vem sempre em `finish` e no `PATCH /api/worklog/{id}` (`null` quando não havia cronômetro
  na tarefa ou o status enviado não foi `done`). `finish` idempotente responde `{ok, existing: true, completed_at,
  stopped: null}`. No `POST /api/worklog` com `external_ref` existente, `stopped` só aparece quando a chamada concluiu.
- **p08/p09:** lápide de `worklog.delete`: `before.children.time[*].user_id` (inteiro). Com o 409, toda lápide nova só
  tem apontamentos do dono; o campo existe para a devolução (p08) e o desfazer (p09).
- `audit.worklog_snapshot(task_id, user_id, lock=False)`: `lock=True` faz `FOR NO KEY UPDATE` (só dentro de
  `db.transaction()`). NO KEY UPDATE de propósito: `FOR UPDATE` brigaria com o INSERT de apontamento (chave
  estrangeira) e daria impasse entre "parar o cronômetro" e "concluir" simultâneos.
- `worklog.stop_timer_of` passou a devolver o `stopped` (antes `None`).

## Pendências e avisos

- **MCP (lido, não alterado; é do p10):** `t_complete_task` (`mcp.py`, perto da linha 459) e `t_update_task` ignoram
  `res["stopped"]`. Com cronômetro esquecido, a IA responde "Concluída" sem dizer que o tempo não foi apontado. O dado
  já está em `res["stopped"]["needs_review"]`; falta a frase (como já existe em `t_stop_timer`). `t_create_task` com
  `external_ref` existente também não mostra o `status` novo.
- **`docs/API.md` e `docs/openapi.json` não foram editados** (fora da lista): faltam `stopped` nas linhas de
  `finish`/`PATCH`, o `status` e o "status done conclui" na linha do `POST /` (e na receita perto da linha 620), o 409 da
  exclusão, a regra dos 5 min do `at` para a chave "só registrar" e a idempotência por mesma solução/data.
- Idempotência do finish por data: compara o instante resolvido. `completed_at` só com a data de **hoje** resolve para
  "agora" e continua sendo edição (403 para a chave "só registrar"), como antes.
- O 409 da exclusão também impede quem recebeu de se livrar da tarefa transferida (só concluir); excluir a conta de quem
  recebeu ainda apaga as horas de quem saiu em cascata (ressalva do revisor em pentest-autorizacao #2, fora do pacote).
- `finish`, `PATCH` e `start` agora seguram uma conexão em transação do começo ao fim (com a linha travada). O aviso a
  quem atribuiu continua saindo depois de gravar.
- Não feito, de propósito (instruções): CHECK status/completed_at, trava do teto de 24 h, reopen por `external_ref`.
- O teste da edição simultânea usa barreira de threads: garante o encadeamento antes/depois, mas a janela é de
  milissegundos; não medi quantas vezes ele falharia sem a trava.
