"""Aba "Catalogo do agente": mostra no portal o que a API do agente de IA
(servico agente-ia-api, pasta agente_api/) devolve para a Omnichat.

O portal NAO calcula preco: so repassa a busca para a API do agente, assim o
que aparece aqui e exatamente o que o agente vai responder ao cliente.

Env vars no servico do portal:
    AGENTE_API_URL    (padrao: https://agente-ia-api-r6cb.onrender.com)
    AGENTE_API_TOKEN  (o mesmo AGENTE_API_TOKEN do servico agente-ia-api)
"""

from __future__ import annotations

import os

import requests
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/agente-ia", tags=["agente-ia"])

AGENTE_API_URL = os.getenv("AGENTE_API_URL", "https://agente-ia-api-r6cb.onrender.com").strip().rstrip("/")
AGENTE_API_TOKEN = os.getenv("AGENTE_API_TOKEN", "").strip()
# No plano Free o servico do agente dorme e leva ~1 min para acordar.
TIMEOUT_S = 75

TIPOS = {"TEXT", "ID", "SKUID", "REFERENCE", "URL"}


def _exigir_admin(request: Request) -> None:
    if getattr(getattr(request.state, "auth_user", None), "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem consultar o catalogo do agente.")


@router.get("/catalogo")
def consultar_catalogo(
    request: Request,
    query: str = Query(..., min_length=1),
    searchType: str = Query("TEXT"),
    size: int = Query(10, ge=1, le=20),
):
    _exigir_admin(request)
    tipo = searchType.strip().upper()
    if tipo not in TIPOS:
        raise HTTPException(status_code=400, detail=f"Tipo de busca invalido: {searchType}")
    if not AGENTE_API_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="AGENTE_API_TOKEN nao configurado no portal. Copie o valor do servico agente-ia-api "
                   "(Environment) para o Environment do portal.",
        )
    try:
        resp = requests.get(
            f"{AGENTE_API_URL}/omnichat/ecommerce/search",
            params={"query": query.strip(), "searchType": tipo, "size": size, "from": 0},
            headers={"x-api-key": AGENTE_API_TOKEN},
            timeout=TIMEOUT_S,
        )
    except requests.Timeout as exc:
        raise HTTPException(status_code=504, detail="A API do agente nao respondeu a tempo. Tente de novo.") from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao chamar a API do agente: {exc.__class__.__name__}") from exc

    try:
        corpo = resp.json()
    except ValueError:
        corpo = None

    if resp.status_code == 401:
        raise HTTPException(status_code=502, detail="A API do agente recusou o token: o AGENTE_API_TOKEN do portal "
                                                    "esta diferente do servico agente-ia-api.")
    if resp.status_code != 200 or not isinstance(corpo, list):
        detalhe = (corpo.get("motivo") or corpo.get("detail")) if isinstance(corpo, dict) else None
        raise HTTPException(status_code=502, detail=detalhe or f"A API do agente respondeu HTTP {resp.status_code}.")

    return {"itens": corpo, "agente_api_url": AGENTE_API_URL}
