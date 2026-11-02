import re
from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from .config import config

Status = Literal["todo", "in_progress", "blocked", "done"]

_PW = Field(min_length=config.MIN_PASSWORD_LEN, max_length=config.MAX_PASSWORD_LEN)


RoleName = Literal["user", "admin", "assigner", "viewer"]


class InviteIn(BaseModel):
    email: EmailStr
    # Nome da conta até o primeiro acesso (no tour a pessoa confirma ou ajusta).
    display_name: Optional[str] = Field(default=None, max_length=60)
    # Papéis já no convite (mudam depois em Papéis…). Padrão: só Usuário.
    roles: list[RoleName] = Field(default_factory=lambda: ["user"], min_length=1, max_length=4)


class InviteChoiceIn(BaseModel):
    """Convidar a partir de um pedido: nome (padrão: o do pedido) e papéis (padrão: só Usuário)."""
    display_name: Optional[str] = Field(default=None, max_length=60)
    roles: list[RoleName] = Field(default_factory=lambda: ["user"], min_length=1, max_length=4)


class OrgIn(BaseModel):
    """Admin › Para empresas e instituições. Campo ausente = mantém."""
    team_visibility: Optional[Literal["self", "managers"]] = None  # cada pessoa escolhe / visível para quem gerencia
    identity_managed: Optional[bool] = None  # nome e e-mail definidos pela administração
    tour_required: Optional[bool] = None     # tour obrigatório no primeiro acesso


class AdminProfileIn(BaseModel):
    """Admin › pessoa › Editar nome e e-mail. Campo ausente = mantém; nome vazio = derivado do e-mail."""
    display_name: Optional[str] = Field(default=None, max_length=60)
    email: Optional[EmailStr] = None


class EmailChangeIn(BaseModel):
    new_email: EmailStr
    password: str = Field(min_length=1, max_length=config.MAX_PASSWORD_LEN)  # senha atual


class EmailConfirmIn(BaseModel):
    token: str = Field(min_length=20, max_length=100)


class RolesIn(BaseModel):
    roles: list[RoleName] = Field(min_length=1, max_length=4)


class AppSettingsIn(BaseModel):
    retro_days: int = Field(ge=1, le=366)  # tarefas: criar/concluir até N dias atrás
    support_contact: Optional[str] = Field(default=None, max_length=200)  # "Ajuda": a quem recorrer
    photo_quota_mb: Optional[int] = Field(default=None, ge=0, le=100000)  # fotos por pessoa (MB); ausente = mantém


class DeleteUserIn(BaseModel):
    confirm_email: str = Field(max_length=320)  # o admin digita o e-mail da conta


class DeleteMeIn(BaseModel):
    password: str = Field(max_length=128)


class ConsentIn(BaseModel):
    accept: bool  # aceitar (receber tarefas de um atribuidor / ser visto pelo visualizador)


class AssignIn(BaseModel):
    user_id: int
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=300)
    due_date: Optional[date] = None
    priority: int = Field(default=2, ge=1, le=3)
    ticket: Optional[str] = Field(default=None, max_length=41)
    after_hours: bool = False

    @model_validator(mode="after")
    def _norm(self):
        self.ticket = _ticket(self.ticket)
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("título em branco")
        return self


