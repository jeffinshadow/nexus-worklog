# Shadow Nexus Worklog

Worklog pessoal **multiusuário**, self-hosted, sem frameworks JS e sem
dependências externas em runtime. Deploy por `git push` + `docker compose`.
Prioridades: **simples > seguro > funcional > elegante**.

Cada usuário cria a própria conta e vê **apenas** os próprios dados. Um único
**admin master** pode consultar (somente leitura) o board, o dashboard e os
relatórios de qualquer usuário.

## Arquitetura (3 containers + túnel no host)

```
Internet ──► cloudflared (host) ──► web (nginx) ──► backend (FastAPI) ──► db (Postgres)
             systemd, sem portas    127.0.0.1:80        │                  │
             abertas na VM          estático + /api   auth/CRUD/agreg.   rede interna,
                                    + headers                            porta não exposta
```

- **db** — PostgreSQL, volume nomeado, porta **não** exposta ao host.
- **backend** — FastAPI, **não** exposto à internet; só o nginx o acessa.
- **web** — nginx: serve o frontend, faz proxy de `/api/*` e aplica os headers
  de segurança (CSP rígida, HSTS, etc.).
- **cloudflared** — instalado no host (pacote oficial + serviço systemd), fora do
  compose: **única** exposição à internet. O nginx só escuta no loopback.

## Stack

Frontend: HTML/CSS/JS vanilla, **zero frameworks**, sem build step. Material
Design 3 via design tokens (CSS custom properties), tema claro/escuro.
Backend: FastAPI + psycopg3, senhas com **Argon2id**, sessão server-side em
cookie `HttpOnly; Secure; SameSite=Strict`, CSRF por header, rate limit no
login. Banco: PostgreSQL (schema SQL idempotente aplicado no startup).

---

## Setup local

Pré-requisitos: Docker + Docker Compose.

1. **Crie o `.env`** a partir do exemplo (este arquivo **não** vai para o git):

   ```bash
   cp .env.example .env
   ```

