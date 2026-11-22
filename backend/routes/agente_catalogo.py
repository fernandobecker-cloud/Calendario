"""Aba "Catalogo do agente": mostra no portal o que a API do agente de IA
(servico agente-ia-api, pasta agente_api/) devolve para a Omnichat.

O portal NAO calcula preco: so repassa a busca para a API do agente, assim o
que aparece aqui e exatamente o que o agente vai responder ao cliente.

Tambem guarda a planilha da campanha (plano B enquanto o Akamai bloqueia o
site): o admin sobe o .xlsx/.csv aqui, o portal valida e grava no BigQuery, e
a API do agente le as linhas em /planilha/feed (autenticado pelo token, fora
do Basic Auth do portal - ver basic_auth_middleware em server.py).

Env vars no servico do portal:
    AGENTE_API_URL    (padrao: https://agente-ia-api-r6cb.onrender.com)
    AGENTE_API_TOKEN  (o mesmo AGENTE_API_TOKEN do servico agente-ia-api)
"""

from __future__ import annotations

import hmac
import os

import requests
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from backend.routes.filas_publico import chave_do_link
from backend.services import agente_filas, agente_planilha, agente_site, agente_televendas

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


# --- Planilha da campanha -----------------------------------------------------

MAX_BYTES_PLANILHA = 5 * 1024 * 1024


def _status_do_agente() -> dict | None:
    """Fonte que a API do agente esta usando (planilha ou site). Se ela estiver
    dormindo (plano Free), nao espera."""
    try:
        resp = requests.get(f"{AGENTE_API_URL}/health", timeout=4)
        return resp.json() if resp.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def _site() -> dict | None:
    try:
        return agente_site.carregar()
    except agente_planilha.PlanilhaErroBQ:
        return None


def _resumo(feed: dict | None) -> dict:
    site = _site()
    return {
        "planilha": agente_site.completar(feed, site),
        "site": {k: v for k, v in site.items() if k not in ("por_produto", "por_sku")} if site else None,
        "cobertura_site": agente_site.cobertura(feed, site),
        "colunas": [
            {"nome": nome, "obrigatoria": obrig, "explicacao": exp}
            for nome, (_tipo, obrig, _apelidos, exp) in agente_planilha.COLUNAS.items()
        ],
    }


@router.get("/planilha")
def ver_planilha(request: Request):
    _exigir_admin(request)
    try:
        feed = agente_planilha.carregar()
    except agente_planilha.PlanilhaErroBQ as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {**_resumo(feed), "agente": _status_do_agente()}


@router.get("/planilha/modelo")
def modelo_planilha(request: Request):
    _exigir_admin(request)
    return Response(
        content=agente_planilha.modelo_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="modelo_planilha_agente.csv"'},
    )


@router.post("/planilha")
async def subir_planilha(request: Request, arquivo: str = Query(..., min_length=1)):
    """Recebe o arquivo cru no corpo (sem multipart) e substitui a planilha."""
    _exigir_admin(request)
    conteudo = await request.body()
    if not conteudo:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")
    if len(conteudo) > MAX_BYTES_PLANILHA:
        raise HTTPException(status_code=400, detail="Arquivo maior que 5 MB.")
    try:
        linhas, avisos = agente_planilha.validar(conteudo, arquivo)
    except agente_planilha.PlanilhaInvalida as exc:
        raise HTTPException(status_code=400, detail={"mensagem": "A planilha tem erros e nao foi carregada.",
                                                     "erros": exc.erros}) from exc
    try:
        feed = agente_planilha.salvar(linhas, arquivo, request.state.auth_user.username)
    except agente_planilha.PlanilhaErroBQ as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {**_resumo(feed), "avisos": avisos}


