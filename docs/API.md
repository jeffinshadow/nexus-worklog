# Referência da API

API REST do Shadow Nexus Worklog. Todas as rotas ficam sob o prefixo **`/api`** e
são servidas pelo backend (FastAPI) atrás do nginx. As docs interativas
(Swagger/OpenAPI) são **desabilitadas de propósito** (`docs_url=None` em
`main.py`) — esta página é a referência.

> Base: mesmo domínio do app (ex.: `https://seu-host/api/...`). Corpos são JSON
> (`Content-Type: application/json`), respostas também.

## Autenticação

Há dois jeitos de se autenticar:

### 1. Chave de API (para IA, scripts e automações) — recomendado fora do navegador

Crie em **Configurações → Chaves de API** no app. A chave (`nxs_...`) aparece
**uma única vez**; o servidor guarda só um hash. Mande em toda requisição:

```
Authorization: Bearer nxs_...
```

- **Sem CSRF e sem cookie.** Não use mais e-mail/senha em ferramentas de IA.
- **Escopo:** `write` (lê e altera) ou `read` (só lê; escrita → **403**).
- **Validade** de 1 a 365 dias (padrão 90) ou sem validade; revogue no app.
- Limite: 240 requisições por minuto por chave (**429** ao passar).
- Uma chave **nunca** acessa `/api/admin/*`, `/api/tokens` nem troca a senha.
- Tudo que a chave alterar fica no **histórico** com o nome dela.

### 2. Sessão do app (o que o frontend usa)

A sessão é **server-side**, transportada por um cookie:

- **Cookie `session`** — `HttpOnly; Secure; SameSite=Strict`, expiração
  deslizante (`SESSION_TTL_DAYS`, padrão 7 dias). O front nunca lê esse cookie;
  o navegador o envia sozinho (mande as requisições com credenciais —
  `fetch(..., { credentials: "same-origin" })`).
- **CSRF** — o login (e `GET /api/auth/me`) devolvem um `csrf_token`. **Toda
  mutação** (`POST`, `PATCH`, `DELETE`) exige esse valor no header
  **`X-CSRF-Token`**. Sem ele → **403**. (`POST /login` é a exceção: ainda não
  existe sessão.)

**Fluxo típico do front:**

1. `POST /api/auth/login` → guarda o cookie (automático) e o `csrf_token`.
2. Nas escritas seguintes, envia o header `X-CSRF-Token: <csrf_token>`.
3. No boot, `GET /api/auth/me` confirma se a sessão ainda vale (401 se não).

**Papéis:** `user` (comum) e `admin`. Todo dado é filtrado por `user_id` no
backend — um usuário só enxerga/altera o que é dele. As rotas `/api/admin/*`
exigem `role = "admin"` e sessão do app (senão **403**).

### Códigos de status comuns

| Código | Significado |
| ------ | ----------- |
| `401`  | não autenticado / sessão inválida ou expirada |
| `403`  | CSRF inválido, troca de senha obrigatória, ou acesso restrito a admin |
| `404`  | recurso não encontrado (ou não pertence ao usuário) |
| `409`  | conflito (ex.: e-mail já cadastrado) |
| `422`  | corpo inválido (validação Pydantic) |
| `429`  | rate limit (login) |

---

## Auth — `/api/auth`

### `POST /api/auth/register` → `201`
Cria uma conta comum (`role = "user"`).
```json
{ "email": "user@exemplo.com", "password": "senha-forte-10+" }
```
Resposta: `{ "ok": true }`. Erros: `409` (e-mail já cadastrado), `422` (senha
fora de 10–128 caracteres).

### `POST /api/auth/login`
```json
{ "email": "user@exemplo.com", "password": "..." }
```
Sucesso (`200`): grava o cookie `session` e devolve a identidade + o CSRF:
```json
{ "id": 1, "email": "user@exemplo.com", "role": "user",
  "must_change_password": false, "csrf_token": "..." }
```
Erros: `401` (credenciais inválidas), `429` (muitas tentativas — limite por IP e
por e-mail).

### `POST /api/auth/logout`  · *auth + CSRF*
Encerra a sessão atual e limpa o cookie. Resposta: `{ "ok": true }`.

### `GET /api/auth/me`  · *auth*
Identidade da sessão atual (usado no boot). Mesmo corpo do login. `401` se o
cookie não valer mais.

### `POST /api/auth/change-password`  · *auth + CSRF*
```json
{ "current_password": "...", "new_password": "nova-senha-10+" }
```
Troca a senha e encerra as **outras** sessões do usuário (mantém a atual).
Erros: `400` (senha atual incorreta ou nova senha fraca).

---

## Board — `/api/board`

### `GET /api/board`  · *auth*
Quadro completo do usuário, em três listas:
```json
{
  "recurring":   [ { "id": 1, "label": "...", "position": 0, "done_today": false } ],
  "in_progress": [ { "id": 9, "title": "...", "description": "...",
                     "status": "in_progress", "due_date": null,
                     "created_at": "2026-08-19T18:26:39Z" } ],
  "done":        [ { "id": 3, "title": "...", "description": "...", "status": "done",
                     "due_date": null, "created_at": "...", "completed_at": "..." } ]
}
```
`in_progress` traz as tarefas pontuais **não** concluídas (status ≠ `done`);
`done` traz as concluídas.

