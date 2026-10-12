# Shadow Nexus Worklog

Registro do dia de trabalho para profissionais de TI — suporte, infraestrutura,
redes, segurança, desenvolvimento — e para quem precisa do relatório deles.
Multiusuário, auto-hospedado, sem frameworks JS nem passo de build.
Prioridades: **simples > seguro > funcional > elegante**.

Cada pessoa vê **apenas** os próprios dados. As contas são criadas pelo
**admin** (convite com senha temporária); o admin consulta, só para leitura, o
quadro, o dashboard e os relatórios de qualquer usuário.

## O que faz

- **Hoje** — o dia em um olhar: rotinas da agenda, tarefas abertas por urgência
  (atrasadas, bloqueadas), registro rápido e resumos (último dia útil e a semana,
  comparada com a anterior). É a primeira tela.
- **Rotinas** — verificações que se repetem (backups, alertas, fila…), com agenda:
  dias úteis, dias da semana, mensal (inclui "último dia") ou a cada N dias.
  Marcação até 7 dias para trás; feito fora da agenda conta como *extra*.
- **Tarefas** — status, prioridade, prazo, projeto/cliente, checklist,
  anotações e apontamento de tempo.
- **Relatórios** — PDF por período, por projeto ou do projeto inteiro;
  exportação em CSV (planilha) e JSON (backup).
- **Dashboard**, **histórico com desfazer**, **busca** sem acento, **feed de
  calendário (ICS)**, **avisos por e-mail** (opt-in) e **identidade visual**
  configurável pelo admin.
- **IA** — chaves de API e servidor **MCP** (`/mcp`): a IA registra o que você
  contar, com tudo marcado no histórico pelo nome da chave.

## Arquitetura

```
Internet ──► cloudflared (host) ──► web (nginx) ──► backend (FastAPI) ──► db (Postgres)
             systemd, sem portas    127.0.0.1:PORT      │                 rede interna,
             abertas na VM          estático + /api    regras, PDF,       porta não exposta
                                    + /mcp + headers   e-mail
```

- **db** — PostgreSQL 16, volume nomeado, sem porta no host.
- **backend** — FastAPI + psycopg3, um processo; aplica `backend/sql/*.sql`
  (idempotentes, só aditivos) a cada início e roda o agendador de avisos.
- **web** — nginx: frontend estático, proxy de `/api/` e `/mcp`, CSP estrita.
- **cloudflared** — no host (systemd), fora do compose: a única exposição.

Frontend: HTML/CSS/JS puro (módulos ES), tema escuro, fontes Google Sans
Flex/Code self-hosted (OFL). PDF com fpdf2 e as mesmas fontes.

## Setup

Pré-requisitos: Docker + Docker Compose.

1. `cp .env.example .env` (o `.env` **nunca** vai para o git) e preencha:
   - `SECRET_KEY` (32+ caracteres; menos que isso o backend não sobe):
     `python -c "import secrets; print(secrets.token_urlsafe(64))"`
   - `POSTGRES_PASSWORD` (o mesmo valor dentro de `DATABASE_URL`)
   - `ADMIN_EMAIL` / `ADMIN_INITIAL_PASSWORD`
   - sem HTTPS (teste local): `COOKIE_SECURE=false`
   - opcional, avisos por e-mail: `SMTP_HOST`, `SMTP_PORT` (465 = TLS, 587 =
     STARTTLS), `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`, `APP_URL`
2. `docker compose up -d --build` — o nginx fica em `127.0.0.1:${WEB_PORT}`.
3. Entre com o admin: a troca de senha é obrigatória no primeiro acesso.
   Depois, **Admin › Novo usuário** cria as contas.

Desenvolvimento com e-mail falso: `docker-compose.mailpit.yml` (instruções no
próprio arquivo).

### Testes

```bash
docker compose -f docker-compose.test.yml run --rm --build tests
```

Postgres descartável (tmpfs), projeto compose separado — nunca encosta nos dados reais.

## Deploy

`./deploy.sh` na VM: confere o `.env`, faz `pg_dump` verificado do banco, `git
pull --ff-only`, rebuild e smoke test (`--install` prepara uma VM Debian/Ubuntu
limpa). O túnel: `cloudflared` como serviço systemd com o token em
`/etc/cloudflared/<nome>.env` (root, 600), *public hostname* →
`http://localhost:${WEB_PORT}`. Cloudflare Access na frente é opcional (defesa
em profundidade).

**O banco de produção é preservado**: migrações só adicionam; nunca
`docker compose down -v`.

## Segurança (resumo)

- **Senhas** Argon2id, mínimo 10 caracteres; login com limite por IP e por
  e-mail (só falhas contam).
- **Sessão** server-side: o banco guarda só o HMAC do token; cookie
  `HttpOnly; Secure; SameSite=Strict`, prazo fixo (`SESSION_TTL_DAYS`).
  **CSRF** por header em toda mutação. Argon2 no perfil OWASP, no máximo 2
  hashes simultâneos (cabe na VM pequena).
- **Chaves de API** (`nxs_…`) e **link do calendário** (`nxc_…`): só o HMAC no
  banco, revogáveis; trocar a senha (ou o reset pelo admin) revoga ambos. Chave nunca
  acessa rotas de admin, chaves, calendário ou avisos.
- **Isolamento**: toda consulta filtra por `user_id`; permissões em
  `backend/app/deps.py`.
- **nginx**: CSP sem inline, HSTS, `nosniff`, `DENY` em frames; o link do
  calendário não vai para o log. Logo enviado validado pelo conteúdo e servido
  em sandbox.
- **Sem rastreamento**: só o cookie de sessão; e-mails sem pixel nem links
  redirecionados; CSV exportado neutraliza fórmulas.

## Estrutura

```
backend/app/       rotas (routers/), regras (services.py), PDF, e-mail, MCP
backend/sql/       migrações numeradas (o modelo de dados está aqui)
backend/tests/     suíte (pytest + Postgres real)
web/static/        index.html, login.html, js/ (um módulo por tela), css/
docs/API.md        referência da API e do MCP (o Swagger fica desligado)
```

Fuso da aplicação em `APP_TZ` (define "hoje", semana — que começa no
domingo — e mês, no backend e na interface).
