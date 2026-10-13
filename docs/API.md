# Referência da API

API REST do Shadow Nexus Worklog, sob **`/api`**, mais o servidor MCP em
**`/mcp`**. O Swagger/OpenAPI fica **desligado de propósito** — esta página é a
referência. Campos e limites exatos de cada corpo: os modelos Pydantic em
`backend/app/schemas.py`. Corpos e respostas em JSON; datas `AAAA-MM-DD` no fuso
`APP_TZ`; timestamps ISO 8601 com fuso.

## Autenticação

### Chave de API — para IA, scripts e automações

Crie em **Configurações › IA e API**. A chave (`nxs_…`) aparece **uma vez**; o
servidor guarda só o HMAC.

```
Authorization: Bearer nxs_...
```

- Sem cookie e sem CSRF. Escopo `write` (lê e altera) ou `read` (escrita → 403).
- Validade de 1 a 365 dias ou sem validade; revogável. 240 req/min por pessoa, somando as chaves (429).
- Trocar a própria senha (ou o reset pelo admin) revoga todas as chaves e o link do calendário.
- Uma chave **nunca** acessa `/api/admin/*`, `/api/tokens`, `/api/calendar`,
  `/api/notifications` nem troca senha. Tudo o que ela fizer vai para o
  histórico com o nome dela.

### Sessão do app — o que o frontend usa

- Cookie `session` `HttpOnly; Secure; SameSite=Strict`, prazo fixo de
  `SESSION_TTL_DAYS` (padrão 7); depois disso, novo login.
- O login e `GET /api/auth/me` devolvem `csrf_token`; **toda mutação** exige o
  header `X-CSRF-Token` (senão 403).

**Papéis:** `user` e `admin`. Todo dado é filtrado por `user_id`; `/api/admin/*`
exige admin com sessão do app.

| Código | Quando |
| --- | --- |
| 400 | regra de negócio (ex.: dia fora da janela, nada a atualizar) |
| 401 | sem sessão/chave válida |
| 403 | CSRF, troca de senha pendente, chave em rota só do app, não-admin |
| 404 | não existe ou não é seu |
| 409 | conflito (nome repetido, desfazer fora de ordem, tarefa com filhos) |
| 422 | corpo inválido |
| 413 / 415 | logo grande demais / tipo de arquivo não aceito |
| 429 | limite de tentativas/requisições (login, troca de senha, chave, PDF, teste de e-mail, feed ICS) |
| 502 / 503 | envio de e-mail falhou / e-mail não configurado |

Legenda: **S** = só sessão do app · **W** = exige escopo `write` (chave) ou CSRF (sessão).

## Conta — `/api/auth`

| Rota | | Corpo / observação |
| --- | --- | --- |
| `POST /login` | público | `{email, password}` → identidade + `csrf_token`; limite por IP e por e-mail (falhas) |
| `POST /logout` | S W | |
| `GET /me` | | `{id, email, display_name, name, avatar, assistant, role, must_change_password, work_days, tz, csrf_token}` — `name` é o de exibição ou, sem ele, o derivado do e-mail |
| `POST /change-password` | S W | `{current_password, new_password}`; encerra as outras sessões e revoga chaves e calendário |
| `POST /settings` | W | `{work_days}` — máscara, domingo = bit 0 (seg–sex = 62). Não reescreve o passado: rotinas "dias úteis" com história são encerradas com os dias antigos e recomeçam hoje; não se desfaz pelo histórico |

## Perfil e assistente — `/api/me` (só pelo app)

| Rota | | Corpo / observação |
| --- | --- | --- |
| `PUT /profile` | S W | `{display_name}` (até 60; vazio = volta ao nome do e-mail) |
| `POST /avatar` · `DELETE /avatar` | S W | corpo bruto PNG, JPEG ou WebP até 256 KB (tipo pelo conteúdo; SVG não). O app recorta e reduz antes |
| `GET /avatar/{user_id}?v=` | S | a própria foto; o admin vê a de todos |
| `PUT /assistant` | S W | `{enabled, idle_on, idle_minutes (5–480), idle_start, idle_end}` — janela em minutos do dia |
| `GET /activity` | S | `{last_activity, timer}`: último registro de qualquer origem (tarefa, rotina, anotação, checklist, tempo, cronômetro) e o cronômetro rodando |
| `PUT /tickets` | S W | `{ticket_url}` — endereço do sistema de chamados; `{id}` vira o número (sem `{id}`, vai no fim) |

