#!/usr/bin/env bash
# Deploy do Shadow Nexus Worklog.
# Uso:
#   ./deploy.sh          → verifica dependências e faz o deploy (não instala nada)
#   ./deploy.sh --install → tenta instalar dependências que faltam (Debian/Ubuntu), depois faz deploy
set -euo pipefail

INSTALL=false
[[ "${1:-}" == "--install" ]] && INSTALL=true

log()  { printf '\033[1;34m[deploy]\033[0m %s\n' "$1"; }
err()  { printf '\033[1;31m[erro]\033[0m %s\n' "$1" >&2; }

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
        sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
          -o /etc/apt/keyrings/docker.asc
        sudo chmod a+r /etc/apt/keyrings/docker.asc
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
          | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        sudo apt-get update
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
          docker-buildx-plugin docker-compose-plugin
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
if grep -vE '^[[:space:]]*(#|$)' .env | grep -qE 'CHANGE_?ME|your_?secret|placeholder'; then
  err ".env ainda contém valores placeholder. Preencha antes de subir."
  exit 1
fi

# --- 4. Backup do banco ANTES de qualquer mudança ---
# O banco de produção é o que não pode se perder. Se o Postgres já está no ar,
# fazemos um pg_dump (formato custom) e conferimos o índice do arquivo; se o
# backup falhar, o deploy para aqui, antes de mexer em código ou containers.
KEEP_BACKUPS="${KEEP_BACKUPS:-14}"
PREV_COMMIT="$(git rev-parse HEAD)"
BACKUP=""

if [[ -n "$(docker compose ps --status running -q db 2>/dev/null)" ]]; then
  mkdir -p -m 700 backups
  BACKUP="backups/pre-deploy-$(date +%Y%m%d-%H%M%S)-${PREV_COMMIT:0:7}.dump"
  log "Backup do banco em $BACKUP ..."
  (
    umask 077
    docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$BACKUP"
  ) || { err "pg_dump falhou. Deploy abortado; nada foi alterado."; rm -f "$BACKUP"; exit 1; }

  tables=$(docker compose exec -T db pg_restore --list < "$BACKUP" 2>/dev/null | grep -c "TABLE DATA" || true)
  if [[ ! -s "$BACKUP" || "$tables" -lt 1 ]]; then
    err "Backup vazio ou ilegível ($BACKUP). Deploy abortado; nada foi alterado."
    exit 1
  fi
  log "Backup ok: $(du -h "$BACKUP" | cut -f1), $tables tabelas com dados."

  # Retenção: mantém só os KEEP_BACKUPS mais recentes.
  ls -1t backups/pre-deploy-*.dump 2>/dev/null | tail -n +"$((KEEP_BACKUPS + 1))" | xargs -r rm --
else
  log "Banco ainda não está rodando (primeira instalação?): sem backup a fazer."
fi

# --- 5. Deploy ---
log "Atualizando código..."
git pull --ff-only

log "Subindo containers..."
docker compose up -d --build

# --- 6. Teste de fumaça: nginx -> backend respondendo pela rede interna ---
log "Conferindo se a aplicação respondeu..."
ok=false
for _ in $(seq 1 30); do
  if docker compose exec -T web wget -q -O /dev/null http://127.0.0.1/api/auth/config 2>/dev/null; then
    ok=true; break
  fi
  sleep 2
done

log "Estado dos serviços:"
docker compose ps

if [[ "$ok" != true ]]; then
  err "A aplicação não respondeu depois do deploy."
  err "Rollback do código:  git checkout $PREV_COMMIT && docker compose up -d --build"
  if [[ -n "$BACKUP" ]]; then
    err "Rollback do banco (só se uma migration estragou dados):"
    err "  docker compose exec -T db sh -c 'pg_restore -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" --clean --if-exists' < $BACKUP"
  fi
  exit 1
fi

log "Deploy concluído (antes: ${PREV_COMMIT:0:7}, agora: $(git rev-parse --short HEAD))."
if [[ -n "$BACKUP" ]]; then log "Backup pré-deploy: $BACKUP"; fi
