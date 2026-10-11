from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator

from .config import config

Status = Literal["todo", "in_progress", "blocked", "done"]

_PW = Field(min_length=config.MIN_PASSWORD_LEN, max_length=config.MAX_PASSWORD_LEN)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = _PW


class InviteIn(BaseModel):
    email: EmailStr


class LoginIn(BaseModel):
    email: EmailStr
    password: str


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
    label: Optional[str] = Field(default=None, min_length=1, max_length=200)
    active: Optional[bool] = None
    position: Optional[int] = None


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


class WorklogIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=300)
    status: Status = "todo"
    due_date: Optional[date] = None
    project_id: Optional[int] = None
    priority: int = Field(default=2, ge=1, le=3)  # 1 alta, 2 normal, 3 baixa


class WorklogUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=300)
    status: Optional[Status] = None
    due_date: Optional[date] = None
    project_id: Optional[int] = None  # enviado como null = tirar do projeto
    priority: Optional[int] = Field(default=None, ge=1, le=3)


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
