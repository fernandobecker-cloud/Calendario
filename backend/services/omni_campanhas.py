"""Fontes da apuração do WhatsApp Omnichat (NPI) gravadas pelo portal.

- portal_crm.omni_campanha_status: status das mensagens de campanha (enviada,
  entregue, lida, falha), vindos do webhook message-status da Omnichat pela API do
  agente. Substitui a exportação manual (apuracao_npi26.dados_omni) dali em diante.
- portal_crm.emarsys_telefones: ponte contato da Emarsys <-> celular, carregada
  pelo botão da aba Resultados NPI. Substitui a carga manual de
  apuracao_npi26.dados-emarsys.

As consultas da apuração (backend/routes/open_data.py) leem as tabelas antigas e
as novas juntas.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import tempfile
from datetime import datetime, timezone
from typing import Any

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from backend.services.agente_planilha import PlanilhaErroBQ, _DATASET, _PROJECT_ID, _cliente

log = logging.getLogger(__name__)

TABELA_STATUS = "omni_campanha_status"
TABELA_PONTE = "emarsys_telefones"
_TIMEOUT_S = 120

_SCHEMA_STATUS = [
    bigquery.SchemaField("trace_id", "STRING"),
    bigquery.SchemaField("momento", "TIMESTAMP"),
    bigquery.SchemaField("status", "STRING"),  # SENT / DELIVERED / READ / FAILED (como a Omnichat mandar)
    bigquery.SchemaField("telefone", "STRING"),
    bigquery.SchemaField("campanha_id", "STRING"),
    bigquery.SchemaField("campanha_nome", "STRING"),
    bigquery.SchemaField("template", "STRING"),
    bigquery.SchemaField("disparo_id", "STRING"),
    bigquery.SchemaField("bruto", "STRING"),  # evento completo (só nos primeiros e quando falta campo)
    bigquery.SchemaField("recebido_em", "TIMESTAMP"),
]
_SCHEMA_PONTE = [
    bigquery.SchemaField("user_id", "STRING"),
    bigquery.SchemaField("telefone", "STRING"),
    bigquery.SchemaField("carregado_em", "TIMESTAMP"),
    bigquery.SchemaField("carregado_por", "STRING"),
]
_estado = {"tabela_ok": False}


def tabela(nome: str) -> str:
    if not _PROJECT_ID:
        raise PlanilhaErroBQ("Variavel BASE_VENDAS_BQ_PROJECT nao configurada")
    return f"{_PROJECT_ID}.{_DATASET}.{nome}"


def _garantir_status() -> None:
    if _estado["tabela_ok"]:
        return
    t = bigquery.Table(tabela(TABELA_STATUS), schema=_SCHEMA_STATUS)
    t.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="momento")
    t.clustering_fields = ["template", "status"]
    _cliente().create_table(t, exists_ok=True, timeout=_TIMEOUT_S)
    _estado["tabela_ok"] = True


def garantir_tabelas() -> None:
    """As consultas da apuração leem as duas tabelas: precisam existir, mesmo vazias."""
    _garantir_status()
    t = bigquery.Table(tabela(TABELA_PONTE), schema=_SCHEMA_PONTE)
    _cliente().create_table(t, exists_ok=True, timeout=_TIMEOUT_S)


def receber_status(registros: list[dict[str, Any]]) -> dict[str, int]:
    agora = datetime.now(timezone.utc).isoformat()
    linhas = []
    for r in registros:
        if not isinstance(r, dict) or not r.get("trace_id"):
            continue
        linha = {c.name: (str(r[c.name]) if r.get(c.name) is not None else None) for c in _SCHEMA_STATUS}
        linha["recebido_em"] = agora
        linha["momento"] = linha["momento"] or agora
        linhas.append(linha)
    if not linhas:
        return {"recebidos": len(registros), "gravados": 0}
    try:
        _garantir_status()
        erros = []
        for i in range(0, len(linhas), 5000):
            parte = linhas[i:i + 5000]
            erros += _cliente().insert_rows_json(tabela(TABELA_STATUS), parte,
                                                 row_ids=[l["trace_id"] for l in parte], timeout=_TIMEOUT_S)
    except PlanilhaErroBQ:
        raise
    except Exception as exc:
        raise PlanilhaErroBQ(f"Falha ao gravar status de campanha no BigQuery: {exc}") from exc
    if erros:
        log.warning("omni_campanhas: BigQuery recusou %s linha(s): %s", len(erros), erros[:3])
    return {"recebidos": len(registros), "gravados": len(linhas) - len(erros)}


# --- Ponte Emarsys (contato <-> celular) -----------------------------------------

_APELIDOS_ID = ("user_id", "userid", "id", "contact_id", "contactid", "id do contato", "id do usuario",
                "id do usuário", "id_contato")
_APELIDOS_TEL = ("número do celular", "numero do celular", "celular", "mobile", "telefone celular",
                 "telefone", "phone", "mobile phone", "telefone_celular")


class PonteInvalida(ValueError):
    pass


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "").replace("﻿", "").strip().strip('"').lower())


def salvar_ponte(caminho: str, usuario: str) -> dict[str, Any]:
    """Lê o CSV exportado da Emarsys (id do contato + celular) e substitui a ponte."""
    with open(caminho, "rb") as fh:
        amostra = fh.read(65536)
    texto_amostra = amostra.decode("utf-8-sig", errors="replace")
    primeira = texto_amostra.splitlines()[0] if texto_amostra else ""
    delim = max((";", ",", "\t"), key=primeira.count)
    agora = datetime.now(timezone.utc).isoformat()
    total, com_tel = 0, 0
    with open(caminho, encoding="utf-8-sig", errors="replace", newline="") as entrada, \
            tempfile.NamedTemporaryFile("w+", suffix=".csv", newline="", encoding="utf-8") as saida:
        leitor = csv.reader(entrada, delimiter=delim)
        cabecalho = [_norm(c) for c in next(leitor, [])]
        col_id = next((cabecalho.index(a) for a in _APELIDOS_ID if a in cabecalho), None)
        col_tel = next((cabecalho.index(a) for a in _APELIDOS_TEL if a in cabecalho), None)
        if col_id is None or col_tel is None:
            raise PonteInvalida("Não achei as colunas do id do contato (ex.: user_id) e do celular "
                                f"(ex.: Número do celular). Colunas do arquivo: {', '.join(cabecalho) or '(vazio)'}")
        escritor = csv.writer(saida)
        for linha in leitor:
            if len(linha) <= max(col_id, col_tel):
                continue
            uid, tel = linha[col_id].strip(), linha[col_tel].strip()
            if not uid:
                continue
            total += 1
            if tel:
                com_tel += 1
                escritor.writerow([uid, tel, agora, usuario])
        if not com_tel:
            raise PonteInvalida("O arquivo não tem nenhum contato com celular preenchido.")
        saida.flush()
        saida.seek(0)
        job = bigquery.LoadJobConfig(schema=_SCHEMA_PONTE, source_format=bigquery.SourceFormat.CSV,
                                     write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
        try:
            with open(saida.name, "rb") as binario:
                _cliente().load_table_from_file(binario, tabela(TABELA_PONTE), job_config=job).result(
                    timeout=_TIMEOUT_S * 5)
        except PlanilhaErroBQ:
            raise
        except Exception as exc:
            raise PlanilhaErroBQ(f"Falha ao gravar a base da Emarsys no BigQuery: {exc}") from exc
    return {"contatos": total, "com_celular": com_tel, "carregado_em": agora}


def _consulta(sql: str) -> list[dict[str, Any]]:
    try:
        return [dict(r.items()) for r in _cliente().query(sql).result(timeout=60)]
    except NotFound:
        return []  # a tabela ainda não foi criada
    except Exception as exc:
        raise PlanilhaErroBQ(f"Falha ao ler as fontes da apuração no BigQuery: {exc}") from exc


def situacao() -> dict[str, Any]:
    """Para a aba Resultados NPI: o que já chegou de cada fonte."""
    ponte = _consulta(f"SELECT COUNT(*) AS linhas, MAX(carregado_em) AS carregado_em, ANY_VALUE(carregado_por) AS por "
                      f"FROM `{tabela(TABELA_PONTE)}`")
    status = _consulta(f"""
        SELECT DATE(momento, 'America/Sao_Paulo') AS dia, COUNT(*) AS avisos, COUNT(DISTINCT telefone) AS telefones,
               COUNTIF(COALESCE(template, campanha_nome) IS NULL) AS sem_template,
               STRING_AGG(DISTINCT COALESCE(template, campanha_nome), ' · ' LIMIT 8) AS templates
        FROM `{tabela(TABELA_STATUS)}`
        WHERE momento >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
        GROUP BY dia ORDER BY dia DESC""")
    p = ponte[0] if ponte and ponte[0].get("linhas") else None
    if p and p.get("carregado_em"):
        p["carregado_em"] = p["carregado_em"].isoformat()
    return {"ponte": p, "status_7d": [{**s, "dia": s["dia"].isoformat()} for s in status]}
