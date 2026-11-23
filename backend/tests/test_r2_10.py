"""r2-10: o vigia não avisa durante o deploy (marcador estado/deploy-em-andamento) e a
trava da senha do Postgres aceita a senha codificada com %XX na DATABASE_URL.

Os dois scripts rodam por subprocesso, com docker, git e logger falsos no PATH (nada de
docker de verdade). Eles ficam fora da pasta backend/: o container de testes precisa
de dois volumes no docker-compose.test.yml (./deploy.sh:/deploy.sh:ro e
./tools:/tools:ro); sem eles os testes são pulados."""
import os
import pathlib
import shutil
import subprocess
import time

import pytest

RAIZ = pathlib.Path(__file__).parents[2]
DEPLOY = RAIZ / "deploy.sh"
VIGIA = RAIZ / "tools" / "vigia.sh"
pytestmark = pytest.mark.skipif(
    not (DEPLOY.is_file() and VIGIA.is_file()),
    reason="deploy.sh e tools/vigia.sh não estão montados no container de testes")

# docker falso: anota cada chamada em $REG e responde conforme as variáveis FALSO_*.
DOCKER_FALSO = r"""#!/usr/bin/env bash
echo "docker $*" >> "$REG"
case "$*" in
  "compose version") exit 0 ;;
  "compose ps -a -q db") [[ -n "${FALSO_SEM_DOCKER:-}" ]] && exit 1; exit 0 ;;   # vazio: primeira instalação
  "compose ps -a --format"*) printf '%s\n' "$FALSO_PS" ;;
  "compose up -d") [[ -f estado/deploy-em-andamento ]] && echo "marcador presente no up" >> "$REG"
                   exit "${FALSO_UP_RC:-0}" ;;
  *"wget"*) exit "${FALSO_HEALTH_RC:-0}" ;;
  *"mailer.send"*) echo "EMAIL $*" >> "$REG" ;;
esac
exit 0
"""
GIT_FALSO = "#!/usr/bin/env bash\ncase \"$1\" in rev-parse) echo 0123456789abcdef ;; esac\nexit 0\n"
LOGGER_FALSO = "#!/usr/bin/env bash\necho \"logger $*\" >> \"$REG\"\n"
SLEEP_FALSO = "#!/usr/bin/env bash\necho \"sleep $*\" >> \"$REG\"\n"   # as esperas dos scripts (2 s e 10 s) não entram no teste


