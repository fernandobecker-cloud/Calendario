"""Planilha da campanha do agente de IA (plano B enquanto o Akamai bloqueia o
site): leitura do .xlsx/.csv que o CRM sobe no portal, validacao e
gravacao no BigQuery.

Uma linha por SKU. A API do agente (servico agente-ia-api) le as linhas
validadas pelo endpoint /api/agente-ia/planilha/feed.

Gravacao = load job WRITE_TRUNCATE e leitura = list_rows: nenhum dos dois
cobra query no BigQuery (a cota do projeto e de ~30 GiB/dia).
"""

from __future__ import annotations

import csv
import io
import math
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any

from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from openpyxl import load_workbook

from backend.event_sources import build_bigquery_client

_PROJECT_ID = os.getenv("BASE_VENDAS_BQ_PROJECT", "").strip()
_DATASET = os.getenv("PORTAL_BQ_DATASET", "portal_crm").strip()
_TABELA = "agente_planilha"
_TIMEOUT_S = 60
_CACHE_TTL_S = 60

# coluna -> (tipo, obrigatoria, apelidos aceitos no cabecalho, explicacao para a tela)
COLUNAS: dict[str, tuple[str, bool, list[str], str]] = {
    "produto_id": ("texto", False, ["id produto", "id do produto", "codigo produto"],
                   "Id do produto no site (ex.: 100544PR). Agrupa as variantes e permite buscar pelo link."),
    "produto": ("texto", True, ["nome", "nome do produto"],
                "Nome do produto como o cliente procura (ex.: iPhone 17 Pro Max)."),
    "sku": ("texto", True, ["codigo sku", "sku id", "id sku"], "Código do SKU (uma linha por SKU)."),
    "variante": ("texto", False, ["nome variante"], "Nome da variante (ex.: 256GB Laranja-cósmico)."),
    "cor": ("texto", False, [], "Cor."),
    "capacidade": ("texto", False, ["armazenamento"], "Capacidade ou tamanho (ex.: 256GB, 46mm)."),
    "preco_de": ("numero", False, ["preco de", "de"], "Preço \"de\" (riscado). Em branco = sem desconto."),
    "preco_por": ("numero", False, ["preco por", "por", "preco site", "preco"],
                  "Preço do site como aparece grande na página (o preço no Pix). Também vale para o televendas. Em branco = item só de loja (aí preco_loja é obrigatório)."),
    "preco_pix": ("numero", False, ["pix", "preco no pix"], "Preço no Pix, se for diferente do preco_por. Em branco = preco_por."),
    "preco_cartao": ("numero", False, ["cartao", "preco no cartao", "preco cartao"],
                     "Preço no cartão (base do parcelamento). Em branco = Pix ÷ 0,9, como no site."),
    "parcelas": ("inteiro", False, ["max parcelas", "qtd parcelas"], "Máximo de parcelas no cartão. Em branco = 21 (menos, se a parcela ficar abaixo de R$ 5)."),
    "juros_mes": ("numero", False, ["juros", "juros a m", "juros ao mes"],
                  "Juros ao mês no cartão, em % (0 = sem juros). Em branco = 1,05."),
    "preco_loja": ("numero", False, ["preco loja", "preco na loja"],
                   "Preço na loja física. Só é mostrado se o cliente escolher comprar na loja."),
    "condicao_loja": ("texto", False, ["pagamento loja", "condicao loja", "parcelamento loja"],
                      "Condição de pagamento na loja, em texto (ex.: 10x sem juros)."),
    "estoque": ("inteiro", False, ["quantidade", "qtd estoque"],
                "Quantidade em estoque. 0 = esgotado (o agente não oferece). Em branco = disponível."),
    "categoria": ("texto", False, ["categoria do produto"],
                  "Categoria (ex.: IPHONE, WATCH, CAPAS IPHONE APPLE). Aparelhos aparecem antes de acessórios na busca. "
                  "Em branco = usa o \"Categoria: X\" da descrição, se houver."),
    "link": ("texto", False, ["url", "link site", "url do produto"], "Link da página do produto no site."),
    "imagem": ("texto", False, ["foto", "url imagem", "imagem url"], "Link da imagem do produto."),
    "descricao": ("texto", False, ["descricao do produto"], "Descrição curta para o agente."),
    "ativo": ("bool", False, [], "S ou N. N tira o SKU do agente sem apagar a linha. Em branco = S."),
}

_SCHEMA = (
    [bigquery.SchemaField("linha", "INT64")]
    + [
        bigquery.SchemaField(
            nome,
            {"texto": "STRING", "numero": "FLOAT64", "inteiro": "INT64", "bool": "BOOL"}[tipo],
        )
        for nome, (tipo, *_resto) in COLUNAS.items()
    ]
    + [
        bigquery.SchemaField("arquivo", "STRING"),
        bigquery.SchemaField("carregado_por", "STRING"),
        bigquery.SchemaField("carregado_em", "TIMESTAMP"),
    ]
)

_RE_NAO_ALFANUM = re.compile(r"[^a-z0-9]+")
_RE_MILHAR = re.compile(r"^\d{1,3}(\.\d{3})+$")
MAX_ERROS = 40


