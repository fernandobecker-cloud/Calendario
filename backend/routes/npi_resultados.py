"""Resultados NPI - tabela manual (canal x periodo) da campanha NPI.

Tudo editado a mao pelo time de CRM (role=admin) - sem fonte automatica do
BigQuery. Motivo: uma tentativa anterior de puxar so o WhatsApp (Omni) do
BigQuery/Emarsys e deixar so essa linha manual nao funcionou na pratica (a
Emarsys nao enxerga o Omnichat, e amarrar o lancamento manual a um periodo
exato de data ficava fragil sempre que o periodo mudava) - por isso a
tabela inteira (todos os canais) virou manual, com periodos fixos
cadastrados pelo admin em vez de um seletor de datas livre.

Persistido no Google Sheets (backend/sheets_db.py, planilha "crm_database",
abas "npi_periodos" e "npi_valores") - o disco do Render nao e persistente
entre deploys, entao SQLite local perderia os dados a cada novo deploy.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend import sheets_db

router = APIRouter(prefix="/api/open-data/npi", tags=["npi"])

# Canais fixos da tabela - a ordem aqui e a ordem de exibicao das linhas.
CANAIS = [
    {"key": "sem_atribuicao", "label": "Sem atribuição"},
    {"key": "email", "label": "Email"},
    {"key": "sms", "label": "SMS"},
    {"key": "whatsapp_nativo", "label": "WhatsApp (nativo)"},
    {"key": "whatsapp_omni", "label": "WhatsApp (Omnichat)"},
]
CANAL_KEYS = {c["key"] for c in CANAIS}


def _require_admin(request: Request) -> None:
    auth_user = getattr(request.state, "auth_user", None)
    if auth_user is None:
        raise HTTPException(status_code=401, detail="Nao autenticado")
    if getattr(auth_user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem executar esta acao")


@router.get("/resultados")
def get_resultados() -> dict[str, Any]:
    """Leitura - qualquer usuario logado ve a tabela, sem checagem de admin
    (o controle de edicao fica so no frontend + nos endpoints de escrita
    abaixo)."""
    try:
        periodos = sheets_db.get_npi_periodos()
        valores = sheets_db.get_npi_valores()
    except sheets_db.SheetsDBError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    tabela: dict[int, dict[str, float]] = {p["id"]: {} for p in periodos}
    for v in valores:
        if v["periodo_id"] in tabela and v["canal"] in CANAL_KEYS:
            tabela[v["periodo_id"]][v["canal"]] = v["receita"]

    return {"canais": CANAIS, "periodos": periodos, "valores": tabela}


class PeriodoPayload(BaseModel):
    nome: str
    start_date: str
    end_date: str


@router.post("/periodos")
def criar_periodo(request: Request, payload: PeriodoPayload) -> dict[str, Any]:
    _require_admin(request)
    auth_user = request.state.auth_user
    if not payload.nome.strip():
        raise HTTPException(status_code=400, detail="Nome do periodo e obrigatorio.")
    try:
        return sheets_db.create_npi_periodo(
            payload.nome.strip(),
            payload.start_date,
            payload.end_date,
            created_by=getattr(auth_user, "username", "") or "admin",
        )
    except sheets_db.SheetsDBError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.put("/periodos/{periodo_id}")
def editar_periodo(periodo_id: int, request: Request, payload: PeriodoPayload) -> dict[str, Any]:
    _require_admin(request)
    if not payload.nome.strip():
        raise HTTPException(status_code=400, detail="Nome do periodo e obrigatorio.")
    try:
        item = sheets_db.update_npi_periodo(periodo_id, {
            "nome": payload.nome.strip(),
            "start_date": payload.start_date,
            "end_date": payload.end_date,
        })
    except sheets_db.SheetsDBError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=404, detail="Periodo nao encontrado.")
    return item


@router.delete("/periodos/{periodo_id}")
def remover_periodo(periodo_id: int, request: Request) -> dict[str, Any]:
    _require_admin(request)
    try:
        ok = sheets_db.delete_npi_periodo(periodo_id)
    except sheets_db.SheetsDBError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Periodo nao encontrado.")
    return {"ok": True}


class ValorPayload(BaseModel):
    periodo_id: int
    canal: str
    receita: float


@router.put("/valores")
def salvar_valor(request: Request, payload: ValorPayload) -> dict[str, Any]:
    _require_admin(request)
    auth_user = request.state.auth_user
    if payload.canal not in CANAL_KEYS:
        raise HTTPException(status_code=400, detail=f"Canal invalido: {payload.canal}")
    try:
        return sheets_db.upsert_npi_valor(
            payload.periodo_id,
            payload.canal,
            round(payload.receita, 2),
            updated_by=getattr(auth_user, "username", "") or "admin",
        )
    except sheets_db.SheetsDBError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
