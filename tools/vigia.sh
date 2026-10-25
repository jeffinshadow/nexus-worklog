#!/usr/bin/env bash
# Vigia de saúde: o "restart: unless-stopped" do compose não age quando um
# container fica unhealthy. Rodado por um timer do systemd (tools/nexus-vigia.*),
# reinicia o serviço doente e avisa por e-mail UMA vez por incidente (usa o SMTP
# do próprio Nexus, de dentro do backend). Sem alerta de terceiros.
#   Uso: tools/vigia.sh            (na pasta do projeto ou com NEXUS_DIR)
#   Destino do aviso: ALERT_EMAIL no .env (padrão: ADMIN_EMAIL).
set -uo pipefail
cd "${NEXUS_DIR:-$(dirname "$0")/..}" || exit 1
STATE=".vigia-alerta"   # existe enquanto há incidente aberto (já avisado)

env_get() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2-; }
para="$(env_get ALERT_EMAIL)"; para="${para:-$(env_get ADMIN_EMAIL)}"

avisar() {  # $1 assunto, $2 texto
  [[ -n "$para" ]] || return 0
  docker compose exec -T -e VIGIA_PARA="$para" -e VIGIA_ASSUNTO="$1" -e VIGIA_TEXTO="$2" backend \
    python -c 'import os; from app import mailer; mailer.send(os.environ["VIGIA_PARA"], os.environ["VIGIA_ASSUNTO"], os.environ["VIGIA_TEXTO"])' \
    >/dev/null 2>&1 || logger -t nexus-vigia "não consegui mandar o e-mail de alerta"
}

doentes=$(docker compose ps --format '{{.Service}} {{.Health}}' | awk '$2=="unhealthy"{print $1}')
if [[ -z "$doentes" ]]; then
  if [[ -f "$STATE" ]]; then
    rm -f "$STATE"
    logger -t nexus-vigia "tudo saudável de novo"
    avisar "Nexus: tudo saudável de novo" "Os serviços do Nexus voltaram a responder em $(uname -n) às $(date '+%d/%m %H:%M')."
  fi
  exit 0
fi

for s in $doentes; do
  logger -t nexus-vigia "serviço $s unhealthy: reiniciando"
  docker compose restart "$s" >/dev/null 2>&1
done
if [[ ! -f "$STATE" ]]; then
  date -Is > "$STATE"
  avisar "Nexus: serviço reiniciado ($doentes)" \
    "O vigia encontrou $doentes sem responder em $(uname -n) às $(date '+%d/%m %H:%M') e reiniciou. Se continuar, veja: docker compose ps; docker compose logs --tail 100 $doentes"
fi
