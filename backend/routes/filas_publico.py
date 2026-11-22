"""Painel das filas de atendimento (lojas e televendas) por link, sem login.

O link leva uma chave (env FILAS_LINK_CHAVE no serviço do portal) para os
gerentes acompanharem sem usuário no portal: /filas/<chave>. Só mostra números
por loja e por regional, sem nome de cliente nem de vendedor. Para cortar o
acesso, basta trocar a chave no Render.
"""

from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, HTTPException, Query

from backend.services import agente_filas

router = APIRouter(prefix="/api/publico", tags=["publico"])


def chave_do_link() -> str:
    return os.getenv("FILAS_LINK_CHAVE", "").strip()


@router.get("/filas")
def painel_das_filas(chave: str = Query("", max_length=200)):
    esperada = chave_do_link()
    if not esperada:
        raise HTTPException(status_code=503, detail="O painel das filas ainda não foi liberado (FILAS_LINK_CHAVE).")
    if not hmac.compare_digest(chave.strip().encode(), esperada.encode()):
        raise HTTPException(status_code=404, detail="Link inválido ou expirado. Peça o link novo ao CRM.")
    return agente_filas.painel()
