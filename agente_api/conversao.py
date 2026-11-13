"""Converte produto do Oracle para o formato "SearchProduct" da Omnichat.

Contrato: https://developers.omni.chat/docs/how-to-implement-the-searchproduct-api.md
"""

from __future__ import annotations

import html
import math
import re

from . import config

_RE_STYLE = re.compile(r"<style\b.*?</style>", re.S | re.I)
_RE_SUP = re.compile(r"<sup\b.*?</sup>", re.S | re.I)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_ESPACO = re.compile(r"[ \t\r\f\v]+")
_RE_LINHAS = re.compile(r"\n\s*\n+")
_LIMITE_DESCRICAO = 1500


def arredondar(valor: float) -> float:
    return round(valor + 1e-9, 2)


def truncar(valor: float) -> float:
    return math.floor(valor * 100 + 1e-6) / 100


def parcela_price(valor: float, parcelas: int, juros_mensal_pct: float) -> float:
    """Valor da parcela pela tabela Price (juros compostos). O site TRUNCA os
    centavos (582,2086 -> 582,20), entao fazemos igual para bater com a pagina."""
    if parcelas <= 1:
        return arredondar(valor)
    i = juros_mensal_pct / 100
    if i <= 0:
        return truncar(valor / parcelas)
    return truncar(valor * i / (1 - (1 + i) ** -parcelas))


def opcoes_de_pagamento(preco_venda: float) -> list[dict]:
    """Uma entrada por forma de pagamento, com o maior parcelamento de cada uma
    (como pede o contrato da Omnichat)."""
    opcoes = []
    n = config.CARTAO_MAX_PARCELAS
    juros = config.CARTAO_JUROS_MENSAL_PCT
    if n >= 1:
        parcela = parcela_price(preco_venda, n, juros)
        opcoes.append({
            "name": "Cartão de crédito",
            "oneTimePayment": arredondar(preco_venda),
            "maxInstallments": n,
            "installmentPrice": parcela,
            "interest": juros if n > 1 else 0,
            "totalWithInterest": arredondar(parcela * n),
        })
    pix = arredondar(preco_venda * (1 - config.PIX_DESCONTO))
    opcoes.append({
        "name": "Pix",
        "oneTimePayment": pix,
        "maxInstallments": 1,
        "installmentPrice": pix,
        "interest": 0,
        "totalWithInterest": pix,
    })
    return opcoes


def url_absoluta(caminho: str | None) -> str | None:
    if not caminho:
        return None
    if caminho.startswith("http"):
        return caminho
    return f"{config.ORACLE_BASE_URL}{caminho}"


def link_do_produto(rota: str | None) -> str | None:
    url = url_absoluta(rota)
    if not url or not config.UTM:
        return url
    return f"{url}{'&' if '?' in url else '?'}{config.UTM}"


def descricao_em_texto(produto: dict) -> str:
    """Texto limpo da descricao do site (o campo vem em HTML com CSS embutido)."""
    bruto = produto.get("x_caracteristicasHtml") or ""
    if bruto:
        texto = _RE_STYLE.sub(" ", bruto)
        texto = _RE_SUP.sub("", texto)
        texto = re.sub(r"</(li|h3|section|p)>", "\n", texto, flags=re.I)
        texto = html.unescape(_RE_TAG.sub(" ", texto))
        linhas = [_RE_ESPACO.sub(" ", linha).strip() for linha in texto.split("\n")]
        texto = _RE_LINHAS.sub("\n", "\n".join(linha for linha in linhas if linha)).strip()
        # "Avisos legais" sao notas de rodape longas e nao ajudam o agente.
        texto = texto.split("Avisos legais")[0].strip()
    else:
        texto = (produto.get("description") or produto.get("displayName") or "").strip()
    if len(texto) > _LIMITE_DESCRICAO:
        texto = texto[:_LIMITE_DESCRICAO].rsplit(" ", 1)[0] + "..."
    return texto


def _preco_venda(sku: dict) -> float | None:
    venda = sku.get("salePrice")
    lista = sku.get("listPrice")
    if venda:
        return float(venda)
    return float(lista) if lista else None


def _variante(sku: dict, produto: dict, estoque: dict) -> dict | None:
    sku_id = sku.get("repositoryId")
    preco = _preco_venda(sku)
    if not sku_id or preco is None or sku.get("active") is False:
        return None
    info = estoque.get(sku_id) or {}
    quantidade = info.get("quantidade", 0) if info.get("status") == "IN_STOCK" else 0
    variacoes = [
        {"key": rotulo, "value": sku.get(campo)}
        for campo, rotulo in (("x_cor", "Cor"), ("x_capacidade", "Capacidade"), ("x_tamanho", "Tamanho"))
        if sku.get(campo)
    ]
    variante = {
        "objectId": sku_id,
        "externalImageURL": url_absoluta(sku.get("primaryFullImageURL") or produto.get("primaryFullImageURL")),
        "erpId": sku_id,
        "name": sku.get("displayName") or produto.get("displayName"),
        "visible": quantidade > 0,
        "price": float(sku.get("listPrice") or preco),
        "salePrice": preco,
        "quantity": quantidade,
        "sellerId": "1",
        "sellerName": "iPlace",
        "installmentOptions": opcoes_de_pagamento(preco),
        "variations": variacoes,
    }
    if (sku.get("x_apenasRetireEmLoja") or "").upper() == "S":
        variante["variations"].append({"key": "Entrega", "value": "Somente retirada em loja"})
    return variante


def produto_omnichat(produto: dict, estoque: dict, somente_sku: str | None = None) -> dict | None:
    """Monta um produto da Omnichat. Volta None se nao houver variante
    vendavel (sem preco, inativa ou - por padrao - sem estoque)."""
    if produto.get("active") is False:
        return None
    variantes = [
        v for v in (_variante(sku, produto, estoque) for sku in produto.get("childSKUs") or [])
        if v is not None
    ]
    if somente_sku:
        variantes = [v for v in variantes if v["objectId"] == somente_sku]
    com_estoque = [v for v in variantes if v["quantity"] > 0]
    if not com_estoque and not config.MOSTRAR_SEM_ESTOQUE:
        return None
    if not variantes:
        return None
    # Variante principal = a mais barata com estoque (o "a partir de" do site).
    principal = min(com_estoque or variantes, key=lambda v: v["salePrice"])
    return {
        "blocked": False,
        "objectId": produto["id"],
        "name": produto.get("displayName"),
        "productDescription": descricao_em_texto(produto),
        "externalUrl": link_do_produto(produto.get("route")),
        "externalProduct": True,
        "mainVariant": principal,
        "variants": variantes,
        "sellOutOfStock": False,
        "trackInventory": True,
    }