@pytest.fixture
def pasta(tmp_path):
    """Pasta de projeto de mentira: os dois scripts, um .env e os comandos falsos."""
    (tmp_path / "tools").mkdir()
    shutil.copy(DEPLOY, tmp_path / "deploy.sh")
    shutil.copy(VIGIA, tmp_path / "tools" / "vigia.sh")
    (tmp_path / "estado").mkdir()
    (tmp_path / ".env").write_text("ADMIN_EMAIL=admin@example.com\nAPP_URL=http://localhost\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for nome, corpo in (("docker", DOCKER_FALSO), ("git", GIT_FALSO), ("logger", LOGGER_FALSO), ("sleep", SLEEP_FALSO)):
        (bin_ / nome).write_text(corpo)
        (bin_ / nome).chmod(0o755)
    return tmp_path


def rodar(pasta, script, **extra):
    env = {"PATH": f"{pasta / 'bin'}:{os.environ['PATH']}", "REG": str(pasta / "chamadas.log"), **extra}
    r = subprocess.run(["bash", str(pasta / script)], env=env, capture_output=True, text=True, timeout=60)
    reg = pasta / "chamadas.log"
    return r, (reg.read_text() if reg.exists() else "")


WEB_PARADO = "db running healthy\nbackend running healthy\nweb exited "
TUDO_NO_AR = "db running healthy\nbackend running healthy\nweb running healthy"


def test_vigia_pula_a_passada_com_o_marcador_do_deploy(pasta):
    marca = pasta / "estado" / "deploy-em-andamento"
    marca.write_text("")
    r, reg = rodar(pasta, "tools/vigia.sh", FALSO_PS=WEB_PARADO)
    assert r.returncode == 0
    assert "EMAIL" not in reg and "logger" not in reg and "restart" not in reg
    assert not (pasta / ".vigia-alerta").exists()

    # Marcador velho (deploy que morreu sem apagar): o vigia volta a avisar.
    velho = time.time() - 16 * 60
    os.utime(marca, (velho, velho))
    r, reg = rodar(pasta, "tools/vigia.sh", FALSO_PS=WEB_PARADO)
    assert r.returncode == 0
    assert "EMAIL" in reg and "serviço com problema (web(exited))" in reg
    assert (pasta / ".vigia-alerta").exists()


def test_vigia_sem_marcador_avisa_do_health_sem_resposta_com_tudo_running(pasta):
    r, reg = rodar(pasta, "tools/vigia.sh", FALSO_PS=TUDO_NO_AR, FALSO_HEALTH_RC="1")
    assert r.returncode == 0
    assert reg.count("wget") == 3 and reg.count("sleep 10") == 2   # três tentativas em 20 s, sem espera no fim
    assert "os três containers estão rodando" in reg and "docker compose up -d)" not in reg
    assert "logger -t nexus-vigia doente: aplicação(/api/health sem resposta)" in reg
    assert "serviço com problema (aplicação(/api/health sem resposta))" in reg and "restart" not in reg
    # Voltou a responder: fecha o incidente e avisa uma vez.
    r, reg = rodar(pasta, "tools/vigia.sh", FALSO_PS=TUDO_NO_AR)
    assert "tudo saudável de novo" in reg and not (pasta / ".vigia-alerta").exists()


def test_deploy_grava_o_marcador_antes_de_subir_e_apaga_ao_sair(pasta):
    marca = pasta / "estado" / "deploy-em-andamento"
    r, reg = rodar(pasta, "deploy.sh")
    assert r.returncode == 0, r.stderr
    assert "marcador presente no up" in reg
    assert not marca.exists()
    # Deploy que falha também apaga (senão o vigia ficaria 15 min calado com o site fora).
    (pasta / "chamadas.log").unlink()
    r, reg = rodar(pasta, "deploy.sh", FALSO_UP_RC="1")
    assert r.returncode == 1 and "marcador presente no up" in reg
    assert not marca.exists()


@pytest.mark.parametrize("crua,na_url,aceita", [
    ("xy@zw", "xy%40zw", True),              # codificada na URL, crua na outra: o caso certo
    ("a/b c%d#e?f", "a%2Fb%20c%25d%23e%3Ff", True),
    ("so-letras-123", "so-letras-123", True),
    ("xy%40zw", "xy%40zw", False),           # igual nas duas: o banco fica com a forma codificada e a URL diz outra
    ("xy@zw", "xy@zw", False),               # crua na URL: corta o endereço
    ("xy/zw", "xy/zw", False),
    ("xy%zw", "xy%zw", False),               # % solto na URL
    ("xy@zw", "xy%40zz", False),             # codificada, mas é outra senha
])
def test_trava_da_senha_compara_a_url_decodificada_com_a_senha_crua(pasta, crua, na_url, aceita):
    with (pasta / ".env").open("a") as f:
        f.write(f"POSTGRES_PASSWORD={crua}\nDATABASE_URL=postgresql://nexus:{na_url}@db:5432/nexus_worklog\n")
    # O docker falso recusa o "ps" do banco: quem passa da trava para logo depois, sem mexer em nada.
    r, _ = rodar(pasta, "deploy.sh", FALSO_SEM_DOCKER="1")
    assert r.returncode == 1
    if aceita:
        assert "docker compose ps falhou" in r.stderr and "POSTGRES_PASSWORD" not in r.stderr
    else:
        assert "docker compose ps falhou" not in r.stderr
        assert "POSTGRES_PASSWORD: a senha crua" in r.stderr and "DATABASE_URL: a mesma senha" in r.stderr
        assert crua not in r.stderr and na_url not in r.stderr   # a mensagem não mostra a senha