## Cronômetro e modelos

| Rota | | Corpo / observação |
| --- | --- | --- |
| `GET /api/timer` | | `{timer}`: `{task_id, title, started_at}` ou null (um por pessoa, vale em qualquer aparelho) |
| `POST /api/timer/start` | W | `{task_id}` — tarefa aberta; se outro estiver rodando, ele para e aponta (`stopped`). "A fazer" vira "em andamento" |
| `POST /api/timer/stop` | W | para e aponta o tempo (nota "cronômetro", no dia em que começou); concluir a tarefa também para |
| `DELETE /api/timer` | W | descarta sem apontar |
| `GET /api/templates` · `POST` · `PUT /{id}` · `DELETE /{id}` | (W) | `{name, title, description, priority, project_id, after_hours, checklist: [itens]}` — até 50 modelos, 30 itens |
| `POST /api/templates/{id}/use` | W | cria a tarefa do modelo, com o checklist |

## Hoje e quadro

| Rota | | Observação |
| --- | --- | --- |
| `GET /api/board?day=&project=` | | `day` até 7 dias atrás (padrão hoje); `project` filtra as tarefas (`0` = sem projeto). Devolve `recurring` (com `due`, `done_today`, agenda), `in_progress` (tarefas abertas: a fazer, em andamento, bloqueadas; com `touched_at`, o último movimento), `timer`, `done`, `day`, `today`, `min_day`, `work_day` |
| `GET /api/summary` | | `last_day` (do último dia útil até ontem), `week` (com `previous` = mesmos dias da semana passada) e `today_stats` (o dia de hoje): rotinas, tarefas concluídas, minutos, por projeto, rotinas não feitas |
| `GET /api/dashboard` | | retrospectiva: `heatmap` (4 semanas), `task_adherence` (30 dias, a mais pulada primeiro), `throughput`, `projects` (tempo, 30 dias), `backlog` |

## Rotinas — `/api/recurring`

| Rota | | Corpo |
| --- | --- | --- |
| `POST /` | W | `{label, freq?, weekdays?, month_day?, interval_days?}` |
| `PATCH /{id}` | W | `{label?, freq?…}` — mudar a agenda exige `freq` + o parâmetro dela; se a rotina já tem passado, ela é encerrada hoje e uma nova (devolvida em `id`) começa hoje — uma ação só no histórico |
| `DELETE /{id}` | W | remove daqui para a frente (o passado fica) |
| `POST /{id}/toggle` | W | `{done, day?}` — `day` até 7 dias atrás e só quando a rotina existia |

Agenda: `daily` (dias úteis do dono) · `weekly` + `weekdays` (máscara) ·
`monthly` + `month_day` (1–31; 31 = último dia) · `interval` + `interval_days`
(2–365, contando da criação). Feito fora da agenda = **extra** (não entra no %).

## Tarefas — `/api/worklog`

| Rota | | Corpo / observação |
| --- | --- | --- |
| `POST /` | W | `{title, description?, status?, due_date?, project_id?, priority?, ticket?, after_hours?}` (prioridade 1 alta, 2 normal, 3 baixa; `ticket` = número do chamado, sem o "#"; `after_hours` = plantão) |
| `GET /{id}` | | tarefa + `checklist`, `notes`, `time`, `minutes`, `today` |
| `PATCH /{id}` | W | campos a mudar; `description`/`due_date`/`project_id`/`ticket` = `null` apaga |
| `POST /{id}/finish` | W | conclui (com o cronômetro rodando nela, ele para e aponta) |
| `DELETE /{id}` | W | exclui junto anotações, checklist e tempo (o desfazer devolve tudo) |
| `POST /{id}/notes` | W | `{body}` (até 2000) |
| `DELETE /api/notes/{id}` | W | |
| `POST /{id}/checklist` | W | `{label}` |
| `PATCH /api/checklist/{id}` | W | `{label?, done?}` |
| `DELETE /api/checklist/{id}` | W | |
| `POST /{id}/time` | W | `{minutes, day?, note?}` — 1–1440 min; até 366 dias atrás, nunca no futuro; máx. 24h somadas por dia |
| `DELETE /api/time/{id}` | W | |

## Projetos — `/api/projects`

| Rota | | Corpo |
| --- | --- | --- |
| `GET /?include_archived=` | | com `open_tasks` e `total_tasks` |
| `POST /` | W | `{name, color?}` — nome único por usuário (409) |
| `PATCH /{id}` | W | `{name?, color?, archived?}` |
| `DELETE /{id}` | W | as tarefas ficam sem projeto (o desfazer as devolve) |

