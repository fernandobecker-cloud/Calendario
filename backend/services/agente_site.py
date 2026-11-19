"""Descricoes comerciais e links dos produtos do site, para o agente de IA.

O Akamai bloqueia chamadas de servidor ao site, entao a copia e feita UMA vez
pelo navegador do CRM (script colado no console em www.iplace.com.br, que baixa
um .json) e o arquivo e enviado aqui. Fica gravado no BigQuery
(portal_crm.agente_site_produtos) e o feed da planilha usa esses dados para
completar a descricao e o link de cada linha, casando pelo produto_id ou pelo SKU.

Gravacao = load job WRITE_TRUNCATE e leitura = list_rows (sem custo de query).
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from agente_api.conversao import descricao_em_texto
from backend.services.agente_planilha import PlanilhaErroBQ, _DATASET, _PROJECT_ID, _cliente

_TABELA = "agente_site_produtos"
_TIMEOUT_S = 120
_CACHE_TTL_S = 600
SITE = "https://www.iplace.com.br"

_SCHEMA = (
    bigquery.SchemaField("produto_id", "STRING"),
    bigquery.SchemaField("nome", "STRING"),
    bigquery.SchemaField("skus", "STRING"),  # separados por virgula
    bigquery.SchemaField("descricao", "STRING"),
    bigquery.SchemaField("link", "STRING"),
    bigquery.SchemaField("carregado_por", "STRING"),
    bigquery.SchemaField("carregado_em", "TIMESTAMP"),
)

# Script que o CRM cola no console do navegador, com o site da iPlace aberto.
# Busca a lista de produtos em paginas, com pausa entre elas, e baixa um .json.
SCRIPT_NAVEGADOR = r"""(async () => {
  const campos = ['id','displayName','route','active','x_caracteristicasHtml','childSKUs.repositoryId'];
  const fields = 'totalResults,' + campos.map(c => 'items.' + c).join(',');
  const produtos = [];
  let offset = 0, total = 1;
  while (offset < total) {
    const r = await fetch(`/ccstore/v1/products?limit=100&offset=${offset}&fields=${fields}`);
    if (!r.ok) { alert('Erro ' + r.status + ' ao ler os produtos. Tente de novo em alguns minutos.'); return; }
    const d = await r.json();
    total = d.totalResults || 0;
    for (const p of d.items || []) {
      if (p.active === false) continue;
      produtos.push({
        id: p.id, nome: p.displayName, route: p.route,
        skus: (p.childSKUs || []).map(s => s.repositoryId),
        html: (p.x_caracteristicasHtml || '').replace(/<(style|script)[\s\S]*?<\/\1>/gi, ''),
      });
    }
    offset += 100;
    console.log(`Produtos lidos: ${Math.min(offset, total)} de ${total}`);
    await new Promise(ok => setTimeout(ok, 400));
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(produtos)], {type: 'application/json'}));
  a.download = 'produtos_site_iplace.json';
  a.click();
  console.log(`Pronto: ${produtos.length} produtos ativos no arquivo produtos_site_iplace.json`);
})();"""


class ArquivoInvalido(ValueError):
    pass


def _tabela_id() -> str:
    if not _PROJECT_ID:
        raise PlanilhaErroBQ("Variavel BASE_VENDAS_BQ_PROJECT nao configurada")
    return f"{_PROJECT_ID}.{_DATASET}.{_TABELA}"


def _texto(valor: Any) -> str:
    return str(valor).strip() if valor is not None else ""


def ler_arquivo(conteudo: bytes) -> list[dict[str, Any]]:
    """Le o .json gerado pelo script do navegador. Tambem aceita a resposta crua
    da API ({"items": [...]}) com os campos originais."""
    try:
        dados = json.loads(conteudo.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArquivoInvalido("O arquivo não é um JSON válido. Use o produtos_site_iplace.json gerado pelo script.") from exc
    if isinstance(dados, dict):
        dados = dados.get("items")
    if not isinstance(dados, list):
        raise ArquivoInvalido("Formato inesperado: era para ser a lista de produtos gerada pelo script.")
    produtos: dict[str, dict[str, Any]] = {}
    for item in dados:
        if not isinstance(item, dict) or item.get("active") is False:
            continue
        pid = _texto(item.get("id")).upper()
        if not pid:
            continue
        skus = item.get("skus")
        if skus is None:
            skus = [s.get("repositoryId") for s in item.get("childSKUs") or [] if isinstance(s, dict)]
        html = item.get("html") if "html" in item else item.get("x_caracteristicasHtml")
        rota = _texto(item.get("route"))
        produtos[pid] = {
            "produto_id": pid,
            "nome": _texto(item.get("nome") or item.get("displayName")),
            "skus": ",".join(_texto(s).upper() for s in skus or [] if _texto(s)),
            # So a descricao comercial; o campo "description" do site e o nome do ERP.
            "descricao": descricao_em_texto({"x_caracteristicasHtml": html or ""}) or None,
            "link": (rota if rota.startswith("http") else f"{SITE}{rota}") if rota else None,
        }
    if not produtos:
        raise ArquivoInvalido("Nenhum produto ativo no arquivo.")
    return list(produtos.values())


_lock = threading.Lock()
_cache: dict[str, Any] = {"lido_em": 0.0, "dados": None}


def salvar(produtos: list[dict[str, Any]], usuario: str) -> dict[str, Any] | None:
    agora = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    registros = [{**p, "carregado_por": usuario, "carregado_em": agora} for p in produtos]
    config = bigquery.LoadJobConfig(schema=_SCHEMA, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
    try:
        _cliente().load_table_from_json(registros, _tabela_id(), job_config=config).result(timeout=_TIMEOUT_S)
    except PlanilhaErroBQ:
        raise
    except Exception as exc:
        raise PlanilhaErroBQ(f"Falha ao gravar os produtos do site no BigQuery: {exc}") from exc
    return carregar(forcar=True)


def carregar(forcar: bool = False) -> dict[str, Any] | None:
    """{carregado_em, carregado_por, por_produto, por_sku} ou None se nunca foi carregado."""
    with _lock:
        if not forcar and _cache["lido_em"] and time.monotonic() - _cache["lido_em"] < _CACHE_TTL_S:
            return _cache["dados"]
        try:
            linhas = list(_cliente().list_rows(_tabela_id(), timeout=_TIMEOUT_S))
        except NotFound:
            linhas = []
        except PlanilhaErroBQ:
            raise
        except Exception as exc:
            if _cache["lido_em"]:
                return _cache["dados"]  # BigQuery fora: segue com a ultima copia
            raise PlanilhaErroBQ(f"Falha ao ler os produtos do site no BigQuery: {exc}") from exc
        dados = None
        if linhas:
            por_produto: dict[str, dict] = {}
            por_sku: dict[str, dict] = {}
            for row in linhas:
                p = {"produto_id": row["produto_id"], "nome": row["nome"],
                     "descricao": row["descricao"], "link": row["link"]}
                por_produto[p["produto_id"]] = p
                for sku in (row["skus"] or "").split(","):
                    if sku:
                        por_sku.setdefault(sku, p)
            em = linhas[0]["carregado_em"]
            dados = {
                "carregado_em": em.isoformat() if isinstance(em, datetime) else em,
                "carregado_por": linhas[0]["carregado_por"],
                "produtos": len(por_produto),
                "com_descricao": sum(1 for p in por_produto.values() if p["descricao"]),
                "por_produto": por_produto,
                "por_sku": por_sku,
            }
        _cache.update(dados=dados, lido_em=time.monotonic())
        return dados


def produto_da_linha(linha: dict[str, Any], dados: dict[str, Any] | None) -> dict[str, Any] | None:
    if not dados:
        return None
    pid = _texto(linha.get("produto_id")).upper()
    achou = dados["por_produto"].get(pid) if pid else None
    return achou or dados["por_sku"].get(_texto(linha.get("sku")).upper())


def completar(feed: dict[str, Any] | None, dados: dict[str, Any] | None) -> dict[str, Any] | None:
    """Feed da planilha com a descricao comercial e o link do site em cada linha.
    A descricao do site vem primeiro; o que o CRM escreveu na planilha fica depois.
    O link da planilha, se preenchido, tem prioridade."""
    if not feed or not dados:
        return feed
    linhas = []
    for linha in feed["linhas"]:
        site = produto_da_linha(linha, dados)
        if site:
            linha = dict(linha)
            if site["descricao"]:
                propria = (linha.get("descricao") or "").strip()
                linha["descricao"] = f"{site['descricao']}\n\n{propria}".strip() if propria else site["descricao"]
            if not linha.get("link") and site["link"]:
                linha["link"] = site["link"]
        linhas.append(linha)
    return {**feed, "linhas": linhas}


def cobertura(feed: dict[str, Any] | None, dados: dict[str, Any] | None) -> dict[str, int] | None:
    if not feed or not dados:
        return None
    ligadas = [produto_da_linha(l, dados) for l in feed["linhas"]]
    return {
        "linhas": len(feed["linhas"]),
        "ligadas": sum(1 for s in ligadas if s),
        "com_descricao": sum(1 for s in ligadas if s and s["descricao"]),
        "com_link": sum(1 for l, s in zip(feed["linhas"], ligadas) if l.get("link") or (s and s["link"])),
    }