@router.get("/planilha/feed")
def feed_planilha(request: Request):
    """Para a API do agente. Sem Basic Auth: exige o AGENTE_API_TOKEN."""
    recebido = (request.headers.get("x-api-key") or "").strip()
    if not AGENTE_API_TOKEN or not hmac.compare_digest(recebido.encode(), AGENTE_API_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Token invalido.")
    try:
        feed = agente_planilha.carregar()
    except agente_planilha.PlanilhaErroBQ as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not feed:
        raise HTTPException(status_code=404, detail="Nenhuma planilha carregada.")
    return agente_site.completar(feed, _site())


MAX_BYTES_SITE = 80 * 1024 * 1024


@router.get("/site/script")
def script_do_site(request: Request):
    _exigir_admin(request)
    return {"script": agente_site.SCRIPT_NAVEGADOR}


@router.post("/site")
async def subir_produtos_do_site(request: Request):
    """Recebe o produtos_site_iplace.json (gerado no navegador) e grava no BigQuery."""
    _exigir_admin(request)
    conteudo = await request.body()
    if not conteudo:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")
    if len(conteudo) > MAX_BYTES_SITE:
        raise HTTPException(status_code=400, detail="Arquivo maior que 80 MB.")
    try:
        produtos = agente_site.ler_arquivo(conteudo)
        agente_site.salvar(produtos, request.state.auth_user.username)
        feed = agente_planilha.carregar()
    except agente_site.ArquivoInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except agente_planilha.PlanilhaErroBQ as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {**_resumo(feed), "agente": _status_do_agente()}



# --- Fila do televendas -------------------------------------------------------


def _token_do_agente(request: Request) -> None:
    recebido = (request.headers.get("x-api-key") or "").strip()
    if not AGENTE_API_TOKEN or not hmac.compare_digest(recebido.encode(), AGENTE_API_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Token invalido.")


def _fila_do_agente() -> dict | None:
    """Situacao da fila contada pela API do agente (webhooks da Omnichat)."""
    if not AGENTE_API_TOKEN:
        return None
    try:
        resp = requests.get(f"{AGENTE_API_URL}/fila", headers={"x-api-key": AGENTE_API_TOKEN}, timeout=8)
        return resp.json() if resp.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def _config_televendas() -> dict | None:
    try:
        return agente_televendas.carregar()
    except agente_planilha.PlanilhaErroBQ as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _link_filas(request: Request) -> str | None:
    chave = chave_do_link()
    if not chave:
        return None
    base = str(request.base_url).rstrip("/")
    if base.startswith("http://") and "localhost" not in base and "127.0.0.1" not in base:
        base = "https://" + base[len("http://"):]  # atras do proxy da Render
    return f"{base}/filas/{chave}"


@router.get("/televendas")
def ver_televendas(request: Request):
    _exigir_admin(request)
    return {"config": _config_televendas(), "fila": _fila_do_agente(), "link_filas": _link_filas(request)}


@router.put("/televendas")
async def salvar_televendas(request: Request):
    _exigir_admin(request)
    try:
        dados = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="JSON invalido.") from exc
    try:
        config = agente_televendas.salvar(dados if isinstance(dados, dict) else {}, request.state.auth_user.username)
    except agente_televendas.ConfigInvalida as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except agente_planilha.PlanilhaErroBQ as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"config": config, "fila": _fila_do_agente(), "link_filas": _link_filas(request)}


@router.get("/televendas/config")
def config_televendas(request: Request):
    """Para a API do agente. Sem Basic Auth: exige o AGENTE_API_TOKEN."""
    _token_do_agente(request)
    config = _config_televendas()
    if not config:
        raise HTTPException(status_code=404, detail="Televendas ainda nao configurado.")
    return config


@router.post("/fila/eventos")
async def receber_eventos_da_fila(request: Request):
    """Para a API do agente: lote de eventos de atendimento da Omnichat."""
    _token_do_agente(request)
    try:
        corpo = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="JSON invalido.") from exc
    eventos = corpo.get("eventos") if isinstance(corpo, dict) else None
    if not isinstance(eventos, list):
        raise HTTPException(status_code=400, detail="Esperava {\"eventos\": [...]}.")
    return agente_filas.receber(eventos)


@router.get("/fila/painel")
def painel_das_filas_admin(request: Request):
    """Aba Filas do portal: o mesmo painel do link dos gerentes, com o televendas."""
    _exigir_admin(request)
    return {**agente_filas.painel(com_televendas=True), "link_filas": _link_filas(request)}


@router.get("/fila/diagnostico")
def diagnostico_das_filas(request: Request):
    _exigir_admin(request)
    return {**agente_filas.diagnostico(), "omnichat_api": (_fila_do_agente() or {}).get("omnichat_api")}