class PlanilhaInvalida(Exception):
    def __init__(self, erros: list[str]):
        super().__init__("; ".join(erros))
        self.erros = erros


class PlanilhaErroBQ(Exception):
    pass


def _norm(texto: Any) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return _RE_NAO_ALFANUM.sub(" ", sem_acento.lower()).strip()


_APELIDOS = {}
for _nome, (_tipo, _obrig, _apelidos, _exp) in COLUNAS.items():
    for _a in [_nome, *_apelidos]:
        _APELIDOS[_norm(_a)] = _nome


def modelo_csv() -> bytes:
    """Cabecalho da planilha, em CSV com ; e BOM (abre direto no Excel pt-BR)."""
    saida = io.StringIO()
    csv.writer(saida, delimiter=";").writerow(COLUNAS.keys())
    return ("﻿" + saida.getvalue()).encode("utf-8")


def _celula(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))  # SKU e precos redondos que o Excel guardou como numero
    return str(valor)


def _ler_tabela(conteudo: bytes, arquivo: str) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Cabecalho + linhas com o numero da linha como aparece no Excel."""
    nome = arquivo.lower()
    if nome.endswith((".xlsx", ".xlsm")):
        try:
            planilha = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True).worksheets[0]
            linhas = [[_celula(v) for v in row] for row in planilha.iter_rows(values_only=True)]
        except Exception as exc:
            raise PlanilhaInvalida([f"Não consegui abrir o Excel: {exc}"]) from exc
    elif nome.endswith((".csv", ".txt")):
        texto = ""
        for codificacao in ("utf-8-sig", "cp1252"):
            try:
                texto = conteudo.decode(codificacao)
                break
            except UnicodeDecodeError:
                continue
        primeira = texto.splitlines()[0] if texto else ""
        delimitador = ";" if primeira.count(";") >= primeira.count(",") else ","
        linhas = list(csv.reader(io.StringIO(texto), delimiter=delimitador))
    else:
        raise PlanilhaInvalida(["Formato não aceito. Envie .xlsx ou .csv."])
    if not linhas:
        return [], []
    return linhas[0], [(i + 2, linha) for i, linha in enumerate(linhas[1:])]


def _numero(valor: str) -> float:
    texto = valor.strip().replace("R$", "").replace("%", "").replace(" ", "").replace(" ", "")
    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")
    elif _RE_MILHAR.match(texto):
        texto = texto.replace(".", "")
    numero = float(texto)
    if math.isnan(numero) or math.isinf(numero):
        raise ValueError
    return numero


def _converter(nome: str, tipo: str, bruto: str) -> Any:
    if tipo == "texto":
        texto = bruto.strip()
        if nome == "sku" and re.fullmatch(r"\d+\.0+", texto):
            texto = texto.split(".")[0]  # Excel guardou o SKU como numero
        return texto or None
    if tipo == "bool":
        texto = _norm(bruto)
        if texto in ("", "s", "sim", "1", "true", "x"):
            return True
        if texto in ("n", "nao", "0", "false"):
            return False
        raise ValueError
    if not bruto.strip():
        return None
    numero = _numero(bruto)
    if tipo == "inteiro":
        if numero != int(numero):
            raise ValueError
        return int(numero)
    return round(numero, 2)


def validar(conteudo: bytes, arquivo: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Linhas validadas + avisos. Levanta PlanilhaInvalida com a lista de erros."""
    cabecalho, registros = _ler_tabela(conteudo, arquivo)
    if not cabecalho:
        raise PlanilhaInvalida(["A planilha está vazia."])

    mapa: dict[int, str] = {}
    for posicao, titulo in enumerate(cabecalho):
        coluna = _APELIDOS.get(_norm(titulo))
        if coluna and coluna not in mapa.values():
            mapa[posicao] = coluna
    faltando = [n for n, (_t, obrig, *_r) in COLUNAS.items() if obrig and n not in mapa.values()]
    if faltando:
        raise PlanilhaInvalida([f"Faltam as colunas obrigatórias: {', '.join(faltando)}. "
                                "Baixe o modelo para ver os nomes."])

    erros: list[str] = []
    avisos: list[str] = []
    linhas: list[dict[str, Any]] = []
    skus: dict[str, int] = {}
    for numero_linha, registro in registros:
        if not any(str(v or "").strip() for v in registro):
            continue
        linha: dict[str, Any] = {"linha": numero_linha}
        invalidas: set[str] = set()
        for posicao, coluna in mapa.items():
            tipo = COLUNAS[coluna][0]
            bruto = registro[posicao] if posicao < len(registro) else ""
            try:
                linha[coluna] = _converter(coluna, tipo, bruto)
            except (ValueError, OverflowError):
                invalidas.add(coluna)
                linha[coluna] = None
                erros.append(f"Linha {numero_linha}, coluna {coluna}: valor inválido \"{bruto.strip()}\".")
        for coluna in COLUNAS:
            linha.setdefault(coluna, True if coluna == "ativo" else None)

        for coluna in ("produto", "sku"):
            if linha.get(coluna) in (None, "") and coluna not in invalidas:
                erros.append(f"Linha {numero_linha}: {coluna} em branco.")
        # Sem preco_por vale como item só de loja, desde que tenha preco_loja.
        if linha.get("preco_por") in (None, "") and not linha.get("preco_loja") \
                and "preco_por" not in invalidas and "preco_loja" not in invalidas:
            erros.append(f"Linha {numero_linha}: preencha preco_por (site) ou preco_loja (item só de loja).")
        if linha.get("preco_por") is not None and linha["preco_por"] <= 0:
            erros.append(f"Linha {numero_linha}: preco_por precisa ser maior que zero.")
        if linha.get("parcelas") is not None and not 1 <= linha["parcelas"] <= 36:
            erros.append(f"Linha {numero_linha}: parcelas deve ficar entre 1 e 36.")
        if linha.get("juros_mes") is not None and not 0 <= linha["juros_mes"] <= 10:
            erros.append(f"Linha {numero_linha}: juros_mes deve ficar entre 0 e 10 (% ao mês).")
        if linha.get("estoque") is not None and linha["estoque"] < 0:
            erros.append(f"Linha {numero_linha}: estoque não pode ser negativo.")
        sku = linha.get("sku")
        if sku:
            if sku in skus:
                erros.append(f"Linha {numero_linha}: SKU {sku} repetido (já está na linha {skus[sku]}).")
            skus[sku] = numero_linha
        if linha.get("preco_de") and linha.get("preco_por") and linha["preco_de"] < linha["preco_por"]:
            avisos.append(f"Linha {numero_linha}: preco_de menor que preco_por (o agente não vai mostrar desconto).")
        pix = linha.get("preco_pix") or linha.get("preco_por")
        if linha.get("preco_cartao") and pix and linha["preco_cartao"] < pix:
            avisos.append(f"Linha {numero_linha}: preco_cartao menor que o preço no Pix.")
        linhas.append(linha)

    if not linhas:
        erros.append("Nenhuma linha preenchida.")
    if erros:
        extra = len(erros) - MAX_ERROS
        raise PlanilhaInvalida(erros[:MAX_ERROS] + ([f"... e mais {extra} erro(s)."] if extra > 0 else []))
    return linhas, avisos[:MAX_ERROS]


