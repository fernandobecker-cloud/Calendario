"""Leitura da API publica de vitrine do Oracle Commerce Cloud (site iPlace).

So GET, sem login, nos mesmos endpoints que o proprio site usa:
  - busca:   /ccstore/v1/assembler/pages/Default/osf/catalog?Ntt=...
  - produto: /ccstore/v1/products?productIds=...&fields=...
  - SKU:     /ccstore/v1/skus/{id}
  - estoque: /ccstore/v1/stockStatus?products=prod:sku,...

Toda resposta fica num cache em memoria (TTL curto) e as chamadas ao site sao
limitadas em concorrencia, para nao pesar no site no pico da Black.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

import requests

from . import config

log = logging.getLogger("agente_api.oracle")

CAMPOS_PRODUTO = ",".join([
    "id", "displayName", "description", "brand", "route", "active",
    "primaryFullImageURL", "x_caracteristicasHtml",
    "childSKUs.repositoryId", "childSKUs.displayName", "childSKUs.active",
    "childSKUs.listPrice", "childSKUs.salePrice", "childSKUs.primaryFullImageURL",
    "childSKUs.x_cor", "childSKUs.x_capacidade", "childSKUs.x_tamanho",
    "childSKUs.x_apenasRetireEmLoja",
])

# O stockStatus em lote aceita varios pares produto:sku; quebramos em lotes
# para a URL nao ficar gigante.
LOTE_ESTOQUE = 40


class OracleErro(RuntimeError):
    """O site nao respondeu (timeout, erro HTTP ou JSON invalido)."""


class _Cache:
    def __init__(self, ttl_s: int, max_itens: int):
        self.ttl_s = ttl_s
        self.max_itens = max_itens
        self._dados: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, chave: str):
        with self._lock:
            item = self._dados.get(chave)
            if not item:
                return None
            expira, valor = item
            if expira < time.monotonic():
                del self._dados[chave]
                return None
            self._dados.move_to_end(chave)
            return valor

    def set(self, chave: str, valor) -> None:
        with self._lock:
            self._dados[chave] = (time.monotonic() + self.ttl_s, valor)
            self._dados.move_to_end(chave)
            while len(self._dados) > self.max_itens:
                self._dados.popitem(last=False)


_cache = _Cache(config.CACHE_TTL_S, config.CACHE_MAX_ITENS)
_limite = threading.BoundedSemaphore(config.ORACLE_MAX_CONCORRENTES)
_sessao = requests.Session()
_sessao.headers.update({"User-Agent": config.USER_AGENT, "Accept": "application/json"})
if config.ORACLE_HEADER_LIBERACAO_NOME and config.ORACLE_HEADER_LIBERACAO_VALOR:
    _sessao.headers[config.ORACLE_HEADER_LIBERACAO_NOME] = config.ORACLE_HEADER_LIBERACAO_VALOR


def _get(caminho: str, params: dict | None = None):
    url = f"{config.ORACLE_BASE_URL}{caminho}"
    if params:
        url = f"{url}?{urlencode(params, safe=',:')}"
    em_cache = _cache.get(url)
    if em_cache is not None:
        return em_cache
    inicio = time.monotonic()
    with _limite:
        try:
            resp = _sessao.get(url, timeout=config.ORACLE_TIMEOUT_S)
        except requests.RequestException as exc:
            raise OracleErro(f"falha ao chamar o site: {exc.__class__.__name__}") from exc
    ms = int((time.monotonic() - inicio) * 1000)
    if resp.status_code == 404:
        log.info("oracle 404 %s (%sms)", caminho, ms)
        _cache.set(url, {})
        return {}
    if resp.status_code == 403 and "akamai" in (resp.headers.get("server") or "").lower():
        raise OracleErro(
            "Akamai bloqueou a chamada (403). O TI precisa liberar este servico "
            "(IP de saida da Render ou cabecalho ORACLE_HEADER_LIBERACAO_*)."
        )
    if resp.status_code != 200:
        raise OracleErro(f"site respondeu HTTP {resp.status_code} em {caminho}")
    try:
        dados = resp.json()
    except ValueError as exc:
        raise OracleErro(f"resposta do site nao e JSON em {caminho}") from exc
    log.info("oracle %s (%sms)", caminho, ms)
    _cache.set(url, dados)
    return dados


def _registros_da_busca(no) -> list[dict]:
    """Acha a lista de resultados da busca (o JSON do assembler e aninhado)."""
    if isinstance(no, dict):
        regs = no.get("records")
        if isinstance(regs, list) and regs and isinstance(regs[0], dict) and "attributes" in regs[0]:
            return regs
        for valor in no.values():
            achou = _registros_da_busca(valor)
            if achou:
                return achou
    elif isinstance(no, list):
        for valor in no:
            achou = _registros_da_busca(valor)
            if achou:
                return achou
    return []


def buscar_ids_por_texto(termo: str, inicio: int, quantidade: int) -> list[str]:
    """Ids de produto na mesma ordem da busca do site (ja com os filtros da
    vitrine: catalogo iplace2, produto ativo, mostrar na busca)."""
    dados = _get(
        "/ccstore/v1/assembler/pages/Default/osf/catalog",
        {"Ntt": termo, "Nrpp": quantidade, "No": inicio},
    )
    ids: list[str] = []
    for reg in _registros_da_busca(dados):
        valores = (reg.get("attributes") or {}).get("product.repositoryId") or []
        if valores and valores[0] not in ids:
            ids.append(valores[0])
    return ids


def carregar_produtos(ids: list[str]) -> dict[str, dict]:
    """Produto + variantes (SKUs) com preco, em uma chamada so."""
    if not ids:
        return {}
    dados = _get("/ccstore/v1/products", {"productIds": ",".join(ids), "fields": CAMPOS_PRODUTO})
    itens = dados.get("items") if isinstance(dados, dict) else None
    if itens is None and isinstance(dados, dict) and dados.get("id"):
        itens = [dados]
    return {p["id"]: p for p in (itens or []) if isinstance(p, dict) and p.get("id")}


def produto_do_sku(sku_id: str) -> str | None:
    dados = _get(f"/ccstore/v1/skus/{sku_id}", {"fields": "repositoryId,parentProducts.id"})
    pais = (dados or {}).get("parentProducts") or []
    return pais[0].get("id") if pais and isinstance(pais[0], dict) else None


def carregar_estoque(pares: list[tuple[str, str]]) -> dict[str, dict]:
    """Estoque por SKU: {sku_id: {"status": "IN_STOCK", "quantidade": 5}}."""
    lotes = [pares[i:i + LOTE_ESTOQUE] for i in range(0, len(pares), LOTE_ESTOQUE)]
    if not lotes:
        return {}

    def _lote(lote):
        return _get("/ccstore/v1/stockStatus", {"products": ",".join(f"{p}:{s}" for p, s in lote)})

    # Lotes em paralelo (o semaforo de _get continua limitando a concorrencia).
    with ThreadPoolExecutor(max_workers=min(len(lotes), config.ORACLE_MAX_CONCORRENTES)) as pool:
        respostas = list(pool.map(_lote, lotes))

    resultado: dict[str, dict] = {}
    for dados in respostas:
        itens = dados.get("items") if isinstance(dados, dict) else None
        if itens is None and isinstance(dados, dict) and dados.get("catRefId"):
            itens = [dados]
        for item in itens or []:
            sku = item.get("catRefId")
            if not sku:
                continue
            resultado[sku] = {
                "status": item.get("stockStatus"),
                "quantidade": int(item.get("orderableQuantity") or 0),
            }
    return resultado
