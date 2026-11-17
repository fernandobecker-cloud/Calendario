"""Catalogo vindo da planilha da campanha (plano B enquanto o Akamai bloqueia
o site).

O CRM sobe a planilha no portal (aba "Catalogo do agente"); o portal valida,
guarda no BigQuery e expoe as linhas em /api/agente-ia/planilha/feed. Aqui a
gente le esse feed, guarda em memoria por PLANILHA_TTL_S e monta os produtos
no mesmo formato da Omnichat que a fonte "site" devolve.

Preco do site/televendas = preco_por (com Pix e cartao). Preco de loja e
diferente e vai como texto na descricao do produto, para o agente so usar
depois que o cliente escolher comprar na loja.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata

import requests

from . import config
from .conversao import link_do_produto, opcoes_de_pagamento

log = logging.getLogger("agente_api.planilha")

# Palavras que o cliente escreve mas nao ajudam a achar o produto.
_STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das", "e", "em", "no", "na",
    "para", "pra", "com", "quero", "queria", "comprar", "preco", "valor", "tem", "voces",
    # Quase tudo e Apple e os nomes do ERP nao repetem a marca ("WATCH SE 3 44...").
    "apple",
}

# Os nomes da planilha vem do ERP, abreviados e com cor em ingles. Cada palavra
# do nome ganha as formas que o cliente escreve ("ORANGE" tambem acha "laranja").
_SINONIMOS = {
    "iph": "iphone", "iphon": "iphone", "macb": "macbook", "ult": "ultra", "ult2": "ultra 2",
    "ultra2": "ultra 2", "ultra3": "ultra 3", "ultra4": "ultra 4", "s10": "series 10", "s11": "series 11",
    "3ger": "3 geracao", "4ger": "4 geracao", "5ger": "5 geracao", "wf": "wifi", "wi": "wifi",
    "cel": "cellular celular 5g", "cell": "cellular celular 5g", "pel": "pelicula",
    "orange": "laranja", "org": "laranja", "lara": "laranja", "cos": "cosmico",
    "black": "preto", "bk": "preto", "pto": "preto", "white": "branco", "bco": "branco",
    "blue": "azul", "blu": "azul", "azl": "azul", "green": "verde", "pink": "rosa",
    "purple": "roxo", "pur": "roxo", "yellow": "amarelo", "silver": "prata", "sil": "prata",
    "red": "vermelho", "midnight": "meia noite", "mdn": "meia noite", "starlight": "estelar",
    "star": "estelar", "stl": "estelar", "gray": "cinza", "grey": "cinza", "gr": "cinza",
    "sg": "cinza espacial", "spg": "cinza espacial", "spgr": "cinza espacial", "spb": "preto espacial",
    "gold": "dourado", "gd": "dourado", "teal": "verde", "ultramarine": "azul ultramarino",
    "ultmarine": "azul ultramarino", "nt": "natural", "ti": "titanio", "al": "aluminio",
}

# Categorias de aparelho: aparecem antes de capa, pelicula, cabo... quando o
# cliente procura "watch" ou "iphone 17".
_CATEGORIAS_APARELHO = {
    "iphone", "ipad", "watch", "mac", "fones de ouvido apple", "airtag apple", "apple tv", "caixas de som apple",
}
_PALAVRAS_ACESSORIO = {
    "capa", "capas", "case", "pelicula", "peliculas", "cabo", "cabos", "carregador", "carregadores",
    "pulseira", "pulseiras", "adaptador", "suporte", "bolsa", "mochila", "fonte", "protetor", "acessorio",
    "acessorios", "sleeve",
}
_RE_CATEGORIA = re.compile(r"categoria:\s*([^|\n]+)", re.I)
_RE_NAO_ALFANUM = re.compile(r"[^a-z0-9]+")
_RE_ID_PRODUTO_NA_URL = re.compile(r"/([0-9]+PR)\b", re.I)


class PlanilhaErro(RuntimeError):
    """Nao foi possivel ler a planilha da campanha no portal."""


_lock = threading.Lock()
_estado: dict = {"lido_em": 0.0, "feed": None}


def normalizar(texto: str | None) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return _RE_NAO_ALFANUM.sub(" ", sem_acento.lower()).strip()


def _baixar_feed() -> dict:
    try:
        resp = requests.get(
            config.PLANILHA_URL,
            headers={"x-api-key": config.TOKEN, "User-Agent": config.USER_AGENT},
            timeout=config.PLANILHA_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        raise PlanilhaErro(f"portal nao respondeu ao ler a planilha: {exc.__class__.__name__}") from exc
    if resp.status_code == 404:
        raise PlanilhaErro("nenhuma planilha da campanha foi carregada no portal ainda")
    if resp.status_code != 200:
        raise PlanilhaErro(f"portal respondeu HTTP {resp.status_code} ao ler a planilha")
    try:
        feed = resp.json()
    except ValueError as exc:
        raise PlanilhaErro("portal devolveu a planilha em formato invalido") from exc
    if not isinstance(feed, dict) or not isinstance(feed.get("linhas"), list):
        raise PlanilhaErro("portal devolveu a planilha em formato invalido")
    return feed


def carregar_feed() -> dict:
    """Feed em memoria; rele do portal a cada PLANILHA_TTL_S. Se a releitura
    falhar, segue com a ultima copia boa (o agente nao para se o portal cair)."""
    with _lock:
        feed = _estado["feed"]
        if feed is not None and time.monotonic() - _estado["lido_em"] < config.PLANILHA_TTL_S:
            return feed
        try:
            feed = _baixar_feed()
        except PlanilhaErro as exc:
            if _estado["feed"] is not None:
                log.warning("releitura da planilha falhou, usando a ultima copia: %s", exc)
                _estado["lido_em"] = time.monotonic()  # nao tenta de novo a cada busca
                return _estado["feed"]
            raise
        _estado.update(feed=feed, lido_em=time.monotonic())
        log.info("planilha carregada: %s linhas (carregada no portal em %s)",
                 len(feed["linhas"]), feed.get("carregado_em"))
        return feed


def _chave_produto(linha: dict) -> str:
    return (linha.get("produto_id") or "").strip().upper() or normalizar(linha.get("produto"))


def _ativa(linha: dict) -> bool:
    return linha.get("ativo") is not False and bool(linha.get("sku")) and linha.get("preco_por")


def agrupar(linhas: list[dict]) -> list[dict]:
    """Agrupa as linhas (uma por SKU) em produtos, na ordem da planilha."""
    grupos: dict[str, dict] = {}
    for linha in linhas:
        if not _ativa(linha):
            continue
        chave = _chave_produto(linha)
        if not chave:
            continue
        grupo = grupos.setdefault(chave, {"chave": chave, "linhas": []})
        grupo["linhas"].append(linha)
    return list(grupos.values())


def _brl(valor: float) -> str:
    inteiro, centavos = f"{valor:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


def _nome_variante(linha: dict) -> str:
    return (linha.get("variante") or " ".join(
        str(linha.get(c)) for c in ("capacidade", "cor") if linha.get(c)
    ) or linha.get("produto") or "").strip()


def _nome_completo(linha: dict) -> str:
    produto = (linha.get("produto") or "").strip()
    variante = _nome_variante(linha)
    if not variante or variante == produto:
        return produto
    # A planilha do ERP repete o nome do produto na variante ("WATCH SE 3 ... MXEK3BE/A").
    if normalizar(variante).startswith(normalizar(produto)):
        return variante
    return f"{produto} {variante}"


def _variante(linha: dict) -> dict:
    preco = float(linha["preco_por"])
    estoque = linha.get("estoque")
    # Estoque em branco = o CRM nao controla: o agente considera disponivel.
    quantidade = int(estoque) if estoque is not None else 1
    variacoes = [
        {"key": rotulo, "value": linha.get(campo)}
        for campo, rotulo in (("cor", "Cor"), ("capacidade", "Capacidade"))
        if linha.get(campo)
    ]
    return {
        "objectId": str(linha["sku"]),
        "externalImageURL": linha.get("imagem") or None,
        "erpId": str(linha["sku"]),
        "name": _nome_completo(linha),
        "visible": quantidade > 0,
        "price": float(linha.get("preco_de") or preco),
        "salePrice": preco,
        "quantity": quantidade,
        "sellerId": "1",
        "sellerName": "iPlace",
        "installmentOptions": opcoes_de_pagamento(
            preco,
            parcelas=linha.get("parcelas"),
            juros_mensal_pct=linha.get("juros_mes"),
            preco_pix=linha.get("preco_pix"),
        ),
        "variations": variacoes,
    }


def _texto_loja(linhas: list[dict]) -> str:
    com_preco = [l for l in linhas if l.get("preco_loja")]
    if not com_preco:
        return ""
    itens = []
    for linha in com_preco:
        texto = f"- {_nome_variante(linha)} (SKU {linha['sku']}): {_brl(float(linha['preco_loja']))}"
        if linha.get("condicao_loja"):
            texto += f", {linha['condicao_loja']}"
        itens.append(texto)
    return (
        "PREÇO NA LOJA FÍSICA (use somente se o cliente escolher comprar na loja; "
        "site e televendas usam o preço principal):\n" + "\n".join(itens)
    )


def produto_omnichat(grupo: dict, somente_sku: str | None = None) -> dict | None:
    linhas = grupo["linhas"]
    if somente_sku:
        linhas = [l for l in linhas if str(l["sku"]) == somente_sku]
    if not linhas:
        return None
    variantes = [_variante(l) for l in linhas]
    com_estoque = [v for v in variantes if v["quantity"] > 0]
    if not com_estoque and not config.MOSTRAR_SEM_ESTOQUE:
        return None
    principal = min(com_estoque or variantes, key=lambda v: v["salePrice"])
    primeira = linhas[0]
    descricao = next((l["descricao"] for l in linhas if l.get("descricao")), "") or ""
    loja = _texto_loja(linhas)
    if loja:
        descricao = f"{descricao}\n\n{loja}".strip()
    link = next((l["link"] for l in linhas if l.get("link")), None)
    imagem = next((l["imagem"] for l in linhas if l.get("imagem")), None)
    for v in variantes:
        v["externalImageURL"] = v["externalImageURL"] or imagem
    return {
        "blocked": False,
        "objectId": (primeira.get("produto_id") or "").strip().upper() or grupo["chave"],
        "name": primeira.get("produto"),
        "productDescription": descricao,
        "externalUrl": link_do_produto(link) if link else None,
        "externalProduct": True,
        "mainVariant": principal,
        "variants": variantes,
        "sellOutOfStock": False,
        # Se alguma linha nao informou estoque, o agente nao deve prometer quantidade.
        "trackInventory": all(l.get("estoque") is not None for l in linhas),
    }


def categoria(linha: dict) -> str:
    """Coluna categoria ou, se vier vazia, o "Categoria: X" da descricao."""
    if linha.get("categoria"):
        return normalizar(linha["categoria"])
    achou = _RE_CATEGORIA.search(linha.get("descricao") or "")
    return normalizar(achou.group(1)) if achou else ""


def _texto_de_busca(grupo: dict) -> list[str]:
    partes = []
    for l in grupo["linhas"]:
        partes += [l.get("produto"), l.get("variante"), l.get("cor"), l.get("capacidade"),
                   l.get("produto_id"), str(l.get("sku")), categoria(l)]
        cat = categoria(l)
        if "acessorios watch" in cat:
            partes.append("pulseira")
        if "protecao de tela" in cat:
            partes.append("pelicula")
    palavras = normalizar(" ".join(p for p in partes if p)).split()
    return palavras + [extra for p in palavras for extra in _SINONIMOS.get(p, "").split()]


def buscar_texto(termo: str, inicio: int, quantidade: int) -> list[dict]:
    """Busca simples por palavras: o produto precisa ter todas as palavras do
    termo (cada uma pode ser o comeco de uma palavra: "256" acha "256gb").
    Ordem: aparelhos antes de acessorios (a menos que o cliente peca acessorio),
    depois o nome com menos palavras alem das pedidas ("iphone 17" traz o 17
    antes do 17 Pro Max) e o menor preco (256GB antes de 1TB)."""
    tokens = [t for t in normalizar(termo).split() if t not in _STOPWORDS]
    if not tokens:
        return []
    quer_acessorio = any(t in _PALAVRAS_ACESSORIO for t in tokens)
    achados = []
    for ordem, grupo in enumerate(agrupar(carregar_feed()["linhas"])):
        palavras = _texto_de_busca(grupo)
        if all(any(p.startswith(t) for p in palavras) for t in tokens):
            primeira = grupo["linhas"][0]
            acessorio = 0 if quer_acessorio or categoria(primeira) in _CATEGORIAS_APARELHO else 1
            nome = normalizar(primeira.get("produto")).split()
            sobrando = sum(1 for p in nome if p not in tokens)  # "17e" conta como a mais em "iphone 17"
            menor_preco = min(float(l["preco_por"]) for l in grupo["linhas"])
            achados.append(((acessorio, sobrando, menor_preco, ordem), grupo))
    achados.sort(key=lambda x: x[0])
    resultado = []
    for _, grupo in achados[inicio:]:
        item = produto_omnichat(grupo)
        if item:
            resultado.append(item)
        if len(resultado) >= quantidade:
            break
    return resultado


def buscar_por_produto(ids: list[str]) -> list[dict]:
    alvos = {i.strip().upper() for i in ids if i.strip()}
    grupos = agrupar(carregar_feed()["linhas"])
    resultado = []
    for grupo in grupos:
        pid = (grupo["linhas"][0].get("produto_id") or "").strip().upper()
        if (pid and pid in alvos) or grupo["chave"].upper() in alvos:
            item = produto_omnichat(grupo)
            if item:
                resultado.append(item)
    return resultado


def buscar_por_sku(sku: str) -> list[dict]:
    sku = sku.strip()
    for grupo in agrupar(carregar_feed()["linhas"]):
        if any(str(l["sku"]) == sku for l in grupo["linhas"]):
            item = produto_omnichat(grupo, somente_sku=sku)
            return [item] if item else []
    return []


def buscar_por_url(url: str, quantidade: int) -> list[dict]:
    ids = [i.upper() for i in _RE_ID_PRODUTO_NA_URL.findall(url)]
    if ids:
        return buscar_por_produto(ids)[:quantidade]
    # Sem id na URL: compara com a coluna link (sem os parametros).
    base = url.split("?")[0].rstrip("/").lower()
    resultado = []
    for grupo in agrupar(carregar_feed()["linhas"]):
        if any((l.get("link") or "").split("?")[0].rstrip("/").lower() == base for l in grupo["linhas"]):
            item = produto_omnichat(grupo)
            if item:
                resultado.append(item)
    return resultado[:quantidade]


def buscar(tipo: str, termo: str, inicio: int, quantidade: int) -> list[dict]:
    if tipo == "TEXT":
        return buscar_texto(termo, inicio, quantidade)
    if tipo == "ID":
        return buscar_por_produto(termo.split(","))[:quantidade]
    if tipo == "SKUID":
        return buscar_por_sku(termo)
    if tipo == "REFERENCE":
        return buscar_por_produto([termo]) or buscar_por_sku(termo)
    if tipo == "URL":
        return buscar_por_url(termo, quantidade)
    return []

