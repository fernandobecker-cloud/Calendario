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

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from . import config, fila, oracle, planilha
from .conversao import produto_omnichat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("agente_api")

app = FastAPI(title="API do agente de IA (Omnichat)", docs_url=None, redoc_url=None, openapi_url=None)



@app.on_event("startup")
def _iniciar() -> None:
    fila.iniciar_envio()


@app.on_event("shutdown")
def _encerrar() -> None:
    # Deploy: manda o que estiver no buffer antes de desligar.
    fila.enviar_pendentes()


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


TIPOS = {"TEXT", "ID", "SKUID", "REFERENCE", "URL"}


def _buscar(tipo: str, termo: str, inicio: int, quantidade: int) -> list[dict]:
    if tipo not in TIPOS:
        raise HTTPException(status_code=400, detail=f"searchType nao suportado: {tipo}")
    if config.FONTE == "planilha":
        return planilha.buscar(tipo, termo, inicio, quantidade)
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
    return {"ok": True, "fonte": config.FONTE}


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
    except (oracle.OracleErro, planilha.PlanilhaErro) as exc:
        log.warning("busca falhou fonte=%s tipo=%s termo=%r: %s", config.FONTE, tipo, termo, exc)
        # "detail" e o texto neutro para a Omnichat; "motivo" ajuda quem diagnostica
        # (a aba Catalogo do agente no portal mostra ele). Nao tem dado sensivel.
        return JSONResponse(status_code=502, content={
            "detail": "Catalogo da iPlace indisponivel no momento.",
            "motivo": str(exc),
        })
    if resultado and not fila.televendas_disponivel():
        for item in resultado:
            item["productDescription"] = f"{fila.AVISO_INDISPONIVEL}\n\n{item.get('productDescription') or ''}".strip()
    log.info(
        "busca fonte=%s tipo=%s termo=%r from=%s size=%s -> %s produtos (%sms)",
        config.FONTE, tipo, termo, inicio, quantidade, len(resultado), int((time.monotonic() - comeco) * 1000),
    )
    return resultado


@app.post("/omnichat/webhook")
async def webhook_omnichat(
    request: Request,
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
):
    """Eventos de atendimento da Omnichat (chat-routed, chat-finished) para a fila do televendas.
    Responde rápido: a Omnichat espera no máximo 8 s e tenta só 3 vezes."""
    try:
        fila.autorizar_webhook(authorization, x_api_key)
    except fila.WebhookNaoAutorizado as exc:
        # Diagnostico sem expor segredo: so o formato e o tamanho do que chegou.
        def _formato(valor: str | None) -> str:
            if not valor:
                return "ausente"
            v = valor.strip()
            if v.lower().startswith("bearer "):
                return f"'Bearer ' + {len(v[7:].strip())} caracteres"
            return f"sem 'Bearer ', {len(v)} caracteres"
        log.warning(
            "webhook recusado (%s): Authorization=%s, x-api-key=%s, esperado=%s caracteres, headers=%s",
            exc, _formato(authorization), _formato(x_api_key), len(config.OMNI_WEBHOOK_TOKEN),
            sorted(h for h in request.headers.keys()),
        )
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        evento = await request.json()
    except ValueError as exc:
        log.warning("webhook com corpo que nao e JSON: %r", (await request.body())[:300])
        raise HTTPException(status_code=400, detail="JSON invalido.") from exc
    eventos = evento if isinstance(evento, list) else [evento]
    for item in eventos:
        if isinstance(item, dict):
            feito = fila.registrar_evento(item)
            if feito != "ignorado":  # message-sent chega a cada mensagem: só loga o que serviu
                log.info("webhook %s %s -> %s", item.get("type"), (item.get("payload") or {}).get("objectId"), feito)
    return {"ok": True}


@app.get("/fila")
def ver_fila(
    token: str | None = Query(None),
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
):
    """Situação da fila do televendas, para a aba do portal."""
    _autorizar(x_api_key, authorization, token)
    return fila.situacao()