---

## Worklog (tarefas pontuais) — `/api/worklog`

`status` ∈ `todo` | `in_progress` | `blocked` | `done`. *Todas as rotas: auth + CSRF.*

### `POST /api/worklog` → `201`
```json
{ "title": "Título (1–200)", "description": "opcional (≤300)",
  "status": "todo", "due_date": "2026-09-30" }
```
Só `title` é obrigatório (`status` assume `todo`). Resposta: `{ "id": 42 }`.

### `PATCH /api/worklog/{id}`
Atualização parcial — envie só os campos a mudar (`title`, `description`,
`status`, `due_date`). Passar `status: "done"` carimba `completed_at`; sair de
`done` limpa. Resposta: `{ "ok": true }`. `404` se não for sua / não existir;
`400` se o corpo não trouxer nada.

### `POST /api/worklog/{id}/finish`
Atalho: marca `status = "done"` e preenche `completed_at`. `{ "ok": true }` /
`404`.

### `DELETE /api/worklog/{id}`
Remove a tarefa. `{ "ok": true }` / `404`.

---

## Recorrentes (tarefas diárias) — `/api/recurring`

*Todas: auth + CSRF.*

### `POST /api/recurring` → `201`
```json
{ "label": "Texto da tarefa recorrente (1–200)" }
```
Resposta: a tarefa criada.

### `PATCH /api/recurring/{id}`
Campos opcionais: `label`, `active` (bool), `position` (int). `{ "ok": true }`.

### `DELETE /api/recurring/{id}`
Desativa a recorrente. `{ "ok": true }`.

### `POST /api/recurring/{id}/toggle`
Marca/desmarca a recorrente como feita **hoje**:
```json
{ "done": true }
```
Resposta: `{ "ok": true, "done": true }`.

---

## Dashboard — `/api/dashboard`

### `GET /api/dashboard`  · *auth*
Agregações do usuário (contadores por status, recorrentes do dia, etc.). A
semana começa no **domingo** (ver `services.py`).

---

## Relatórios — `/api/reports`

### `GET /api/reports/export?start=YYYY-MM-DD&end=YYYY-MM-DD`  · *auth*
Gera um **PDF** do período (`Content-Type: application/pdf`,
`Content-Disposition: attachment`).

---

## Admin — `/api/admin`

Somente `role = "admin"` (verificado no backend). Leitura dos dados de qualquer
usuário; a única mutação é o reset de senha.

### `GET /api/admin/users`  · *admin*
Lista os usuários.

### `GET /api/admin/users/{user_id}/board`  · *admin*
Board de um usuário (mesmo formato de `/api/board`).

### `GET /api/admin/users/{user_id}/dashboard`  · *admin*
Dashboard de um usuário.

### `GET /api/admin/users/{user_id}/reports/export?start=...&end=...`  · *admin*
PDF de um usuário.

### `POST /api/admin/users/{user_id}/reset-password`  · *admin + CSRF*
Gera uma senha temporária (usuário fica com `must_change_password`).
Resposta: `{ "email": "...", "temp_password": "..." }`.


---

## Chaves de API — `/api/tokens` (só pelo app)

### `GET /api/tokens`
Lista as chaves do usuário: `id, name, prefix, scope, created_at, expires_at,
last_used_at, revoked_at, active`. Nunca devolve a chave completa.

### `POST /api/tokens` → `201`
```json
{ "name": "Claude do Kaique", "scope": "write", "expires_in_days": 90 }
```
`expires_in_days` de 1 a 365, ou `null` para sem validade. Resposta inclui
`"token": "nxs_..."` — **única vez** em que a chave aparece. Máximo de 20 ativas.

### `DELETE /api/tokens/{id}`
Revoga a chave na hora.

## Histórico — `/api/history`

### `GET /api/history?limit=50&entity=worklog&entity_id=12`
Ações na conta, da mais recente para a mais antiga: `id, created_at, actor`
(`web` app, `api` chave, `mcp` IA, `admin`), `token_name`, `action`, `entity`,
`entity_id`, `summary` (texto pronto), `undone`, `can_undo`.

### `POST /api/history/{id}/undo`
Desfaz a ação. Só vale para a **mais recente de cada item** (senão **409**) e
para criar/editar/concluir/excluir tarefa, criar/editar/remover/marcar
recorrente e alterar dias úteis. O próprio desfazer entra no histórico.

## MCP — `POST /mcp`

Servidor [Model Context Protocol](https://modelcontextprotocol.io) para IAs
(Claude Code, Cursor, etc.). Transporte *Streamable HTTP* com resposta JSON,
autenticado **só por chave de API**. Exemplo no Claude Code:

```bash
claude mcp add --transport http nexus https://nexus.shadow.tec.br/mcp \
  --header "Authorization: Bearer nxs_..."
```

Ferramentas: `get_today`, `list_tasks`, `list_recurring`, `get_history`
(leitura) e `create_task`, `update_task`, `complete_task`, `set_recurring`,
`undo` (escrita; chaves `read` não as veem). A IA **não exclui** tarefas.
Tudo que ela fizer aparece no histórico como `mcp` com o nome da chave.
