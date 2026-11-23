#!/usr/bin/env bash
# Vigia de saúde: o "restart: unless-stopped" do compose não age quando um
# container fica unhealthy. Rodado por um timer do systemd (tools/nexus-vigia.*),
# reinicia o serviço doente e avisa por e-mail UMA vez por incidente (usa o SMTP
# do próprio Nexus, de dentro do backend). Sem alerta de terceiros.
#   Uso: tools/vigia.sh            (na pasta do projeto ou com NEXUS_DIR)
#   Destino do aviso: ALERT_EMAIL no .env (padrão: ADMIN_EMAIL).
#
# O critério é o mesmo do deploy.sh: /api/health respondendo pelo nginx (passa por
# web, backend e banco). Serviço parado, ausente ou em laço de reinício também
# conta como doente, mas o vigia NÃO sobe o que está parado: pode ter sido parado
# de propósito (restauração, seção 9 do ADMIN.md). Ele só reinicia o que está
# rodando e unhealthy, e avisa.
# Limite conhecido: o e-mail sai de dentro do backend. Com o backend fora do ar
# (ou sem SMTP) o aviso não sai; fica no journal (journalctl -t nexus-vigia) e é
# tentado de novo a cada passada.
#
# Durante um ./deploy.sh o vigia não faz nada: o deploy deixa o marcador
# estado/deploy-em-andamento e o apaga ao sair. Marcador com 15 min ou mais é
# deploy que morreu sem apagar: o vigia volta a olhar e a avisar.
#
# Antes de restaurar um backup, pare o timer (systemctl stop nexus-vigia.timer).
set -uo pipefail
cd "${NEXUS_DIR:-$(dirname "$0")/..}" || exit 1
STATE=".vigia-alerta"   # existe enquanto há incidente aberto (já avisado)

em_deploy() { [[ -n "$(find estado/deploy-em-andamento -mmin -15 2>/dev/null)" ]]; }
em_deploy && exit 0

env_get() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2-; }
para="$(env_get ALERT_EMAIL)"; para="${para:-$(env_get ADMIN_EMAIL)}"

avisar() {  # $1 assunto, $2 texto; devolve 0 só se o e-mail saiu
  [[ -n "$para" ]] || { logger -t nexus-vigia "sem ALERT_EMAIL nem ADMIN_EMAIL: aviso só no journal"; return 1; }
  docker compose exec -T -e VIGIA_PARA="$para" -e VIGIA_ASSUNTO="$1" -e VIGIA_TEXTO="$2" backend \
    python -c 'import os; from app import mailer; mailer.send(os.environ["VIGIA_PARA"], os.environ["VIGIA_ASSUNTO"], os.environ["VIGIA_TEXTO"])' \
    >/dev/null 2>&1 || { logger -t nexus-vigia "não consegui mandar o e-mail de alerta"; return 1; }
}

# Três tentativas em 20 s: um backend que acabou de subir (health: starting) não é incidente.
responde() {
  for _ in 1 2 3; do
    docker compose exec -T web wget -q -O /dev/null http://127.0.0.1/api/health 2>/dev/null && return 0
    sleep 10
  done
  return 1
}

if ! estado="$(docker compose ps -a --format '{{.Service}} {{.State}} {{.Health}}')"; then
  logger -t nexus-vigia "docker compose ps falhou: não sei o estado dos serviços"
  exit 1
fi

doentes=""      # tudo que não está bem (vai no aviso)
reiniciar=""    # só o que está rodando e unhealthy
for s in db backend web; do
  linha="$(awk -v s="$s" '$1==s{print $2, $3}' <<<"$estado")"
  case "$linha" in
    "")                  doentes+="$s(ausente) " ;;
    "running unhealthy") doentes+="$s(unhealthy) "; reiniciar+="$s " ;;
    running*)            ;;
    *)                   doentes+="$s(${linha%% *}) " ;;   # restarting, exited, paused, created, dead
  esac
done
if [[ -z "$doentes" ]] && ! responde; then
  doentes="aplicação(/api/health sem resposta) "
fi
doentes="${doentes% }"
# Deploy que começou no meio desta passada: a parada é dele, não é incidente.
[[ -n "$doentes" ]] && em_deploy && exit 0

if [[ -z "$doentes" ]]; then
  # Só aqui, com o health respondendo, o incidente fecha.
  if [[ -f "$STATE" ]]; then
    rm -f "$STATE"
    logger -t nexus-vigia "tudo saudável de novo"
    avisar "Nexus: tudo saudável de novo" "Os serviços do Nexus voltaram a responder em $(uname -n) às $(date '+%d/%m %H:%M')."
  fi
  exit 0
fi

logger -t nexus-vigia "doente: $doentes"
for s in $reiniciar; do
  logger -t nexus-vigia "serviço $s unhealthy: reiniciando"
  docker compose restart "$s" >/dev/null 2>&1
done
if [[ ! -f "$STATE" ]]; then
  fiz="não reiniciou nada (serviço parado não é religado pelo vigia: docker compose up -d)"
  [[ -n "$reiniciar" ]] && fiz="reiniciou: $reiniciar"
  # O incidente só fica marcado como avisado se o e-mail saiu; senão a próxima passada tenta de novo.
  if avisar "Nexus: serviço com problema ($doentes)" \
    "O vigia encontrou em $(uname -n) às $(date '+%d/%m %H:%M'): $doentes. Ele $fiz. Veja: docker compose ps; docker compose logs --tail 100"; then
    date -Is > "$STATE"
  fi
fi
exit 0
