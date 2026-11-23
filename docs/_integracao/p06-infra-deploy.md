# p06-infra-deploy: notas para a integração

Branch `lab/p06-infra-deploy`. Não toca em `web/static`, `backend/tests`, `CHANGELOG.md`, `openapi.json` nem
`version.py`. Sem rota, parâmetro, dependência ou variável nova.

## Linhas para o CHANGELOG

Corrigido
- Restaurar um backup (guia e rollback do `deploy.sh`) agora apaga e recria o banco antes do `pg_restore`, que roda
  numa transação e para no primeiro erro. O comando antigo (`--clean --if-exists`) deixava dados do dump misturados
  aos atuais quando a versão nova tinha criado tabelas, e o guia dizia que "erro de verdade interrompe".
- `deploy.sh` com o banco parado subia a versão nova sem backup; agora sobe só o banco, faz o backup e segue. Se o
  `docker compose ps` falhar, aborta.
- Migração que passa de 15 s não era aplicada (o backend não subia); migrações rodam sem o teto, as rotas continuam com ele.
- Depois de o Postgres reiniciar, as chamadas seguintes davam erro 500 até o pool se renovar; o pool confere a conexão antes de usar.
- Consultas paralelas em tabela grande falhavam com `/dev/shm` de 64 MB: o banco passa a ter 256 MB.
- nginx não comprimia nada atrás do túnel ou de proxy (pedido com `Via`); agora comprime e manda `Vary: Accept-Encoding`.
- Recriar o backend em outro endereço deixava o nginx em 502 até reiniciar o `web`; ele volta a achar o backend em até 10 s.
- Vigia: declarava "tudo saudável" com o banco ou o backend parados e marcava o incidente como avisado sem o e-mail ter saído.
- `./deploy.sh --install` em Debian usava o repositório do Ubuntu e deixava um `docker.list` quebrado.
- README: a exclusão de conta deixa nome e e-mail no histórico de quem atribuiu tarefas à pessoa, por até 180 dias.

Novo
- `./deploy.sh --backup`: só o backup verificado (para o cron), com a mesma retenção e a mesma linha na Saúde do Nexus.
- Backup com zstd (`pg_dump -Fc --compress=zstd:1`), bem mais rápido com muitas fotos.
- `deploy.sh` baixa as imagens base a cada deploy (`build --pull` e `pull db`); nginx na linha `stable`.
- `deploy.sh` diz quais variáveis ainda têm marcador, recusa senha do Postgres que quebra a `DATABASE_URL` e avisa quando falta `APP_URL`; o backend avisa no log de início.
- Containers sem capacidades extras e com `no-new-privileges`.
- Log de acesso do nginx sem a query string (o texto buscado não fica gravado).
- `jit=off` nas conexões do backend.

Obsoleto (doc)
- `heatmap`, `task_adherence` e `throughput` de `GET /api/dashboard`: seguem respondendo, saem na 3.0.

## Avisos para quem atualiza

- **A retenção agora vale para todo `*.dump` de `backups/`**, não só `pre-deploy-*`: dumps manuais antigos entram na
  conta dos 14 (`KEEP_BACKUPS`) e os mais velhos são apagados no próximo deploy ou `--backup`. Copie para fora antes
  o que quiser guardar.
- **Dumps novos usam zstd**: só restauram com `pg_restore` 16+ compilado com zstd (o do container `db` serve). Os
  dumps antigos (gzip) continuam restaurando.
- Quem agendou no cron o `pg_dump` do guia antigo: troque por `./deploy.sh --backup` (seção 9 do ADMIN.md).
- O primeiro deploy depois desta versão baixa `nginx:stable-alpine` e pode baixar um `postgres:16-alpine` mais novo
  (o container do banco é recriado: alguns segundos de 503). O `db` também é recriado por causa do `shm_size` e do `cap_drop`.
- Quem usa o vigia: não há o que reinstalar (o timer roda o script da pasta do projeto), mas o comportamento mudou:
  ele avisa de serviço parado e **não** o religa. Pare o timer antes de restaurar um backup.
- Quem publica por proxy próprio (sem Cloudflare): o proxy tem de sobrescrever `CF-Connecting-IP` (ADMIN.md, seção 1).
- `.env` sem `APP_URL`: o backend sobe, mas avisa no log. A remoção do padrão espera o dono; antes dela, conferir
  que o `.env` de produção tem a linha.
- Apagar `ADMIN_INITIAL_PASSWORD` do `.env` depois do primeiro acesso (depende do p01 mudar o `seed_admin`; conferir
  que o texto das seções 3, 5 e 13 do ADMIN.md bate com o que o p01 entregou).

## Pendências e o que não foi verificado

- `deploy.sh` inteiro (passos 5 e 6: `git pull`, `pull db`, `build --pull`, `up`, fumaça) **não foi rodado de ponta
  a ponta**: o `git pull` iria ao GitHub. Rodei até o `git pull` com um `git` de mentira que recusa o `pull`.
- `--install` em Debian/Ubuntu não foi rodado (exige `sudo` e rede); só leitura e `shellcheck`.
- Vigia com backend em laço de reinício real (502 com todos "running") não foi reproduzido; testei banco parado,
  backend parado e a volta. A linha do cron não foi instalada num crontab de verdade.
- Depois de o Postgres reiniciar, a primeira chamada pode levar uns 3 s ou responder 503 (com `Retry-After`) se
  chegar enquanto o banco ainda sobe; não é mais 500.
- No log do nginx o `Referer` continua inteiro (o app não põe busca na URL da página, então não leva `?q=`).
- Linhas 99-100 do ADMIN.md (equipes) não foram tocadas; o ADMIN.md cresceu acima delas (seção 1), o p02 vai
  encontrá-las algumas linhas abaixo.
- Não implementado, por instrução: `TRUST_CF_IP`/`CLIENT_IP_HEADER`, IP real no log, `--require-hashes`, registro de
  migrações, `read_only` no backend, remoção do padrão de `APP_URL`.
