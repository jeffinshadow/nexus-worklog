"""Integração com o GLPI (11 ou superior), pela API REST legada (apirest.php).

O chamado aberto no nome da pessoa vira tarefa; a tarefa concluída vira a
solução do chamado (o GLPI passa o chamado para "solucionado"; fechar continua
sendo regra de lá). O GLPI segue dono do chamado: o Nexus só guarda o número.

- O admin informa o endereço do GLPI (e o App-Token, se o cliente de API de lá
  exigir). Cada pessoa cola o próprio token do GLPI: sem conta de serviço, a
  solução sai com o nome dela.
- Os dois tokens ficam cifrados (Fernet, chave derivada do SECRET_KEY): o
  vazamento só do banco não os entrega. Nunca voltam pela API nem vão ao log.
- Roda no agendador (notify.scheduler), em laço próprio: a cada 5 minutos por
  pessoa conectada, mais o "Atualizar agora". Falha → 1, 5, 30 min, 2 h e 12 h;
  5 seguidas pausam (a tela mostra o motivo). Token recusado pausa na hora.
- O vínculo chamado -> tarefa (glpi_tickets, sql/060) é gravado só aqui: uma
  tarefa criada por chave de API com external_ref "glpi:N" não manda solução.
- O endereço é só do admin e tem checagem própria (rede interna é aceita de
  propósito: é onde o GLPI costuma ficar); sem redirecionamento, prazo curto e
  resposta limitada.
"""
import base64
import hashlib
import hmac
import html
import http.client
import ipaddress
import json
import logging
import re
import socket
import threading
from contextlib import contextmanager
from datetime import date
from urllib.parse import urlencode, urlsplit

from cryptography.fernet import Fernet, InvalidToken

from . import audit, db, webhooks
from .config import config
from .services import default_project

log = logging.getLogger("uvicorn.error")

MIN_VERSION = 11  # versões testadas: 11.0.13 e 12.0.2
EVERY_MIN = 5  # intervalo da sincronização de cada pessoa
MAX_FAILURES = 5
MAX_TICKETS = 100  # chamados abertos por pessoa em cada passada
MAX_BODY = 1024 * 1024  # resposta do GLPI, em bytes
UNDO_SECONDS = 60  # a solução espera um pouco: dá tempo de desfazer uma conclusão por engano
SOLVED = 5  # status do chamado no GLPI: 5 solucionado, 6 fechado
CTX = {"actor": "system", "token_name": "GLPI"}  # autoria do que a sincronização grava

REOPENED = "O chamado foi reaberto no GLPI (a solução não foi aceita)."
GONE = "Este chamado não está mais aberto no seu nome no GLPI (foi encerrado ou passou para outra pessoa)."
TOKEN_REFUSED = "o GLPI recusou o seu token: gere outro em Preferências › API token e conecte de novo"


class GlpiError(Exception):
    """Falha na conversa com o GLPI, já em linguagem comum. `down`: o GLPI não
    respondeu (vale para todos); `auth`: o token da pessoa não serve mais."""

    def __init__(self, message: str, down: bool = False, auth: bool = False):
        super().__init__(message)
        self.down, self.auth = down, auth


# -------------------------------------------------------------------- cifra --

