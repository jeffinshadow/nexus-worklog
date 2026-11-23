# p12: agendador, e-mail, pedido de convite, Saúde, ordenação com acentos e código morto

Branch `lab/p12-agendador-email-convite`. Sem migration (a 051 reservada não foi usada), sem dependência nova, sem opção nova.

## O que mudou

| Item | Onde | Resumo |
|---|---|---|
| Passada: push e agenda antes do e-mail | `notify.py` (`_pass`) | A passada virou `_pass(now, agenda, push)`: `push.run_once`, `agenda.run_once`, depois o e-mail (com SMTP), e na hora cheia a faxina das fotos e a do banco. O `now` é o de antes, como já era. |
| Tempo de conexão do SMTP | `mailer.py` | 5 s para conectar, TLS e login (`CONNECT_TIMEOUT`); 20 s para a entrega (`TALK_TIMEOUT`). |
| E-mail que não saiu é tentado de novo | `mailer.py`, `notify.py` | `mailer.MailNotSent` (subclasse de `MailError`): falha antes do `send_message`, menos senha recusada. `notify.deliver` apaga a reserva e devolve `"retry"`; a próxima passada tenta, dentro das 2 h. Falha a partir do `send_message` continua `MailError` e não reenvia. O erro segue em `mailer.last`. |
| Faxina de hora em hora | `notify.py` (`faxina`), `routers/auth.py` | Os 4 `DELETE` do login foram para `notify.faxina()`, mais `notification_log` com mais de 30 dias (por `sent_at`). Roda no minuto 0, mesmo sem SMTP. O login só chama a faxina com `MAIL_SCHEDULER=false`. |
| Assunto numa linha | `mailer.py` | `" ".join(subject.split())`. |
| Pedido de convite: texto fixo | `routers/invite_requests.py` | E-mail e push aos admins: "Chegou um pedido de convite. Veja em Admin." e o endereço de quem pediu. Nome, origem e motivo só no app. O dicionário `SOURCES` ficou sem uso e saiu. |
| Dois admins no mesmo pedido | `routers/invite_requests.py` | `_decide(rid, "invited")` primeiro, na mesma `db.transaction()` de `invite_user`; o 409 de conta existente desfaz a decisão (o pedido volta a pendente e a linha do histórico não fica). |
| Saúde | `routers/saude.py`, `web/static/js/saude.js` | `version.number` (de `version.py`) e `scheduler_last_pass` (raiz da resposta; `null` antes da primeira passada). Linha "Agendador" na tela, com alerta acima de 5 min. |
| `done_limit=1` | `review.py`, `notify.py` | Os 4 chamadores de `get_board` que não leem as concluídas. |
| Ordem com acentos | `services.py`, `teams.py`, `routers/templates.py`, `me.py`, `search.py`, `equipes.py`, `admin.py`, `assign.py` | `ORDER BY nx_fold(...)` no lugar de `lower(...)`. |
| Código morto | `teams.py`, `routers/packs.py`, `services.py` | Saíram `teams.is_member`, `TER`, `QUA` e `task_retro_days()` (as 4 chamadas usam `TASK_RETRO_DAYS`). |

## Para o integrador

- **`docs/openapi.json`**: `GET /api/admin/health` não tem schema de resposta, então não deve mudar; se `test_openapi_em_dia` reclamar, é só regerar.
- **`CHANGELOG.md`** (não editei). Sugestão de texto: "Os avisos por e-mail que falham porque o servidor de e-mail estava fora do ar são tentados de novo nas passadas seguintes (até 2 h). Notificações dos aparelhos saem antes do e-mail. A faxina (sessões vencidas, histórico de 180 dias, links e avisos antigos) passou a rodar de hora em hora. O e-mail e a notificação do pedido de convite aos admins levam só um texto fixo e o endereço de quem pediu. Saúde do Nexus mostra o número da versão e a última passada do agendador. Listas em ordem alfabética não jogam mais os nomes com acento para o fim."
- **Mudança visível em API**: `notify.deliver` pode devolver `"retry"` (interno); o push do pedido de convite tem `body` fixo; a ordem de `GET /api/projects`, equipes, modelos e pessoas muda para nomes com acento.
- **`routers/worklog.py`** (fora da lista de arquivos do pacote) teve 2 linhas trocadas: o import e a chamada de `task_retro_days()` → `TASK_RETRO_DAYS`. Sem isso a remoção da função quebrava a rota. `routers/auth.py` e `routers/admin.py` tiveram a mesma troca, além do trecho da faxina (auth) e do `ORDER BY` (admin:69).
- **Conflitos prováveis**: `auth.py` (p01) no fim de `login`; `services.py` (p05) só nas linhas de `ORDER BY` e na função removida; `admin.py`, `me.py`, `equipes.py` (p02), `assign.py` (p08), `search.py` (p16): uma linha de `ORDER BY` em cada.
- **Documentação do usuário** (`docs/ADMIN.md`, se citar a faxina no login ou o conteúdo do e-mail de pedido de convite): não conferi nem editei.

## Não feito / ressalvas

- **Pedido de convite revela pelo tempo quem tem conta (pentest-autenticacao #6, metade): não feito.** Responder antes e gravar o pedido na thread quebraria os testes existentes que leem `GET /api/admin/invite-requests` logo depois do `POST` sem trocar `threading.Thread` (não posso editá-los), e a diferença medida pelo revisor é de ~3,5 ms.
- **`routers/viewer.py:157`** (sort em Python): não é de uma linha (precisa importar `labels.fold`); ficou como estava. O mesmo vale para `viewer.py:63`, `viewer.py:92` (`ORDER BY archived, lower(name)`) e `equipes.py:59`, que não estavam na lista.
- **O e-mail do convite ainda sai dentro da transação** em `POST /api/admin/invite-requests/{id}/invite`: quem envia é `admin.invite_user` → `_send_invite` (arquivo do p02), de forma síncrona. Consequências: a linha do pedido fica travada durante o SMTP (até 5 s de conexão), e se o `COMMIT` falhasse depois do envio a pessoa receberia um link sem conta. Para tirar, `invite_user` precisa separar "criar a conta" de "mandar o convite".
- Senha do SMTP recusada (`SMTPAuthenticationError`) NÃO é tentada de novo (revisão): fica como erro do dia em `notification_log`, como antes do pacote. Com outra falha permanente antes da entrega (servidor desligado de vez, certificado inválido), cada aviso é tentado a cada minuto durante as 2 h da janela, com uma linha de aviso no log por tentativa; nada fica em `notification_log` (o erro aparece na Saúde por `mailer.last`, que zera ao reiniciar).
- `scheduler_last_pass` é do processo (como `mailer.last`): com mais de um worker, cada um responderia o seu.
