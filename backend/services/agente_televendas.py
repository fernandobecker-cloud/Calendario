"""Configuracao da fila do televendas para o agente de IA (Omnichat).

O CRM escolhe no portal o modo (automatico, disponivel ou indisponivel), o time
do televendas na Omnichat e os limites da fila. Fica gravado numa tabela de uma
linha no BigQuery (portal_crm.agente_televendas) e a API do agente le por
/api/agente-ia/televendas/config a cada 30 s. A fila em si e contada na API do
agente, pelos webhooks da Omnichat (ver agente_api/fila.py).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from backend.services.agente_planilha import PlanilhaErroBQ, _DATASET, _PROJECT_ID, _cliente

_TABELA = "agente_televendas"
_TIMEOUT_S = 60
_CACHE_TTL_S = 300
MODOS = ("automatico", "disponivel", "indisponivel")

_SCHEMA = (
    bigquery.SchemaField("modo", "STRING"),
    bigquery.SchemaField("time_id", "STRING"),
    bigquery.SchemaField("time_nome", "STRING"),
    bigquery.SchemaField("limite_desliga", "INTEGER"),
    bigquery.SchemaField("limite_religa", "INTEGER"),
    bigquery.SchemaField("alterado_por", "STRING"),
    bigquery.SchemaField("alterado_em", "TIMESTAMP"),
)

_lock = threading.Lock()
_cache: dict[str, Any] = {"lido_em": 0.0, "dados": None}


class ConfigInvalida(ValueError):
    pass


def _tabela_id() -> str:
    if not _PROJECT_ID:
        raise PlanilhaErroBQ("Variavel BASE_VENDAS_BQ_PROJECT nao configurada")
    return f"{_PROJECT_ID}.{_DATASET}.{_TABELA}"


def validar(dados: dict[str, Any]) -> dict[str, Any]:
    modo = str(dados.get("modo") or "").strip().lower()
    if modo not in MODOS:
        raise ConfigInvalida("Modo inválido: use automatico, disponivel ou indisponivel.")
    time_id = str(dados.get("time_id") or "").strip() or None
    try:
        desliga = int(dados.get("limite_desliga") or 0)
        religa = int(dados.get("limite_religa") or 0)
    except (TypeError, ValueError) as exc:
        raise ConfigInvalida("Os limites precisam ser números inteiros.") from exc
    if modo == "automatico":
        if not time_id:
            raise ConfigInvalida("No modo automático, escolha o time do televendas.")
        if desliga < 1:
            raise ConfigInvalida("O limite para desligar precisa ser pelo menos 1 cliente na fila.")
        if not 0 <= religa < desliga:
            raise ConfigInvalida("O limite para religar precisa ser menor que o limite para desligar.")
    return {
        "modo": modo,
        "time_id": time_id,
        "time_nome": str(dados.get("time_nome") or "").strip() or None,
        "limite_desliga": desliga,
        "limite_religa": religa,
    }


def salvar(dados: dict[str, Any], usuario: str) -> dict[str, Any]:
    registro = {**validar(dados), "alterado_por": usuario,
                "alterado_em": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    config = bigquery.LoadJobConfig(schema=_SCHEMA, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
    try:
        _cliente().load_table_from_json([registro], _tabela_id(), job_config=config).result(timeout=_TIMEOUT_S)
    except PlanilhaErroBQ:
        raise
    except Exception as exc:
        raise PlanilhaErroBQ(f"Falha ao gravar a configuração do televendas no BigQuery: {exc}") from exc
    with _lock:
        _cache.update(dados=registro, lido_em=time.monotonic())
    return registro


def carregar() -> dict[str, Any] | None:
    with _lock:
        if _cache["lido_em"] and time.monotonic() - _cache["lido_em"] < _CACHE_TTL_S:
            return _cache["dados"]
        try:
            linhas = list(_cliente().list_rows(_tabela_id(), timeout=_TIMEOUT_S))
        except NotFound:
            linhas = []
        except PlanilhaErroBQ:
            raise
        except Exception as exc:
            if _cache["lido_em"]:
                return _cache["dados"]
            raise PlanilhaErroBQ(f"Falha ao ler a configuração do televendas no BigQuery: {exc}") from exc
        dados = None
        if linhas:
            dados = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in linhas[0].items()}
        _cache.update(dados=dados, lido_em=time.monotonic())
        return dados
