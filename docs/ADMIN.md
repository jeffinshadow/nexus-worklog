# Guia de administração e operação

Para quem hospeda o Nexus Worklog numa empresa ou instituição (ou para si mesmo). O uso do dia a dia está no
[manual](https://shadow.tec.br/nexus-manual); a API, em [`API.md`](API.md); a visão geral, no
[`README`](../README.md); o que mudou em cada versão, no [`CHANGELOG`](../CHANGELOG.md).

Nada aqui traz valor real de senha ou chave: onde aparece `<...>`, é o que você preenche.

## 1. Requisitos

- Uma máquina Linux (Debian/Ubuntu é o caminho testado) com **Docker** e **Docker Compose** (plugin `docker compose`) e **git**.
  `./deploy.sh --install` instala o que faltar em Debian/Ubuntu (pede `sudo`).
- Cerca de 1 GB de RAM livre (o backend tem teto de 512 MB; em máquina pequena, use swap) e disco para o banco, as
  fotos e os backups.
- Um nome de domínio com HTTPS na frente do app. O Nexus **não expõe portas**: o nginx escuta só em
  `127.0.0.1:${WEB_PORT}`, e a publicação é por um túnel (Cloudflare Tunnel, via `cloudflared` no host) ou por um
  proxy reverso seu. Sem HTTPS (só teste local), `COOKIE_SECURE=false`.
- Opcional: um servidor SMTP (avisos, convites e senha por e-mail).

## 2. Instalação

```bash
git clone https://github.com/jeffinshadow/nexus-worklog
cd nexus-worklog
cp .env.example .env        # o .env nunca vai para o git
$EDITOR .env                # preencha as variáveis da seção 3
./deploy.sh                 # ou: docker compose up -d --build
```

O `deploy.sh` recusa subir enquanto o `.env` tiver um marcador de exemplo (`CHANGEME`, `seu-dominio`…). O banco
(PostgreSQL 16, volume nomeado, sem porta no host), o backend (FastAPI) e o nginx sobem juntos; o backend aplica
as migrações de `backend/sql/` a cada início. Confira: `docker compose ps` e `curl http://127.0.0.1:${WEB_PORT}/api/health`.

**Publicar:** aponte o túnel (*public hostname*) para `http://localhost:${WEB_PORT}`. Com `cloudflared` como
serviço systemd, guarde o token em `/etc/cloudflared/<nome>.env` (root, modo 600). Cloudflare Access na frente é
opcional. **Cuidado com o nome da pasta:** ele vira o nome do projeto do compose e, com ele, o do volume do banco.
Mantenha a mesma pasta entre deploys; para renomear, fixe antes `COMPOSE_PROJECT_NAME` no `.env` com o nome antigo,
senão o Nexus sobe com um banco vazio (o antigo continua no volume de antes).

## 3. Variáveis de ambiente (`.env`)

O backend lê tudo de `backend/app/config.py`; o compose repassa o `.env`. Valores abaixo são os padrões do código.

| Variável | O que é | Padrão |
| --- | --- | --- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Credenciais e nome do banco criado pelo container `db` | sem padrão no compose |
| `DATABASE_URL` | Conexão do backend ao banco (`postgresql://usuário:senha@db:5432/banco`, com os **mesmos** valores acima) | obrigatória |
| `SECRET_KEY` | Segredo (pepper) dos HMAC de sessão, chaves de API e calendário. 32+ caracteres, senão o backend não sobe. **Trocar invalida sessões, chaves e links.** Gere com `python -c "import secrets; print(secrets.token_urlsafe(64))"` | obrigatória |
| `ADMIN_EMAIL`, `ADMIN_INITIAL_PASSWORD` | Primeiro admin, criado só se ainda não existir; a senha tem troca obrigatória no primeiro acesso | vazios (sem eles, nenhum admin é criado) |
| `SESSION_TTL_DAYS` | Prazo fixo da sessão, em dias | `7` |
| `COOKIE_SECURE` | `true` exige HTTPS (cookie `__Host-session`); `false` só em teste local | `true` |
| `APP_TZ` | Fuso que define "hoje", semana (começa no domingo) e mês, no backend e na tela | `America/Sao_Paulo` |
| `PHOTO_QUOTA_MB` | Cota de fotos por pessoa, em MB (0 = sem fotos novas) | `500` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | Servidor de e-mail. Sem `SMTP_HOST`, tudo que depende de e-mail fica desligado. Porta 465 = TLS direto, 587 = STARTTLS, outra (ex.: 1025 do Mailpit) = sem TLS | vazio / `465` |
| `MAIL_FROM` | Remetente | `Nexus Worklog <nexus@localhost>` |
| `APP_URL` | Endereço público do app, usado nos links dos e-mails (sem `/` no fim) | **`https://nexus.shadow.tec.br`: troque** |
| `MAIL_SCHEDULER` | `false` desliga o agendador de avisos (usado nos testes) | `true` |
| `STATE_DIR` | Pasta (só leitura no container) onde o `deploy.sh` grava `deploy.json` e `backup.json` | `/app/estado` |
| `WEB_PORT` | Porta do nginx no loopback do host (usada só pelo compose) | `80` |
| `ALERT_EMAIL` | Destino dos avisos do vigia de saúde (`tools/vigia.sh`); vazio = `ADMIN_EMAIL` | vazio |
| `COMPOSE_PROJECT_NAME` | Fixa o nome do projeto compose (e do volume do banco) se a pasta for renomeada | nome da pasta |
| `KEEP_BACKUPS` | Quantos dumps o `deploy.sh` guarda (variável do script, não do `.env`) | `14` |

## 4. E-mail (SMTP) e notificações push

**E-mail.** Preencha `SMTP_*`, `MAIL_FROM` e `APP_URL` e reinicie o backend (`docker compose up -d`). Com e-mail,
liga: convite por **link** (7 dias, uso único), "Esqueci a senha" (link de 1 hora), link de nova senha mandado pelo
admin, confirmação de e-mail novo, avisos de atribuição, resumo semanal e "Seu dia" pela manhã (cada pessoa liga o
que quer em Configurações), e o pedido de convite. Sem e-mail, o convite vira **senha temporária** que o admin repassa.
Para testar sem servidor real, `docker-compose.mailpit.yml` (instruções no arquivo). Em **Admin > Geral**, a Saúde
do Nexus mostra se o e-mail está configurado e o último envio ou erro.

**Push (Web Push).** Não há configuração: o backend **gera sozinho** a chave VAPID (ES256) na primeira vez e a guarda
no banco (tabela `app_secrets`). Não depende de Firebase nem de conta externa. Cada pessoa liga as notificações por
aparelho em Configurações. Exige HTTPS. A Saúde do Nexus mostra se as chaves existem, quantos aparelhos e quantos falham.
Perder o banco gera outra chave, e os aparelhos precisam reativar as notificações.

## 5. Primeiro admin e papéis

Entre com `ADMIN_EMAIL` e `ADMIN_INITIAL_PASSWORD`; o app obriga a trocar a senha. Depois, **Admin > Contas** cria as
demais pessoas. Não há cadastro público. Os papéis são acumuláveis (Admin > Contas > ⋮ > Papéis…):

| Papel | O que dá |
| --- | --- |
| **Usuário** | O próprio registro (tarefas, rotinas, tempo, relatórios). O admin também o tem |
| **Admin** | Convites, contas, papéis, configurações. **Não vê os registros de ninguém** |
| **Vê a equipe** (viewer) | Libera a tela Equipe: consulta, só leitura, o quadro, o mês, os relatórios, as horas e as fotos de quem permitiu |
| **Manda tarefas** (assigner) | Libera Atribuir tarefa na Equipe e a lista Tarefas que atribuí: manda tarefas a quem recebe |

Todo sistema precisa de ao menos um admin; o último não sai (nem por exclusão). Quem ganha ou perde um papel é
avisado no app (e por e-mail, se configurado).

### Equipes e admin master

**Admin > Equipes** cadastra as equipes (criar, renomear, arquivar, excluir; membros em lote no diálogo da equipe)
e mostra o admin master. Uma pessoa pode estar em **várias** equipes; todo mundo começa **sem equipe** e só o admin
define (no diálogo da equipe, em Contas > ⋮ > **Equipes…** ou já no convite). Contas mostra a coluna "Equipes" e
filtra por equipe (ou "Sem equipe").

- **Sem nenhuma equipe ativa** (uso pessoal): tudo funciona como antes; o escopo só passa a valer quando a primeira
  equipe é criada (o diálogo avisa). Equipe arquivada não conta para nada.
- **Com equipes**, "Vê a equipe" e "Manda tarefas" alcançam só quem compartilha **pelo menos uma equipe** com quem vê
  ou atribui, somado às regras de sempre (o aceite da pessoa ou as opções de Para empresas). Vale no app, na API, no
  MCP, no CSV e no PDF, no painel da Equipe e em "Precisa de atenção". Quem está **sem equipe** não é visto nem recebe
  tarefas de ninguém, exceto do admin master. A tela Equipe ganha um seletor de equipe para quem está em mais de uma;
  o Atribuir agrupa as pessoas pela equipe em comum. Tarefas atribuídas antes, entre quem não compartilha mais
  equipe, continuam na lista de quem mandou, mas não se alteram nem se cancelam.
- **Para empresas** passa a valer só para quem está em alguma equipe: sem equipe, a pessoa volta às próprias
  escolhas (guardadas). Exceções globais: "Solicitar convite" na tela de login e a política de privacidade.
- **Admin master:** o primeiro admin da instância (a migração 043 marca o admin mais antigo); sempre existe
  exatamente um. Com os próprios papéis "Vê a equipe" e "Manda tarefas" ligados (um toque em Admin > Equipes), vê e
  manda tarefas para **todos**, com ou sem equipe (ainda respeitando o aceite de cada pessoa ou Para empresas);
  desligados, nada disso aparece para ele. O que ele abre do registro de outras pessoas vai para o log de admin
  (o Histórico dele). Não pode ser bloqueado, excluído nem perder o papel Admin enquanto for o master.
- **Transferir o master:** só o próprio master, em Admin > Equipes > "Transferir o papel de master…": escolhe outro
  admin (que já entrou e está com acesso), confirma com a **senha** e digita o **código de 6 dígitos** mandado ao
  e-mail dele (vale 10 minutos, uso único, 5 tentativas). Exige e-mail configurado. Quem recebe é avisado no app e
  por e-mail; tudo fica no log de admin. Se o servidor ficar sem master (ex.: banco restaurado), ao subir o admin
  mais antigo assume.

## 6. Convites

Em **Admin > Contas > Convidar pessoa**: e-mail, **nome**, **papéis** e, havendo equipes, as **equipes** já no convite (também ao convidar a partir de um pedido).
- Com e-mail configurado: a pessoa recebe um **link** (7 dias, uso único), cria a senha e já entra. Sem e-mail:
  o app mostra uma **senha temporária** (troca obrigatória no primeiro acesso).
- Convite pendente pode ser reenviado ou **cancelado** (a conta sem dados sai e o link deixa de valer).
- **Pedido de convite** (opt-in, desligado por padrão): ligado em Para empresas (e só com e-mail no servidor), a tela de login
  oferece "Solicitar convite"; o pedido (nome, e-mail, de onde conhece, motivo) chega em Contas e o admin o
  **convida a partir do pedido** (nome e papéis editáveis) ou recusa. Limites: 5 por hora por IP, 2 por dia por
  e-mail, 20 por dia no total. Pedidos decididos são apagados em 30 dias; sem resposta, em 180.
- Toda conta nova faz o **tour** guiado no primeiro acesso (obrigatório).

Outras ações por conta (⋮): editar nome e e-mail; **redefinir senha** (com e-mail, manda o link; sem, mostra uma senha
temporária; encerra sessões e revoga chaves e passkeys); **bloquear acesso** (a pessoa sai de todos os aparelhos e
chaves e passkeys param; os dados ficam; redefinir senha libera); **excluir** (apaga a conta e todos os dados,
confirmando o e-mail). Ao bloquear ou excluir, é possível **passar as tarefas abertas** a outra pessoa. A lista mostra
a data de criação e o último acesso, e filtra por papel e situação.

## 7. Opções do Admin

**Admin > Geral:** **contato de suporte** (texto mostrado à pessoa) e a **Saúde do Nexus** (seção 8). Dois
valores deixaram de ser opção da tela (2.0): o limite de **lançamento retroativo** é fixo em **60 dias** e a **cota
de fotos por pessoa** vem da variável de ambiente `PHOTO_QUOTA_MB` (MB; padrão 500; 0 = ninguém envia fotos novas).
Os campos `retro_days` e `photo_quota_mb` de `PUT /api/admin/settings` são obsoletos (aceitos e ignorados; saem na 3.0).

**Admin > Identidade visual:** logo e as duas linhas do lockup (menu e login).

**Admin > Para empresas e instituições** (tudo desligado por padrão: o padrão é o organizador pessoal). Cada mudança
vai ao histórico do admin.

| Opção | Efeito |
| --- | --- |
| **Visibilidade da equipe** | "Cada pessoa escolhe" (padrão): só aparece em Equipe quem ligou "Permitir que quem tem o papel Vê a equipe veja meu registro". "Visível para quem gerencia": quem tem o papel Vê a equipe vê todos, e a chave de aceite de cada um fica bloqueada, com o motivo; as escolhas ficam guardadas para quando voltar |
| **Receber tarefas atribuídas** | "Cada pessoa escolhe" (padrão): recebe só quem aceitou. "Todos recebem de quem atribui": todo Usuário com conta em uso (convite aceito, sem bloqueio) recebe de quem tem o papel Manda tarefas; a chave fica bloqueada e as escolhas, guardadas; quem já usava vê um aviso único |
| **Nome e e-mail definidos pela administração** | Ligado, só o admin muda nome e e-mail (Contas > ⋮ > Editar); na Conta de cada pessoa os campos ficam bloqueados com o motivo. Desligado, cada um muda os seus e o e-mail novo só vale depois de confirmado por link |
| **Endereço do sistema de chamados** | URL com `{id}` no lugar do número (GLPI, TomTicket, Jira…) valendo para todos; vazio, cada pessoa usa o seu |
| **Política de privacidade** | URL `https://`; vira link na tela de login, na Conta e no e-mail de convite; vazio, sem link |
| **"Solicitar convite" na tela de login** | Ligado (exige e-mail no servidor), a tela de login oferece o pedido; desligado, só entra quem o admin convidou |

Visibilidade e recebimento são duas coisas independentes: nada disso dá ao admin acesso ao registro de alguém.
Com equipes cadastradas, estas opções valem só para quem está em alguma equipe, exceto o pedido de convite e a
política de privacidade, que valem para a instância toda (ver *Equipes e admin master*).

## 8. Saúde do Nexus

Em Admin > Geral, só leitura: versão (commit e data do último deploy, última migração, início do backend), último
**backup** (data, tamanho, tabelas), e-mail, push, fotos (quem passa de 80% da cota), webhooks (quantos
desligados), contas, pedidos de convite, chaves de API e tamanho do banco. Só contagens e datas. "Copiar diagnóstico"
gera um texto para suporte, sem dados de pessoas nem segredos. O `deploy.sh` alimenta versão e backup pela pasta
`estado/`; sem ele rodar, esses campos ficam vazios.

**Vigia (opcional):** `tools/vigia.sh` com o timer do systemd (`tools/nexus-vigia.service` e `.timer`, instruções nos
arquivos) confere a cada 5 minutos a saúde dos containers, reinicia o que estiver *unhealthy* e avisa por e-mail
(`ALERT_EMAIL` ou `ADMIN_EMAIL`), uma vez por incidente e outra quando volta. Os logs dos containers têm rotação
(10 MB x 5).

## 9. Backups e como restaurar

**O que é feito.** A cada `./deploy.sh`, **antes de mexer em código ou containers**, se o banco já está rodando, o
script faz `pg_dump` (formato custom) para `backups/pre-deploy-AAAAMMDD-HHMMSS-<commit>.dump` (pasta com modo 700,
arquivo 600), confere o índice com `pg_restore --list` e **aborta o deploy** se o backup falhar ou vier vazio. Mantém
os **14 mais recentes** (`KEEP_BACKUPS`). Grava em `estado/backup.json` a data, o tamanho e o número de tabelas
(que a Saúde do Nexus mostra). `backups/` e `estado/` ficam fora do git.

**Limites:** o backup só existe a cada deploy, então **agende também um backup periódico** (cron com o mesmo
`pg_dump`, abaixo) e **copie os dumps para fora da máquina** (outro disco ou servidor). Uma conta excluída sai dos
backups quando o último dump que a continha é descartado. O dump não inclui o `.env`: guarde-o à parte, em lugar
seguro. Sem o mesmo `SECRET_KEY`, as sessões, chaves de API e links antigos deixam de valer.

Backup manual (ou para o cron), na pasta do projeto:

```bash
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/manual-$(date +%Y%m%d-%H%M%S).dump
```

**Restaurar** (é o mesmo comando que o `deploy.sh` mostra no rollback). Isto **substitui** os dados atuais pelos do
dump; antes, faça um backup do estado atual (comando acima) se ele ainda tiver valor.

1. Escolha o dump: `ls -1t backups/`.
2. Pare quem escreve no banco: `docker compose stop backend web`.
3. Suba só o banco, se estiver parado: `docker compose up -d db` (espere ficar *healthy*: `docker compose ps`).
4. Restaure:
   ```bash
   docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < backups/<arquivo>.dump
   ```
   Avisos sobre objetos que "não existem" em `--clean` são esperados em banco novo; erro de verdade interrompe e aparece no fim.
5. Se o dump é de uma versão **anterior** do código, volte o código também: `git checkout <commit do nome do arquivo>`
   (o nome do dump termina com o commit de antes do deploy). Se é da versão atual, fique no `main`.
6. Suba tudo: `docker compose up -d --build`. O backend reaplica as migrações aditivas, que são idempotentes.
7. Confira: `curl http://127.0.0.1:${WEB_PORT}/api/health`, entre no app e veja a Saúde do Nexus. Depois volte ao
   `main` (`git checkout main`) quando quiser atualizar de novo.

**Restaurar numa máquina nova:** instale o Nexus (seção 2) com o **mesmo `.env`** (principalmente `SECRET_KEY`,
`POSTGRES_*` e `DATABASE_URL`), suba só o banco (`docker compose up -d db`), faça os passos 4 a 7 com o dump copiado
para `backups/`. As fotos estão no banco, então vão junto.

**Nunca** use `docker compose down -v` (apaga o volume do banco).

## 10. Atualizar para uma nova versão

Na pasta do projeto, na máquina de produção:

```bash
git fetch && git log --oneline HEAD..origin/main    # o que vem
less CHANGELOG.md                                   # confira quebras de contrato (versão maior)
./deploy.sh
```

O `deploy.sh`: confere o `.env`; faz o backup verificado (seção 9); `git pull --ff-only`; `docker compose up -d --build`;
espera o `/api/health` responder pelo nginx (até 1 minuto); grava `estado/deploy.json` (commit novo, commit anterior,
hora). Se a aplicação não responder, ele **não desfaz sozinho**: imprime o rollback do código
(`git checkout <commit anterior> && docker compose up -d --build`) e do banco (o `pg_restore` da seção 9, só se uma
migração estragou dados).

- **Migrações** (`backend/sql/*.sql`) são numeradas, **só aditivas e idempotentes**, aplicadas a cada início do backend:
  atualizar não apaga dado, e rodar de novo não faz mal. Por isso voltar o código sem voltar o banco costuma funcionar.
- **nginx:** a configuração (`web/nginx.conf`) vai na imagem `web`, reconstruída pelo próprio `deploy.sh`.
- Variáveis novas aparecem em `.env.example` e neste guia: compare com seu `.env` (`diff <(grep -o '^[A-Z_]*' .env.example | sort) <(grep -o '^[A-Z_]*' .env | sort)`).
- Um cliente MCP com a lista de ferramentas velha recebe, ao chamar, a dica de reconectar (`/mcp`).

## 11. Versionamento e compatibilidade

O Nexus segue **SemVer** (`MAJOR.MINOR.PATCH`); o número está em `backend/app/version.py`, no `serverInfo` do MCP e no
`docs/openapi.json`, e o histórico está no [`CHANGELOG`](../CHANGELOG.md) (etiquetas git `vX.Y.Z`).

- **MAJOR**: quebra de contrato da API REST ou do MCP, ou redesenho profundo de como o app é usado.
- **MINOR**: recurso novo, sem quebrar nada.
- **PATCH**: só correção (ou ajuste sem função nova).
- **Quebras só em versão maior.** Dentro da mesma maior, rota, campo ou ferramenta antiga **continua funcionando**; quando
  existe forma melhor, a antiga é marcada como **obsoleta** (na doc e no changelog) e só sai na maior seguinte. Exemplo
  na 2.0.0: `GET /api/auth/link` segue respondendo, mas o correto é `POST /api/auth/link`.
- Migrações de banco são sempre aditivas dentro de uma maior.
- Cada deploy em produção vira uma versão; antes de atualizar uma maior, leia as "Quebras" do changelog e avise quem
  integra por API, webhook ou MCP.

## 12. Segurança

Resumo: senhas Argon2id (mínimo 10 caracteres), login limitado por IP e por e-mail, sessão no servidor (cookie
`__Host-session`, `HttpOnly; Secure; SameSite=Strict`, prazo fixo), CSRF por cabeçalho em toda mutação, chaves de API
e links de calendário guardados só como HMAC, toda consulta filtrada por pessoa, CSP estrita no nginx, sem rastreamento.
Detalhes e LGPD (exportar, excluir, histórico de 180 dias, backups) na seção "Segurança (resumo)" do
[`README`](../README.md#segurança-resumo).

Recomendações de operação: mantenha o `.env` com modo 600 e fora do git; não exponha a porta do nginx além do
loopback; guarde e rotacione os backups fora da máquina; atualize com frequência (dependências e imagens são
reconstruídas a cada `deploy.sh`); mantenha o túnel/proxy com HTTPS; crie ao menos dois admins para não ficar sem acesso.

## 13. Solução de problemas

| Sintoma | Causa provável e o que fazer |
| --- | --- |
| Backend não sobe: "Variavel de ambiente obrigatoria ausente" ou "SECRET_KEY curta demais" | Falta `DATABASE_URL` ou `SECRET_KEY`, ou ela tem menos de 32 caracteres. `docker compose logs backend` |
| `deploy.sh`: ".env ainda contém valores placeholder" | Algum valor do `.env` ainda tem `CHANGEME`, `seu-dominio`… Preencha |
| `deploy.sh`: "pg_dump falhou. Deploy abortado" | Nada foi alterado. Veja `docker compose ps` (banco saudável?) e o espaço em disco; rode de novo |
| Aplicação não responde depois do deploy | Siga o rollback que o script imprimiu (seção 10); veja `docker compose logs backend web` |
| Nexus abriu **vazio** depois de renomear a pasta | O compose criou outro volume. Volte a pasta ao nome antigo ou fixe `COMPOSE_PROJECT_NAME` com ele (seção 2); o banco antigo está no volume de antes |
| Não consigo entrar (login em loop) | `COOKIE_SECURE=true` sem HTTPS: o navegador descarta o cookie. Use HTTPS ou `false` só em teste |
| Muitas tentativas / "tente mais tarde" no login | Limite por IP e por e-mail; espere alguns minutos. Atrás de proxy, confira se o IP real chega ao nginx |
| Convite, "esqueci a senha" ou avisos não chegam | Saúde do Nexus mostra o último erro de e-mail; confira `SMTP_*`, `MAIL_FROM` e `APP_URL`. Sem `SMTP_HOST`, nada é enviado |
| "Solicitar convite" não aparece no login | Opt-in: ligue em Admin > Para empresas, e é preciso e-mail no servidor |
| Link do e-mail aponta para o endereço errado | `APP_URL` no `.env` (o padrão do código é de outro domínio) |
| Notificações não chegam | Exigem HTTPS e a permissão do aparelho; veja a linha Push da Saúde. Chave VAPID refeita = reativar nos aparelhos |
| Foto não sobe | Cota por pessoa estourada (Admin > Geral) ou arquivo grande demais |
| Equipe vazia | Cada pessoa precisa permitir (Configurações > Conta), ou ligue "Visível para quem gerencia"; quem vê precisa do papel Vê a equipe |
| Atribuir diz que a pessoa não aceita | Ela ainda não ligou "Receber tarefas atribuídas", ou use "Todos recebem de quem atribui" |
| Container *unhealthy* | `docker compose logs <serviço>`; o vigia (seção 8) reinicia e avisa |
| Backend reinicia sozinho | Teto de 512 MB estourado (relatório muito grande): veja `docker compose logs backend` e a memória do host |
