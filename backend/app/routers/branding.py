"""Identidade visual (logo + duas linhas de texto do lockup), editável pelo admin.

GET /api/branding e /api/branding/logo são públicos: a tela de login precisa
deles antes de existir sessão. O logo enviado é validado pelo CONTEÚDO (não
pelo nome nem pelo Content-Type do cliente) e servido com uma CSP que impede
execução de qualquer coisa dentro dele (SVG pode carregar script).
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from .. import audit, db
from ..deps import require_admin_csrf
from ..schemas import BrandingIn

router = APIRouter(tags=["branding"])

MAX_LOGO_BYTES = 256 * 1024
# Em SVG, recusa tudo que executa ou busca algo fora: script, handlers on*,
# javascript:, foreignObject (HTML embutido) e links (href) que não sejam
# âncoras internas (#id) ou imagens embutidas (data:image/...).
_SVG_PERIGOSO = re.compile(
    rb"<script|\bon[a-z]+\s*=|javascript:|<foreignobject|<iframe|<embed|<object|"
    rb"href\s*=\s*[\"']\s*(?!#|data:image/)",
    re.IGNORECASE,
)


def _sniff(data: bytes) -> str | None:
    """Tipo real da imagem pelo conteúdo, ou None se não for aceito."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    head = data[:2048].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<svg") or head.startswith(b"<!--"):
        if b"<svg" in data[:4096].lower():
            return "image/svg+xml"
    return None


def branding() -> dict:
    """A identidade visual (a linha id=1 sempre existe: sql/005). `logo` em bytes
    ou None — para o PDF, o e-mail e o calendário."""
    r = db.query_one("""SELECT line1, line2, logo, extract(epoch FROM updated_at)::bigint AS v
                          FROM app_branding WHERE id = 1""")
    if r["logo"] is not None:
        r["logo"] = bytes(r["logo"])
    return r


@router.get("/api/branding")
def get_branding():
    r = branding()
    return {
        "line1": r["line1"],
        "line2": r["line2"],
        # URL versionada: troca o logo -> muda a URL -> cache não segura o antigo.
        "logo": f"/api/branding/logo?v={r['v']}" if r["logo"] is not None else None,
    }


@router.get("/api/branding/logo")
def get_logo():
    r = db.query_one("SELECT logo, logo_mime FROM app_branding WHERE id = 1")
    if not r or r["logo"] is None:
        raise HTTPException(status_code=404, detail="sem logo personalizado")
    return Response(
        content=bytes(r["logo"]),
        media_type=r["logo_mime"],
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        },
    )


@router.put("/api/admin/branding")
def put_branding(data: BrandingIn, admin=Depends(require_admin_csrf)):
    before = branding()
    db.execute(
        "UPDATE app_branding SET line1 = %s, line2 = %s, updated_at = now(), updated_by = %s WHERE id = 1",
        (data.line1.strip(), data.line2.strip(), admin["user_id"]),
    )
    audit.record({**admin, "actor": "admin"}, "branding.update", "branding", 1,
                 before={"line1": before["line1"], "line2": before["line2"]},
                 after={"line1": data.line1.strip(), "line2": data.line2.strip()})
    return get_branding()


@router.post("/api/admin/branding/logo")
async def upload_logo(request: Request, admin=Depends(require_admin_csrf)):
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="arquivo vazio")
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="logo acima de 256 KB")
    mime = _sniff(data)
    if not mime:
        raise HTTPException(status_code=415, detail="use SVG, PNG ou WebP")
    if mime == "image/svg+xml" and _SVG_PERIGOSO.search(data):
        raise HTTPException(status_code=400, detail="SVG com script, eventos ou links externos não é aceito")
    db.execute(
        "UPDATE app_branding SET logo = %s, logo_mime = %s, updated_at = now(), updated_by = %s WHERE id = 1",
        (data, mime, admin["user_id"]),
    )
    audit.record({**admin, "actor": "admin"}, "branding.logo", "branding", 1,
                 after={"mime": mime, "bytes": len(data)})
    return get_branding()


@router.delete("/api/admin/branding/logo")
def reset_logo(admin=Depends(require_admin_csrf)):
    db.execute(
        "UPDATE app_branding SET logo = NULL, logo_mime = NULL, updated_at = now(), updated_by = %s WHERE id = 1",
        (admin["user_id"],),
    )
    audit.record({**admin, "actor": "admin"}, "branding.logo_reset", "branding", 1)
    return get_branding()
