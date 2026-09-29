"""Resultados NPI - tabela (canal x periodo) da campanha NPI.

Historico: primeira versao era 100% manual (role=admin digitava cada
celula) porque a Emarsys nao enxerga o Omnichat e nao dava pra calcular o
WhatsApp (Omni) automaticamente. Isso mudou: o usuario carregou no BigQuery
uma ponte contact_id<->telefone e os disparos entregues pelo Omnichat (ver
`calcular_npi_canal` em backend/routes/open_data.py), permitindo calcular
os 5 canais automaticamente por periodo. A edicao manual continua existindo
(POST/PUT/DELETE periodos, PUT valores) como fallback/ajuste pontual - o
calculo automatico (POST /periodos/{id}/calcular) so REESCREVE as celulas
calculadas, o admin pode editar depois se quiser ajustar algo.

Persistido no Google Sheets (backend/sheets_db.py, planilha "crm_database",
abas "npi_periodos" e "npi_valores") - o disco do Render nao e persistente
entre deploys, entao SQLite local perderia os dados a cada novo deploy.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from backend import sheets_db
from backend.routes.open_data import (
    calcular_npi_canal,
    listar_npi_templates_disponiveis,
    reconciliar_revenue_attribution_x_si_purchases,
)

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


@router.get("/reconciliacao-si-purchases")
def reconciliacao_si_purchases(
    request: Request,
    start: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    """Diagnostico pontual (nao faz parte do fluxo normal da tela) - compara
    revenue_attribution x si_purchases pro periodo, pra descobrir a origem
    do gap entre "Total geral" (Resultados NPI) e "Total iPlace" (Resultado
    Geral). Admin only, so por ser um dado financeiro sensivel."""
    _require_admin(request)
    return reconciliar_revenue_attribution_x_si_purchases(start, end)


@router.get("/templates-disponiveis")
def templates_disponiveis() -> dict[str, Any]:
    """Templates distintos existentes em dados_omni (com volume e datas) -
    usado pelo frontend pra montar a lista de checkboxes do "Calcular
    automaticamente", em vez do admin ter que digitar/colar o nome de
    cabeça."""
    return {"items": listar_npi_templates_disponiveis()}


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


class CalcularPayload(BaseModel):
    template_titles: list[str]
    janela_dias: int = 7


@router.post("/periodos/{periodo_id}/calcular")
def calcular_periodo(periodo_id: int, request: Request, payload: CalcularPayload) -> dict[str, Any]:
    """Calcula os 5 canais automaticamente pro periodo (via BigQuery, ver
    `calcular_npi_canal`) e SALVA (sobrescreve) as celulas correspondentes -
    o admin pode ajustar manualmente depois se precisar. `template_titles`
    e a lista de templates do Omnichat que contam como o disparo dessa
    campanha (o mesmo filtro que entra no WHERE template_title IN (...) da
    query original) - varia por campanha/repique, por isso e passado a cada
    calculo, nao fixo no backend."""
    _require_admin(request)
    auth_user = request.state.auth_user

    periodo = next((p for p in sheets_db.get_npi_periodos() if p["id"] == periodo_id), None)
    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo nao encontrado.")
    if not payload.template_titles:
        raise HTTPException(status_code=400, detail="Informe pelo menos um template_title.")

    receitas_por_canal = calcular_npi_canal(
        periodo["start_date"], periodo["end_date"], payload.template_titles, payload.janela_dias,
    )

    salvos: dict[str, float] = {}
    outros_canais: dict[str, float] = {}
    updated_by = getattr(auth_user, "username", "") or "admin"
    for canal, receita in receitas_por_canal.items():
        if canal in CANAL_KEYS:
            item = sheets_db.upsert_npi_valor(periodo_id, canal, round(receita, 2), updated_by=updated_by)
            salvos[canal] = item["receita"]
        else:
            outros_canais[canal] = receita
    # Canais dos 5 conhecidos que nao apareceram no resultado (sem receita
    # nesse periodo) - zera explicitamente, pra nao deixar celula com valor
    # antigo de um calculo anterior.
    for canal_key in CANAL_KEYS - salvos.keys():
        item = sheets_db.upsert_npi_valor(periodo_id, canal_key, 0.0, updated_by=updated_by)
        salvos[canal_key] = item["receita"]

    return {
        "periodo_id": periodo_id,
        "valores_salvos": salvos,
        "outros_canais_nao_salvos": outros_canais,
    }
