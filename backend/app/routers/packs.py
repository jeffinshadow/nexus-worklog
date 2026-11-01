"""Pacotes de rotina por área: um ponto de partida pronto (manutenção predial,
suporte de TI, atendimento...) que cria, num toque, um projeto com ícone e as
rotinas daquela área com agenda e horário sensatos. A pessoa escolhe os itens
antes de criar e depois edita tudo como qualquer rotina ou projeto.

A lista é fixa no código (sem tabela). Aplicar é idempotente: projeto de mesmo
nome é reaproveitado (e volta do arquivo) e rotina ativa de mesmo nome não se
repete. Cada criação passa pelas rotas de sempre (validação e histórico com
desfazer, um item por vez)."""
from datetime import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .. import db
from ..deps import active_user, active_user_csrf
from ..schemas import ProjectIn, ProjectUpdate, RecurringIn
from . import projects as project_routes
from . import recurring as recurring_routes

router = APIRouter(prefix="/api/routine-packs", tags=["recurring"])

SEG, TER, QUA, QUI, SEX = 2, 4, 8, 16, 32  # máscara da semana: domingo = bit 0


def _r(key, label, freq="daily", at=None, weekdays=None, month_day=None, interval_days=None, note=False):
    return {"key": key, "label": label, "freq": freq, "weekdays": weekdays, "month_day": month_day,
            "interval_days": interval_days, "remind_at": at, "require_note": note}


# Linguagem de quem faz o trabalho; nada de TI onde a área não é TI.
PACKS = [
    {"id": "manutencao", "name": "Manutenção predial", "icon": "manutencao",
     "description": "Ronda, quadro elétrico, bombas e os equipamentos de segurança do prédio.",
     "items": [
         _r("ronda", "Fazer a ronda do prédio", at="08:00"),
         _r("bombas", "Conferir as bombas e o nível da caixa d'água", at="08:30"),
         _r("quadro", "Conferir o quadro elétrico (aquecimento e disjuntores)", "weekly", "09:00", weekdays=SEG),
         _r("extintores", "Conferir os extintores (validade e lacre)", "monthly", "10:00", month_day=1, note=True),
         _r("emergencia", "Testar a iluminação de emergência", "monthly", "10:00", month_day=15, note=True),
     ]},
    {"id": "ti", "name": "Suporte de TI", "icon": "computador",
     "description": "Backups, monitoramento, fila de chamados e a saúde das máquinas.",
     "items": [
         _r("backups", "Conferir os backups da noite", at="08:00", note=True),
         _r("alertas", "Olhar os alertas do monitoramento", at="08:15"),
         _r("fila", "Revisar a fila de chamados", at="08:30"),
         _r("antivirus", "Conferir o antivírus (alertas e máquinas desatualizadas)", "weekly", "10:00", weekdays=SEG),
         _r("atualizacoes", "Aplicar as atualizações pendentes", "weekly", "16:00", weekdays=SEX),
     ]},
    {"id": "atendimento", "name": "Atendimento e recepção", "icon": "pessoa",
     "description": "E-mail e mensagens, a agenda do dia e o retorno do que ficou pendente.",
     "items": [
         _r("agenda", "Conferir a agenda do dia", at="08:00"),
         _r("mensagens", "Responder e-mails e mensagens", at="08:15"),
         _r("recados", "Conferir recados e ligações perdidas", at="13:30"),
         _r("retorno", "Dar retorno das pendências", at="16:00"),
     ]},
    {"id": "campo", "name": "Redes e campo", "icon": "rede",
     "description": "Links e VPN, os equipamentos das filiais e o inventário.",
     "items": [
         _r("material", "Conferir o material antes de sair para o campo", at="07:45"),
         _r("links", "Conferir os links de internet e a VPN", at="08:00"),
         _r("filiais", "Conferir os equipamentos das filiais", "weekly", "09:00", weekdays=SEG | QUI),
         _r("inventario", "Atualizar o inventário de equipamentos", "monthly", "10:00", month_day=5),
     ]},
    {"id": "seguranca", "name": "Segurança da informação", "icon": "seguranca",
     "description": "Registros de acesso, quem tem acesso a quê e a validade dos certificados.",
     "items": [
         _r("logs", "Olhar os registros de acesso e os alertas (logs)", at="09:00"),
         _r("acessos", "Revisar quem tem acesso (contas e permissões)", "weekly", "10:00", weekdays=SEG),
         _r("certificados", "Conferir a validade dos certificados", "monthly", "10:00", month_day=1),
     ]},
]
_BY_ID = {p["id"]: p for p in PACKS}
_LABELS = [i["label"] for p in PACKS for i in p["items"]]


