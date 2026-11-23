#!/usr/bin/env bash
# Deploy do Nexus Worklog.
# Uso:
#   ./deploy.sh          → verifica dependências e faz o deploy (não instala nada)
#   ./deploy.sh --install → tenta instalar dependências que faltam (Debian/Ubuntu), depois faz deploy
#   ./deploy.sh --backup  → só o backup verificado do banco (para o cron): não atualiza
#                           código, não reconstrói nem reinicia nada
set -euo pipefail

INSTALL=false
ONLY_BACKUP=false
case "${1:-}" in
  "") ;;
  --install) INSTALL=true ;;
  --backup)  ONLY_BACKUP=true ;;
  *) printf 'Uso: %s [--install | --backup]\n' "$0" >&2; exit 2 ;;
esac
# O cron chama de qualquer pasta: tudo aqui é relativo à pasta do projeto.
cd "$(dirname "$0")"

log()  { printf '\033[1;34m[deploy]\033[0m %s\n' "$1"; }
err()  { printf '\033[1;31m[erro]\033[0m %s\n' "$1" >&2; }

# estado/<arquivo>: números para a Saúde do Nexus (Admin > Geral). O backend lê
# a pasta estado/ só leitura (nunca vê backups/). Falhar aqui nunca para o deploy.
write_state() {
  { mkdir -p estado && printf '%s\n' "$2" > "estado/$1.tmp" && chmod 644 "estado/$1.tmp" \
      && mv -f "estado/$1.tmp" "estado/$1"; } \
    || log "aviso: não gravei estado/$1 (a Saúde do Nexus fica sem essa informação)"
}

# --- 1. Verificação de dependências ---
missing=()
command -v git            >/dev/null 2>&1 || missing+=("git")
command -v docker         >/dev/null 2>&1 || missing+=("docker")
docker compose version    >/dev/null 2>&1 || missing+=("docker-compose-plugin")

