#!/usr/bin/env python3
"""Gera docs/openapi.json a partir do app (o Swagger continua desligado em produção).

Para conector personalizado (Power Automate), n8n, Make e geradores de cliente.
Rode depois de mudar rotas ou schemas; o teste test_openapi_em_dia falha se o
arquivo versionado ficar para trás. Precisa das dependências do backend — use o
container de testes, na raiz do repositório:

  docker compose -f docker-compose.test.yml run --rm --no-deps --user "$(id -u)" \
      -v "$PWD:/repo" -w /repo tests python tools/openapi.py
"""
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
# Só importa o app: nada conecta no banco (o pool abre no lifespan).
os.environ.setdefault("DATABASE_URL", "postgresql://gerador@localhost/nada")
os.environ.setdefault("SECRET_KEY", "somente-para-gerar-o-openapi-0123456789abcdef")


def render() -> str:
    from app.main import app
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "openapi.json"
    out.write_text(render(), encoding="utf-8")
    print(f"gravado {out}")