class AssignEditIn(BaseModel):
    """Quem atribuiu ajusta enquanto a tarefa está "a fazer". Só o que vier muda
    (due_date ou description: null tira)."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=300)  # null ou vazio tira
    due_date: Optional[date] = None
    priority: Optional[int] = Field(default=None, ge=1, le=3)

    @model_validator(mode="after")
    def _norm(self):
        if self.title is not None:
            self.title = self.title.strip()
            if not self.title:
                raise ValueError("título em branco")
        if self.description is not None:
            self.description = self.description.strip() or None
        return self


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)  # senha gigante = Argon2 caro à toa


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = _PW


class ForgotIn(BaseModel):
    email: EmailStr


class LinkPasswordIn(BaseModel):
    token: str = Field(min_length=20, max_length=100)
    password: str = _PW
    display_name: Optional[str] = Field(default=None, max_length=60)  # só no convite


_HORA = re.compile(r"^(\d{1,2})(?:[:hH](\d{2})?)?$")


def parse_hour(txt) -> tuple[int, int]:
    """Hora escrita como se fala ou no relógio: "7h30", "7h", "07:30", "7:30",
    "18". Mesmo formato para o cronômetro e o horário das rotinas."""
    m = _HORA.match(str(txt).strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        raise ValueError(f"hora inválida: {txt} (use HH:MM, ex.: 07:30, ou 7h30)")
    return int(m.group(1)), int(m.group(2) or 0)


def _remind_at(v):
    """remind_at aceita "7h30"/"7h" além de HH:MM (e HH:MM:SS do próprio app)."""
    if isinstance(v, str) and v.strip() and v.count(":") < 2:
        hh, mm = parse_hour(v)
        return time(hh, mm)
    return v


Freq = Literal["daily", "weekly", "monthly", "interval", "after"]
_PARAM = {"weekly": "weekdays", "monthly": "month_day", "interval": "interval_days", "after": "interval_days"}


class _Agenda(BaseModel):
    """Agenda da recorrente. daily = dias úteis do dono (padrão); weekly exige
    weekdays (máscara, domingo = bit 0); monthly exige month_day (31 = último
    dia); interval exige interval_days (a cada N dias desde a criação); after
    também (N dias depois da última marcação)."""
    freq: Optional[Freq] = None
    weekdays: Optional[int] = Field(default=None, ge=1, le=127)
    month_day: Optional[int] = Field(default=None, ge=1, le=31)
    interval_days: Optional[int] = Field(default=None, ge=2, le=365)

    @model_validator(mode="after")
    def _agenda_coerente(self):
        if self.freq is None:
            if any(getattr(self, f) is not None for f in _PARAM.values()):
                raise ValueError("para mudar a agenda, envie freq junto")
            return self
        need = _PARAM.get(self.freq)
        if need and getattr(self, need) is None:
            raise ValueError(f"freq={self.freq} exige {need}")
        return self

    def agenda(self) -> dict:
        """Colunas de agenda normalizadas (só o parâmetro da freq escolhida)."""
        need = _PARAM.get(self.freq)
        return {"freq": self.freq, **{f: (getattr(self, f) if f == need else None) for f in set(_PARAM.values())}}


class RecurringIn(_Agenda):
    label: str = Field(min_length=1, max_length=200)
    require_note: bool = False  # marcar exige evidência (auditoria)
    remind_at: Optional[time] = None  # horário: a interface lembra (e toca) perto dele
    remind_at_hora = field_validator("remind_at", mode="before")(_remind_at)


class RecurringUpdate(_Agenda):
    """Nome e agenda. Remover = DELETE; voltar atrás = desfazer pelo histórico
    (reativar por aqui reescreveria a vigência e apagaria o passado)."""
    label: Optional[str] = Field(default=None, min_length=1, max_length=200)
    require_note: Optional[bool] = None
    remind_at: Optional[time] = None  # null tira o horário (só se o campo vier)
    remind_at_hora = field_validator("remind_at", mode="before")(_remind_at)


class PauseIn(BaseModel):
    """Pausar a rotina de hoje até `until` (inclusive; no dia seguinte ela volta)."""
    until: date


class ToggleIn(BaseModel):
    done: bool
    # Dia da marcação; ausente = hoje. Vale até RETRO_DAYS dias para trás.
    day: Optional[date] = None
    # Evidência curta da verificação ("backup OK, 2,1 TB"); só com done=true.
    note: Optional[str] = Field(default=None, max_length=200)


class _PushKeys(BaseModel):
    p256dh: str = Field(min_length=80, max_length=200)
    auth: str = Field(min_length=16, max_length=100)


class PushDeviceIn(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1000)
    keys: _PushKeys
    label: Optional[str] = Field(default=None, max_length=60)  # ex.: "Chrome · Android"


class PushPrefsIn(BaseModel):
    routine: bool = True
    follow_up: bool = True
    deadline: bool = True
    assigned: bool = True
    morning_hour: int = Field(default=8, ge=0, le=23)
    hide_content: bool = False


class SnoozeIn(BaseModel):
    minutes: int = Field(default=10, ge=5, le=120)


class ThemeIn(BaseModel):
    theme: Literal["auto", "light", "dark"]


class InviteRequestIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    source: Literal["colega", "site", "github", "outro"]
    source_note: Optional[str] = Field(default=None, max_length=120)
    reason: str = Field(min_length=3, max_length=600)
    website: Optional[str] = Field(default=None, max_length=200)  # armadilha: gente não vê, robô preenche


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    scope: Literal["read", "write", "append"] = "write"  # append = só registrar (deps.APPEND_ROUTES)
    # Validade em dias; None = sem validade (revogue quando não usar mais).
    expires_in_days: Optional[int] = Field(default=90, ge=1, le=365)


class TokenRenewIn(BaseModel):
    # Nova validade, contada de agora; None = sem validade.
    expires_in_days: Optional[int] = Field(default=90, ge=1, le=365)


def _events(events: list[str]) -> list[str]:
    evs = [e.strip() for e in events]
    if any(not re.fullmatch(r"\*|[a-z_]{1,30}\.(\*|[a-z_]{1,30})", e) for e in evs):
        raise ValueError('eventos: "*", "entidade.*" ou "entidade.acao" (ex.: worklog.finish)')
    return ["*"] if "*" in evs else sorted(set(evs))


class WebhookIn(BaseModel):
    url: str = Field(min_length=9, max_length=500)  # https://...
    # "*" (tudo), a ação exata ("worklog.finish") ou o grupo ("worklog.*").
    events: list[str] = Field(default=["*"], min_length=1, max_length=30)

    @model_validator(mode="after")
    def _norm(self):
        self.url = self.url.strip()
        self.events = _events(self.events)
        return self


class WebhookUpdate(BaseModel):
    """Editar sem recriar (o segredo continua): só o que vier muda."""
    url: Optional[str] = Field(default=None, min_length=9, max_length=500)
    events: Optional[list[str]] = Field(default=None, min_length=1, max_length=30)

    @model_validator(mode="after")
    def _norm(self):
        if self.url is not None:
            self.url = self.url.strip()
        if self.events is not None:
            self.events = _events(self.events)
        return self


class BrandingIn(BaseModel):
    line1: str = Field(min_length=1, max_length=24)
    line2: str = Field(default="", max_length=24)


class SettingsIn(BaseModel):
    # Máscara de dias úteis (domingo = bit 0). Ver sql/003_user_work_days.sql.
    work_days: int = Field(ge=1, le=127)


class ProfileIn(BaseModel):
    # Vazio ou None = volta ao nome derivado do e-mail.
    display_name: Optional[str] = Field(default=None, max_length=60)


class AssistantIn(BaseModel):
    enabled: bool = True
    idle_on: bool = True
    idle_minutes: int = Field(default=30, ge=5, le=480)
    idle_start: int = Field(default=480, ge=0, le=1439)  # minutos do dia
    idle_end: int = Field(default=1080, ge=1, le=1440)
    reopen_on: bool = True                                 # fala fechada no X volta sozinha
    reopen_minutes: int = Field(default=10, ge=1, le=240)
    summary_from: int = Field(default=840, ge=0, le=1439)  # resumo do dia sem nada concluído: a partir de (min do dia)
    stale_days: int = Field(default=5, ge=1, le=60)        # aguardando há N dias sem data de cobrança: o assistente avisa

    @model_validator(mode="after")
    def _janela(self):
        if self.idle_start >= self.idle_end:
            raise ValueError("o início da janela precisa ser antes do fim")
        return self


def _not_past(v):
    """Dia para cobrar: hoje ou depois (passado é engano de digitação)."""
    if v is not None:
        from .services import app_today  # import tardio: services importa o banco
        if v < app_today():
            raise ValueError("o dia para cobrar não pode estar no passado")
    return v


def _ticket(v):
    """Número do chamado: sem espaços e sem o "#" que as pessoas costumam digitar."""
    if v is None:
        return None
    v = str(v).strip().lstrip("#").strip()
    if len(v) > 40:
        raise ValueError("número do chamado com até 40 caracteres")
    return v or None


Ticket = Field(default=None, max_length=41)

# Data retroativa: "AAAA-MM-DD" ou data e hora ISO ("2026-09-29T14:30", com ou
# sem fuso; sem fuso = fuso da app). As regras (futuro, limite, ordem) ficam
# em routers/worklog.py, que conhece a criação da tarefa.
When = Field(default=None, min_length=10, max_length=40)


class WorklogIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=300)
    status: Status = "todo"
    due_date: Optional[date] = None
    project_id: Optional[int] = None  # ausente = o projeto padrão da pessoa
    extra_project_ids: list[int] = Field(default_factory=list, max_length=10)  # além do principal
    objective_id: Optional[int] = None  # objetivo do projeto principal (sem projeto: vem do objetivo)
    priority: int = Field(default=2, ge=1, le=3)  # 1 alta, 2 normal, 3 baixa
    ticket: Optional[str] = Ticket          # número no sistema de chamados
    after_hours: bool = False               # plantão / fora do horário
    created_at: Optional[str] = When        # lançamento retroativo (padrão: agora)
    completed_at: Optional[str] = When      # com status done (padrão: agora)
    external_ref: Optional[str] = Field(default=None, min_length=1, max_length=120)  # idempotência
    blocked_reason: Optional[str] = Field(default=None, max_length=120)  # o que se aguarda (status blocked)
    follow_up_on: Optional[date] = None  # aguardando (blocked): dia combinado para cobrar
    resolution: Optional[str] = Field(default=None, max_length=1000)  # com status done: como foi resolvido

    @model_validator(mode="after")
    def _norm(self):
        self.ticket = _ticket(self.ticket)
        self.follow_up_on = _not_past(self.follow_up_on)
        if self.external_ref is not None:
            self.external_ref = self.external_ref.strip() or None
        # Data de conclusão sem status: a tarefa já nasce concluída.
        if self.completed_at and "status" not in self.model_fields_set:
            self.status = "done"
        if self.completed_at and self.status != "done":
            raise ValueError("completed_at só vale com status done")
        return self


class WorklogUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=300)
    status: Optional[Status] = None
    due_date: Optional[date] = None
    project_id: Optional[int] = None  # enviado como null = tirar do projeto
    extra_project_ids: Optional[list[int]] = Field(default=None, max_length=10)  # troca a lista inteira
    objective_id: Optional[int] = None  # null = tirar do objetivo
    priority: Optional[int] = Field(default=None, ge=1, le=3)
    ticket: Optional[str] = Ticket     # null ou vazio = tirar o chamado
    after_hours: Optional[bool] = None
    completed_at: Optional[str] = When  # corrigir a data de uma tarefa concluída
    resolution: Optional[str] = Field(default=None, max_length=1000)  # como foi resolvido (null apaga)
    blocked_reason: Optional[str] = Field(default=None, max_length=120)  # o que se aguarda (status blocked)
    follow_up_on: Optional[date] = None  # aguardando (blocked): dia combinado para cobrar

    @model_validator(mode="after")
    def _norm(self):
        # Só quando veio no corpo: atribuir marca o campo como enviado no
        # Pydantic, e o PATCH apagaria o chamado de quem só mudou o status.
        if "ticket" in self.model_fields_set:
            self.ticket = _ticket(self.ticket)
        if "follow_up_on" in self.model_fields_set:
            self.follow_up_on = _not_past(self.follow_up_on)
        return self


class FinishIn(BaseModel):
    completed_at: Optional[str] = When  # ausente = agora
    resolution: Optional[str] = Field(default=None, max_length=1000)  # como foi resolvido (opcional)


def _renewal_label(m):
    if m.label is not None:
        m.label = m.label.strip()
        if not m.label:
            raise ValueError("informe o que vence")
    return m


class RenewalIn(BaseModel):
    """Algo que vence: certificado, licença, domínio, garantia, contrato."""
    label: str = Field(min_length=1, max_length=120)
    expires_on: date
    warn_days: int = Field(default=30, ge=1, le=365)  # avisar com quantos dias de antecedência
    project_id: Optional[int] = None
    note: Optional[str] = Field(default=None, max_length=200)
    renew_months: Optional[int] = Field(default=None, ge=1, le=120)  # repete a cada N meses (Renovei sugere)

    @model_validator(mode="after")
    def _label(self):
        return _renewal_label(self)


class RenewalUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=120)
    expires_on: Optional[date] = None
    warn_days: Optional[int] = Field(default=None, ge=1, le=365)
    project_id: Optional[int] = None
    note: Optional[str] = Field(default=None, max_length=200)
    renew_months: Optional[int] = Field(default=None, ge=1, le=120)  # null apaga

    @model_validator(mode="after")
    def _label(self):
        return _renewal_label(self)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=300)
    priority: int = Field(default=2, ge=1, le=3)
    project_id: Optional[int] = None
    after_hours: bool = False
    checklist: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def _itens(self):
        self.checklist = [i.strip()[:200] for i in self.checklist if i and i.strip()]
        self.name, self.title = self.name.strip(), self.title.strip()
        if not self.name or not self.title:
            raise ValueError("nome e título não podem ficar em branco")
        return self


class DefaultProjectIn(BaseModel):
    project_id: Optional[int] = None  # null = nenhum (tarefa sem projeto fica sem)


class TourIn(BaseModel):
    done: bool  # false = reabrir no próximo acesso


class TicketUrlIn(BaseModel):
    # Ex.: https://glpi.empresa.com/front/ticket.form.php?id={id}  ({id} vira o número)
    ticket_url: Optional[str] = Field(default=None, max_length=300, pattern=r"^(https?://\S+)?$")


class TimerIn(BaseModel):
    task_id: int
    # Hora em que a pessoa iniciou no aparelho (feito sem sinal e enviado depois); até 24 h atrás.
    at: Optional[datetime] = None


class TimerStopIn(BaseModel):
    at: Optional[datetime] = None  # hora em que parou, no aparelho (sem sinal)
    task_id: Optional[int] = None  # o cronômetro que a pessoa parou (a parada da fila não vale para outro)


Color = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


Ref = Field(default=None, min_length=1, max_length=120)  # chave externa (idempotência)


def _ref(value):
    return (value or "").strip() or None


# Ícones de projeto: a biblioteca fixa do app (sprite `#icon-proj-<nome>` em
# index.html, mesma ordem da grade). Sem ícone escolhido = "pasta".
PROJECT_ICONS = ("pasta", "predio", "loja", "clinica", "fabrica", "escola", "casa", "escritorio", "servidor", "rede",
                 "wifi", "seguranca", "manutencao", "eletrica", "hidraulica", "veiculo", "pessoa", "maleta",
                 "computador", "celular", "camera", "carrinho", "calendario", "estrela")
ProjectIcon = Literal[PROJECT_ICONS]


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: Optional[str] = Color
    icon: Optional[ProjectIcon] = None  # ausente ou null = pasta
    description: Optional[str] = Field(default=None, max_length=500)
    external_ref: Optional[str] = Ref

    @model_validator(mode="after")
    def _norm(self):
        self.external_ref = _ref(self.external_ref)
        return self


class ObjectiveIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    due_date: Optional[date] = None
    position: Optional[int] = Field(default=None, ge=1)  # 1 = primeiro; ausente = no fim da fila
    external_ref: Optional[str] = Ref

    @model_validator(mode="after")
    def _norm(self):
        self.external_ref = _ref(self.external_ref)
        return self


class ObjectiveUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)  # null apaga
    due_date: Optional[date] = None                                   # null apaga


class OrderIn(BaseModel):
    ids: list[int] = Field(max_length=500)  # na ordem de execução


class TaskOrderIn(BaseModel):
    objective_id: Optional[int] = None      # null = "Sem objetivo"
    task_ids: list[int] = Field(max_length=500)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    color: Optional[str] = Color
    icon: Optional[ProjectIcon] = None  # null volta para a pasta
    description: Optional[str] = Field(default=None, max_length=500)  # null apaga
    archived: Optional[bool] = None


class ArchiveIn(BaseModel):
    """Arquivar com as tarefas em aberto (as que têm o projeto como principal):
    keep = continuam como estão; done = concluídas agora; move = vão para move_to."""
    open_tasks: Literal["keep", "done", "move"] = "keep"
    move_to: Optional[int] = None

    @model_validator(mode="after")
    def _alvo(self):
        if self.open_tasks == "move" and not self.move_to:
            raise ValueError("informe move_to: o projeto que recebe as tarefas")
        return self


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    external_ref: Optional[str] = Ref  # repetida devolve a existente
    at: Optional[datetime] = None  # hora do aparelho (feita sem sinal, enviada depois); até 24 h atrás

    @model_validator(mode="after")
    def _norm(self):
        self.external_ref = _ref(self.external_ref)
        return self


class NoteUpdate(BaseModel):
    """Corrigir o texto de uma anotação (a hora original fica)."""
    body: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _norm(self):
        self.body = self.body.strip()
        if not self.body:
            raise ValueError("anotação em branco")
        return self


class ChecklistIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)


class ChecklistUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=200)
    done: Optional[bool] = None


class TimeIn(BaseModel):
    minutes: int = Field(ge=1, le=1440)
    day: Optional[date] = None  # padrão: hoje
    note: Optional[str] = Field(default=None, max_length=200)
    external_ref: Optional[str] = Ref  # repetido devolve o existente

    @model_validator(mode="after")
    def _norm(self):
        self.external_ref = _ref(self.external_ref)
        return self


class TimeUpdate(BaseModel):
    """Corrigir um apontamento. Só o que vier muda (note: null ou vazio tira a observação)."""
    minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    day: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=200)


# Avisos por e-mail: os padrões daqui valem também quando o usuário ainda não
# salvou nada (notify.get_prefs).
class PrefsIn(BaseModel):
    morning: bool = False
    morning_hour: int = Field(default=8, ge=0, le=23)
    evening: bool = False
    evening_hour: int = Field(default=17, ge=0, le=23)
    weekly: bool = False
    weekly_hour: int = Field(default=8, ge=0, le=23)
    show_titles: bool = True
    weekly_pdf: bool = False                 # o relatório da semana em PDF, anexado
    weekly_cc: Optional[EmailStr] = None     # cópia do resumo semanal (gestor, cliente)


class FeedIn(BaseModel):
    include_recurring: bool = True
