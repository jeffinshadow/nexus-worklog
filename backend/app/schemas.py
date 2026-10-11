from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field

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


class RecurringIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)


class RecurringUpdate(BaseModel):
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


class WorklogUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=300)
    status: Optional[Status] = None
    due_date: Optional[date] = None