if [[ ${#missing[@]} -gt 0 ]]; then
  err "Dependências ausentes: ${missing[*]}"
  if [[ "$INSTALL" == false ]]; then
    err "Instale-as manualmente, ou rode: ./deploy.sh --install (Debian/Ubuntu)"
    exit 1
  fi

  # --- 2. Instalação (só com --install, só o necessário) ---
  # O repositório da Docker é por distribuição: só Debian e Ubuntu têm caminho
  # aqui. Em derivadas (Mint, Pop!_OS...) o codinome não existe lá e o apt quebraria.
  # shellcheck disable=SC1091
  distro="$(. /etc/os-release 2>/dev/null && echo "${ID:-}")"
  if [[ " ${missing[*]} " == *" docker"* && "$distro" != debian && "$distro" != ubuntu ]]; then
    err "--install só sabe instalar o Docker em Debian e Ubuntu (este sistema: ${distro:-desconhecido})."
    err "Siga https://docs.docker.com/engine/install/ e rode ./deploy.sh de novo."
    exit 1
  fi
  log "Instalando dependências ausentes (requer sudo)..."
  sudo apt-get update
  # git é trivial; Docker segue o método oficial (repo da Docker), não o pacote da distro
  for dep in "${missing[@]}"; do
    case "$dep" in
      git)
        sudo apt-get install -y git
        ;;
      docker|docker-compose-plugin)
        # Instala Docker Engine + Compose plugin pelo repositório oficial
        sudo apt-get install -y ca-certificates curl
        sudo install -m 0755 -d /etc/apt/keyrings
        sudo curl -fsSL "https://download.docker.com/linux/$distro/gpg" \
          -o /etc/apt/keyrings/docker.asc
        sudo chmod a+r /etc/apt/keyrings/docker.asc
        # shellcheck disable=SC1091
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/$distro $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
          | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        # Se falhar, o docker.list sai: deixado lá, quebraria todo "apt-get update" seguinte.
        if ! { sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
          docker-buildx-plugin docker-compose-plugin; }; then
          sudo rm -f /etc/apt/sources.list.d/docker.list
          err "Não consegui instalar o Docker pelo repositório oficial (removi o docker.list que criei)."
          err "Siga https://docs.docker.com/engine/install/ e rode ./deploy.sh de novo."
          exit 1
        fi
        log "Docker instalado. Talvez seja preciso reabrir a sessão para usá-lo sem sudo."
        break  # o bloco docker cobre ambas as entradas
        ;;
    esac
  done
fi

# --- 3. Pré-condições de configuração ---
if [[ ! -f .env ]]; then
  err ".env não encontrado. Copie .env.example para .env e preencha os valores."
  err "  cp .env.example .env"
  exit 1
fi

# Garante que segredos placeholder não passem despercebidos.
# Ignora comentários (linhas iniciadas por #) e linhas em branco.
# Mostra só o NOME das variáveis (o valor pode ser um segredo meio preenchido).
env_get() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2-; }
if [[ "$ONLY_BACKUP" == false ]]; then
  marcadas="$(grep -vE '^[[:space:]]*(#|$)' .env | grep -E 'CHANGE_?ME|your_?secret|placeholder|seu-dominio' \
    | cut -d= -f1 | sort -u | tr '\n' ' ' || true)"
  if [[ -n "$marcadas" ]]; then
    err ".env ainda contém valores placeholder. Preencha antes de subir: ${marcadas% }"
    exit 1
  fi

  # A senha do banco vai dentro da DATABASE_URL: com / @ # ? % ou espaço ela corta
  # a URL e o backend não conecta ("failed to resolve host"). Só recusa quando a
  # senha aparece assim, crua, na URL (quem a escreveu codificada com %XX passa).
  pgpass="$(env_get POSTGRES_PASSWORD)"
  if [[ "$pgpass" =~ [/@#?%[:space:]] && "$(env_get DATABASE_URL)" == *"$pgpass"* ]]; then
    err "POSTGRES_PASSWORD tem caractere reservado de URL (/ @ # ? % ou espaço) e quebra a DATABASE_URL."
    err "Gere uma só com letras e números (openssl rand -hex 24) e ponha a mesma nas duas variáveis."
    err "Se o banco já foi criado com a senha antiga, veja docs/ADMIN.md, seção 13."
    exit 1
  fi

  if ! grep -qE '^APP_URL=.' .env; then
    log "aviso: o .env não define APP_URL. Os links dos e-mails, o calendário, as passkeys e o push"
    log "       vão usar o endereço padrão do código, que não é o seu. Acrescente APP_URL=https://<seu endereço>."
  fi
fi

# --- 4. Backup do banco ANTES de qualquer mudança ---
# O banco de produção é o que não pode se perder. Se o container do banco existe,
# fazemos um pg_dump (formato custom, zstd) e conferimos o índice do arquivo; se o
# backup falhar, o deploy para aqui, antes de mexer em código ou containers.
# Com --backup é só este bloco (o cron chama assim).
KEEP_BACKUPS="${KEEP_BACKUPS:-14}"
PREV_COMMIT="$(git rev-parse HEAD)"
BACKUP=""

# Sem "2>/dev/null || true": se o docker não respondeu, não dá para saber se há
# banco, e seguir seria atualizar sem backup.
if ! db_id="$(docker compose ps -a -q db)"; then
  err "docker compose ps falhou: não sei se o banco existe. Abortado; nada foi alterado."
  exit 1
fi

if [[ -n "$db_id" ]]; then
  if [[ -z "$(docker compose ps --status running -q db)" ]]; then
    if [[ "$ONLY_BACKUP" == true ]]; then
      err "O banco está parado: sem backup (o --backup não liga nem reinicia nada)."
      exit 1
    fi
    # Banco existe mas está parado: sobe só ele, para não atualizar sem backup.
    log "O banco existe mas está parado: subindo só ele para o backup..."
    docker compose up -d --wait db \
      || { err "Não consegui subir o banco para o backup. Deploy abortado; nada foi alterado."; exit 1; }
  fi
  mkdir -p -m 700 backups
  prefixo=pre-deploy; [[ "$ONLY_BACKUP" == true ]] && prefixo=agendado
  BACKUP="backups/$prefixo-$(date +%Y%m%d-%H%M%S)-${PREV_COMMIT:0:7}.dump"
  log "Backup do banco em $BACKUP ..."
  (
    umask 077
    docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --compress=zstd:1' > "$BACKUP"
  ) || { err "pg_dump falhou. Abortado; nada foi alterado."; rm -f "$BACKUP"; exit 1; }

  tables=$(docker compose exec -T db pg_restore --list < "$BACKUP" 2>/dev/null | grep -c "TABLE DATA" || true)
  if [[ ! -s "$BACKUP" || "$tables" -lt 1 ]]; then
    err "Backup vazio ou ilegível ($BACKUP). Abortado; nada foi alterado."
    rm -f "$BACKUP"  # não fica na pasta passando por backup bom nem ocupa vaga na retenção
    exit 1
  fi
  log "Backup ok: $(du -h "$BACKUP" | cut -f1), $tables tabelas com dados."
  # Só data, tamanho e tabelas (sem o caminho do arquivo).
  write_state backup.json "{\"at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"size_bytes\":$(stat -c %s "$BACKUP"),\"tables\":$tables}"

  # Retenção: mantém só os KEEP_BACKUPS dumps mais recentes da pasta, de qualquer
  # origem (deploy, agendado ou manual): quem quer guardar um, copia para fora.
  find backups -maxdepth 1 -type f -name '*.dump' -printf '%T@ %p\0' | sort -z -rn \
    | tail -z -n +"$((KEEP_BACKUPS + 1))" | cut -z -d' ' -f2- | xargs -0 -r rm --
elif [[ "$ONLY_BACKUP" == true ]]; then
  err "Não há container do banco nesta pasta: sem backup a fazer."
  exit 1
else
  log "Banco ainda não existe (primeira instalação): sem backup a fazer."
fi

if [[ "$ONLY_BACKUP" == true ]]; then exit 0; fi

# Como voltar atrás: impresso sempre que o deploy falha depois de o código mudar
# (com set -e, um "up" que falhasse saía do script sem dizer nada disto).
rollback_hint() {
  err "Rollback do código:  git checkout $PREV_COMMIT && docker compose up -d --build"
  if [[ -n "$BACKUP" ]]; then
    err "Rollback do banco (só se uma migration estragou dados; DEPOIS do rollback do código."
    err "Apaga o banco atual inteiro e recria do dump):"
    err "  docker compose stop backend web"
    err "  docker compose exec -T db sh -c 'psql -U \"\$POSTGRES_USER\" -d postgres -v ON_ERROR_STOP=1 -c \"DROP DATABASE IF EXISTS \\\"\$POSTGRES_DB\\\" WITH (FORCE)\" -c \"CREATE DATABASE \\\"\$POSTGRES_DB\\\" OWNER \\\"\$POSTGRES_USER\\\"\"'"
    err "  docker compose exec -T db sh -c 'pg_restore -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" --exit-on-error --single-transaction' < $BACKUP"
    err "  docker compose up -d"
    err "  (passo a passo em docs/ADMIN.md, seção 9)"
  fi
}

# --- 5. Deploy ---
log "Atualizando código..."
git pull --ff-only || { err "git pull falhou (há mudança local ou o histórico divergiu?). O código e os containers não mudaram: a versão de antes continua no ar."; exit 1; }

# Imagens base novas a cada deploy: --pull renova as do build (python, nginx) e o
# "pull db" a do Postgres, que é "image:" e o build não alcança.
log "Renovando imagens e subindo containers..."
docker compose pull db || log "aviso: não consegui baixar a imagem do banco; sigo com a que já está aqui."
if ! { docker compose build --pull && docker compose up -d; }; then
  err "O docker compose falhou ao construir ou subir os containers."
  docker compose ps || true
  rollback_hint
  exit 1
fi

# --- 6. Teste de fumaça: nginx -> backend respondendo pela rede interna ---
log "Conferindo se a aplicação respondeu..."
ok=false
for _ in $(seq 1 30); do
  if docker compose exec -T web wget -q -O /dev/null http://127.0.0.1/api/health 2>/dev/null; then
    ok=true; break
  fi
  sleep 2
done

log "Estado dos serviços:"
docker compose ps

if [[ "$ok" != true ]]; then
  err "A aplicação não respondeu depois do deploy."
  rollback_hint
  exit 1
fi

log "Deploy concluído (antes: ${PREV_COMMIT:0:7}, agora: $(git rev-parse --short HEAD))."
write_state deploy.json "{\"commit\":\"$(git rev-parse --short HEAD)\",\"previous\":\"${PREV_COMMIT:0:7}\",\"at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
if [[ -n "$BACKUP" ]]; then log "Backup pré-deploy: $BACKUP"; fi