def _fernet() -> Fernet:
    raw = hmac.new(config.SECRET_KEY.encode(), b"glpi-token", hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def seal(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def unseal(sealed: str) -> str:
    """Trocou o SECRET_KEY (ou o valor foi adulterado): não abre, e a pessoa reconecta."""
    try:
        return _fernet().decrypt(sealed.encode()).decode()
    except (InvalidToken, ValueError):
        raise GlpiError("o token guardado não abre mais: conecte de novo ao GLPI", auth=True) from None


# ----------------------------------------------------------------- endereço --

def _ip_ok(raw: str) -> bool:
    """Rede interna pode (é onde o GLPI fica); o próprio servidor, link-local
    (metadados de nuvem) e faixas reservadas, não."""
    ip = ipaddress.ip_address(raw.split("%")[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved)


def check_base(url: str) -> tuple[str, str, int, str, str]:
    """Valida e resolve o endereço do GLPI: (esquema, host, porta, caminho, IP).
    A conexão usa esse mesmo IP (o DNS não troca entre a checagem e o envio)."""
    url = (url or "").strip()
    if re.search(r"[\x00-\x20\x7f]|%0[0-9a-f]|%1[0-9a-f]|%7f", url, re.I):
        raise webhooks.Refused("o endereço tem caracteres inválidos")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise webhooks.Refused("use um endereço começando com http:// ou https://")
    if parts.username or parts.password:
        raise webhooks.Refused("sem usuário e senha no endereço")
    if parts.query or parts.fragment:
        raise webhooks.Refused("informe só o endereço do GLPI, sem ? nem #")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise webhooks.Refused("porta inválida") from None
    try:
        ips = webhooks.resolve(parts.hostname, port)
    except (OSError, UnicodeError):
        raise webhooks.Refused("endereço não encontrado (DNS)") from None
    if not ips or not all(_ip_ok(ip) for ip in ips):
        raise webhooks.Refused("esse endereço aponta para o próprio servidor ou para uma faixa reservada")
    return parts.scheme, parts.hostname, port, parts.path.rstrip("/"), sorted(ips)[0]


def clean_base(url: str | None) -> str | None:
    """O endereço como é guardado: sem a barra do fim e sem o /apirest.php (o Nexus acrescenta)."""
    url = (url or "").strip().rstrip("/")
    if url.lower().endswith("/apirest.php"):
        url = url[:-len("/apirest.php")].rstrip("/")
    return url or None


def request(base: str, method: str, path: str, headers: dict, body: dict | None = None) -> tuple[int, object]:
    """Uma chamada à API legada: (status, JSON ou None). Sem seguir
    redirecionamento; prazo por operação e para a chamada inteira; resposta limitada."""
    scheme, host, port, prefix, ip = check_base(base)
    if scheme == "https":
        conn = webhooks._Pinned(host, port, ip)
    else:
        conn = http.client.HTTPConnection(ip, port, timeout=webhooks.TIMEOUT)
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Host": host if port in (80, 443) else f"{host}:{port}", **headers,
               **({"Content-Type": "application/json"} if data else {})}

    def cut():
        try:
            if conn.sock:
                conn.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    timer = threading.Timer(webhooks.DEADLINE, cut)
    timer.start()
    try:
        conn.request(method, f"{prefix}/apirest.php{path}", body=data, headers=headers)
        res = conn.getresponse()
        raw = res.read(MAX_BODY + 1)
    finally:
        timer.cancel()
        conn.close()
    if len(raw) > MAX_BODY:
        raise ValueError("resposta grande demais")
    try:
        return res.status, json.loads(raw) if raw else None
    except ValueError:
        return res.status, None  # página HTML (endereço errado, proxy): quem chamou decide pelo status


# ------------------------------------------------------------------ cliente --

def settings() -> dict | None:
    """Endereço e App-Token da instância (None = o admin não configurou o GLPI)."""
    r = db.query_one("SELECT glpi_url, glpi_app_token FROM app_settings WHERE id = 1")
    if not r or not r["glpi_url"]:
        return None
    return {"url": r["glpi_url"], "app_token": unseal(r["glpi_app_token"]) if r["glpi_app_token"] else None}


def _api(cfg: dict, method: str, path: str, headers: dict, body: dict | None = None) -> tuple[int, object]:
    h = {"Accept": "application/json", "User-Agent": "Nexus-Worklog-GLPI/1", **headers}
    if cfg["app_token"]:
        h["App-Token"] = cfg["app_token"]
    try:
        status, data = request(cfg["url"], method, path, h, body)
    except webhooks.Refused as e:
        raise GlpiError(f"endereço do GLPI: {e}", down=True) from None
    except Exception as e:  # noqa: BLE001 — rede, TLS, prazo: vira explicação, nunca 500
        raise GlpiError(webhooks._explain(e).replace("destino", "GLPI"), down=True) from None
    if status >= 500:
        raise GlpiError(f"o GLPI respondeu HTTP {status}", down=True)
    return status, data


def _login_error(status: int, data) -> GlpiError:
    """A recusa do initSession em linguagem comum (os códigos são os mesmos no GLPI 11 e no 12)."""
    code = data[0] if isinstance(data, list) and data and isinstance(data[0], str) else ""
    if code == "ERROR_GLPI_LOGIN_USER_TOKEN" or status == 401:
        return GlpiError(TOKEN_REFUSED, auth=True)
    if code == "ERROR_APP_TOKEN_PARAMETERS_MISSING":
        return GlpiError("o GLPI exige um App-Token, e o Nexus não tem um configurado (Admin › Para empresas › GLPI)")
    if code == "ERROR_WRONG_APP_TOKEN_PARAMETER":
        return GlpiError("o GLPI recusou o App-Token: ele está errado, ou o IP do Nexus está fora da faixa "
                         "do cliente de API do GLPI")
    if code == "ERROR":
        return GlpiError("o GLPI recusou a conexão: confira se a API está ligada lá (Configurar › Geral › API)")
    if not code:
        return GlpiError(f"esse endereço não respondeu como um GLPI (HTTP {status}): confira o endereço", down=True)
    return GlpiError(f"o GLPI recusou a conexão (HTTP {status})")


@contextmanager
def session(cfg: dict, user_token: str):
    """Sessão de uma passada: (chamar, dados da sessão). Sempre encerra (killSession)."""
    status, data = _api(cfg, "GET", "/initSession?get_full_session=true", {"Authorization": f"user_token {user_token}"})
    if status != 200 or not isinstance(data, dict) or not data.get("session_token"):
        raise _login_error(status, data)

    def call(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        return _api(cfg, method, path, {"Session-Token": data["session_token"]}, body)
    try:
        yield call, data.get("session") or {}
    finally:
        try:
            call("GET", "/killSession")
        except GlpiError:
            pass


def probe(cfg: dict) -> dict:
    """Admin › Testar: um initSession sem usuário. Com endereço e App-Token certos,
    o GLPI responde que falta o login: é esse o sinal de "tudo certo"."""
    try:
        status, data = _api(cfg, "GET", "/initSession", {})
    except GlpiError as e:
        return {"ok": False, "error": str(e)}
    if isinstance(data, list) and data and data[0] == "ERROR_LOGIN_PARAMETERS_MISSING":
        return {"ok": True, "error": None}
    return {"ok": False, "error": str(_login_error(status, data))}


def _open_tickets(call) -> list[dict]:
    """Chamados abertos (não solucionados nem fechados) em que a pessoa é o técnico."""
    q = {"criteria[0][field]": 5, "criteria[0][searchtype]": "equals", "criteria[0][value]": "myself",
         "criteria[1][link]": "AND", "criteria[1][field]": 12, "criteria[1][searchtype]": "equals",
         "criteria[1][value]": "notold", "range": f"0-{MAX_TICKETS - 1}"}
    for i, f in enumerate((2, 1, 21, 3, 18)):  # id, título, descrição, prioridade, prazo (tempo para solução)
        q[f"forcedisplay[{i}]"] = f
    status, data = call("GET", "/search/Ticket?" + urlencode(q))
    if status not in (200, 206) or not isinstance(data, dict):
        raise GlpiError(f"o GLPI não deixou listar os seus chamados (HTTP {status}): confira o seu perfil lá")
    return [t for t in data.get("data") or [] if isinstance(t, dict) and str(t.get("2", "")).isdigit()]


# ----------------------------------------------------------- texto <-> HTML --

def plain(text) -> str:
    """HTML do GLPI -> texto simples (o Nexus nunca guarda nem mostra HTML de fora)."""
    t = html.unescape(str(text or ""))  # a busca às vezes devolve o HTML escapado (&#60;p&#62;)
    t = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", "", t)
    t = re.sub(r"(?i)<(br|/p|/li|/div|/h\d|/tr)\s*/?>", "\n", t)
    t = html.unescape(re.sub(r"(?s)<[^>]*>", "", t))
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t\r\xa0]+", " ", t)).strip()


def _cut(text: str, size: int) -> str:
    return text if len(text) <= size else text[:size - 1].rstrip() + "…"


def to_html(text: str) -> str:
    """Texto do Nexus -> HTML para o GLPI: tudo escapado; quebra de linha vira <br>."""
    return "".join(f"<p>{html.escape(p.strip()).replace(chr(10), '<br>')}</p>"
                   for p in re.split(r"\n\s*\n", text) if p.strip())


def solution_text(task: dict) -> str:
    """O que vai para o chamado: como foi resolvido e o tempo apontado. As
    anotações da tarefa NÃO vão (são da pessoa; o requerente lê a solução)."""
    parts = [(task["resolution"] or "").strip() or "Concluído."]
    if task["minutes"]:
        parts.append(f"Tempo registrado: {task['minutes'] // 60} h {task['minutes'] % 60:02d} min")
    parts.append("Registrado pelo Nexus Worklog.")
    return "\n\n".join(parts)


# ------------------------------------------------------------ sincronização --

def connect(user_id: int, token: str) -> str:
    """Confere o token no GLPI (e a versão de lá) e guarda cifrado. Devolve o nome no GLPI."""
    cfg = settings()
    if not cfg:
        raise GlpiError("o GLPI não foi configurado pela administração")
    with session(cfg, token) as (call, info):
        _, conf = call("GET", "/getGlpiConfig")
    version = str(((conf or {}).get("cfg_glpi") or {}).get("version") or "") if isinstance(conf, dict) else ""
    if version.split(".")[0].isdigit() and int(version.split(".")[0]) < MIN_VERSION:
        raise GlpiError(f"esse GLPI é da versão {version}; a integração precisa do GLPI {MIN_VERSION} ou superior")
    name = " ".join(str(info.get(k) or "") for k in ("glpifirstname", "glpirealname")).strip() or info.get("glpiname")
    db.execute(
        """INSERT INTO glpi_accounts (user_id, token, glpi_name) VALUES (%s, %s, %s)
           ON CONFLICT (user_id) DO UPDATE SET token = EXCLUDED.token, glpi_name = EXCLUDED.glpi_name,
                 failures = 0, last_error = NULL, next_attempt_at = NULL, last_sync_at = NULL""",
        (user_id, seal(token), _cut(str(name or ""), 120) or None))
    return name


def _import(user_id: int, t: dict) -> None:
    """Chamado novo na lista da pessoa -> tarefa (uma vez só: o vínculo é a trava)."""
    tid = int(t["2"])
    with db.transaction():
        if not db.query_one("""INSERT INTO glpi_tickets (user_id, ticket_id) VALUES (%s, %s)
                               ON CONFLICT DO NOTHING RETURNING ticket_id""", (user_id, tid)):
            return
        # Já existe uma tarefa com essa chave, criada por fora (automação, chave de API): não duplica
        # nem adota. O vínculo fica sem tarefa: só o que a sincronização criou manda solução.
        if db.query_one("SELECT 1 FROM worklog_tasks WHERE user_id = %s AND external_ref = %s", (user_id, f"glpi:{tid}")):
            return
        from .routers.objectives import next_position  # import tardio: os routers importam este módulo
        project_id = default_project(user_id)
        prio = t.get("3") if isinstance(t.get("3"), int) else 3
        try:
            due = date.fromisoformat(str(t.get("18"))[:10])
        except ValueError:
            due = None
        task = db.query_one(
            """INSERT INTO worklog_tasks (user_id, title, description, status, due_date, project_id, priority,
                                          ticket, external_ref, exec_position)
               VALUES (%s, %s, %s, 'todo', %s, %s, %s, %s, %s, %s) RETURNING id""",
            (user_id, _cut(plain(t.get("1")), 200) or f"Chamado {tid}", _cut(plain(t.get("21")), 300) or None, due,
             project_id, 1 if prio >= 4 else 3 if prio <= 2 else 2, str(tid), f"glpi:{tid}",
             next_position(user_id, project_id, None)))
        audit.record({**CTX, "user_id": user_id}, "worklog.create", "worklog", task["id"],
                     after=audit.worklog_snapshot(task["id"], user_id))
        db.execute("UPDATE glpi_tickets SET task_id = %s WHERE user_id = %s AND ticket_id = %s",
                   (task["id"], user_id, tid))


def _reopened(user_id: int, ticket_id: int) -> None:
    """O chamado já solucionado voltou à lista de abertos (solução recusada): a
    próxima conclusão manda outra solução; a tarefa concluída é reaberta, com uma anotação."""
    with db.transaction():
        link = db.query_one(
            """UPDATE glpi_tickets SET sent_at = NULL, tries = 0, last_error = NULL
                WHERE user_id = %s AND ticket_id = %s AND sent_at IS NOT NULL RETURNING task_id""",
            (user_id, ticket_id))
        before = link and link["task_id"] and audit.worklog_snapshot(link["task_id"], user_id)
        if not before or before["status"] != "done":
            return
        db.execute("UPDATE worklog_tasks SET status = 'todo', completed_at = NULL WHERE id = %s AND user_id = %s",
                   (before["id"], user_id))
        db.execute("INSERT INTO task_notes (task_id, user_id, body, actor, token_name) VALUES (%s, %s, %s, %s, %s)",
                   (before["id"], user_id, REOPENED, CTX["actor"], CTX["token_name"]))
        audit.record({**CTX, "user_id": user_id}, "worklog.update", "worklog", before["id"], before=before,
                     after=audit.worklog_snapshot(before["id"], user_id))


def _pull(user_id: int, call) -> None:
    tickets = _open_tickets(call)
    known = {r["ticket_id"]: r["sent_at"] for r in db.query_all(
        "SELECT ticket_id, sent_at FROM glpi_tickets WHERE user_id = %s", (user_id,))}
    for t in tickets:
        tid = int(t["2"])
        if tid not in known:
            _import(user_id, t)
        elif known[tid]:
            _reopened(user_id, tid)
    if len(tickets) < MAX_TICKETS:  # lista inteira: o que não veio saiu do nome da pessoa
        # Tarefa ainda aberta de um chamado que saiu da lista: UMA anotação; a pessoa decide o destino.
        db.execute(
            """INSERT INTO task_notes (task_id, user_id, body, actor, token_name, external_ref)
               SELECT g.task_id, g.user_id, %s, %s, %s, 'glpi:' || g.ticket_id || ':saiu'
                 FROM glpi_tickets g JOIN worklog_tasks w ON w.id = g.task_id
                WHERE g.user_id = %s AND w.status <> 'done' AND NOT (g.ticket_id = ANY(%s))
               ON CONFLICT DO NOTHING""",
            (GONE, CTX["actor"], CTX["token_name"], user_id, [int(t["2"]) for t in tickets]))


def _push(user_id: int, call, manual: bool) -> None:
    """Tarefas concluídas de chamados importados -> solução no GLPI (confere o status antes de enviar)."""
    rows = db.query_all(
        """SELECT g.ticket_id, w.resolution,
                  (SELECT COALESCE(sum(e.minutes), 0) FROM time_entries e WHERE e.task_id = w.id)::int AS minutes
             FROM glpi_tickets g JOIN worklog_tasks w ON w.id = g.task_id
            WHERE g.user_id = %s AND g.sent_at IS NULL AND g.tries < %s AND w.status = 'done'
              AND (%s OR w.completed_at <= now() - make_interval(secs => %s))
            ORDER BY g.ticket_id""", (user_id, MAX_FAILURES, manual, UNDO_SECONDS))

    def solved(tid: int) -> bool:
        status, t = call("GET", f"/Ticket/{tid}")
        return status == 200 and isinstance(t, dict) and (t.get("status") or 0) >= SOLVED

    for r in rows:
        tid, error = r["ticket_id"], None
        if not solved(tid):  # já solucionado (por outra pessoa, ou envio cuja resposta se perdeu): nada a mandar
            status, _ = call("POST", "/ITILSolution",
                             {"input": {"itemtype": "Ticket", "items_id": tid, "content": to_html(solution_text(r))}})
            if status not in (200, 201) and not solved(tid):
                error = f"o GLPI recusou a solução (HTTP {status}): o chamado pode ter sido excluído ou saído do seu alcance"
        db.execute(
            """UPDATE glpi_tickets SET sent_at = CASE WHEN %(e)s::text IS NULL THEN now() END, last_error = %(e)s,
                      tries = CASE WHEN %(e)s::text IS NULL THEN 0 ELSE tries + 1 END
                WHERE user_id = %(u)s AND ticket_id = %(t)s""", {"e": error, "u": user_id, "t": tid})


def sync(user_id: int, manual: bool = False) -> GlpiError | None:
    """Uma passada de uma pessoa: puxa os chamados e manda as soluções pendentes.
    Nunca levanta por causa do GLPI: a falha fica registrada na conta (e é devolvida)."""
    acc = db.query_one("SELECT token, failures FROM glpi_accounts WHERE user_id = %s", (user_id,))
    if not acc:
        return None
    try:
        cfg = settings()
        if not cfg:
            return None
        with session(cfg, unseal(acc["token"])) as (call, _):
            _pull(user_id, call)
            _push(user_id, call, manual)
    except GlpiError as e:
        step = webhooks.BACKOFF_MIN[min(acc["failures"], len(webhooks.BACKOFF_MIN) - 1)]
        db.execute(
            """UPDATE glpi_accounts SET failures = CASE WHEN %s THEN %s ELSE failures + 1 END, last_error = %s,
                      next_attempt_at = now() + make_interval(mins => %s) WHERE user_id = %s""",
            (e.auth, MAX_FAILURES, str(e)[:200], step, user_id))
        return e
    db.execute("""UPDATE glpi_accounts SET last_sync_at = now(), failures = 0, last_error = NULL, next_attempt_at = NULL
                   WHERE user_id = %s""", (user_id,))
    return None


def retry(user_id: int) -> None:
    """"Atualizar agora": tira a pausa e tenta de novo as soluções que o GLPI recusou."""
    db.execute("UPDATE glpi_accounts SET failures = 0, next_attempt_at = NULL WHERE user_id = %s", (user_id,))
    db.execute("UPDATE glpi_tickets SET tries = 0 WHERE user_id = %s AND sent_at IS NULL", (user_id,))


def run_once() -> list[tuple[int, str | None]]:
    """Uma passada do agendador: (pessoa, erro) de cada conta na vez. Conta
    bloqueada ou sem o papel Usuário não sincroniza."""
    rows = db.query_all(
        """SELECT a.user_id FROM glpi_accounts a JOIN users u ON u.id = a.user_id
            WHERE a.failures < %s AND (a.next_attempt_at IS NULL OR a.next_attempt_at <= now())
              AND (a.last_sync_at IS NULL OR a.last_sync_at <= now() - make_interval(mins => %s))
              AND u.blocked_at IS NULL
              AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'user')
            ORDER BY a.last_sync_at NULLS FIRST, a.user_id""", (MAX_FAILURES, EVERY_MIN))
    done = []
    for r in rows:
        try:
            error = sync(r["user_id"])
        except Exception:  # noqa: BLE001 — uma conta com problema não para as outras
            log.exception("sincronização do GLPI do usuário %s falhou nesta passada", r["user_id"])
            continue
        done.append((r["user_id"], str(error) if error else None))
        if error and error.down:  # GLPI fora do ar: não espera o prazo de cada pessoa; tenta na próxima passada
            break
    return done


def state(user_id: int) -> dict:
    """O que a tela mostra (Configurações › Chamados). O token nunca sai daqui."""
    available = bool(db.query_one("SELECT 1 FROM app_settings WHERE id = 1 AND glpi_url IS NOT NULL"))
    acc = db.query_one("SELECT glpi_name, last_sync_at, failures, last_error FROM glpi_accounts WHERE user_id = %s",
                       (user_id,))
    if not acc:
        return {"available": available, "connected": False}
    n = db.query_one("""SELECT count(*) FILTER (WHERE w.status <> 'done')::int AS open,
                               count(*) FILTER (WHERE w.status = 'done' AND g.sent_at IS NULL
                                                  AND g.last_error IS NULL)::int AS pending
                          FROM glpi_tickets g JOIN worklog_tasks w ON w.id = g.task_id WHERE g.user_id = %s""", (user_id,))
    failed = db.query_all("""SELECT ticket_id, task_id, last_error AS error FROM glpi_tickets
                              WHERE user_id = %s AND sent_at IS NULL AND last_error IS NOT NULL
                              ORDER BY ticket_id""", (user_id,))
    return {"available": available, "connected": True, "name": acc["glpi_name"], "last_sync_at": acc["last_sync_at"],
            "error": acc["last_error"], "paused": acc["failures"] >= MAX_FAILURES,
            "open": n["open"], "pending": n["pending"], "failed": failed}
