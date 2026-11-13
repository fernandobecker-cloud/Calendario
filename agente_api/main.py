"""API do agente de IA da Omnichat (Whizz) - catalogo do e-commerce iPlace.

Servico separado do portal (outro Web Service na Render), para um relatorio
pesado no portal nao deixar o agente lento e um deploy do portal nao derrubar
o agente.

Rodar local:
    AGENTE_API_TOKEN=teste uvicorn agente_api.main:app --reload --port 8100
    curl -H 'x-api-key: teste' 'http://127.0.0.1:8100/omnichat/ecommerce/search?query=iphone 17&size=3'

Contrato da Omnichat (o mesmo endpoint atende todos os tipos de busca):
    GET ?searchType=TEXT|ID|SKUID|REFERENCE|URL&query=...&from=0&size=10
    -> lista de produtos (https://developers.omni.chat/docs/how-to-implement-the-searchproduct-api.md)
"""

from __future__ import annotations

import hmac
import logging
import re
import time

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from . import config, oracle
from .conversao import produto_omnichat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("agente_api")

app = FastAPI(title="API do agente de IA (Omnichat)", docs_url=None, redoc_url=None, openapi_url=None)

_RE_ID_PRODUTO_NA_URL = re.compile(r"/([0-9]+PR)\b", re.I)


def _autorizar(x_api_key: str | None, authorization: str | None, token_url: str | None) -> None:
    if not config.TOKEN:
        raise HTTPException(status_code=503, detail="AGENTE_API_TOKEN nao configurado no servidor.")
    recebido = x_api_key or token_url or ""
    if not recebido and authorization and authorization.lower().startswith("bearer "):
        recebido = authorization[7:]
    if not hmac.compare_digest(recebido.strip().encode(), config.TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Token invalido.")


def _ids_da_url(texto: str) -> list[str]:
    ids: list[str] = []
    for achado in _RE_ID_PRODUTO_NA_URL.findall(texto):
        achado = achado.upper()
        if achado not in ids:
            ids.append(achado)
    return ids


def _montar(ids: list[str], somente_sku: str | None = None) -> list[dict]:
    produtos = oracle.carregar_produtos(ids)
    pares = [
        (pid, sku["repositoryId"])
        for pid in ids if pid in produtos
        for sku in produtos[pid].get("childSKUs") or []
        if sku.get("repositoryId") and (not somente_sku or sku["repositoryId"] == somente_sku)
    ]
    estoque = oracle.carregar_estoque(pares)
    resultado = []
    for pid in ids:
        if pid not in produtos:
            continue
        item = produto_omnichat(produtos[pid], estoque, somente_sku=somente_sku)
        if item:
            resultado.append(item)
    return resultado


def _buscar(tipo: str, termo: str, inicio: int, quantidade: int) -> list[dict]:
    if tipo == "TEXT":
        # Pede o dobro ao site porque produtos sem estoque sao descartados.
        ids = oracle.buscar_ids_por_texto(termo, inicio, min(quantidade * 2, 40))
        return _montar(ids)[:quantidade]
    if tipo == "ID":
        ids = [parte.strip() for parte in termo.split(",") if parte.strip()]
        return _montar(ids[:quantidade])
    if tipo == "SKUID":
        produto = oracle.produto_do_sku(termo)
        return _montar([produto], somente_sku=termo) if produto else []
    if tipo == "REFERENCE":
        # Referencia pode vir como id do produto (100544PR) ou codigo SAP do SKU.
        achou = _montar([termo])
        if achou:
            return achou
        produto = oracle.produto_do_sku(termo)
        return _montar([produto], somente_sku=termo) if produto else []
    if tipo == "URL":
        return _montar(_ids_da_url(termo)[:quantidade])
    raise HTTPException(status_code=400, detail=f"searchType nao suportado: {tipo}")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/omnichat/ecommerce/search")
def buscar_produtos(
    query: str = Query("", description="Termo de busca, id, SKU, referencia ou URL"),
    inicio: int = Query(0, alias="from", ge=0),
    size: int = Query(10, ge=1),
    searchType: str = Query("TEXT"),
    token: str | None = Query(None, description="Alternativa ao header x-api-key"),
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
):
    _autorizar(x_api_key, authorization, token)
    tipo = (searchType or "TEXT").strip().upper()
    termo = query.strip()
    if not termo:
        return []
    quantidade = min(size, config.MAX_ITENS_POR_BUSCA)
    comeco = time.monotonic()
    try:
        resultado = _buscar(tipo, termo, inicio, quantidade)
    except oracle.OracleErro as exc:
        log.warning("busca falhou tipo=%s termo=%r: %s", tipo, termo, exc)
        return JSONResponse(status_code=502, content={"detail": "Site da iPlace indisponivel no momento."})
    log.info(
        "busca tipo=%s termo=%r from=%s size=%s -> %s produtos (%sms)",
        tipo, termo, inicio, quantidade, len(resultado), int((time.monotonic() - comeco) * 1000),
    )
    return resultado