def find(pack_id: str) -> dict:
    p = _BY_ID.get((pack_id or "").strip().lower())
    if not p:
        raise HTTPException(status_code=404, detail="pacote não encontrado; veja a lista de pacotes")
    return p


class PackApplyIn(BaseModel):
    """items: as chaves escolhidas (ausente ou null = todas); project: criar
    (ou reaproveitar) o projeto da área."""
    items: Optional[list[str]] = Field(default=None, max_length=20)
    project: bool = True


def _existing(uid: int) -> set:
    """Rótulos (sem maiúsculas e acentos, como a busca) das rotinas ativas da pessoa
    que coincidem com algum item de pacote."""
    return {r["label"] for r in db.query_all(
        """SELECT i.label FROM unnest(%s::text[]) AS i(label)
            WHERE EXISTS (SELECT 1 FROM recurring_tasks t
                           WHERE t.user_id = %s AND t.active AND nx_fold(t.label) = nx_fold(i.label))""",
        (_LABELS, uid))}


@router.get("")
def list_packs(user=Depends(active_user)):
    """Os pacotes, cada item com a agenda e o horário; `exists` marca as rotinas
    que a pessoa já tem (mesmo nome), que aplicar pula."""
    have = _existing(user["user_id"])
    return [{**{k: v for k, v in p.items() if k != "items"},
             "project": {"name": p["name"], "icon": p["icon"]},
             "items": [{**i, "exists": i["label"] in have} for i in p["items"]]}
            for p in PACKS]


def apply_pack(pack_id: str, data: PackApplyIn, user: dict) -> dict:
    uid = user["user_id"]
    p = find(pack_id)
    keys = set(data.items) if data.items is not None else {i["key"] for i in p["items"]}
    if unknown := keys - {i["key"] for i in p["items"]}:
        raise HTTPException(status_code=400, detail="item que não é deste pacote: " + ", ".join(sorted(unknown)))
    if not keys and not data.project:
        raise HTTPException(status_code=400, detail="escolha pelo menos uma rotina ou o projeto")
    project = None
    if data.project:
        found = project_routes.same_name(uid, p["name"])
        if found:
            if found["archived"]:
                project_routes.update_project(found["id"], ProjectUpdate(archived=False), user=user)
            project = {**found, "archived": False, "created": False}
        else:
            row = project_routes.create_project(ProjectIn(name=p["name"], icon=p["icon"], description=p["description"]),
                                                Response(), user=user)
            project = {**row, "created": True}
    have = _existing(uid)
    created, skipped = [], []
    for i in p["items"]:
        if i["key"] not in keys:
            continue
        if i["label"] in have:
            skipped.append(i["label"])
            continue
        data_r = RecurringIn(label=i["label"], freq=i["freq"], weekdays=i["weekdays"], month_day=i["month_day"],
                             interval_days=i["interval_days"], require_note=i["require_note"],
                             remind_at=time.fromisoformat(i["remind_at"]) if i["remind_at"] else None)
        created.append(recurring_routes.create(data_r, user=user))
    return {"pack": p["id"], "project": project, "created": created, "skipped": skipped}


@router.post("/{pack_id}/apply")
def apply(pack_id: str, data: PackApplyIn, user=Depends(active_user_csrf)):
    """Cria o projeto da área (ou reaproveita o de mesmo nome) e as rotinas
    escolhidas; rotina ativa de mesmo nome é pulada (vem em `skipped`)."""
    return apply_pack(pack_id, data, user)
