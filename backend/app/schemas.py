from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator

from .config import config

Status = Literal["todo", "in_progress", "blocked", "done"]

_PW = Field(min_length=config.MIN_PASSWORD_LEN, max_length=config.MAX_PASSWORD_LEN)


class InviteIn(BaseModel):
    email: EmailStr


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)  # senha gigante = Argon2 caro à toa


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = _PW


Freq = Literal["daily", "weekly", "monthly", "interval"]
_PARAM = {"weekly": "weekdays", "monthly": "month_day", "interval": "interval_days"}


class _Agenda(BaseModel):
    """Agenda da recorrente. daily = dias úteis do dono (padrão); weekly exige
    weekdays (máscara, domingo = bit 0); monthly exige month_day (31 = último
    dia); interval exige interval_days (a cada N dias desde a criação)."""
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
        return {"freq": self.freq, **{f: (getattr(self, f) if f == need else None) for f in _PARAM.values()}}


class RecurringIn(_Agenda):
    label: str = Field(min_length=1, max_length=200)


class RecurringUpdate(_Agenda):
    """Nome e agenda. Remover = DELETE; voltar atrás = desfazer pelo histórico
    (reativar por aqui reescreveria a vigência e apagaria o passado)."""
    label: Optional[str] = Field(default=None, min_length=1, max_length=200)


class ToggleIn(BaseModel):
    done: bool
    # Dia da marcação; ausente = hoje. Vale até RETRO_DAYS dias para trás.
    day: Optional[date] = None


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    scope: Literal["read", "write"] = "write"
    # Validade em dias; None = sem validade (revogue quando não usar mais).
    expires_in_days: Optional[int] = Field(default=90, ge=1, le=365)


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

    @model_validator(mode="after")
    def _janela(self):
        if self.idle_start >= self.idle_end:
            raise ValueError("o início da janela precisa ser antes do fim")
        return self


def _ticket(v):
    """Número do chamado: sem espaços e sem o "#" que as pessoas costumam digitar."""
    if v is None:
        return None
    v = str(v).strip().lstrip("#").strip()
    if len(v) > 40:
        raise ValueError("número do chamado com até 40 caracteres")
    return v or None


Ticket = Field(default=None, max_length=41)


class WorklogIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=300)
    status: Status = "todo"
    due_date: Optional[date] = None
    project_id: Optional[int] = None
    priority: int = Field(default=2, ge=1, le=3)  # 1 alta, 2 normal, 3 baixa
    ticket: Optional[str] = Ticket          # número no sistema de chamados
    after_hours: bool = False               # plantão / fora do horário

    @model_validator(mode="after")
    def _norm(self):
        self.ticket = _ticket(self.ticket)
        return self


class WorklogUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=300)
    status: Optional[Status] = None
    due_date: Optional[date] = None
    project_id: Optional[int] = None  # enviado como null = tirar do projeto
    priority: Optional[int] = Field(default=None, ge=1, le=3)
    ticket: Optional[str] = Ticket     # null ou vazio = tirar o chamado
    after_hours: Optional[bool] = None

    @model_validator(mode="after")
    def _norm(self):
        self.ticket = _ticket(self.ticket)
        return self


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


class TicketUrlIn(BaseModel):
    # Ex.: https://glpi.empresa.com/front/ticket.form.php?id={id}  ({id} vira o número)
    ticket_url: Optional[str] = Field(default=None, max_length=300, pattern=r"^(https?://\S+)?$")


class TimerIn(BaseModel):
    task_id: int


Color = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: Optional[str] = Color


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    color: Optional[str] = Color
    archived: Optional[bool] = None


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class ChecklistIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)


class ChecklistUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=200)
    done: Optional[bool] = None


class TimeIn(BaseModel):
    minutes: int = Field(ge=1, le=1440)
    day: Optional[date] = None  # padrão: hoje
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


class FeedIn(BaseModel):
    include_recurring: bool = True