# --- BigQuery ---------------------------------------------------------------

_lock = threading.Lock()
_cache: dict[str, Any] = {"lido_em": 0.0, "feed": None}


def _tabela_id() -> str:
    if not _PROJECT_ID:
        raise PlanilhaErroBQ("Variavel BASE_VENDAS_BQ_PROJECT nao configurada")
    return f"{_PROJECT_ID}.{_DATASET}.{_TABELA}"


def _cliente() -> bigquery.Client:
    try:
        return build_bigquery_client(_PROJECT_ID)
    except Exception as exc:
        raise PlanilhaErroBQ("Falha ao autenticar no BigQuery") from exc


def salvar(linhas: list[dict[str, Any]], arquivo: str, usuario: str) -> dict[str, Any]:
    agora = datetime.now(timezone.utc).replace(microsecond=0)
    registros = [{**l, "arquivo": arquivo, "carregado_por": usuario, "carregado_em": agora.isoformat()} for l in linhas]
    config = bigquery.LoadJobConfig(schema=_SCHEMA, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
    try:
        _cliente().load_table_from_json(registros, _tabela_id(), job_config=config).result(timeout=_TIMEOUT_S)
    except PlanilhaErroBQ:
        raise
    except Exception as exc:
        raise PlanilhaErroBQ(f"Falha ao gravar a planilha no BigQuery: {exc}") from exc
    with _lock:
        _cache.update(lido_em=0.0, feed=None)
    return carregar(forcar=True)


def _valor(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def carregar(forcar: bool = False) -> dict[str, Any] | None:
    """Planilha atual ({carregado_em, carregado_por, arquivo, linhas}) ou None."""
    with _lock:
        if not forcar and _cache["feed"] is not None and time.monotonic() - _cache["lido_em"] < _CACHE_TTL_S:
            return _cache["feed"]
        try:
            linhas = [{k: _valor(v) for k, v in row.items()}
                      for row in _cliente().list_rows(_tabela_id(), timeout=_TIMEOUT_S)]
        except NotFound:
            linhas = []
        except PlanilhaErroBQ:
            raise
        except Exception as exc:
            if _cache["feed"] is not None:
                return _cache["feed"]  # BigQuery fora: segue com a ultima copia
            raise PlanilhaErroBQ(f"Falha ao ler a planilha no BigQuery: {exc}") from exc
        if not linhas:
            feed = None
        else:
            linhas.sort(key=lambda l: l.get("linha") or 0)
            meta = linhas[0]
            feed = {
                "carregado_em": meta.get("carregado_em"),
                "carregado_por": meta.get("carregado_por"),
                "arquivo": meta.get("arquivo"),
                "linhas": [{k: v for k, v in l.items() if k not in ("arquivo", "carregado_por", "carregado_em")}
                           for l in linhas],
            }
        _cache.update(feed=feed, lido_em=time.monotonic())
        return feed