2. **Gere uma SECRET_KEY forte** e cole em `SECRET_KEY` no `.env`:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(64))"
   # ou:  openssl rand -base64 48
   ```

3. **Defina** `POSTGRES_PASSWORD`, mantenha o mesmo valor no `DATABASE_URL`, e
   escolha `ADMIN_EMAIL` / `ADMIN_INITIAL_PASSWORD`.

4. **Teste local sem HTTPS?** Deixe `COOKIE_SECURE=false` no `.env` (o cookie
   `Secure` não trafega em HTTP). Em produção (via túnel) use `true`.

5. Suba tudo:

   ```bash
   docker compose up -d --build
   ```

   O backend aplica o schema (`backend/sql/*.sql`) e faz o **seed do admin** no
   primeiro start.

6. Para testar sem o túnel, exponha o nginx temporariamente adicionando ao
   serviço `web` no `docker-compose.yml`:

   ```yaml
       ports: ["8080:80"]
   ```

   e acesse `http://localhost:8080`. **Remova** antes de produção.

### Primeiro acesso do admin

1. Vá em **Entrar** e use `ADMIN_EMAIL` + `ADMIN_INITIAL_PASSWORD`.
2. O sistema **obriga a troca de senha** no primeiro login.
3. Depois de trocar, a aba **Admin** fica disponível (seletor de usuário).

Usuários comuns usam **Criar conta** na tela de acesso.

---

## Arquivos que o operador cria localmente e que **NÃO** vão para o git

Já cobertos pelo `.gitignore`:

| Arquivo/dir            | Conteúdo sensível                                          |
| ---------------------- | ---------------------------------------------------------- |
| `.env`                 | `POSTGRES_PASSWORD`, `SECRET_KEY`, `ADMIN_*`               |
| `/etc/cloudflared/*.env` (no host) | token do Cloudflare Tunnel, fora do repositório |
| volume `pgdata`        | dados do Postgres (gerenciado pelo Docker)                 |

O repositório versiona apenas o `.env.example` com
**placeholders**. Nenhum segredo é hardcoded no código.

---

## Deploy (OCI + Cloudflare Tunnel)

1. Numa VM (ex.: Oracle Cloud Always Free), instale Docker + Compose e clone o
   repositório público.
2. Crie o `.env` na VM (nunca versionado) com `COOKIE_SECURE=true`.
3. `docker compose up -d --build`. O nginx fica em `127.0.0.1:${WEB_PORT}`
   (padrão 80), sem nenhuma porta pública.
4. **Túnel no host**: instale o `cloudflared` pelo repositório oficial
   (pkg.cloudflare.com) e rode-o como serviço systemd com o token do túnel em
   `/etc/cloudflared/<nome>.env` (`TUNNEL_TOKEN=...`, dono root, modo 600).
   No Zero Trust (Networks → Tunnels), aponte o *public hostname* para
   `http://localhost:80`.
5. Atualizações: `./deploy.sh` (verifica dependências, `git pull --ff-only`,
   rebuild e mostra o estado dos serviços). Na primeira vez, numa VM limpa
   Debian/Ubuntu, use `./deploy.sh --install` para instalar Docker/Git via
   repositório oficial. O script recusa subir se o `.env` ainda tiver
   placeholders `CHANGEME`.

### Cloudflare Access (opcional, camada extra)

Você pode proteger o hostname com uma policy do **Cloudflare Access** (e-mail
OTP, SSO, etc.) além do login da aplicação. É **defesa em profundidade** — a
autenticação principal continua sendo a da aplicação (contas + sessão).

---

## Segurança (resumo)

- **Senhas**: Argon2id (`argon2-cffi`). Política mínima de 10 caracteres.
- **Sessão**: server-side (`sessions`); o cookie carrega um token aleatório e o
  banco guarda apenas `HMAC-SHA256(SECRET_KEY, token)`. Cookie
  `HttpOnly; Secure; SameSite=Strict`, expiração deslizante (`SESSION_TTL_DAYS`).
- **CSRF**: token por sessão exigido no header `X-CSRF-Token` em toda mutação
  (além de `SameSite=Strict`).
- **Autorização**: toda query filtra por `user_id`. Rotas `/api/admin/*` exigem
  `role='admin'` verificado **no backend**; usuário comum recebe **403**. A
  decisão de permissão é centralizada em `backend/app/deps.py`.
- **Rate limit** no login (por IP e por e-mail).
- **nginx**: CSP sem `unsafe-inline`/`unsafe-eval`, HSTS, `X-Content-Type-Options`,
  `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`.
- **Sem tracking**: apenas o cookie de sessão; nenhuma dependência de terceiros
  em runtime (Roboto Flex e ícones são self-hosted).
- Postgres sem porta no host; backend sem exposição pública; docs da API
  desabilitadas.

## Modelo de dados

`users`, `sessions`, `recurring_tasks`, `recurring_completions`, `worklog_tasks`
— ver `backend/sql/001_schema.sql`. Tudo em `TIMESTAMPTZ`, índices em `user_id`.
A semana começa no **domingo** (agregações ajustadas no `services.py`).

## Estrutura

```
backend/  FastAPI (app/ + sql/)   — auth, CRUD, agregações, rotas admin
web/      nginx + static/         — login, board, relatórios, dashboard, admin
docs/     referência da API
docker-compose.yml, .env.example, .gitignore
```

A referência completa da API REST (`/api/*`) está em **[`docs/API.md`](docs/API.md)**
— útil já que o Swagger/OpenAPI interativo é desabilitado de propósito.

## Notas

- Fonte: coloque `web/static/fonts/RobotoFlex.woff2` (ver README na pasta). Sem
  o arquivo, usa a fonte do sistema — nada quebra.
- Fuso horário da aplicação em `APP_TZ` (define "hoje", semana e mês).