## Relatórios, busca e exportação

| Rota | | Observação |
| --- | --- | --- |
| `GET /api/reports/export?start=&end=&project=` | | PDF (até 6 por minuto). Período até 366 dias (fim limitado a hoje). Com `project` e sem datas: o projeto inteiro (até ~3 anos) |
| `GET /api/reports/preview?start=&end=&project=` | | o que o PDF traria: tarefas concluídas, minutos, rotinas, dias com atividade |
| `GET /api/search?q=` | | 2–100 caracteres, sem acento: tarefas (com onde casou), rotinas, projetos |
| `GET /api/export/apontamentos.csv` | | CSV `;` + BOM (Excel BR) |
| `GET /api/export/tarefas.csv` | | idem |
| `GET /api/export/tudo.json` | | tarefas com anotações/checklist/tempo, rotinas com dias feitos, projetos |

## Histórico — `/api/history`

| Rota | | Observação |
| --- | --- | --- |
| `GET /?limit=&entity=&entity_id=` | | quem fez (app, chave, IA, admin), o quê, `can_undo` |
| `POST /{id}/undo` | W | só a ação mais recente de cada item; criação de tarefa que já tem filhos → 409 |

## Calendário, avisos e chaves (só pelo app)

| Rota | | Observação |
| --- | --- | --- |
| `GET /api/calendar` | S | estado do link |
| `POST /api/calendar` | S W | `{include_recurring}` — cria/troca o link e devolve `path` uma vez |
| `PATCH /api/calendar` · `DELETE /api/calendar` | S W | |
| `GET /api/calendar/{nxc_…}.ics` | público (segredo no link) | prazos (dia inteiro, sem a descrição) e rotinas (RRULE) |
| `GET /api/notifications` · `PUT /api/notifications` | S (W) | `{morning, morning_hour, evening, evening_hour, weekly, weekly_hour, show_titles}` |
| `POST /api/notifications/test` | S W | manda um teste para o e-mail da conta (503 sem SMTP) |
| `GET /api/tokens` · `POST /api/tokens` · `DELETE /api/tokens/{id}` | S (W) | `{name, scope, expires_in_days}`; até 20 ativas |

## Identidade visual

| Rota | | Observação |
| --- | --- | --- |
| `GET /api/branding` · `GET /api/branding/logo` | público | textos do lockup e logo (servido em sandbox) |
| `PUT /api/admin/branding` | admin W | `{line1, line2}` |
| `POST /api/admin/branding/logo` | admin W | corpo = a imagem (PNG, WebP ou SVG seguro, até 256 KB) |
| `DELETE /api/admin/branding/logo` | admin W | volta ao dragão |

## Admin — `/api/admin`

| Rota | | Observação |
| --- | --- | --- |
| `GET /users` | | lista |
| `POST /users` | W | `{email}` → senha temporária (troca no 1º acesso) |
| `GET /users/{id}/board` · `/dashboard` · `/projects` · `/reports/export` | | visão só leitura do usuário |
| `POST /users/{id}/reset-password` | W | senha temporária; encerra sessões e revoga chaves e calendário |
| `GET /export/apontamentos.csv` | | horas de todos, com coluna `usuario` |

## MCP — `POST /mcp`

JSON-RPC 2.0 sobre HTTP, **uma mensagem por requisição** (sem lote, sem SSE),
`Authorization: Bearer nxs_…`. Versões: 2025-11-25, 2025-06-18, 2025-03-26.

Leitura: `get_today`, `get_summary`, `list_tasks`, `get_task`, `search`,
`list_projects`, `list_recurring`, `list_templates`, `get_history`.
Escrita (chave `write`): `create_task`, `update_task` (ambas com `ticket` e `after_hours`), `complete_task`,
`add_note`, `add_checklist_item`, `set_checklist_item`, `log_time`, `start_timer`, `stop_timer`,
`create_from_template`, `set_recurring` (`recurring_id`), `undo` (só ações da própria chave). A IA não exclui o que o usuário fez.

Prompts (`prompts/list`, `prompts/get`): `resumo_semanal` (argumento `para`: gestor, time, cliente) e `daily`.
No Claude Code viram `/mcp__nexus__resumo_semanal` e `/mcp__nexus__daily`.

```bash
claude mcp add --transport http nexus https://SEU-HOST/mcp --header "Authorization: Bearer nxs_SUA_CHAVE"
```
