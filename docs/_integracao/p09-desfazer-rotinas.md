# p09-desfazer-rotinas: notas para o integrador

Branch `lab/p09-desfazer-rotinas`. Arquivos: `backend/app/routers/history.py`, `recurring.py`, `projects.py`,
`backend/tests/test_aud_p09.py`. Sem migration (a 049 reservada não foi usada), sem dependência nova, sem rota nem
parâmetro novo (o `docs/openapi.json` não deve mudar), nada em `web/`.

## O que mudou no comportamento

Regra geral aplicada: o desfazer nunca responde ok sem ter mudado alguma coisa.

| Item | Antes | Agora |
|---|---|---|
| qa-funcional #1 | desfazer "editou a rotina" depois da troca de agenda reativava a antiga (duas ativas) | 409 "a agenda desta rotina foi trocada depois; desfaça a troca primeiro"; `can_undo=false` na lista |
| qa-funcional #2/#3 (marcação) | desfazer "marcou a rotina" depois da troca: 200 sem mudar nada | 409 (mesma frase) quando a rotina está encerrada e o dia é o da troca ou posterior, com `can_undo=false`; 409 "a rotina já não está marcada nesse dia" quando o DELETE não apaga linha |
| arquitetura-backend #3 | desfazer a troca criada pelos dias úteis devolvia a rotina `daily` (+8 faltas no passado) | o retrato da troca já sai congelado (`{**before, **freeze}`): a antiga volta semanal com os dias antigos |
| concorrencia #4 (metade) | duas trocas de agenda simultâneas = duas rotinas novas | `UPDATE ... AND active`; sem linha alterada, 409 "a rotina já foi alterada em outro lugar" |
| concorrencia #9 | "Retomar" encerrava só a pausa mais recente | encerra todas as que cobrem hoje |
| concorrencia #10 / qa #10 | toggle repetido gravava histórico em dobro ou contrário ao estado | o toggle trava a rotina (`FOR UPDATE`, numa transação) e a linha do histórico sai do que o `INSERT ... RETURNING (xmax = 0)` ou o `DELETE` mudou; nada mudou = não grava |
| qa-funcional #8 | desfazer exclusão de projeto não religava vencimentos, modelos e o projeto padrão | a lápide guarda `renewal_ids`, `template_ids`, `was_default`; o desfazer religa só os que continuam sem projeto (e o padrão só se continua vazio) |
| pentest-autorizacao #2 / concorrencia #1 (complemento) | `_put_time` restaurava todo apontamento com o uid de quem desfaz | usa o `user_id` de cada apontamento da lápide; sem o campo (lápide antiga), o uid de quem desfaz |
| concorrencia #5 (desfazer) | conferia `return_resolved` sem trava | trava as linhas `assign.returned` da tarefa no histórico de quem atribuiu (`FOR UPDATE`) e só então confere |
| concorrencia #7 (parte) | desfazer que devolve a tarefa a "concluída" deixava o cronômetro rodando | para o cronômetro e aponta o tempo (`timer.stop_running`, como o concluir faz) |
| privacidade-lgpd #11 | chave de API e MCP liam as linhas de ator `admin` | `list_history` e o feed (`?after=`) filtram `actor <> 'admin'` quando `user.actor != 'web'` |
| testes-qualidade #6 | ramos do desfazer sem teste | tabela de 26 ações com o alvo apagado (409 e banco idêntico) e a janela de 7 dias |

## Mudança de resposta de API (registrar no CHANGELOG e em docs/API.md)

- **Correção de privacidade:** `GET /api/history` (lista e feed `?after=`) e a ferramenta de histórico do MCP deixam de
  devolver, para chave de API e MCP, as linhas de ator `admin` (log de admin: "viu, como admin master, o quadro de
  fulano@…", convites, permissões). E-mails de terceiros iam ao provedor da IA. A sessão do próprio admin no app
  continua vendo tudo. O `X-Total-Count` acompanha o filtro. Os webhooks NÃO foram mexidos (o envio fica fora dos
  arquivos deste pacote): se o webhook de um admin entrega linhas de ator `admin`, continua entregando.
- Novos 409 no `POST /api/history/{id}/undo`, onde antes vinha 200 sem efeito (ou 500): alvo que não existe mais em
  `worklog.create`, `recurring.update/deactivate/replace/pause/resume/toggle`, `objective.create`, `objective.order`
  (projeto sem objetivos), `project.create`, `project.update`.
- `PATCH /api/recurring/{id}` pode responder 409 "a rotina já foi alterada em outro lugar" (antes criava outra rotina).
  `auth.py` (`save_settings`, do p01) chama `replace_routine` num laço: com o `FOR UPDATE` do p01 na conta, o 409 não
  deve aparecer ali; sem ele, a segunda chamada simultânea agora falha com 409 em vez de duplicar as rotinas.

## Dependências entre pacotes

- **p03/p08 (lápide com `user_id` por apontamento):** o `_put_time` já lê `children.time[i].user_id`. Enquanto eles não
  gravarem o campo, o comportamento é o antigo. Decisão minha, fora do texto do pacote: quando o `user_id` gravado é de
  uma conta que não existe mais, o apontamento NÃO é restaurado (não passa as horas para quem desfaz; a FK impediria o
  dono original). O teto de 24 h do dia só confere os apontamentos de quem desfaz.
- **p08 (`assign.py`):** a trava do desfazer só fecha a corrida se "atribuir de novo" e "encerrar" travarem a MESMA
  linha: `audit_log` com `user_id = quem atribuiu`, `action = 'assign.returned'`, `entity = 'assignment'`,
  `entity_id = tarefa`. Eu travo todas as que casam (em ordem de id). Sem o lado do p08, a corrida continua.
- **p03 (`timer.py`):** uso `stop_running(user, only_task=...)` como está na main; se a assinatura mudar, ajustar a
  chamada em `history.py` (ramo `worklog.update/finish/assign_update`).
- `history.feed()` ganhou o parâmetro opcional `admin_log=True` (quem chama sem ele não muda).

## Efeitos colaterais conhecidos

- Depois de desfazer a troca de agenda criada pelos dias úteis, a rotina fica semanal com os dias antigos (aceito pelo
  revisor); os dias úteis da conta continuam os novos.
- O toggle agora abre transação e trava a linha da rotina: toggles simultâneos da mesma rotina entram em fila.
- "Retomar" grava no histórico só a pausa mais recente (como antes); desfazer o "Retomar" reabre só essa.
