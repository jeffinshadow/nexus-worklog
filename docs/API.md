# Referência da API

API REST do Nexus Worklog, sob **`/api`**, mais o servidor MCP em
**`/mcp`**. O Swagger fica **desligado de propósito** no servidor — esta página é a
referência, e o contrato para máquina é o [`openapi.json`](openapi.json) versionado aqui
(conector personalizado do Power Automate, n8n, Make, geradores de cliente), gerado por
`tools/openapi.py` e conferido pelos testes. Campos e limites exatos de cada corpo: os
modelos Pydantic em `backend/app/schemas.py`. Corpos e respostas em JSON; datas
`AAAA-MM-DD` no fuso `APP_TZ`; timestamps ISO 8601 com fuso. Receitas prontas no fim:
[Integração passo a passo](#integração-passo-a-passo) e [avisos e planilha](#receitas-avisos-e-planilha).

## Autenticação

### Chave de API — para IA, scripts e automações

Crie em **Configurações > IA e API**. A chave (`nxs_…`) aparece **uma vez**; o
servidor guarda só o HMAC.

```
Authorization: Bearer nxs_...
```

- Sem cookie e sem CSRF. Escopo `write` (lê e altera) ou `read` (escrita → 403).
- Validade de 1 a 365 dias ou sem validade; revogável. 240 req/min por pessoa, somando as chaves (429).
- Trocar a própria senha (ou o reset pelo admin) revoga todas as chaves e o link do calendário.
- 429 e 503 trazem o header `Retry-After` (segundos).
- Uma chave **nunca** acessa `/api/admin/*`, `/api/viewer/*`, `/api/tokens`, `/api/calendar`,
  `/api/notifications` nem troca senha ou exclui a conta. Atribuir tarefas por chave
  (`/api/assign`, MCP `assign_task`) exige o papel de atribuidor e escopo `write`. Tudo o que ela fizer vai para o
  histórico com o nome dela.

### Sessão do app — o que o frontend usa

- Cookie `__Host-session` (`session` sem HTTPS, em desenvolvimento) `HttpOnly; Secure; SameSite=Strict`, prazo fixo de
  `SESSION_TTL_DAYS` (padrão 7); depois disso, novo login.
- O login e `GET /api/auth/me` devolvem `csrf_token`; **toda mutação** exige o
  header `X-CSRF-Token` (senão 403).

**Papéis** (acumuláveis, em `roles` no `/api/auth/me`): `user` (o próprio registro),
`admin` (contas, permissões, configurações), `assigner` ("Manda tarefas", na tela Equipe: botão Atribuir tarefa e Tarefas que atribuí) e `viewer` ("Vê a equipe", tela Equipe:
registros e relatórios de quem aceitou, `PUT /api/me/viewers`). Todo dado é filtrado por `user_id`; `/api/admin/*`
e `/api/viewer/*` exigem o papel com sessão do app.

| Código | Quando |
| --- | --- |
| 400 | regra de negócio (ex.: dia fora da janela, nada a atualizar) |
| 401 | sem sessão/chave válida |
| 403 | CSRF, troca de senha pendente, chave em rota só do app, não-admin |
| 404 | não existe ou não é seu |
| 409 | conflito (nome repetido, desfazer fora de ordem, tarefa com filhos) |
| 422 | corpo inválido |
| 410 | cursor do feed (`/api/history?after=`) mais antigo que o histórico guardado |
| 413 / 415 | logo grande demais / tipo de arquivo não aceito |
| 429 | limite de tentativas/requisições (login, troca de senha, chave, PDF, teste de e-mail, feed ICS); com `Retry-After` |
| 502 / 503 | envio de e-mail falhou / e-mail não configurado ou servidor ocupado (pool ou consulta acima do limite); 503 com `Retry-After` |

### Erros

Todo erro vem como JSON com `detail`, em duas formas:

- **regra** (400, 401, 403, 404, 409, 410, 429, 503...): `detail` é uma **frase** em português, para mostrar a quem usa.
  `{"detail": "não encontrado"}`
- **validação** (422, corpo ou parâmetro fora do formato): `detail` é uma **lista** no formato do Pydantic
  (`loc` = onde, `msg` = o quê, em inglês). `{"detail": [{"type": "string_too_short", "loc": ["body", "title"], "msg": "String should have at least 1 character", ...}]}`

Para automação: 4xx = corrija a chamada (não adianta repetir igual), exceto 429; 429 e 503 trazem
`Retry-After` (segundos) — espere esse tempo e repita; 5xx sem `Retry-After` = tente mais tarde com
espera crescente. Escrita repetida por timeout não duplica com `external_ref` (tarefas, projetos,
anotações e apontamentos).

### Páginas (listas grandes)

As listas que crescem aceitam `limit` + `offset` e trazem o total no cabeçalho **`X-Total-Count`**; o
corpo continua sendo a mesma lista, então chamar sem esses parâmetros devolve o mesmo de antes. A ordem
termina sempre no `id` (um item nunca aparece em duas páginas) e um `offset` além do fim devolve lista
vazia (não erro). Página N com tamanho T: `offset = (N − 1) × T`. Rotas: `GET /api/history`,
`GET /api/worklog`, `GET /api/projects/{id}/done`. Onde a resposta é um objeto, o total vem no corpo:
`GET /api/board` (`done_offset`, `done_limit`, `done_total`) e `GET /api/search` (`offset`/`limit` das
tarefas, `rec_offset`/`proj_offset`/`side_limit` de rotinas e projetos; `total_tasks`, `total_recurring`,
`total_projects`; o cabeçalho traz `total_tasks`).

Legenda: **S** = só sessão do app · **W** = exige escopo `write` (chave) ou CSRF (sessão).

## Conta — `/api/auth`

| Rota | | Corpo / observação |
| --- | --- | --- |
| `POST /login` | público | `{email, password}` → identidade + `csrf_token`; limite por IP e por e-mail (falhas) |
| `POST /logout` | S W | |
| `GET /sessions` | S | `{others}` — quantas outras sessões (aparelhos, navegadores) estão abertas |
| `POST /logout-others` | S W | sai dos outros aparelhos sem trocar a senha: encerra as outras sessões e mantém esta; chaves de API e calendário não mudam. `{ok, ended}`; vai para o histórico (`sessions.logout_others`) |
| `GET /me` | | `{id, email, display_name, name, avatar, assistant, role, roles, retro_days, support_contact, accepts_assignments_at, viewers_allowed, ticket_url, ticket_url_managed, must_change_password, work_days, tz, org, tour_required, visibility_notice, role_notice, email_pending, csrf_token}` — `name` é o de exibição ou, sem ele, o derivado do e-mail; `role` só espelha `admin` (compatibilidade). `org` = `{team_visibility, identity_managed}` (Admin › Para empresas); `tour_required` = esta conta (nova) está no primeiro acesso: o tour é obrigatório para toda conta nova até concluir (contas que já existiam antes de 01/11 nunca são forçadas); `visibility_notice` = falta o aviso único de "visível para quem gerencia"; `role_notice` = `{added, removed}` papéis que o admin deu ou tirou e a pessoa ainda não viu (ou `null`); `email_pending` = e-mail novo aguardando confirmação; `ticket_url` = o endereço do sistema de chamados que vale para esta pessoa: o da instância (Admin › Para empresas), se definido (`ticket_url_managed: true`), senão o dela |
| `GET /options` | público | `{email, invite_request}` — o que a tela de login oferece: "Esqueci a senha" (com e-mail no servidor) e "Solicitar convite" (com e-mail e se o admin não o desligou em Para empresas) |
| `POST /invite-request` | público | `{name, email, source: "colega"\|"empresa"\|"internet"\|"outro", source_note?, reason}` → 202 sempre (não revela contas); 404 quando o pedido está fora (sem e-mail ou desligado pelo admin) |
| `POST /email/confirm` | público | `{token}` (do link `#email=` mandado ao endereço novo) → `{ok, email}`; 24 h, uso único; avisa o endereço antigo; 409 se o e-mail virou de outra conta, 403 se a administração passou a definir os e-mails |
| `POST /change-password` | S W | `{current_password, new_password}`; encerra as outras sessões e revoga chaves e calendário |
| `POST /settings` | W | `{work_days}` — máscara, domingo = bit 0 (seg–sex = 62). Não reescreve o passado: rotinas "dias úteis" com história são encerradas com os dias antigos e recomeçam hoje; não se desfaz pelo histórico |

## Passkeys — `/api/auth/passkeys`

| Rota | | Corpo |
| --- | --- | --- |
| `GET /` | S | as passkeys da conta (nome, sincronizada, criada, último uso) |
| `POST /register/options` · `POST /register` | S W | opções do WebAuthn (passkey residente, verificação do usuário obrigatória) e depois `{challenge_id, credential, name?}`; até 10 por conta |
| `DELETE /{id}` | S W | remove (entra no histórico) |
| `POST /login/options` · `POST /login` | público | `{challenge_id, credential}` → a mesma sessão do login por senha; mesmo limite de tentativas |

Presas ao domínio do `APP_URL` (a criada na homologação não vale em produção);
o banco guarda só a chave pública e o contador. Reset de senha pelo admin
apaga as passkeys da conta; "Esqueci a senha" mantém e avisa por e-mail.

## Perfil e assistente — `/api/me` (só pelo app)

| Rota | | Corpo / observação |
| --- | --- | --- |
| `PUT /profile` | S W | `{display_name}` (até 60; vazio = volta ao nome do e-mail); 403 com o motivo quando "Nome e e-mail definidos pela administração" está ligado |
| `POST /email` | S W | `{new_email, password}` → `{email_pending}` — pede a troca do próprio e-mail: senha atual, e-mail único, link de confirmação ao endereço NOVO (24 h, uso único; só troca ao confirmar em `POST /api/auth/email/confirm`). 400 sem servidor de e-mail; 403 quando a administração define nome e e-mail |
| `DELETE /email` | S W | desiste da troca pendente (o link deixa de valer) |
| `PUT /tour` | S W | `{done}` — tour visto (`false` = abre de novo). Concluir encerra o primeiro acesso (o tour obrigatório nunca mais força a conta) e conta como visto o aviso de visibilidade → `{tour_done_at, tour_required, visibility_notice}` |
| `PUT /visibility-notice` | S W | "Entendi" no aviso único de "visível para quem gerencia" |
| `PUT /role-notice` | S W | "Entendi" no aviso único de papel ganho ou retirado → `{role_notice: null}` |
| `POST /avatar` · `DELETE /avatar` | S W | corpo bruto PNG, JPEG ou WebP até 256 KB (tipo pelo conteúdo; SVG não). O app recorta e reduz antes |
| `GET /avatar/{user_id}?v=` | S | a própria foto; o admin vê a de todos; o atribuidor, a de quem aceitou receber tarefas (e não está bloqueado); o visualizador, a de quem aceitou ser visto; o resto 404 |
| `PUT /assistant` | S W | `{enabled, idle_on, idle_minutes (5–480), idle_start, idle_end, reopen_on, reopen_minutes (1–240), summary_from, stale_days (1–60, padrão 5)}` — janela em minutos do dia; `stale_days`: tarefa aguardando há tantos dias sem dia para cobrar ganha a pergunta "quer marcar quando cobrar?" (no Hoje sempre; no aviso da manhã, no dia N e de 7 em 7) |
| `GET /visibility` | S | `[{name, roles}]`: quem, além de você, tem papel `viewer` ou `admin` (a linha "Quem pode ver seu registro" em Conta; o visualizador só vê se `viewers_allowed`) |
| `GET /activity` | S | `{last_activity, timer}`: último registro de qualquer origem (tarefa, rotina, anotação, checklist, tempo, cronômetro) e o cronômetro rodando |
| `PUT /tickets` | S W | `{ticket_url}` — endereço do sistema de chamados da pessoa; `{id}` vira o número (sem `{id}`, vai no fim) → `{ticket_url, ticket_url_managed}`. Com o endereço definido pela administração (`PUT /admin/org`), 409 com o motivo; o da pessoa fica guardado e volta a valer quando o admin esvazia o global |
| `PUT /assignments` | S W | `{accept}` — aceitar receber tarefas de um atribuidor (desligar não mexe nas recebidas) |
| `PUT /viewers` | S W | `{accept}` → `{viewers_allowed}` — permitir que quem tem o papel "Vê a equipe" (`viewer`) veja seu registro (quadro, números, PDF, horas, fotos). Contas novas começam com `false`; vai ao histórico (`viewers.consent`). Com a instância em "Visível para quem gerencia": 409 com o motivo, e a escolha guardada não muda (volta a valer quando o admin voltar para "Cada pessoa escolhe") |
| `POST /delete` | S W | `{password}` — exclui a conta e todos os dados dela; o último admin não sai |

## Cronômetro e modelos

| Rota | | Corpo / observação |
| --- | --- | --- |
| `GET /api/timer` | | `{timer}`: `{task_id, title, started_at}` ou null (um por pessoa, vale em qualquer aparelho) |
| `POST /api/timer/start` | W | `{task_id, at?}` — `at` = hora em que iniciou no aparelho (feito sem sinal, até 24 h atrás); tarefa aberta; se outro estiver rodando, ele para e aponta (`stopped`, mesma regra do stop). "A fazer" vira "em andamento". `at` que cai em cima de tempo de cronômetro já apontado (outro aparelho parou depois) → 409, nada muda |
| `POST /api/timer/stop` | W | `{at?}` (hora em que parou, sem sinal) — para e aponta o tempo (nota "cronômetro", no dia em que começou), só o que ainda cabe nas 24 h daquele dia; dia cheio = `stopped: null` (para assim mesmo). Concluir a tarefa também para |
| `DELETE /api/timer` | W | descarta sem apontar |
| `GET /api/templates` · `POST` · `PUT /{id}` · `DELETE /{id}` | (W) | `{name, title, description, priority, project_id, after_hours, checklist: [itens]}` — até 50 modelos, 30 itens |
| `POST /api/templates/{id}/use` | W | cria a tarefa do modelo, com o checklist |

## Hoje e quadro

| Rota | | Observação |
| --- | --- | --- |
| `GET /api/board?day=&project=&done_offset=&done_limit=` | | `day` até 7 dias atrás (padrão hoje); `project` filtra as tarefas (`0` = sem projeto). Devolve `recurring` (com `due`, `done_today`, `note` = evidência do dia, `require_note`, agenda), `in_progress` (tarefas abertas: a fazer, em andamento, aguardando (`blocked`); com `touched_at`, o último movimento, e `blocked_reason`/`blocked_at`/`follow_up_on`), `timer`, `done` (as concluídas mais recentes: `done_limit`, padrão e máximo 200, a partir de `done_offset`), `done_total` (todas as concluídas, com o mesmo filtro), `day`, `today`, `min_day`, `work_day` |
| `GET /api/summary` | | `last_day` (do último dia útil até ontem), `week` (com `previous` = mesmos dias da semana passada) e `today_stats` (o dia de hoje): rotinas, tarefas concluídas, minutos, por projeto, rotinas não feitas; `review` (para o assistente): `invite` (hoje é o último dia útil da semana e a revisão não foi feita nem dispensada), `reviewed`, `stale_days` e `stale` (aguardando há `stale_days` dias ou mais sem `follow_up_on`: `id`, `title`, `blocked_reason`, `days`); só para quem tem o papel de atribuidor, `assigned_news` (`null` sem novidade, ou `{since, done, returned}`: das que atribuiu, quantas foram concluídas e quantas devolvidas — ainda sem decisão — desde o último aviso visto; na primeira vez, os últimos 7 dias) |
| `GET /api/review/week` | | revisão da semana atual (domingo a sábado): `done` (concluídas na semana, com `resolution`), `open` e `waiting` (abertas e aguardando, com `waiting_days` e `follow_up_on`), `suggestions` (até 3 ids para a próxima semana, na ordem do Hoje), `review_day` (último dia útil da semana) e `is_review_day`, `done_at`/`dismissed_at` (revisão feita / convite dispensado), `stale_days` e `stale` |
| `POST /api/review/week/done` | W | `{next: [até 3 ids]}` (opcional, as prioridades da próxima semana) — registra a revisão (o assistente para de convidar) e devolve `{done_at, text}`: o texto da semana pronto para copiar |
| `POST /api/review/week/dismiss` | W | "Agora não" no convite do assistente: não volta nesta semana |
| `GET /api/summary/handoff` | | `{text}` — passagem de turno: em aberto, aguardando com o quê, há quantos dias e o dia de cobrar, concluídas nas últimas 12 h (plantão marcado), rotinas pendentes e vencimentos no aviso |
| `GET /api/dashboard?month=AAAA-MM` | | retrospectiva: `heatmap` (4 semanas), `task_adherence` (30 dias, a mais pulada primeiro), `throughput`, `projects` (tempo, 30 dias), `backlog`, `months` (do mais recente ao primeiro registro). Com `month` (Meu mês), as janelas são o mês (o corrente até hoje) e vem `overview`: `month` e `previous` (o mês anterior inteiro, ou `null` antes do primeiro registro) com `recurring_done`, `recurring_total`, `pontual_done`, `minutes` — os mesmos números do PDF do período —, `routines` (rotinas com dia previsto), `routines_full` (as feitas em todos os dias previstos), `trend` (até 6 meses, do mais antigo ao escolhido, só desde o primeiro registro: `month` + os mesmos 4 números, mês a mês como no PDF; o último traz `now`), `average` (`months`, `recurring_pct`, `pontual_done`, `minutes` por mês e `scale`: a média dos meses anteriores da série, sem o primeiro se começou no meio dele; `null` com menos de 2) e `compare` (`routines`, `tasks`, `minutes`: `"acima"`, `"na média"`, `"abaixo"` ou `null`; faixa: 5 pontos percentuais nas rotinas, 15% nas tarefas e horas com mínimo de 1 tarefa e 60 min; no mês corrente compara com a média × `scale` = dias passados / dias do mês, e só a partir do 7º dia), `weeks` (domingo a sábado, cortadas no mês: `start`, `end`, `pontual_done`, `minutes`), `days` (um por dia até hoje: `date`, `due`, `done`, `extra`, `paused`, `pontual_done`, `minutes`), `behind` (até 5 rotinas com dias feitos < previstos: `label`, `done`, `due`; vazio na visão da Equipe), `projects` (`name`, `color`, `icon`, `minutes`), `multi_project` e `deliveries` (as concluídas, da de mais tempo para a de menos, até 300 — passando disso, `month.pontual_done` diz quantas são e o PDF do mês traz todas: `id`, `title`, `project`, `project_icon`, `minutes`, `resolution`) |

## Rotinas — `/api/recurring`

| Rota | | Corpo |
| --- | --- | --- |
| `POST /` | W | `{label, freq?, weekdays?, month_day?, interval_days?, require_note?, remind_at?}` — `require_note` = marcar exige evidência; `remind_at` (`HH:MM`, também `7h30`/`7h`) = horário do lembrete |
| `PATCH /{id}` | W | `{label?, require_note?, freq?…}` — mudar a agenda exige `freq` + o parâmetro dela; se a rotina já tem passado, ela é encerrada hoje e uma nova (devolvida em `id`) começa hoje — uma ação só no histórico. Para `freq: "after"`, a nova conta da última marcação da antiga (próxima = última + N novo) |
| `DELETE /{id}` | W | remove daqui para a frente (o passado fica) |
| `POST /order` | W | `{ids}` — a ordem das rotinas ativas no Hoje (a primeira em cima). Uma ativa que não veio na lista fica depois, na ordem que tinha; repetida, de outra pessoa ou removida → 400. Rotina nova entra no fim; trocar a agenda mantém o lugar. Vai para o histórico (`recurring.order`, entidade `recurring_order`, com desfazer) |
| `GET /reminders` | R | rotinas com horário previstas hoje: `{today, items: [{id, label, remind_at, require_note, done}]}` (o lembrete da tela) |
| `POST /{id}/pause` | W | `{until}` (`AAAA-MM-DD`, de hoje até 1 ano) — pausa de hoje até `until`, inclusive (férias, folga, prédio fechado); já pausada = muda o fim. Volta sozinha no dia seguinte |
| `DELETE /{id}/pause` | W | retomar agora: a pausa termina ontem e hoje a rotina já é prevista (400 se não está pausada) |
| `POST /{id}/snooze` | W | `{minutes}` (5–120, padrão 10) — adia o lembrete de hoje; as notificações dos aparelhos esperam |
| `POST /{id}/toggle` | W | `{done, day?, note?}` — `day` até 7 dias atrás e só quando a rotina existia; `note` (até 200) = evidência do que foi conferido (vai pro PDF e pro JSON; remarcar sem `note` mantém a anterior; `note` vazio apaga). Rotina com `require_note` só é marcada com evidência (400) |

Agenda: `daily` (dias úteis do dono) · `weekly` + `weekdays` (máscara) ·
`monthly` + `month_day` (1–31; 31 = último dia) · `interval` + `interval_days`
(2–365, contando da criação) · `after` + `interval_days` (2–365 dias **depois da
última marcação**; sem marcação, da criação). Feito fora da agenda = **extra** (não entra no %).

`after` (ex.: trocar o filtro 30 dias depois da última troca): o ciclo vence em
última marcação + N e fica para fazer (no quadro, no lembrete) até ser marcado.
Cada ciclo conta **uma vez** nos números (retrospectiva, PDF, resumos): como
feito no dia em que foi marcado — mesmo atrasado — ou, se ninguém marcar, como
uma falta no último dia do ciclo (vencimento + N − 1), quando abre o seguinte.
Marcar antes de vencer é extra e adianta a próxima data. No quadro, `next_due`
= a próxima data (ou o vencimento já passado do ciclo aberto).

Pausa: nos dias pausados a rotina não é prevista em nada (quadro, lembrete,
notificação, avisos por e-mail, retrospectiva, PDF, resumos, calendário ICS);
marcar conta como extra. Ela começa sempre no dia em que é pedida, então os
números já fechados não mudam; cada pausa fica guardada como um período. No
quadro, `paused_until` = último dia da pausa que cobre o dia mostrado (ou
`null`). Pausar e retomar vão para o histórico (`recurring.pause`,
`recurring.resume`) e se desfazem em até 7 dias. Trocar a agenda de uma rotina
pausada leva a pausa para a nova.

### Pacotes de rotina por área — `/api/routine-packs`

Pontos de partida prontos (lista fixa no código): `manutencao` (Manutenção predial), `ti` (Suporte de TI),
`atendimento` (Atendimento e recepção), `campo` (Redes e campo) e `seguranca` (Segurança da informação).
Cada um traz o projeto da área (nome e ícone) e as rotinas com agenda e horário.

| Rota | | Corpo |
| --- | --- | --- |
| `GET /` | | `[{id, name, description, icon, project: {name, icon}, items: [{key, label, freq, weekdays, month_day, interval_days, remind_at, require_note, exists}]}]` — `exists` = a pessoa já tem uma rotina ativa com esse nome (sem diferenciar maiúsculas e acentos) |
| `POST /{id}/apply` | W | `{items?, project?}` — `items` = as `key` escolhidas (ausente = todas); `project` (padrão `true`) cria o projeto da área com ícone e descrição, ou reaproveita o de mesmo nome (e o tira do arquivo). Idempotente: rotina ativa de mesmo nome é pulada. Devolve `{pack, project: {…, created} \| null, created: [rotinas criadas], skipped: [nomes pulados]}`; 404 pacote desconhecido, 400 item de outro pacote ou nada escolhido. Cada criação entra no histórico (desfaz uma a uma) |

## Tarefas — `/api/worklog`

| Rota | | Corpo / observação |
| --- | --- | --- |
| `GET /` | | `?from=&to=` (dias, inclusive) `&by=created\|completed&status=open\|done\|all&limit=` (até 500, padrão 200) `&offset=`: tarefas por período, com `external_ref`, da mais nova à mais velha (desempate pelo `id`); total em `X-Total-Count`. `?external_ref=` = só a tarefa com essa chave (lista vazia se não houver) |
| `POST /` | W | `{title, description?, status?, due_date?, project_id?, priority?, ticket?, after_hours?, created_at?, completed_at?, external_ref?, blocked_reason?, follow_up_on?, resolution?}` (`resolution` só com status done: como foi resolvido) (prioridade 1 alta, 2 normal, 3 baixa; `ticket` = número do chamado, sem o "#"; `after_hours` = plantão). Datas retroativas: `AAAA-MM-DD` (criação às 9h, conclusão às 18h) ou data e hora, fuso da app; nunca no futuro, nunca conclusão antes da criação, até `retro_days` (padrão 60). `completed_at` sem `status` = já concluída; sem `created_at`, começou na própria conclusão (só a data: 9h do dia). `external_ref` repetido devolve a existente (200, `existing: true`) |
| `GET /{id}` | | tarefa + `checklist`, `notes`, `time`, `minutes`, `today` |
| `PATCH /{id}` | W | campos a mudar (concluir uma atribuída avisa quem atribuiu, uma vez; reabrir uma concluída = `{status: "todo"}`, que limpa `completed_at` e aparece no histórico como "reabriu a tarefa"); `description`/`due_date`/`project_id`/`ticket` = `null` apaga; `completed_at` corrige a data de uma concluída; `resolution` (até 1000; null apaga; só em tarefa concluída) = como foi resolvido; `blocked_reason` (até 120) e `follow_up_on` (dia combinado para cobrar; em dia não útil vai para o dia útil anterior) com status `blocked` = o que se aguarda (`blocked_at` marca desde quando; sair de `blocked` limpa tudo). Na tela, `blocked` se chama "aguardando" |
| `POST /{id}/finish` | W | conclui agora, ou `{completed_at, resolution?}` (mesmas regras; `resolution` = como foi resolvido, até 1000, entra na busca); limpa a espera (`blocked_reason`, `blocked_at`, `follow_up_on`); com o cronômetro rodando nela, ele para e aponta. Tarefa atribuída: quem atribuiu recebe um e-mail, uma vez |
| `POST /{id}/duplicate` | W | `201 {id}` — tarefa nova `todo` com título, descrição, projetos (principal e outros), prioridade e checklist (desmarcado); sem tempo, fotos, anotações, chamado nem datas. Entra no histórico como criação (desfazer apaga a cópia) |
| `DELETE /{id}` | W | exclui junto anotações, checklist e tempo (o desfazer devolve tudo) |
| `POST /{id}/notes` | W | `{body, external_ref?, at?}` (até 2000) — `external_ref` repetido devolve a existente (200, `existing: true`); `at` = hora do aparelho (feita sem sinal e enviada depois): até 24 h atrás (senão 400), no futuro vale agora |
| `PATCH /api/notes/{id}` | W | `{body}` (até 2000) — corrige o texto; a hora da anotação continua a original. Histórico `note.update`, com desfazer |
| `DELETE /api/notes/{id}` | W | |
| `POST /{id}/checklist` | W | `{label}` |
| `PATCH /api/checklist/{id}` | W | `{label?, done?}` |
| `DELETE /api/checklist/{id}` | W | |
| `POST /{id}/time` | W | `{minutes, day?, note?, external_ref?}` — 1–1440 min; até 366 dias atrás, nunca no futuro; máx. 24h somadas por dia; `external_ref` repetido devolve o existente sem somar de novo (200, `existing: true`) |
| `PATCH /api/time/{id}` | W | `{minutes?, day?, note?}` — corrige um apontamento, com as mesmas regras do lançamento (o próprio apontamento não conta duas vezes no limite de 24 h); `note` `null` ou vazio tira. Histórico `time.update`, com desfazer |
| `DELETE /api/time/{id}` | W | |

## Fotos (só pelo app)

| Rota | | Corpo |
| --- | --- | --- |
| `POST /api/worklog/{id}/photos` | S W | `{image, thumb, width?, height?, at?, external_ref?}` em base64 (`at` = hora do aparelho, mesma regra das anotações; `external_ref` repetido devolve a foto que já existe, 200 com `existing`) — PNG, JPEG ou WebP pelo conteúdo; foto até 1 MB (o app já reduz a 1600 px e regrava, sem EXIF/GPS), miniatura até 96 KB; até 10 por tarefa; cota por pessoa em Admin > Geral |
| `POST /api/recurring/{id}/photos?day=` · `GET` | S W | o mesmo, como evidência da rotina no dia (até 7 dias atrás) |
| `GET /api/photos/{id}?thumb=` | S | a imagem (dona, ou visualizador se a dona aceitou); cache privado e imutável |
| `DELETE /api/photos/{id}` | S W | some na hora; volta pelo histórico em até 7 dias, depois sai de vez |
| `GET /api/export/fotos.zip` | S | todas as fotos, numa pasta por tarefa e por rotina |

O detalhe da tarefa traz `photos` e o quadro, `photos_count`. A IA (MCP) vê só
quantas fotos a tarefa tem.

## Projetos — `/api/projects`

| Rota | | Corpo |
| --- | --- | --- |
| `GET /?include_archived=&external_ref=` | | com `icon`, `description`, `external_ref` e os números (numa consulta só): `open_tasks`, `waiting_tasks` (aguardando), `done_tasks`, `total_tasks` (principal e extras), `minutes_month` (tempo apontado no mês corrente; a tarefa em dois projetos conta inteira em cada um), `objectives`, `objectives_done` (todas as tarefas concluídas) e `last_activity` (a mais recente entre criação do projeto ou de objetivo, tarefa criada/concluída/posta em espera, tempo apontado e anotação); `external_ref` = só o projeto com essa chave, arquivado ou não |
| `POST /` | W | `{name, color?, icon?, description?, external_ref?}` — nome único por usuário, sem diferenciar maiúsculas e acentos (409); `external_ref` repetido devolve o existente (200, `existing`) |
| `PATCH /{id}` | W | `{name?, color?, icon?, description?, archived?}` — `description: null` apaga; `icon: null` volta para a pasta |
| `POST /{id}/archive` | W | `{open_tasks: "keep" \| "done" \| "move", move_to?}` — arquiva e decide as tarefas em aberto que têm o projeto como principal: continuam (`keep`, padrão), são concluídas agora (`done`) ou vão para o projeto `move_to` (`move`; ativo e seu, no fim do "Sem objetivo"). Cada tarefa mexida entra no histórico (desfazer uma a uma). Devolve `{open_tasks, done, moved, kept}` |
| `DELETE /{id}` | W | as tarefas ficam sem projeto (o desfazer as devolve) |
| `GET /{id}/overview` | | a tela do projeto: `project` (com os números acima), `objectives` na ordem (progresso, status, tarefas abertas em `tasks`, as 30 concluídas mais recentes em `done_tasks` e o número real em `done`), `unassigned` ("Sem objetivo"), `totals` e `upcoming` (até 5 prazos: tarefas abertas e objetivos não concluídos com data, do mais cedo — atrasados primeiro: `kind` `task`/`objective`, `id`, `title`, `due_date`) |
| `GET /{id}/done?objective=&limit=&offset=` | | as concluídas de um bloco (`objective` = id do objetivo, `0` = "Sem objetivo"), da mais recente à mais antiga, em páginas (`limit` até 100, padrão 10); total em `X-Total-Count` |

**Ícone** (`icon`): um nome da biblioteca fixa do app — `pasta` (o padrão), `predio`, `loja`, `clinica`,
`fabrica`, `escola`, `casa`, `escritorio`, `servidor`, `rede`, `wifi`, `seguranca`, `manutencao`, `eletrica`,
`hidraulica`, `veiculo`, `pessoa`, `maleta`, `computador`, `celular`, `camera`, `carrinho`, `calendario`,
`estrela`. Outro valor: 422. O projeto sempre vem com um ícone (sem escolha = `pasta`); nas tarefas, o do
projeto principal vem em `project_icon` (nulo sem projeto) e o de cada extra em `extra_projects[].icon`.

## Relatórios, busca e exportação

| Rota | | Observação |
| --- | --- | --- |
| `GET /api/reports/export?start=&end=&project=` | | PDF (até 6 por minuto). Período até 366 dias (fim limitado a hoje). Com `project` e sem datas: o projeto inteiro (até ~3 anos) |
| `GET /api/reports/preview?start=&end=&project=` | | o que o PDF traria: tarefas concluídas, minutos, rotinas, dias com atividade |
| `GET /api/search/similar?title=` | | "já resolvi isso antes?": tarefas concluídas com `resolution` e título parecido — palavras de 3+ letras (sem as vazias) e siglas de 2 em maiúsculas (AD, IP, RH) como palavra inteira; com 4+ palavras exige 2 em comum; só as de maior pontuação, até 3 |
| `GET /api/search?q=` | | 2–100 caracteres, sem acento: tarefas (com onde casou: título, descrição, chamado, anotação, checklist, apontamento, como resolveu; abertas primeiro, pela prioridade, depois as concluídas mais recentes), rotinas, projetos. Cada seção pagina sozinha: `offset` e `limit` (padrão 40, até 100) das tarefas, `rec_offset`, `proj_offset` e `side_limit` (padrão 20, até 50) de rotinas e projetos. Totais reais em `total_tasks` (também no `X-Total-Count`), `total_recurring` e `total_projects` |
| `GET /api/export/apontamentos.csv?start=&end=` | | CSV `;` + BOM (Excel BR). Com `start` e `end` (os dois, até 1 ano): só os apontamentos do período; sem eles, todos |
| `GET /api/export/tarefas.csv?start=&end=` | | idem, com as colunas `aguardando` (o que a tarefa aguarda) e `como_resolveu`. Com período: as tarefas que estiveram em aberto nele (criadas até o fim e não concluídas antes do início) ou com tempo apontado nele, e mais duas colunas, `minutos_no_periodo` e `horas_no_periodo` |
| `GET /api/export/plantao.csv?start=&end=` | | atendimentos de plantão do período (padrão: o mês), com horas por dia e total |
| `GET /api/export/rotinas.csv?start=&end=` | | trilha de auditoria: cada rotina em cada dia do período (até hoje), prevista/extra, feita (sim/não/pendente) e a evidência — dia sem nada feito também aparece |
| `GET /api/export/tudo.json` | | `user`, `profile` (nome, tema, chamados, projeto padrão, aceite), `prefs` (e-mail, notificações, assistente), `projects` (com `icon`, `description`, `external_ref` e `objectives`), `templates`, `tasks` (com `external_ref`, objetivo, projetos extras, anotações/checklist/tempo), `recurring` (dias feitos, `require_note`, `evidence`), `renewals` e `photos` (quantas; as imagens vão no `fotos.zip`) |

## Histórico — `/api/history`

| Rota | | Observação |
| --- | --- | --- |
| `GET /?limit=&offset=&entity=&entity_id=` | | quem fez (app, chave, IA, admin), o quê, `can_undo` (do mais novo ao mais velho; `limit` até 200, padrão 50); `offset` pula os N mais novos e o total vem em `X-Total-Count` (os 180 dias guardados) |
| `GET /?after=<id>&limit=` | | **feed de mudanças**, para sincronizar: os eventos da pessoa com id maior que `after`, do mais velho ao mais novo (até 200 por vez) |
| `POST /{id}/undo` | W | só a ação mais recente de cada item; criação de tarefa que já tem filhos → 409 |

**Feed de mudanças.** Cada item: `{id, at, action, entity, entity_id, actor, token_name, external_ref?}`.
`action` = `entidade.verbo` (`worklog.create`, `worklog.update`, `worklog.finish`, `worklog.delete`,
`note.create`, `time.create`, `recurring.toggle`, `project.update`, `undo`...); `external_ref` vem quando o item tem um.
Exclusão é uma **lápide** (`*.delete`, o id do item que sumiu). Tarefa atribuída: `worklog.assign` = chegou
(criação); `worklog.assign_update` = quem atribuiu mudou título, descrição, prazo ou prioridade (trate como `worklog.update`);
cancelamento por quem atribuiu ou devolução por quem recebeu = `worklog.delete` (lápide comum). Registros antigos podem trazer
`worklog.assign_cancel`, que também é exclusão. Para buscar o estado atual, leia o item pela
rota dele (`GET /api/worklog/{entity_id}`). Guarde o último `id` e peça `after=<ele>` de novo; lista vazia =
em dia. `after=0` começa do mais velho guardado. O histórico guarda 180 dias: um cursor mais velho que isso
(integração parada há meses) recebe **410** — recomece com `after=0`. Os eventos dos últimos 2 segundos só
aparecem na próxima leitura (garante a ordem). Escopo `read` basta.

## Webhooks — `/api/webhooks`

O Nexus avisa outro sistema a cada mudança: o mesmo evento do feed, empurrado por `POST`.

| Rota | | Corpo / observação |
| --- | --- | --- |
| `GET /` | | os webhooks, com `active`, `failures`, `last_error`, `last_delivered_at`, `disabled_at` |
| `POST /` | S | `{url, events?}` (só pelo app: uma chave vazada não cadastra destino) — só `https://` com endereço público; `events` = `["*"]` (padrão), ações exatas (`worklog.finish`) ou grupos (`worklog.*`); até 5 por pessoa. Devolve `secret` (`whsec_…`) **uma vez** |
| `PATCH /{id}` | S | `{url?, events?}` (só pelo app) — edita sem recriar: o segredo e a fila continuam; o endereço novo passa pela mesma checagem do cadastro. Histórico `webhook.update` |
| `POST /{id}/enable` | S | religa um desligado por falhas; continua do evento em que parou |
| `POST /{id}/test` | S | envia **agora** um evento de teste (`ping`) e devolve `{ok, status, ms, error}` (`error` em linguagem comum: certificado inválido, sem resposta, HTTP 401…). Não conta como falha nem desliga; vale para um desligado. Até 5 testes por minuto (429) |
| `DELETE /{id}` | W | |

- Corpo: o item do feed + `data` (o estado do item logo depois da mudança, para tarefa, anotação, checklist,
  tempo, rotina, projeto, objetivo e vencimento; `null` nas exclusões e nos demais). Fotos nunca vão.
- Headers: `X-Nexus-Event` (a `action`), `X-Nexus-Delivery` (= `id` do evento; use para ignorar repetição) e
  `X-Nexus-Signature: t=<unix>,v1=<hex>`, onde `v1 = HMAC-SHA256(segredo, "<t>.<corpo bruto>")`. Confira a
  assinatura e recuse `t` muito antigo (ex.: mais de 5 min).
- Teste (`X-Nexus-Event: ping`): mesmo caminho, assinatura e prazo de um evento real; o corpo é
  `{"id": 0, "action": "ping", "entity": "webhook", "entity_id": <webhook>, "test": true, "data": {"message": …}}`
  e `X-Nexus-Delivery` = `test-<aleatório>`. Responda 2xx; quem só trata alguns eventos pode ignorar o `ping`.
- Entrega: uma passada por minuto, um evento por vez e em ordem; só os eventos criados depois do cadastro.
  Resposta 2xx = entregue. Outra resposta (inclusive redirecionamento, que não é seguido), erro de conexão
  ou mais de 5 s = falha: tenta de novo em 1 min, 5 min, 30 min, 2 h e 12 h; **5 falhas seguidas desligam**
  o webhook (aparece em `GET` e na tela). Trocar a senha também desliga todos.
- O endereço é resolvido a cada envio e recusado se apontar para rede interna, loopback, link-local ou faixa
  reservada.

## Calendário, avisos, notificações e chaves (só pelo app)

| Rota | | Observação |
| --- | --- | --- |
| `GET /api/calendar` | S | estado do link |
| `POST /api/calendar` | S W | `{include_recurring}` — cria/troca o link e devolve `path` uma vez |
| `PATCH /api/calendar` · `DELETE /api/calendar` | S W | |
| `GET /api/calendar/{nxc_…}.ics` | público (segredo no link) | prazos (dia inteiro, sem a descrição), dias de cobrar impedimentos (sem o motivo), vencimentos (dia de vencer e de começar a avisar) e rotinas (RRULE) |
| `GET /api/notifications` · `PUT /api/notifications` | S (W) | `{morning, morning_hour, evening, evening_hour, weekly, weekly_hour, show_titles}` |
| `POST /api/notifications/test` | S W | manda um teste para o e-mail da conta (503 sem SMTP) |
| `GET /api/push?endpoint=` | S | chave pública VAPID, preferências e aparelhos (`current` = o do `endpoint`) |
| `POST /api/push/devices` · `DELETE /api/push/devices/{id}` | S W | `{endpoint, keys: {p256dh, auth}, label?}` — só serviços de push dos navegadores (Google, Mozilla, Apple, Microsoft); o mesmo navegador com outra conta passa para quem entrou |
| `PUT /api/push/prefs` | S W | `{routine, follow_up, deadline, assigned, morning_hour, hide_content}` (o app grava o mesmo `morning_hour` do e-mail "Seu dia": uma hora da manhã só, um Salvar na aba Avisos) |
| `POST /api/push/test?device_id=` | S W | notificação de teste (502 se o serviço do aparelho recusar) |
| `GET /api/tokens` · `POST /api/tokens` · `DELETE /api/tokens/{id}` | S (W) | `{name, scope, expires_in_days}`; até 20 ativas |
| `POST /api/tokens/{id}/renew` | S W | `{expires_in_days}` (1–365; `null` = sem validade) — nova validade, contada de agora, para uma chave não revogada (vencida volta a funcionar com o mesmo valor; revogada → 404). Conta no limite de 20 ativas. Histórico `token.renew` |

## Identidade visual

| Rota | | Observação |
| --- | --- | --- |
| `GET /api/branding` · `GET /api/branding/logo` | público | textos do lockup e logo (servido em sandbox) |
| `PUT /api/admin/branding` | admin W | `{line1, line2}` |
| `POST /api/admin/branding/logo` | admin W | corpo = a imagem (PNG, WebP ou SVG seguro, até 256 KB) |
| `DELETE /api/admin/branding/logo` | admin W | volta ao dragão |

## Vencimentos — `/api/renewals`

| Rota | | Corpo / observação |
| --- | --- | --- |
| `GET /` | | lista do que vence primeiro ao último, com `days_left`, `warn_from` (início do aviso; em dia não útil, antecipa para o último dia útil) e `warning` |
| `POST /` | W | `{label, expires_on, warn_days? (padrão 30), project_id?, note?, renew_months?}` — `renew_months` = repete a cada N meses (o app sugere a próxima data ao renovar) |
| `PATCH /{id}` | W | campos a mudar; nova `expires_on` = renovação (no histórico como "renovou"; desfaz) |
| `DELETE /{id}` | W | desfaz pelo histórico |

Aparecem no Hoje (só os no aviso), no e-mail da manhã e no calendário (dia de vencer e dia de começar a avisar). MCP: `list_renewals`.

## Admin — `/api/admin` (só pelo app, papel admin)

| Rota | | Observação |
| --- | --- | --- |
| `GET /users` | | contas em ordem de nome (sem acento nem caixa), com `roles`, `accepts_assignments_at`, `viewers_allowed` (liberou o registro ao visualizador), `invite_pending`/`invite_expired`, `blocked_at`, `created_at`, `last_seen_at` (último acesso: login ou uso do app, gravado no máximo a cada 5 min; `null` = nunca entrou) e `open_tasks` (tarefas não concluídas) |
| `POST /users` | W | `{email, display_name?, roles?}` → convite por link (com e-mail no servidor) ou senha temporária (troca no 1º acesso). `display_name` vira o nome da conta até o primeiro acesso (no tour a pessoa confere); `roles` = os papéis já no convite (padrão `["user"]`, ao menos um) |
| `PUT /users/{id}/profile` | W | `{display_name?, email?}` (ausente = mantém) — edita nome e e-mail de uma conta; trocar o e-mail avisa o antigo e o novo (conta que já entrou); 409 se o e-mail é de outra conta; vai ao histórico (`user.profile`) |
| `POST /invite-requests/{id}/invite` | W | `{display_name?, roles?}` (opcional) — convida quem pediu; nome padrão = o do pedido, papéis padrão = `["user"]` |
| `PUT /users/{id}/roles` | W | `{roles: [...]}` (ao menos um); não tira o próprio admin nem deixa o sistema sem admin. → `{id, roles, notified}`: a pessoa (que já entrou e não está bloqueada) recebe o aviso único no app (`role_notice`) e, com e-mail no servidor, um e-mail com o que ganhou ou perdeu |
| `POST /users/{id}/reset-password` | W | `{method?: "temp"\|"link"}` (padrão `temp`). `temp` → `{email, temp_password}`; `link` (só com e-mail no servidor, senão 400) manda o link de nova senha (24 h, uso único) e devolve `{email, reset_url, emailed}`. Nos dois, a senha atual deixa de valer, encerra sessões e revoga chaves, calendário e passkeys; numa conta bloqueada, libera o acesso |
| `POST /users/{id}/block` | W | bloqueia o acesso sem apagar nada: senha que ninguém sabe, sessões, chaves, calendário, notificações e passkeys cortados, links de e-mail sem valor e "Esqueci a senha" sem efeito (`blocked_at`); não a própria conta, nem convite pendente. `reset-password` libera. Corpo opcional `{transfer_to}`: as tarefas abertas passam para essa conta (papel `user`, acesso liberado; senão 400 e nada muda) — ver *Transferir tarefas* abaixo. → `{ok, email, transferred}` (`{count, to, to_id, emailed}` ou `null`) |
| `POST /users/{id}/cancel-invite` | W | convite ainda não aceito: a conta (sem dados) sai e o link deixa de valer; o pedido de convite que a gerou volta a pendente; 400 se a pessoa já entrou (aí é `delete`) |
| `POST /users/{id}/delete` | W | `{confirm_email, transfer_to?}` — exclui a conta e todos os dados (não a própria, nunca o último admin); com `transfer_to`, antes as tarefas abertas passam para essa conta (`transferred` na resposta); e-mail e contagens ficam no histórico de quem excluiu |
| `GET /settings` · `PUT /settings` | W | `{retro_days (1–366), support_contact?}` |
| `GET /org` · `PUT /org` | W | Para empresas e instituições, tudo desligado por padrão: `{team_visibility: "self"\|"managers", identity_managed, invite_request_off, ticket_url}` (ausente = mantém; o GET também traz `mail_configured`). `managers` = quem tem o papel `viewer` vê o registro de todos (as escolhas de cada um ficam guardadas); `identity_managed` = só o admin muda nome e e-mail; `invite_request_off` = a tela de login não oferece "Solicitar convite"; `ticket_url` = endereço do sistema de chamados para todos (`{id}` = o número; `""` ou `null` = vazio, cada pessoa usa o seu). Cada mudança vai ao histórico do admin (`app.team_visibility`, `app.identity_managed`, `app.invite_request_off`, `app.ticket_url`). O tour do primeiro acesso é obrigatório para toda conta nova (deixou de ser opção) |

**Transferir tarefas** (bloquear ou excluir com `transfer_to`): as tarefas não concluídas mudam de dono numa gravação só, com as anotações, o checklist e as fotos; entram no projeto padrão de quem recebe (os projetos são de cada pessoa) e perdem o objetivo e o `external_ref`; o tempo já registrado fica no registro de quem saiu. Cada tarefa vai ao histórico de quem recebe (`worklog.transfer`, não desfazível) e a transferência ao do admin (`user.transfer_tasks`); quem recebe é avisado como numa atribuição (e-mail, com e-mail no servidor, e notificação no aparelho, se ligou as de tarefas atribuídas). Rotinas não são transferidas.


## Vê a equipe — `/api/viewer` (só pelo app, papel viewer; tela Equipe)

Quem pode ser visto é decidido num lugar só (`backend/app/visibility.py`, `visible_sql`/`can_see`): papel `user` e
o aceite (`PUT /api/me/viewers`) — ou todos, com a instância em "Visível para quem gerencia" (`PUT /api/admin/org`).
Vale para todas as rotas abaixo, para as fotos e para a foto de perfil.

| Rota | | Observação |
| --- | --- | --- |
| `GET /team?month=AAAA-MM` | | o painel da Equipe (padrão: o mês corrente, até hoje), tudo SOMADO de quem pode ser visto e está com a conta em uso: `month {recurring_done, recurring_total, pontual_done, minutes, now}` (a soma do PDF/Meu mês de cada pessoa; as horas são as do CSV do mesmo período), `trend` (até 6 meses da equipe, terminando no escolhido), `waiting`/`open` (agora), `attention` (até 6: `kind` `returned` = atribuída por você e devolvida, ainda sem decisão — vem com `reason` e entra mesmo de quem não compartilha, porque está na sua lista de atribuídas —, `assigned` = atribuída por você e aguardando ou a fazer sem nada registrado há 5 dias, `waiting` = aguardando há mais tempo, `due` = prazo até 7 dias ou já passado; com `task_id`, `user_id`, `name`, `days`), `projects` (tempo por nome de projeto), `people` (ordem alfabética: `open`, `waiting`, `last_activity`, `avatar`), `people_count`, `hidden_count` (contas com registro que não compartilham, sem nomes; você não conta), `months` (para o seletor) e `can_assign`. Sem média, tendência ou ranking por pessoa |
| `GET /users` | | contas com registro próprio (papel `user`) visíveis (aceite ou "Visível para quem gerencia") e com a conta em uso |
| `GET /users/{id}/board` · `/dashboard` · `/projects` · `/reports/export` | | visão só leitura da pessoa; sem o aceite, 404. No `/dashboard?month=`, o `overview` vem sem `behind`, `trend`, `average` e `compare` (sem placar nem comparação) |
| `GET /export/apontamentos.csv?start=&end=` | | horas de quem aceitou, com coluna `usuario`, do período (`AAAA-MM-DD`; padrão: o mês corrente; até 1 ano) |

## Atribuição — `/api/assign`

| Rota | | Observação |
| --- | --- | --- |
| `GET /people` | | admin (app) ou atribuidor: contas com registro e se aceitam (`accepts`, desde quando); conta com acesso bloqueado vem com `blocked: true` e `accepts: false` (não recebe atribuição: 404). Foto (`avatar`) só de quem aceita, salvo para o admin |
| `POST /` | W | atribuidor: `{user_id, title, description?, due_date?, priority?, ticket?, after_hours?, from_return?}` → a tarefa nasce na conta de quem aceitou, com e-mail; não a si mesmo. `from_return` = id de uma tarefa sua que foi devolvida e ainda espera decisão (atribuir de novo, à mesma pessoa ou a outra; já resolvida → 409) |
| `GET /sent` | | atribuidor: tarefas que atribuiu, com status atual, `editable` (ainda dá para alterar) e `cancelable` (ainda dá para cancelar); as que saíram da conta de quem recebeu nos últimos 60 dias vêm com `status: "removed"` e `ended: {kind: deleted\|canceled\|returned\|removed, at}`; devolvida: também `reason`, `resolved` (`null`, `{kind: "closed", at}` ou `{kind: "reassigned", at, to}`) e `prefill` (título, descrição, prazo, prioridade, chamado e plantão como saiu, para atribuir de novo) |
| `POST /{id}/close` | W | atribuidor: encerra uma devolvida sem atribuir de novo (sai de "Precisa de atenção"; em `/sent`, `resolved.kind = "closed"`). Sem devolução em aberto com esse id → 404 |
| `POST /news/seen` | W | atribuidor: o aviso do Hoje (`assigned_news`) foi visto; o próximo conta a partir de agora |
| `PATCH /{id}` | W | atribuidor que mandou: `{title?, description?, due_date?, priority?}` (`description` até 300, com quebras de linha; `null` tira) enquanto a tarefa está `todo` e sem tempo, anotação, checklist, foto ou cronômetro (senão 409). Só o que muda de fato (nada diferente → 400); campo que quem recebeu já mudou → 409 e nada muda. E-mail para quem recebeu, que pode desfazer pelo histórico |
| `POST /{id}/cancel` | W | idem, e só se quem recebeu não mudou nada na tarefa (senão 409): ela sai da conta de quem recebeu (e-mail avisando; no histórico/feed dela, `worklog.delete`, desfazível) e fica em `/sent` como cancelada, com o título mais recente |

**Devolver (quem recebeu)** — `POST /api/worklog/{id}/return` `{reason}` (W; motivo de 3 a 120 caracteres):
só numa tarefa que outra pessoa atribuiu a você e que não está concluída (senão 400/409). Ela sai da sua conta como
uma exclusão (no seu histórico/feed, `worklog.delete` com o motivo; o desfazer devolve tudo, com anotações, checklist e
tempo, enquanto quem atribuiu não decidir — depois, 409) e ninguém fica com ela até quem atribuiu decidir. Quem atribuiu
recebe e-mail (com SMTP) e push (o mesmo aviso "Tarefas atribuídas"), ganha `assign.returned` no próprio histórico
(e nos webhooks, com `data: {title, to, to_id, reason}`; `to` é quem devolveu) e vê a linha "devolvida" em `/sent` e
em "Precisa de atenção" até atribuir de novo (`from_return`) ou encerrar (`/close`). Devolve `{ok, to}`.

## Operação

| Rota | | Observação |
| --- | --- | --- |
| `GET /api/health` | público | `{ok: true}` com o banco respondendo (healthcheck do compose e do deploy) |
| `POST /api/client-errors` | S | `{message, where}` — erro de JavaScript do navegador vai só para o log; 10 a cada 5 min por pessoa; 204 |

## MCP — `POST /mcp`

JSON-RPC 2.0 sobre HTTP, **uma mensagem por requisição** (sem lote, sem SSE),
`Authorization: Bearer nxs_…`. Versões: 2025-11-25, 2025-06-18, 2025-03-26.

Leitura: `get_today`, `get_summary`, `get_period` (`from`, `to`, `project`: concluídas, tempo por projeto e rotinas de qualquer período, como a prévia do relatório), `get_handoff` (passagem de turno: abertas, aguardando, concluídas nas últimas 12 h, vencimentos no aviso), `get_week_review` (revisão da semana: o que fechou, o que ficou, sugestões e o que aguarda há dias sem dia para cobrar), `list_renewals` (vencimentos), `find_similar` (já resolvi isso antes?), `list_tasks` (com `from`/`to`/`by` por período e `project`; mostra o tempo de cada tarefa), `get_task`, `search`,
`list_projects` (com objetivos e arquivados marcados), `list_objectives`, `list_recurring`, `list_templates`, `list_routine_packs` (pacotes de rotina por área, com `[já existe]`), `get_history`.
Escrita (chave `write`): `create_task` (com `minutes` = tempo gasto, já apontado; `created_at`, `completed_at` — só com a conclusão, começou `minutes` antes dela —, `external_ref`, `blocked_reason`, `follow_up_on`, `resolution`), `update_task` (com `completed_at`, `blocked_reason`, `follow_up_on`, `resolution`; motivo ou dia de cobrar sem `status` só numa tarefa que já aguarda, senão erro pedindo `status: "blocked"` junto — vale também para o `PATCH`), `complete_task` (com `completed_at` e `resolution`),
`add_note`, `add_checklist_item`, `set_checklist_item`, `log_time`, `start_timer` (`at` = hora em que começou), `stop_timer` (`at` = hora em que parou; os dois em HH:MM, "9h" ou data e hora, até 24 h atrás),
`create_from_template`, `set_recurring` (`recurring_id`, `note` = evidência; `paused_until` = pausa até a data, `null` = retoma; com `paused_until` só marca se vier `done: true` explícito — `note` sozinha não marca nem é gravada), `create_recurring` (`label`, `freq` — inclui `after`, N dias depois da última vez —, `weekdays` em nomes seg/ter..., `month_day`, `interval_days`, `remind_at`, `require_note`, `paused_until`; nome repetido devolve a existente), `apply_routine_pack` (`pack`, `items` = as chaves escolhidas, ausente = todas; `project`, padrão `true`: cria o projeto da área com ícone ou reaproveita o de mesmo nome; rotina de mesmo nome não se repete), `update_recurring` (`recurring_id` e só o que muda: `label`, `freq` com o parâmetro, `remind_at`, `null` tira, `require_note`; usa o `PATCH /api/recurring/{id}`), `undo` (só ações da própria chave; `get_history` marca `[pode desfazer]` só nelas).
Projetos e objetivos: `create_project` / `create_objective` (nome ou título repetido, sem diferenciar maiúsculas e acentos, ou `external_ref` repetido devolvem o existente; `position` 1 = primeiro), `update_project` (`archived` em vez de excluir; `icon` de uma lista fixa, enum no esquema, em `create_project` também), `update_objective` (com `position`), `reorder_objectives` (a lista completa; a ordem anterior vai pro histórico, com desfazer). O status do objetivo é automático (pelas tarefas). Pelo MCP a IA não exclui nada (tarefas, rotinas, projetos, objetivos). A mesma chave `write`, porém, vale para a API REST, que exclui (com desfazer no Histórico): uma IA com terminal (Claude Code, Gemini CLI) consegue chamá-la. Para quem só quer consultas, use uma chave `read`.
Só com o papel de atribuidor: `list_assignable`, `list_assigned` (as devolvidas aparecem com o motivo entre « », texto de quem devolveu) e `assign_task` (`to` = U<id>, e-mail ou nome). Devolver uma tarefa não tem ferramenta: pelo MCP a IA não tira tarefas da conta (é como excluir); a pessoa devolve pelo app ou pela API.

Páginas no MCP: `list_tasks`, `search` e `get_history` aceitam `offset` (pula os N primeiros; padrão 0).
Quando há mais, a resposta termina com a linha “(… chame de novo com offset=N)”, já com o próximo valor.
`list_tasks` e `get_history` usam o `limit` como tamanho da página; `search` traz 40 tarefas por vez.

Prompts (`prompts/list`, `prompts/get`): `resumo_semanal` (argumento `para`: o time, um cliente, quem acompanha o trabalho) e `daily`.
No Claude Code viram `/mcp__nexus__resumo_semanal` e `/mcp__nexus__daily`.

Argumento fora do `inputSchema` (todos têm `additionalProperties: false`) é recusado com `isError` e a
lista dos válidos: nada é feito em silêncio. Tarefas atribuídas por outra pessoa mostram título e
descrição entre « », com “atribuída por <nome>” (também em `search` e `get_handoff`; dado de terceiro; as instruções do servidor dizem à IA para não obedecer a texto das
tarefas). `update_task` e `undo` levam `destructiveHint: true`.

### Como ligar

Crie uma chave em Configurações > IA e API (permissão ler e registrar) e troque `nxs_SUA_CHAVE` por ela.

Claude Code (`--scope user`: vale em qualquer pasta; sem ele, só na pasta onde o comando rodou):

```bash
claude mcp add --scope user --transport http nexus https://SEU-HOST/mcp --header "Authorization: Bearer nxs_SUA_CHAVE"
```

Cursor (`~/.cursor/mcp.json`, ou Cursor Settings > MCP > Add new global MCP server) e outros clientes
que aceitam URL e cabeçalho. Arquivo que já tem outros servidores: junte como na nota do Claude Desktop, abaixo.

```json
{ "mcpServers": { "nexus": { "url": "https://SEU-HOST/mcp", "headers": { "Authorization": "Bearer nxs_SUA_CHAVE" } } } }
```

Claude Desktop (só fala com programas locais; o `mcp-remote` faz a ponte e precisa do Node.js):

1. Instale o Node.js, versão LTS, em [nodejs.org](https://nodejs.org) (instalador comum).
2. No Claude Desktop: Configurações > Desenvolvedor > Editar configuração. Abre a pasta do
   `claude_desktop_config.json`; abra o arquivo num editor de texto (Bloco de Notas, TextEdit).
3. Arquivo vazio ou só com `{}`: apague tudo e cole o bloco abaixo. Já tem conteúdo: veja a seguir.
4. Salve, feche o app por completo e abra de novo. O `nexus` aparece no ícone de ferramentas.

```json
{ "mcpServers": { "nexus": {
    "command": "npx",
    "args": ["-y", "mcp-remote", "https://SEU-HOST/mcp", "--header", "Authorization:${NEXUS_AUTH}"],
    "env": { "NEXUS_AUTH": "Bearer nxs_SUA_CHAVE" } } } }
```

Vale para os três arquivos (Claude Desktop, Cursor e Gemini CLI): se o arquivo já tiver conteúdo, não cole por cima nem no fim (o JSON fica inválido e o app abre sem
o Nexus). Já existe `"mcpServers"`: cole só o trecho `"nexus": { … }` dentro dele, separado do
servidor anterior por vírgula. Não existe: acrescente `"mcpServers": { … }` como mais uma chave do
objeto principal, também com vírgula. Exemplo:

```json
{
  "preferences": { "...": "o que já estava aqui" },
  "mcpServers": {
    "outro-servidor": { "...": "o que já estava aqui" },
    "nexus": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://SEU-HOST/mcp", "--header", "Authorization:${NEXUS_AUTH}"],
      "env": { "NEXUS_AUTH": "Bearer nxs_SUA_CHAVE" }
    }
  }
}
```

Gemini CLI, o Gemini de terminal (`~/.gemini/settings.json`; no Windows,
`C:\Users\<você>\.gemini\settings.json`). Depois do primeiro login ele já tem conteúdo (o tipo de
login, o tema): junte como na nota acima, sem colar por cima.

```json
{ "mcpServers": { "nexus": { "httpUrl": "https://SEU-HOST/mcp", "headers": { "Authorization": "Bearer nxs_SUA_CHAVE" } } } }
```

O app e o site do Gemini (gemini.google.com), o ChatGPT e o claude.ai (navegador) ainda não ligam:
os conectores deles exigem OAuth, que o Nexus não tem. Do Gemini, só o Gemini CLI funciona; nos
outros, use um dos clientes acima ou a API REST.

## Integração passo a passo

Receitas com `curl` (em qualquer ferramenta — n8n, Make, Power Automate, script — é a mesma chamada
HTTP). `NEXUS` = o endereço do seu Nexus; `KEY` = uma chave `write` criada em Configurações > IA e API.

```bash
NEXUS=https://SEU-HOST; KEY=nxs_SUA_CHAVE
H=(-H "Authorization: Bearer $KEY" -H "Content-Type: application/json")
```

**1. Alerta vira tarefa (sem duplicar).** O monitoramento usa o id do alerta como `external_ref`; mandar
de novo devolve a mesma tarefa (200, `existing: true`) em vez de criar outra.

```bash
curl -sS -X POST "$NEXUS/api/worklog" "${H[@]}" \
  -d '{"title": "Disco cheio em srv-db01", "description": "/ acima de 90%", "priority": 1, "external_ref": "alerta-48213"}'
# 201 {"id": 512}   (repetido: 200 {"id": 512, "existing": true})
```

**2. Concluir pela referência, com como foi resolvido.**

```bash
ID=$(curl -sS "$NEXUS/api/worklog?external_ref=alerta-48213" "${H[@]}" | jq '.[0].id')
curl -sS -X POST "$NEXUS/api/worklog/$ID/finish" "${H[@]}" \
  -d '{"resolution": "Logs antigos rotacionados; alerta normalizou"}'
```

**3. Apontar tempo (repetir não soma de novo).**

```bash
curl -sS -X POST "$NEXUS/api/worklog/$ID/time" "${H[@]}" \
  -d '{"minutes": 30, "note": "análise e limpeza", "external_ref": "alerta-48213-t1"}'
```

**4. Ler o feed de mudanças (sincronizar).** Guarde o maior `id` recebido e peça a partir dele.

```bash
curl -sS "$NEXUS/api/history?after=0&limit=200" "${H[@]}"      # primeira vez
curl -sS "$NEXUS/api/history?after=91234&limit=200" "${H[@]}"  # depois: só o que mudou
# [{"id": 91235, "at": "...", "action": "worklog.finish", "entity": "worklog", "entity_id": 512,
#   "actor": "web", "token_name": null, "external_ref": "alerta-48213"}, ...]
# 410 = o cursor passou dos 180 dias guardados: recomece com after=0
```

**5. Conferir a assinatura do webhook.** Use o corpo **bruto** (antes de interpretar o JSON) e o
segredo `whsec_…` mostrado na criação. Ignore repetições pelo `X-Nexus-Delivery`.

Python:

```python
import hashlib, hmac, time

def nexus_ok(secret: str, body: bytes, header: str, tolerance: int = 300) -> bool:
    """body = corpo bruto; header = valor de X-Nexus-Signature."""
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    t, v1 = parts.get("t", ""), parts.get("v1", "")
    if not t.isdigit() or abs(time.time() - int(t)) > tolerance:
        return False  # sem carimbo ou velho demais (reenvio malicioso)
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)
```

Node:

```js
const crypto = require("node:crypto");

function nexusOk(secret, rawBody, header, tolerance = 300) {
  // rawBody = Buffer do corpo bruto; header = valor de X-Nexus-Signature
  const parts = Object.fromEntries(header.split(",").map((p) => p.split("=")));
  const t = Number(parts.t);
  if (!Number.isInteger(t) || Math.abs(Date.now() / 1000 - t) > tolerance) return false;
  const expected = crypto.createHmac("sha256", secret).update(`${t}.`).update(rawBody).digest();
  const got = Buffer.from(parts.v1 || "", "hex");
  return got.length === expected.length && crypto.timingSafeEqual(got, expected);
}
```

## Receitas: avisos e planilha

O Nexus só faz duas coisas: **avisa um endereço** (webhook assinado) e **responde à API**. Quem fala com
o chat, o e-mail ou a planilha é uma automação (n8n, Make, Power Automate, Zapier…) ou um script curto
seu; o Nexus não tem código para nenhum desses produtos. Em toda receita com webhook, depois de criar o
webhook em Configurações > IA e API, aperte **Testar** na linha dele: o Nexus manda na hora um evento
`ping` assinado e mostra o que o destino respondeu (código HTTP e tempo, ou o erro em linguagem comum).

**Onde rodar um script.** O Nexus só entrega em `https://` com endereço público e **confere o
certificado** (autoassinado não passa). Rode o script numa máquina sua ouvindo em `127.0.0.1` e
publique-o atrás de um https: um proxy que tira o certificado sozinho (Caddy:
`avisos.seu-dominio.com { reverse_proxy 127.0.0.1:8787 }`) ou um túnel. Para deixar rodando, um
serviço do systemd ou um container. Os scripts usam só a biblioteca padrão do Python 3.

**Pela automação.** O gatilho “Webhook” (recebe `POST`) da ferramenta gera um endereço https: cadastre-o
no Nexus. Se a ferramenta tem um passo de código ou de HMAC, confira a assinatura com a função da
receita 5 (corpo **bruto**). Se não tem, o endereço gerado (longo e aleatório) faz o papel de senha:
não compartilhe e, se vazar, crie outro webhook e apague o antigo.

**6. Avisar um grupo do Telegram quando uma tarefa for concluída ou ficar aguardando.**

Precisa de: um bot (no Telegram, fale com o @BotFather, `/newbot`, e guarde o token), o bot adicionado
ao grupo e o id do grupo (mande `/start` no grupo e abra
`https://api.telegram.org/bot<TOKEN>/getUpdates`: o `chat.id` do grupo começa com `-`).

1. Rode o script abaixo atrás de um https (ver “Onde rodar um script”), com `TG_TOKEN`, `TG_CHAT` e,
   depois do passo 2, `NEXUS_WHSEC`.
2. No Nexus, crie o webhook com o endereço do script e os eventos `worklog.finish, worklog.update`
   (concluir pelo botão gera `worklog.finish`; mudar o status para Aguardando ou Concluída gera
   `worklog.update`). Copie o segredo para `NEXUS_WHSEC` e reinicie o script.
3. Aperte **Testar**: chega no grupo “Teste do Nexus Worklog…” e a linha mostra “HTTP 204”. HTTP 401 =
   segredo errado no script.

```python
# nexus_telegram.py: recebe o webhook do Nexus e avisa num grupo do Telegram.
import hashlib, hmac, json, os, time, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

SEGREDO = os.environ["NEXUS_WHSEC"]                         # whsec_… mostrado ao criar o webhook
BOT, GRUPO = os.environ["TG_TOKEN"], os.environ["TG_CHAT"]  # token do @BotFather e id do grupo
QUANDO = {"done": ("Concluída", "completed_at"), "blocked": ("Aguardando", "blocked_at")}
avisadas = set()  # (tarefa, quando): editar uma tarefa que já está aguardando não avisa de novo

def assinatura_ok(corpo, cabecalho):
    p = dict(x.split("=", 1) for x in cabecalho.split(",") if "=" in x)
    t = p.get("t", "")
    if not t.isdigit() or abs(time.time() - int(t)) > 300:
        return False
    esperado = hmac.new(SEGREDO.encode(), f"{t}.".encode() + corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, p.get("v1", ""))

def telegram(texto):
    dados = urllib.parse.urlencode({"chat_id": GRUPO, "text": texto}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{BOT}/sendMessage", dados, timeout=4)

class Nexus(BaseHTTPRequestHandler):
    def do_POST(self):
        corpo = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not assinatura_ok(corpo, self.headers.get("X-Nexus-Signature", "")):
            self.send_response(401); self.end_headers(); return
        ev = json.loads(corpo); d = ev.get("data") or {}
        if ev["action"] == "ping":
            telegram("Teste do Nexus Worklog: os avisos chegam neste grupo.")
        elif ev["entity"] == "worklog" and d.get("status") in QUANDO:
            rotulo, campo = QUANDO[d["status"]]
            if (d["id"], d.get(campo)) not in avisadas:
                avisadas.add((d["id"], d.get(campo)))
                motivo = f" ({d['blocked_reason']})" if d["status"] == "blocked" and d.get("blocked_reason") else ""
                telegram(f"{rotulo}: {d['title']}{motivo}")
        self.send_response(204); self.end_headers()

HTTPServer(("127.0.0.1", 8787), Nexus).serve_forever()
```

Pela automação: gatilho Webhook → filtro (`data.status` é `done` ou `blocked`) → ação “Telegram: enviar
mensagem” com `data.title`.

**7. Mandar e-mail a alguém quando algo acontecer.**

Pela automação (o mais simples): gatilho Webhook → filtro pela ação (`action` = `worklog.finish`, ou a que
quiser: `recurring.toggle`, `renewal.update`…) → ação “Enviar e-mail” (Gmail, Outlook ou SMTP) com
assunto `Concluída: {{data.title}}` e corpo `data.resolution`. No Nexus, crie o webhook com o endereço do
gatilho e só os eventos que interessam (ex.: `worklog.finish`). Testar: na automação, deixe o gatilho
“ouvindo” e aperte **Testar** no Nexus; o `ping` aparece como exemplo de dados para montar os campos.

Por script (precisa de uma conta SMTP: servidor, usuário e senha de app), mesmo jeito de rodar da
receita 6:

```python
# nexus_email.py: manda um e-mail quando uma tarefa é concluída.
import hashlib, hmac, json, os, smtplib, time
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, HTTPServer

SEGREDO = os.environ["NEXUS_WHSEC"]  # whsec_… mostrado ao criar o webhook
PARA = os.environ["AVISAR"]          # quem recebe
SMTP, USUARIO, SENHA = os.environ["SMTP_HOST"], os.environ["SMTP_USER"], os.environ["SMTP_PASS"]

def assinatura_ok(corpo, cabecalho):
    p = dict(x.split("=", 1) for x in cabecalho.split(",") if "=" in x)
    t = p.get("t", "")
    if not t.isdigit() or abs(time.time() - int(t)) > 300:
        return False
    esperado = hmac.new(SEGREDO.encode(), f"{t}.".encode() + corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, p.get("v1", ""))

def email(assunto, texto):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = USUARIO, PARA, assunto
    m.set_content(texto)
    with smtplib.SMTP(SMTP, 587, timeout=4) as s:
        s.starttls(); s.login(USUARIO, SENHA); s.send_message(m)

class Nexus(BaseHTTPRequestHandler):
    def do_POST(self):
        corpo = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not assinatura_ok(corpo, self.headers.get("X-Nexus-Signature", "")):
            self.send_response(401); self.end_headers(); return
        ev = json.loads(corpo); d = ev.get("data") or {}
        if ev["action"] == "ping":
            email("Teste do Nexus Worklog", "Se chegou, o aviso por e-mail está funcionando.")
        elif ev["action"] == "worklog.finish":
            email(f"Concluída: {d['title']}", d.get("resolution") or "Concluída, sem nota de como foi resolvida.")
        self.send_response(204); self.end_headers()

HTTPServer(("127.0.0.1", 8788), Nexus).serve_forever()
```

O Nexus já manda, sozinho, os avisos de prazo por e-mail à própria pessoa (Configurações > Avisos); esta
receita é para avisar **outra** pessoa, ou outro evento.

**8. Registrar cada tarefa concluída numa planilha (Google Sheets).**

Aqui a planilha **puxa** o feed (não recebe webhook): o Apps Script responde a um `POST` com
redirecionamento (302), que o Nexus conta como falha, e não deixa ler o cabeçalho da assinatura. Puxar
o feed com uma chave **Só leitura** não precisa de endereço público do lado da planilha e não perde
nada se ficar parado (até 180 dias). Precisa de: o Nexus acessível pela internet (o Google chama ele).

1. Na planilha, Extensões > Apps Script; cole o código abaixo.
2. Em Configurações do projeto > Propriedades do script, crie `NEXUS` e `CHAVE`.
3. Rode `puxarConcluidas` uma vez (autorize): ela marca o ponto de partida. Em Acionadores, adicione
   `puxarConcluidas`, “baseado no tempo”, a cada 5 minutos.
4. Testar: conclua uma tarefa no Nexus e rode `puxarConcluidas` de novo: aparece uma linha (data,
   título, projeto, como resolveu, referência externa).

```js
// Na planilha: Extensões > Apps Script. Em Configurações do projeto > Propriedades do script,
// crie NEXUS (https://SEU-HOST) e CHAVE (uma chave "Só leitura"). Fora do código, a chave
// não aparece para quem só abre o script.
function puxarConcluidas() {
  const props = PropertiesService.getScriptProperties();
  const nexus = props.getProperty("NEXUS");
  const opts = { headers: { Authorization: "Bearer " + props.getProperty("CHAVE") }, muteHttpExceptions: true };
  const ler = (caminho) => {
    const r = UrlFetchApp.fetch(nexus + caminho, opts);
    return { code: r.getResponseCode(), json: () => JSON.parse(r.getContentText()) };
  };
  let cursor = props.getProperty("cursor");
  if (cursor === null) {  // 1ª vez: começa do agora (o passado não vira linha)
    const ultimo = ler("/api/history?limit=1").json()[0];
    props.setProperty("cursor", String(ultimo ? ultimo.id : 0));
    return;
  }
  const r = ler(`/api/history?after=${cursor}&limit=200`);
  if (r.code === 410) { props.deleteProperty("cursor"); return; }  // parada há mais de 180 dias
  if (r.code !== 200) throw new Error("Nexus respondeu HTTP " + r.code);
  const aba = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  for (const ev of r.json()) {
    if (ev.action === "worklog.finish") {
      const t = ler("/api/worklog/" + ev.entity_id);
      if (t.code === 200) {
        const d = t.json();
        aba.appendRow([ev.at, d.title, d.project_name || "", d.resolution || "", d.external_ref || ""]);
      }
    }
    props.setProperty("cursor", String(ev.id));  // linha a linha: um erro no meio não repete as anteriores
  }
}
```

Prefere na hora, por webhook? Use a automação: gatilho Webhook → filtro `action` = `worklog.finish` →
“Google Sheets: adicionar linha” com `at`, `data.title`, `data.resolution`, `data.external_ref`. Aí o
**Testar** vale: o `ping` chega com `"test": true` (filtre para não virar linha).

**9. Alerta de monitoramento vira tarefa.** É a receita 1 (criar com `external_ref` = id do alerta, sem
duplicar) e a 2 (concluir pela referência quando o alerta normalizar). Na ferramenta de monitoramento,
configure o envio de alerta “por webhook/HTTP” para fazer essas chamadas com uma chave `write`.
