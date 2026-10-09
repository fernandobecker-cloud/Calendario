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

Persistencia escolhida por NPI_STORAGE: "sheets" (default - planilha
"crm_database", abas "npi_periodos"/"npi_valores", backend/sheets_db.py) ou
"bigquery" (dataset portal_crm, backend/bq_db.py). O disco do Render nao e
persistente entre deploys, entao SQLite local perderia os dados a cada novo
deploy. Migracao Sheets -> BigQuery: POST /migrar-para-bigquery (admin),
depois NPI_STORAGE=bigquery no Render; voltar pra "sheets" e o rollback.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from backend import bq_db, sheets_db
from backend.routes.open_data import (
    _cross_orders_regional,
    calcular_npi_canal,
    listar_npi_templates_disponiveis,
    reconciliar_revenue_attribution_x_si_purchases,
)

router = APIRouter(prefix="/api/open-data/npi", tags=["npi"])

NPI_STORAGE = os.getenv("NPI_STORAGE", "sheets").strip().lower()
npi_db = bq_db if NPI_STORAGE == "bigquery" else sheets_db
_DB_ERRORS = (sheets_db.SheetsDBError, bq_db.BQDBError)

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
        periodos = npi_db.get_npi_periodos()
        valores = npi_db.get_npi_valores()
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    tabela: dict[int, dict[str, float]] = {p["id"]: {} for p in periodos}
    for v in valores:
        if v["periodo_id"] in tabela and v["canal"] in CANAL_KEYS:
            tabela[v["periodo_id"]][v["canal"]] = v["receita"]

    return {"canais": CANAIS, "periodos": periodos, "valores": tabela, "storage": NPI_STORAGE}


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
        return npi_db.create_npi_periodo(
            payload.nome.strip(),
            payload.start_date,
            payload.end_date,
            created_by=getattr(auth_user, "username", "") or "admin",
        )
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.put("/periodos/{periodo_id}")
def editar_periodo(periodo_id: int, request: Request, payload: PeriodoPayload) -> dict[str, Any]:
    _require_admin(request)
    if not payload.nome.strip():
        raise HTTPException(status_code=400, detail="Nome do periodo e obrigatorio.")
    try:
        item = npi_db.update_npi_periodo(periodo_id, {
            "nome": payload.nome.strip(),
            "start_date": payload.start_date,
            "end_date": payload.end_date,
        })
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=404, detail="Periodo nao encontrado.")
    return item


@router.delete("/periodos/{periodo_id}")
def remover_periodo(periodo_id: int, request: Request) -> dict[str, Any]:
    _require_admin(request)
    try:
        ok = npi_db.delete_npi_periodo(periodo_id)
    except _DB_ERRORS as exc:
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
        return npi_db.upsert_npi_valor(
            payload.periodo_id,
            payload.canal,
            round(payload.receita, 2),
            updated_by=getattr(auth_user, "username", "") or "admin",
        )
    except _DB_ERRORS as exc:
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

    periodo = next((p for p in npi_db.get_npi_periodos() if p["id"] == periodo_id), None)
    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo nao encontrado.")
    if not payload.template_titles:
        raise HTTPException(status_code=400, detail="Informe pelo menos um template_title.")

    resultado_calculo = calcular_npi_canal(
        periodo["start_date"], periodo["end_date"], payload.template_titles, payload.janela_dias,
    )
    receitas_por_canal = resultado_calculo["canal_totais"]

    outros_canais = {c: r for c, r in receitas_por_canal.items() if c not in CANAL_KEYS}
    # Canais dos 5 conhecidos que nao apareceram no resultado (sem receita
    # nesse periodo) entram zerados explicitamente, pra nao deixar celula
    # com valor antigo de um calculo anterior.
    a_salvar = {c: round(receitas_por_canal.get(c, 0.0), 2) for c in CANAL_KEYS}
    try:
        itens = npi_db.upsert_npi_valores(
            periodo_id, a_salvar, updated_by=getattr(auth_user, "username", "") or "admin",
        )
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    salvos = {item["canal"]: item["receita"] for item in itens}

    return {
        "periodo_id": periodo_id,
        "valores_salvos": salvos,
        "outros_canais_nao_salvos": outros_canais,
    }


@router.post("/migrar-para-bigquery")
def migrar_para_bigquery(request: Request) -> dict[str, Any]:
    """Copia npi_periodos/npi_valores da planilha pro BigQuery (substitui o
    que ja estiver nas tabelas, preservando ids) e confere contagens e soma
    da receita lendo de volta. Pode ser rodado de novo quantas vezes
    precisar enquanto NPI_STORAGE ainda for "sheets" - depois da troca pra
    "bigquery", rodar de novo apagaria o que foi lancado direto no BigQuery,
    por isso e bloqueado."""
    _require_admin(request)
    if NPI_STORAGE == "bigquery":
        raise HTTPException(
            status_code=409,
            detail="NPI_STORAGE ja e 'bigquery' - migrar de novo sobrescreveria os dados atuais.",
        )
    try:
        periodos = sheets_db.get_npi_periodos()
        valores = sheets_db.get_npi_valores()
        gravados = bq_db.importar_npi(periodos, valores)
        periodos_bq = bq_db.get_npi_periodos()
        valores_bq = bq_db.get_npi_valores()
    except _DB_ERRORS as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    soma_sheets = round(sum(v["receita"] for v in valores), 2)
    soma_bq = round(sum(v["receita"] for v in valores_bq), 2)
    return {
        "gravados": gravados,
        "planilha": {"periodos": len(periodos), "valores": len(valores), "soma_receita": soma_sheets},
        "bigquery": {"periodos": len(periodos_bq), "valores": len(valores_bq), "soma_receita": soma_bq},
        "confere": (
            len(periodos) == len(periodos_bq)
            and len(valores) == len(valores_bq)
            and soma_sheets == soma_bq
        ),
    }


@router.post("/periodos/{periodo_id}/regional")
def regional_periodo(periodo_id: int, payload: CalcularPayload) -> dict[str, Any]:
    """Abertura da receita atribuida (NPI) por regional/loja - mesmo
    cruzamento order_id -> vendas_iplace ja usado em /sms-apuracao-regional
    e /email-apuracao-regional (`_cross_orders_regional`). So leitura (nao
    salva nada), por isso sem checagem de admin - mesmo nivel de acesso de
    GET /resultados. `order_amounts` vem de `calcular_npi_canal` (so
    pedidos com canal != sem_atribuicao, ja que "abertura por loja" so faz
    sentido pra receita de fato atribuida a algum disparo)."""
    periodo = next((p for p in npi_db.get_npi_periodos() if p["id"] == periodo_id), None)
    if not periodo:
        raise HTTPException(status_code=404, detail="Periodo nao encontrado.")
    if not payload.template_titles:
        raise HTTPException(status_code=400, detail="Informe pelo menos um template_title.")

    resultado_calculo = calcular_npi_canal(
        periodo["start_date"], periodo["end_date"], payload.template_titles, payload.janela_dias,
    )
    regional = _cross_orders_regional(resultado_calculo["order_amounts"])

    return {
        "periodo_id": periodo_id,
        **regional,
    }
