# Shadow Nexus Worklog

Registro do dia de trabalho para profissionais de TI — suporte, infraestrutura,
redes, segurança, desenvolvimento — e para quem precisa do relatório deles.
Multiusuário, auto-hospedado, sem frameworks JS nem passo de build.
Prioridades: **simples > seguro > funcional > elegante**.

Cada pessoa vê **apenas** os próprios dados. As contas são criadas pelo
**admin** (convite com senha temporária); não há cadastro público. Papéis
acumuláveis, dados em **Admin › Permissões**: **Usuário** (o próprio registro),
**Admin** (contas, permissões, configurações), **Atribuidor de tarefas** (manda
tarefas a quem aceitou receber) e **Visualizador de tarefas** (consulta, só
para leitura, o quadro, a retrospectiva e os relatórios de cada pessoa).

## O que faz

- **Hoje** — o dia em um olhar, com um **assistente**: saudação, o que está
  pra hoje, o que saiu ontem, o resumo do dia e por onde começar. Avisa tarefa
  bloqueada há dias, prazo de amanhã e tempo esquecido, e copia o texto da
  daily. Cada aviso tem o próprio X; tudo é calculado a partir dos registros da
  pessoa, sem IA chamada a cada tela.
- **Rotinas** — verificações que se repetem (backups, alertas, fila…), com agenda:
  dias úteis, dias da semana, mensal (inclui "último dia") ou a cada N dias.
  Marcação até 7 dias para trás; feito fora da agenda conta como *extra*.
- **Tarefas** — status, prioridade, prazo, projeto/cliente, checklist,
  anotações e apontamento de tempo; **cronômetro** (um por pessoa, vale em
  qualquer aparelho); **número do chamado** (GLPI, TomTicket, Jira…) que vira
  link; **plantão** fora do horário, com o tempo separado no relatório; e
  **modelos** de tarefa com checklist pronto. Lançamento **retroativo** (criada e
  concluída em datas passadas, até um limite configurável pelo admin; padrão 60
  dias).
- **Atribuição** — quem aceita (Configurações › Conta) recebe tarefas de um
  atribuidor pelo app ou pela IA, com aviso por e-mail; a tarefa passa a ser
  dela, e quem atribuiu acompanha o status.
- **Relatórios** — PDF por período, por projeto ou do projeto inteiro;
  exportação em CSV (planilha) e JSON (backup).
- **Retrospectiva** (aderência das rotinas, vazão, tempo por projeto, backlog),
  **histórico com desfazer**, **busca** sem acento (inclusive por `#chamado`),
  **feed de calendário (ICS)**, **avisos por e-mail** (opt-in), **lembrete** no
  app depois de X minutos sem registro, **atalhos de teclado** (`n`, `/`, `s`,
  `?`…), perfil com nome e foto e **identidade visual** configurável pelo admin.
- **IA** — chaves de API e servidor **MCP** (`/mcp`): a IA registra, anota,
  aponta e cronometra o que você contar, com tudo marcado no histórico pelo nome
  da chave. Comandos prontos para o resumo da semana e para a daily. Para
  lançar o que já aconteceu: `created_at`/`completed_at`, `external_ref` (não
  duplica) e `list_tasks` por período.

## Telas

Capturas de uma conta de demonstração, com dados fictícios.

![Tela Hoje com o assistente, as rotinas e as tarefas em aberto](docs/screenshots/01-hoje.webp)
*Hoje — o assistente resume o dia e o anterior e sugere por onde começar, com avisos de prazo, tarefa bloqueada e tempo esquecido. Abaixo, as rotinas e o registro rápido.*

![Quadro de tarefas com chamados, plantão e o cronômetro no menu](docs/screenshots/02-tarefas.webp)
*Tarefas — o número do chamado vira link, o plantão aparece em roxo e o cronômetro roda no menu.*

![Detalhe de uma tarefa com checklist, tempo e anotações](docs/screenshots/03-tarefa.webp)
*Detalhe da tarefa — checklist, apontamentos de tempo e anotações num lugar só.*

![Retrospectiva com aderência, vazão, tempo por projeto e backlog](docs/screenshots/04-retrospectiva.webp)
*Retrospectiva — aderência de cada rotina, vazão por semana, tempo por cliente e saúde do backlog, com uma leitura do assistente no topo.*

![Nova tarefa preenchida a partir de um modelo](docs/screenshots/05-modelo.webp)
*Modelos — escolhe o modelo no “+ Tarefa” e o checklist vem junto.*

<p>
  <img src="docs/screenshots/06-celular.webp" width="300" alt="Tela Hoje no celular">
  <img src="docs/screenshots/07-relatorio.webp" width="420" alt="Primeira página do relatório em PDF">
</p>

*No celular, o mesmo assistente e o cronômetro acima da barra. Ao lado, a primeira página do relatório em PDF: indicadores, ritmo do período, rotinas, projetos e tarefas, com o plantão separado.*

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

Frontend: HTML/CSS/JS puro (módulos ES), tema escuro, fonte Google Sans
Flex self-hosted (OFL). PDF com fpdf2 e a mesma fonte.

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

- **Senhas** Argon2id (perfil OWASP, no máximo 2 cálculos simultâneos — sob
  carga responde 503 em vez de travar), mínimo 10 caracteres; login limitado
  por IP (todas as tentativas; IPv6 por /64) e por e-mail (só as falhas, que
  vão para o log); troca de senha limitada e diferente da atual.
- **Sessão** server-side: o banco guarda só o HMAC do token; cookie
  `__Host-session` (`HttpOnly; Secure; SameSite=Strict`), prazo fixo
  (`SESSION_TTL_DAYS`). Histórico guardado por 180 dias.
  **CSRF** por header em toda mutação.
- **Chaves de API** (`nxs_…`) e **link do calendário** (`nxc_…`): só o HMAC no
  banco, revogáveis; trocar a senha (ou o reset pelo admin) revoga ambos. Chave nunca
  acessa rotas de admin, de visualizador, chaves, calendário ou avisos; atribuir
  por chave exige o papel de atribuidor e escopo de escrita.
- **Isolamento**: toda consulta filtra por `user_id`; permissões em
  `backend/app/deps.py`.
- **nginx**: CSP sem inline, HSTS, `nosniff`, `DENY` em frames; o link do
  calendário não vai para o log. Logo enviado validado pelo conteúdo e servido
  em sandbox.
- **Seus dados (LGPD)**: cada pessoa exporta tudo em JSON ou CSV (Relatórios) e
  exclui a própria conta em Configurações › Conta (com a senha); o admin também
  exclui uma conta (Admin › Usuários, confirmando o e-mail). Tarefas, rotinas,
  tempo, anotações, chaves e histórico vão junto; ficam só o e-mail e as contagens
  no histórico de quem excluiu (180 dias). O último admin não sai.
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
