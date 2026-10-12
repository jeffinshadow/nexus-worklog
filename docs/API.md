# Referência da API

API REST do Shadow Nexus Worklog, sob **`/api`**, mais o servidor MCP em
**`/mcp`**. O Swagger/OpenAPI fica **desligado de propósito** — esta página é a
referência. Campos e limites exatos de cada corpo: os modelos Pydantic em
`backend/app/schemas.py` e, para avisos e calendário, no próprio router. Corpos e respostas em JSON; datas `AAAA-MM-DD` no fuso
`APP_TZ`; timestamps ISO 8601 com fuso.

## Autenticação

### Chave de API — para IA, scripts e automações

Crie em **Configurações › IA e API**. A chave (`nxs_…`) aparece **uma vez**; o
servidor guarda só o HMAC.

```
Authorization: Bearer nxs_...
```

- Sem cookie e sem CSRF. Escopo `write` (lê e altera) ou `read` (escrita → 403).
- Validade de 1 a 365 dias ou sem validade; revogável. 240 req/min por chave (429).
- Trocar a própria senha (ou o reset pelo admin) revoga todas as chaves e o link do calendário.
- Uma chave **nunca** acessa `/api/admin/*`, `/api/tokens`, `/api/calendar`,
  `/api/notifications` nem troca senha. Tudo o que ela fizer vai para o
  histórico com o nome dela. O reset de senha pelo admin revoga as chaves.

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
| 429 | limite de tentativas/requisições (login, chave, PDF) |
| 502 / 503 | envio de e-mail falhou / e-mail não configurado |

Legenda: **S** = só sessão do app · **W** = exige escopo `write` (chave) ou CSRF (sessão).

## Conta — `/api/auth`

| Rota | | Corpo / observação |
| --- | --- | --- |
| `POST /login` | público | `{email, password}` → identidade + `csrf_token`; limite por IP e por e-mail (falhas) |
| `POST /logout` | S W | |
| `GET /me` | | `{id, email, role, must_change_password, work_days, tz, csrf_token}` |
| `POST /change-password` | S W | `{current_password, new_password}`; encerra as outras sessões e revoga chaves e calendário |
| `POST /settings` | W | `{work_days}` — máscara, domingo = bit 0 (seg–sex = 62) |

## Hoje e quadro

| Rota | | Observação |
| --- | --- | --- |
| `GET /api/board?day=&project=` | | `day` até 7 dias atrás (padrão hoje); `project` filtra as tarefas (`0` = sem projeto). Devolve `recurring` (com `due`, `done_today`, agenda), `in_progress` (tarefas abertas: a fazer, em andamento, bloqueadas), `done`, `day`, `today`, `min_day`, `work_day` |
| `GET /api/summary` | | `last_day` (do último dia útil até ontem) e `week` (com `previous` = mesmos dias da semana passada): rotinas, tarefas concluídas, minutos, por projeto, rotinas não feitas |
| `GET /api/dashboard` | | indicadores dia/semana/mês e séries dos gráficos |

## Rotinas — `/api/recurring`

| Rota | | Corpo |
| --- | --- | --- |
| `POST /` | W | `{label, freq?, weekdays?, month_day?, interval_days?}` |
| `PATCH /{id}` | W | `{label?, freq?…}` — mudar a agenda exige `freq` + o parâmetro dela; se a rotina já tem passado, ela é encerrada hoje e uma nova (devolvida em `id`) começa hoje |
| `DELETE /{id}` | W | remove daqui para a frente (o passado fica) |
| `POST /{id}/toggle` | W | `{done, day?}` — `day` até 7 dias atrás e só quando a rotina existia |

Agenda: `daily` (dias úteis do dono) · `weekly` + `weekdays` (máscara) ·
`monthly` + `month_day` (1–31; 31 = último dia) · `interval` + `interval_days`
(2–365, contando da criação). Feito fora da agenda = **extra** (não entra no %).

## Tarefas — `/api/worklog`

| Rota | | Corpo / observação |
| --- | --- | --- |
| `POST /` | W | `{title, description?, status?, due_date?, project_id?, priority?}` (prioridade 1 alta, 2 normal, 3 baixa) |
| `GET /{id}` | | tarefa + `checklist`, `notes`, `time`, `minutes`, `today` |
| `PATCH /{id}` | W | campos a mudar; `description`/`due_date`/`project_id` = `null` apaga |
| `POST /{id}/finish` | W | conclui |
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
| `GET /api/calendar/{nxc_…}.ics` | público (segredo no link) | prazos (dia inteiro) e rotinas (RRULE) |
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
| `GET /users/{id}/board` · `/dashboard` · `/reports/export` | | visão só leitura do usuário |
| `POST /users/{id}/reset-password` | W | senha temporária; encerra sessões e revoga chaves e calendário |
| `GET /export/apontamentos.csv` | | horas de todos, com coluna `usuario` |

## MCP — `POST /mcp`

JSON-RPC 2.0 sobre HTTP, **uma mensagem por requisição** (sem lote, sem SSE),
`Authorization: Bearer nxs_…`. Versões: 2025-11-25, 2025-06-18, 2025-03-26.

Leitura: `get_today`, `get_summary`, `list_tasks`, `get_task`, `search`,
`list_projects`, `list_recurring`, `get_history`.
Escrita (chave `write`): `create_task`, `update_task`, `complete_task`,
`add_note`, `add_checklist_item`, `set_checklist_item`, `log_time`,
`set_recurring` (`recurring_id`), `undo`. A IA não exclui tarefas.

```bash
claude mcp add --transport http nexus https://SEU-HOST/mcp --header "Authorization: Bearer nxs_SUA_CHAVE"
```
