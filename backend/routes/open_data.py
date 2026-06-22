"""Open data routes for BigQuery-backed sources."""

from __future__ import annotations

import os
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import re
from typing import Any

from fastapi import APIRouter, Query
from fastapi import HTTPException

from backend.event_sources import run_bigquery_records

# ---------------------------------------------------------------------------
# CPF prefetch cache — evita re-executar a query Emarsys EU quando o usuário
# abre a apuração e logo em seguida clica em "Ver Regional".
# ---------------------------------------------------------------------------
_CPF_CACHE: dict[str, tuple[float, set[str]]] = {}
_CPF_CACHE_LOCK = threading.Lock()
_CPF_CACHE_TTL = 600  # segundos


def _cpf_cache_get(key: str) -> set[str] | None:
    with _CPF_CACHE_LOCK:
        entry = _CPF_CACHE.get(key)
    if entry and (time.monotonic() - entry[0]) < _CPF_CACHE_TTL:
        return entry[1]
    return None


def _cpf_cache_set(key: str, cpfs: set[str]) -> None:
    with _CPF_CACHE_LOCK:
        _CPF_CACHE[key] = (time.monotonic(), cpfs)


def _prefetch_cpfs(cache_key: str, sql: str, project_id: str, location: str | None) -> None:
    """Executa a query de CPFs em background e armazena no cache."""
    try:
        records = run_bigquery_records(sql, project_id, location=location, timeout=55)
        cpfs = {_normalize_match_key(str(r.get("cpf") or "")) for r in records if r.get("cpf")}
        cpfs.discard("")
        _cpf_cache_set(cache_key, cpfs)
    except Exception:
        pass  # falha silenciosa — o endpoint regional fará a query diretamente


def _prefetch_order_ids(cache_key: str, sql: str, project_id: str, location: str | None) -> None:
    """Executa a query de order_ids em background e armazena no cache."""
    try:
        records = run_bigquery_records(sql, project_id, location=location, timeout=30)
        order_ids = {str(r.get("order_id") or "") for r in records if r.get("order_id")}
        order_ids.discard("")
        _cpf_cache_set(cache_key, order_ids)  # type: ignore[arg-type]
    except Exception:
        pass  # falha silenciosa — o endpoint regional fará a query diretamente


EMARSYS_OPEN_DATA_PROJECT_ID = os.getenv("EMARSYS_OPEN_DATA_PROJECT_ID", "sap-od-herval").strip()
EMARSYS_OPEN_DATA_DATASET = os.getenv("EMARSYS_OPEN_DATA_DATASET", "emarsys_herval_1091660394").strip()
EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE = os.getenv(
    "EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE",
    "email_campaigns_1091660394",
).strip()
EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE = os.getenv(
    "EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE",
    "email_opens_1091660394",
).strip()
EMARSYS_OPEN_DATA_EMAIL_SENDS_TABLE = os.getenv(
    "EMARSYS_OPEN_DATA_EMAIL_SENDS_TABLE",
    "email_sends_1091660394",
).strip()
EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE = os.getenv(
    "EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE",
    "si_purchases_1091660394",
).strip()
EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE = os.getenv(
    "EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE",
    "si_contacts_1091660394",
).strip()
EMARSYS_OPEN_DATA_LOCATION = os.getenv("EMARSYS_OPEN_DATA_LOCATION", "EU").strip()
EMARSYS_OPEN_DATA_QUERY = os.getenv("EMARSYS_OPEN_DATA_QUERY", "").strip()
EMARSYS_OPEN_DATA_LOOKBACK_DAYS = max(
    1,
    int(os.getenv("EMARSYS_OPEN_DATA_LOOKBACK_DAYS", "180").strip() or "180"),
)
EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE = os.getenv(
    "EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE",
    "revenue_attribution_1091660394",
).strip()
EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE = os.getenv(
    "EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE",
    "sms_campaigns_1091660394",
).strip()
EMARSYS_OPEN_DATA_SMS_SENDS_TABLE = os.getenv(
    "EMARSYS_OPEN_DATA_SMS_SENDS_TABLE",
    "sms_sends_1091660394",
).strip()
EMARSYS_OPEN_DATA_SMS_SEND_REPORTS_TABLE = os.getenv(
    "EMARSYS_OPEN_DATA_SMS_SEND_REPORTS_TABLE",
    "sms_send_reports_1091660394",
).strip()
EMARSYS_OPEN_DATA_SESSION_CATEGORIES_TABLE = os.getenv(
    "EMARSYS_OPEN_DATA_SESSION_CATEGORIES_TABLE",
    "session_categories_1091660394",
).strip()
EMARSYS_OPEN_DATA_CLIENT_UPDATES_TABLE = os.getenv(
    "EMARSYS_OPEN_DATA_CLIENT_UPDATES_TABLE",
    "client_updates_1091660394",
).strip()
EMARSYS_OPEN_DATA_CLIENT_SNAPSHOTS_TABLE = os.getenv(
    "EMARSYS_OPEN_DATA_CLIENT_SNAPSHOTS_TABLE",
    "client_snapshots_1091660394",
).strip()

router = APIRouter(prefix="/api/open-data", tags=["open-data"])
TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")

# Fuso horário do Emarsys/iPlace. event_time é UTC no BigQuery;
# usar este TZ garante que as datas de corte de cada dia coincidam com o painel Emarsys.
EMARSYS_TZ = "America/Sao_Paulo"
BASE_VENDAS_BQ_PROJECT = os.getenv("BASE_VENDAS_BQ_PROJECT", "").strip()
BASE_VENDAS_BQ_DATASET = os.getenv("BASE_VENDAS_BQ_DATASET", "dados_vendas").strip()
BASE_VENDAS_BQ_TABLE = os.getenv("BASE_VENDAS_BQ_TABLE", "vw_performance_vendas").strip()
BASE_VENDAS_BQ_LOCATION = os.getenv("BASE_VENDAS_BQ_LOCATION", "southamerica-east1").strip()
# Campos da view vw_performance_vendas (já tipados e sanitizados)
# data_completa DATE | canal STRING | codigo_filial INTEGER | documento_cliente STRING | valor_faturamento_liquido FLOAT

# Tabela vendas_iplace — cruzamento por Numero_Pedido (order_id)
# Campos: Data_Completa STRING | Cod_Filial STRING | Canal STRING | Negocio STRING |
#         Unidade_de_Negocio STRING | Numero_Pedido STRING | Status_Pedidos STRING |
#         Vlr_Pedidos_Captados STRING
VENDAS_BQ_DATASET = os.getenv("VENDAS_BQ_DATASET", "vendas_order").strip()
VENDAS_BQ_TABLE = os.getenv("VENDAS_BQ_TABLE", "vendas_iplace").strip()


def _get_canal_order_ids(canal_filter: str, start: str | None, end: str | None) -> list[str] | None:
    """Busca order_ids na vendas_iplace para o canal dado; usa cache de 10 min."""
    if not canal_filter or not BASE_VENDAS_BQ_PROJECT:
        return None
    safe_canal = canal_filter.replace("'", "''")
    cache_key = f"canal_orders:{safe_canal}:{start}:{end}"
    cached = _cpf_cache_get(cache_key)
    if cached is not None:
        return list(cached)
    date_clause = f"AND Data_Completa BETWEEN '{start}' AND '{end}'" if start and end else ""
    sql = f"""
SELECT DISTINCT CAST(Numero_Pedido AS STRING) AS order_id
FROM `{BASE_VENDAS_BQ_PROJECT}.{VENDAS_BQ_DATASET}.{VENDAS_BQ_TABLE}`
WHERE UPPER(TRIM(Canal)) = '{safe_canal}'
{date_clause}
"""
    records = run_bigquery_records(sql, BASE_VENDAS_BQ_PROJECT, location=None)
    order_ids: set[str] = {str(r["order_id"]) for r in records if r.get("order_id")}
    _cpf_cache_set(cache_key, order_ids)  # type: ignore[arg-type]
    return list(order_ids)


def _make_order_id_filter(canal_order_ids: list | None, id_expr: str = "CAST(r.order_id AS STRING)") -> str:
    """Retorna cláusula SQL AND ... IN UNNEST([...]) ou vazia."""
    if canal_order_ids is None:
        return ""
    if not canal_order_ids:
        return "AND FALSE"
    ids_literal = ", ".join(f"'{str(oid).replace(chr(39), '')}'" for oid in canal_order_ids)
    return f"AND {id_expr} IN UNNEST([{ids_literal}])"


def _quote_identifier(value: str) -> str:
    safe = value.strip().replace("`", "")
    if not safe:
        raise ValueError("Identificador BigQuery vazio")
    return safe


def _validate_table_name(value: str) -> str:
    safe = _quote_identifier(value)
    if not TABLE_NAME_PATTERN.fullmatch(safe):
        raise ValueError("Nome de tabela invalido")
    return safe


def _normalize_open_data_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _records_to_response_items(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: _normalize_open_data_value(value) for key, value in record.items()}
        for record in records
    ]


def _normalize_match_key(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    normalized = re.sub(r"[^0-9A-Za-z]+", "", text).lower()
    if normalized.isdigit() and len(normalized) < 11:
        return normalized.zfill(11)
    return normalized


def _find_column(columns: list[str], expected: str) -> str | None:
    expected_key = _normalize_match_key(expected)
    for column in columns:
        if _normalize_match_key(column) == expected_key:
            return column
    return None



def _sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _validate_optional_iso_date(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    return date.fromisoformat(raw).isoformat()


def _build_partitiontime_filter(start_date: str | None = None, end_date: str | None = None) -> str:
    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)

    if normalized_start and normalized_end:
        return f"DATE(partitiontime) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
    if normalized_start:
        return f"DATE(partitiontime) >= DATE('{normalized_start}')"
    if normalized_end:
        return f"DATE(partitiontime) <= DATE('{normalized_end}')"
    return f"partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"


def _build_columns_metadata_sql(table_name: str | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    table_filter = ""
    if table_name:
      safe_table = _validate_table_name(table_name)
      table_filter = f"AND table_name = '{safe_table}'"

    return f"""
SELECT
  table_name,
  column_name,
  data_type
FROM `{project_id}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
WHERE 1 = 1
  {table_filter}
ORDER BY table_name, ordinal_position
""".strip()


def _build_tables_sql() -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    return f"""
SELECT
  table_name,
  table_type
FROM `{project_id}.{dataset}.INFORMATION_SCHEMA.TABLES`
ORDER BY table_name
""".strip()


def _get_table_columns(table_name: str) -> list[dict[str, Any]]:
    sql = _build_columns_metadata_sql(table_name)
    return run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)


def _build_table_preview_sql(
    table_name: str,
    *,
    limit: int,
    start_date: str | None = None,
    end_date: str | None = None,
    columns: list[dict[str, Any]] | None = None,
) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    safe_table = _validate_table_name(table_name)
    table_columns = columns or _get_table_columns(safe_table)
    column_names = [_quote_identifier(str(item.get("column_name") or "")) for item in table_columns if item.get("column_name")]
    if not column_names:
        raise ValueError("Nao foi possivel identificar colunas da tabela")

    selected_columns = ",\n  ".join(f"`{column_name}`" for column_name in column_names)
    raw_column_names = {str(item.get("column_name") or "").lower() for item in table_columns if item.get("column_name")}
    partitiontime_filter = ""
    if "partitiontime" in raw_column_names:
        partitiontime_filter = f"\nWHERE {_build_partitiontime_filter(start_date, end_date)}"

    return f"""
SELECT
  {selected_columns}
FROM `{project_id}.{dataset}.{safe_table}`{partitiontime_filter}
LIMIT {limit}
""".strip()


def _build_email_campaigns_sql(limit: int, start_date: str | None = None, end_date: str | None = None) -> str:
    if EMARSYS_OPEN_DATA_QUERY:
        return EMARSYS_OPEN_DATA_QUERY

    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    partitiontime_filter = _build_partitiontime_filter(start_date, end_date)

    return f"""
WITH ranked AS (
  SELECT
    id,
    name,
    version_name,
    language,
    category_id,
    parent_campaign_id,
    type,
    sub_type,
    program_id,
    customer_id,
    partitiontime,
    event_time,
    loaded_at,
    ROW_NUMBER() OVER (
      PARTITION BY id, DATE(partitiontime)
      ORDER BY event_time DESC, loaded_at DESC
    ) AS rn
  FROM `{project_id}.{dataset}.{table}`
  WHERE {partitiontime_filter}
)
SELECT
  CAST(id AS STRING) AS campaign_id,
  CAST(COALESCE(program_id, 0) AS STRING) AS program_id,
  DATE(partitiontime) AS data,
  name AS campanha,
  'Email' AS canal,
  CAST(type AS STRING) AS status,
  CAST(sub_type AS STRING) AS direcionamento,
  CAST(category_id AS STRING) AS produto,
  CONCAT(
    'language=', COALESCE(language, ''),
    ' | version_name=', COALESCE(version_name, ''),
    ' | program_id=', CAST(COALESCE(program_id, 0) AS STRING),
    ' | parent_campaign_id=', CAST(COALESCE(parent_campaign_id, 0) AS STRING)
  ) AS observacao
FROM ranked
WHERE rn = 1
  AND name IS NOT NULL
  AND TRIM(name) != ''
ORDER BY data DESC, campanha
LIMIT {limit}
""".strip()


def _build_email_open_rates_sql(limit: int, start_date: str | None = None, end_date: str | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    opens_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE)
    sends_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_SENDS_TABLE)
    partitiontime_filter = _build_partitiontime_filter(start_date, end_date)

    return f"""
WITH campaigns AS (
  SELECT
    CAST(id AS STRING) AS campaign_id,
    CAST(COALESCE(program_id, 0) AS STRING) AS program_id,
    DATE(partitiontime) AS data,
    name AS campanha,
    CAST(type AS STRING) AS status,
    CAST(sub_type AS STRING) AS direcionamento,
    CAST(category_id AS STRING) AS produto,
    CONCAT(
      'language=', COALESCE(language, ''),
      ' | version_name=', COALESCE(version_name, ''),
      ' | program_id=', CAST(COALESCE(program_id, 0) AS STRING),
      ' | parent_campaign_id=', CAST(COALESCE(parent_campaign_id, 0) AS STRING)
    ) AS observacao,
    ROW_NUMBER() OVER (
      PARTITION BY id, DATE(partitiontime)
      ORDER BY event_time DESC, loaded_at DESC
    ) AS rn
  FROM `{project_id}.{dataset}.{campaigns_table}`
  WHERE {partitiontime_filter}
),
sends AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    DATE(partitiontime) AS data,
    COUNT(DISTINCT message_id) AS enviados
  FROM `{project_id}.{dataset}.{sends_table}`
  WHERE {partitiontime_filter}
    AND campaign_id IS NOT NULL
    AND message_id IS NOT NULL
  GROUP BY 1, 2
),
opens AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    DATE(partitiontime) AS data,
    COUNT(DISTINCT message_id) AS aberturas_unicas
  FROM `{project_id}.{dataset}.{opens_table}`
  WHERE {partitiontime_filter}
    AND campaign_id IS NOT NULL
    AND message_id IS NOT NULL
  GROUP BY 1, 2
)
SELECT
  c.campaign_id,
  c.program_id,
  c.data,
  c.campanha,
  'Email' AS canal,
  c.status,
  c.direcionamento,
  c.produto,
  c.observacao,
  COALESCE(s.enviados, 0) AS enviados,
  COALESCE(o.aberturas_unicas, 0) AS aberturas_unicas,
  ROUND(
    SAFE_DIVIDE(COALESCE(o.aberturas_unicas, 0), NULLIF(COALESCE(s.enviados, 0), 0)) * 100,
    2
  ) AS taxa_abertura_percentual
FROM campaigns c
LEFT JOIN sends s ON s.campaign_id = c.campaign_id AND s.data = c.data
LEFT JOIN opens o ON o.campaign_id = c.campaign_id AND o.data = c.data
WHERE c.rn = 1
  AND c.campanha IS NOT NULL
  AND TRIM(c.campanha) != ''
ORDER BY c.data DESC, c.campanha
LIMIT {limit}
""".strip()


def _build_email_program_open_rates_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    opens_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE)
    sends_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_SENDS_TABLE)
    # Campaigns use the full lookback so that automation programs created
    # before the selected period are still resolved to their program_id.
    campaigns_filter = f"partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"
    # Sends and opens are filtered by the user-selected date range.
    activity_filter = _build_partitiontime_filter(start_date, end_date)

    return f"""
WITH campaign_programs AS (
  -- One row per (campaign_id, program_id) across the full lookback window.
  -- Automation programs are created once and run indefinitely, so we must
  -- not restrict this CTE to the user-selected date range.
  SELECT
    CAST(id AS STRING) AS campaign_id,
    CAST(COALESCE(program_id, 0) AS STRING) AS program_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC, loaded_at DESC LIMIT 1)[SAFE_OFFSET(0)] AS campanha,
    ARRAY_AGG(CAST(type AS STRING) IGNORE NULLS ORDER BY event_time DESC, loaded_at DESC LIMIT 1)[SAFE_OFFSET(0)] AS status,
    ARRAY_AGG(CAST(sub_type AS STRING) IGNORE NULLS ORDER BY event_time DESC, loaded_at DESC LIMIT 1)[SAFE_OFFSET(0)] AS direcionamento,
    ARRAY_AGG(CAST(category_id AS STRING) IGNORE NULLS ORDER BY event_time DESC, loaded_at DESC LIMIT 1)[SAFE_OFFSET(0)] AS produto,
    ARRAY_AGG(
      CONCAT(
        'language=', COALESCE(language, ''),
        ' | version_name=', COALESCE(version_name, ''),
        ' | program_id=', CAST(COALESCE(program_id, 0) AS STRING),
        ' | parent_campaign_id=', CAST(COALESCE(parent_campaign_id, 0) AS STRING)
      )
      IGNORE NULLS
      ORDER BY event_time DESC, loaded_at DESC
      LIMIT 1
    )[SAFE_OFFSET(0)] AS observacao
  FROM `{project_id}.{dataset}.{campaigns_table}`
  WHERE {campaigns_filter}
    AND program_id IS NOT NULL
  GROUP BY 1, 2
),
program_info AS (
  -- Pick one representative name per program.
  SELECT
    program_id,
    ARRAY_AGG(campanha IGNORE NULLS ORDER BY campaign_id DESC LIMIT 1)[SAFE_OFFSET(0)] AS campanha,
    ARRAY_AGG(status IGNORE NULLS ORDER BY campaign_id DESC LIMIT 1)[SAFE_OFFSET(0)] AS status,
    ARRAY_AGG(direcionamento IGNORE NULLS ORDER BY campaign_id DESC LIMIT 1)[SAFE_OFFSET(0)] AS direcionamento,
    ARRAY_AGG(produto IGNORE NULLS ORDER BY campaign_id DESC LIMIT 1)[SAFE_OFFSET(0)] AS produto,
    ARRAY_AGG(observacao IGNORE NULLS ORDER BY campaign_id DESC LIMIT 1)[SAFE_OFFSET(0)] AS observacao
  FROM campaign_programs
  GROUP BY 1
),
campaign_sends AS (
  -- COUNT(DISTINCT message_id) per campaign individually.
  -- message_id is only unique within a campaign, not globally, so we must
  -- count per campaign first and then sum — not COUNT(DISTINCT) across all.
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    COUNT(DISTINCT message_id) AS enviados
  FROM `{project_id}.{dataset}.{sends_table}`
  WHERE {activity_filter}
    AND campaign_id IS NOT NULL
    AND message_id IS NOT NULL
  GROUP BY 1
),
campaign_opens AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    COUNT(DISTINCT message_id) AS aberturas_unicas
  FROM `{project_id}.{dataset}.{opens_table}`
  WHERE {activity_filter}
    AND campaign_id IS NOT NULL
    AND message_id IS NOT NULL
  GROUP BY 1
),
program_sends AS (
  -- Sum per-campaign counts across all campaigns in the program.
  SELECT
    cp.program_id,
    SUM(cs.enviados) AS enviados
  FROM campaign_sends cs
  JOIN campaign_programs cp ON cs.campaign_id = cp.campaign_id
  GROUP BY 1
),
program_opens AS (
  SELECT
    cp.program_id,
    SUM(co.aberturas_unicas) AS aberturas_unicas
  FROM campaign_opens co
  JOIN campaign_programs cp ON co.campaign_id = cp.campaign_id
  GROUP BY 1
)
SELECT
  pi.program_id,
  pi.campanha,
  'Email' AS canal,
  pi.status,
  pi.direcionamento,
  pi.produto,
  pi.observacao,
  COALESCE(s.enviados, 0) AS enviados,
  COALESCE(o.aberturas_unicas, 0) AS aberturas_unicas,
  ROUND(
    SAFE_DIVIDE(COALESCE(o.aberturas_unicas, 0), NULLIF(COALESCE(s.enviados, 0), 0)) * 100,
    2
  ) AS taxa_abertura_percentual
FROM program_info pi
LEFT JOIN program_sends s ON s.program_id = pi.program_id
LEFT JOIN program_opens o ON o.program_id = pi.program_id
WHERE pi.campanha IS NOT NULL
  AND TRIM(pi.campanha) != ''
  AND (COALESCE(s.enviados, 0) > 0 OR COALESCE(o.aberturas_unicas, 0) > 0)
ORDER BY pi.campanha
""".strip()


@router.get("/emarsys/email-campaigns")
def emarsys_email_campaigns(
    limit: int = Query(default=50, ge=1, le=200),
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_email_campaigns_sql(limit, start, end)
        records = run_bigquery_records(
            sql,
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
        )
        items = _records_to_response_items(records)
        return {
            "items": items,
            "total": len(items),
            "project_id": EMARSYS_OPEN_DATA_PROJECT_ID,
            "dataset": EMARSYS_OPEN_DATA_DATASET,
            "table": EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE,
            "location": EMARSYS_OPEN_DATA_LOCATION or None,
            "source": "bigquery_emarsys_open_data",
            "lookback_days": EMARSYS_OPEN_DATA_LOOKBACK_DAYS,
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao preparar resposta Open Data: {exc}") from exc


@router.get("/emarsys/email-open-rates")
def emarsys_email_open_rates(
    limit: int = Query(default=50, ge=1, le=200),
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_email_open_rates_sql(limit, start, end)
        records = run_bigquery_records(
            sql,
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
        )
        items = _records_to_response_items(records)
        return {
            "items": items,
            "total": len(items),
            "project_id": EMARSYS_OPEN_DATA_PROJECT_ID,
            "dataset": EMARSYS_OPEN_DATA_DATASET,
            "campaigns_table": EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE,
            "opens_table": EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE,
            "sends_table": EMARSYS_OPEN_DATA_EMAIL_SENDS_TABLE,
            "location": EMARSYS_OPEN_DATA_LOCATION or None,
            "source": "bigquery_emarsys_open_data",
            "lookback_days": EMARSYS_OPEN_DATA_LOOKBACK_DAYS,
            "metric_definition": "aberturas_unicas / enviados * 100",
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao preparar taxa de abertura Open Data: {exc}") from exc


@router.get("/emarsys/email-program-open-rates")
def emarsys_email_program_open_rates(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_email_program_open_rates_sql(start, end)
        records = run_bigquery_records(
            sql,
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
        )
        items = _records_to_response_items(records)
        return {
            "items": items,
            "total": len(items),
            "project_id": EMARSYS_OPEN_DATA_PROJECT_ID,
            "dataset": EMARSYS_OPEN_DATA_DATASET,
            "campaigns_table": EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE,
            "opens_table": EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE,
            "sends_table": EMARSYS_OPEN_DATA_EMAIL_SENDS_TABLE,
            "location": EMARSYS_OPEN_DATA_LOCATION or None,
            "source": "bigquery_emarsys_open_data_program_level",
            "lookback_days": EMARSYS_OPEN_DATA_LOOKBACK_DAYS,
            "metric_definition": "aberturas_unicas / enviados * 100",
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao preparar taxa de abertura por programa Open Data: {exc}") from exc


@router.get("/emarsys/health")
def emarsys_open_data_health() -> dict[str, Any]:
    try:
        sql = "SELECT 1 AS ok"
        records = run_bigquery_records(
            sql,
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
        )
        rows = _records_to_response_items(records)
        return {
            "status": "connected",
            "rows": rows,
            "project_id": EMARSYS_OPEN_DATA_PROJECT_ID,
            "location": EMARSYS_OPEN_DATA_LOCATION or None,
            "source": "bigquery_emarsys_open_data",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao preparar health Open Data: {exc}") from exc


@router.get("/emarsys/debug-program-sends")
def emarsys_debug_program_sends(
    program_id: str = Query(...),
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    """Diagnostic: shows campaign_ids matched for a program and their send counts."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    sends_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_SENDS_TABLE)
    campaigns_filter = f"partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"
    activity_filter = _build_partitiontime_filter(start, end)
    safe_program_id = str(program_id).strip()

    sql = f"""
WITH campaign_programs AS (
  SELECT DISTINCT CAST(id AS STRING) AS campaign_id
  FROM `{project_id}.{dataset}.{campaigns_table}`
  WHERE {campaigns_filter}
    AND CAST(COALESCE(program_id, 0) AS STRING) = '{safe_program_id}'
),
sends_by_campaign AS (
  SELECT
    CAST(s.campaign_id AS STRING) AS campaign_id,
    DATE(s.partitiontime) AS data,
    COUNT(DISTINCT s.message_id) AS enviados
  FROM `{project_id}.{dataset}.{sends_table}` s
  JOIN campaign_programs cp ON CAST(s.campaign_id AS STRING) = cp.campaign_id
  WHERE {activity_filter}
    AND s.campaign_id IS NOT NULL
    AND s.message_id IS NOT NULL
  GROUP BY 1, 2
)
SELECT * FROM sends_by_campaign
ORDER BY data DESC, campaign_id
LIMIT 100
""".strip()

    try:
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        items = _records_to_response_items(records)
        total_sends = sum(int(r.get("enviados") or 0) for r in items)
        return {"program_id": safe_program_id, "start": start, "end": end, "rows": items, "total_campaigns": len({r["campaign_id"] for r in items}), "total_sends": total_sends}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha no debug: {exc}") from exc


def _build_automation_revenue_by_program_sql(
    program_ids: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """
    Receita atribuida por programa usando a tabela revenue_attribution do Emarsys.
    Usa o mesmo modelo de atribuicao nativo do Emarsys (janela por canal),
    garantindo consistencia com os valores exibidos nos relatorios da plataforma.
    """
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)

    safe_program_ids = [str(pid).strip() for pid in program_ids if str(pid).strip()]
    if not safe_program_ids:
        raise ValueError("Informe ao menos um program_id")

    program_id_values = ", ".join(f"'{pid}'" for pid in safe_program_ids)
    campaigns_lookback = f"partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"
    event_time_filter, partition_filter = _build_attribution_date_filters(start_date, end_date, "r")

    return f"""
WITH program_campaigns AS (
  -- Campaign IDs que pertencem aos programas solicitados
  SELECT DISTINCT
    CAST(id AS STRING) AS campaign_id,
    CAST(COALESCE(program_id, 0) AS STRING) AS program_id
  FROM `{project_id}.{dataset}.{campaigns_table}`
  WHERE {campaigns_lookback}
    AND program_id IS NOT NULL
    AND CAST(COALESCE(program_id, 0) AS STRING) IN ({program_id_values})
),
attributed AS (
  -- Receita atribuida pelo Emarsys para cada pedido x campanha de automacao
  SELECT
    pc.program_id,
    r.order_id,
    SUM(t.attributed_amount) AS receita
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  JOIN program_campaigns pc ON CAST(t.campaign_id AS STRING) = pc.campaign_id
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND {event_time_filter}
    AND {partition_filter}
  GROUP BY pc.program_id, r.order_id
)
SELECT
  program_id,
  ROUND(SUM(receita), 2) AS receita
FROM attributed
GROUP BY program_id
ORDER BY program_id
""".strip()


@router.get("/emarsys/automation-program-revenue")
def emarsys_automation_program_revenue(
    program_id: list[str] = Query(...),
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_automation_revenue_by_program_sql(program_id, start, end)
        records = run_bigquery_records(
            sql,
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
        )
        items = _records_to_response_items(records)
        return {
            "items": items,
            "total": len(items),
            "program_ids": program_id,
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
            "source": "bigquery_emarsys_open_data_si_purchases",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao calcular receita por programa: {exc}") from exc


def _build_monthly_revenue_sql(
    start_date: str | None = None,
    end_date: str | None = None,
    canal_order_ids: list | None = None,
) -> str:
    """
    Receita atribuída usando a tabela revenue_attribution do Emarsys Open Data.
    Essa view já aplica a janela de atribuição nativa do Emarsys por canal
    (email abertura, SMS envio, WhatsApp abertura). Pedidos com múltiplos
    treatments são deduplicados por order_id para não duplicar receita.
    """
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)

    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)

    # event_time = data do pedido (UTC); partitiontime = data de carga (até ~7 dias de delay).
    # Filtramos por event_time convertido para BRT (America/Sao_Paulo) para coincidir
    # com o fuso que o Emarsys usa na interface — evita desvio de ±3h nas bordas do mês.
    tz = EMARSYS_TZ
    if normalized_start and normalized_end:
        event_time_filter = f"DATE(r.event_time, '{tz}') BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        partition_filter = f"DATE(r.partitiontime) BETWEEN DATE('{normalized_start}') AND CURRENT_DATE()"
    elif normalized_start:
        event_time_filter = f"DATE(r.event_time, '{tz}') >= DATE('{normalized_start}')"
        partition_filter = f"DATE(r.partitiontime) >= DATE('{normalized_start}')"
    elif normalized_end:
        event_time_filter = f"DATE(r.event_time, '{tz}') <= DATE('{normalized_end}')"
        partition_filter = f"DATE(r.partitiontime) <= CURRENT_DATE()"
    else:
        event_time_filter = f"DATE(r.event_time, '{tz}') >= DATE_SUB(CURRENT_DATE('{tz}'), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"
        partition_filter = f"r.partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS + 7} DAY)"

    return f"""
WITH per_order AS (
  -- Deduplica por order_id: para cada pedido, soma attributed_amount de todos os
  -- treatments dentro da mesma linha e usa MAX para lidar com linhas duplicadas
  -- de um mesmo pedido (partições reprocessadas).
  SELECT
    r.order_id,
    MAX(r.contact_id) AS contact_id,
    FORMAT_DATE('%Y-%m', DATE(MIN(r.event_time), '{tz}')) AS mes,
    MAX(COALESCE(
      (SELECT ROUND(SUM(t.attributed_amount), 2)
       FROM UNNEST(r.treatments) AS t
       WHERE t.attributed_amount > 0),
      0
    )) AS order_attributed
  FROM `{project_id}.{dataset}.{revenue_table}` r
  WHERE r.event_time IS NOT NULL
    AND {event_time_filter}
    AND {partition_filter}
    {_make_order_id_filter(canal_order_ids, "CAST(r.order_id AS STRING)")}
  GROUP BY r.order_id
)
SELECT
  mes,
  ROUND(SUM(order_attributed), 2) AS receita_atribuida,
  COUNT(DISTINCT order_id) AS pedidos_atribuidos,
  COUNT(DISTINCT contact_id) AS compradores_unicos
FROM per_order
WHERE order_attributed > 0
GROUP BY mes
ORDER BY mes
""".strip()


def _build_monthly_revenue_by_channel_sql(
    start_date: str | None = None,
    end_date: str | None = None,
    canal_order_ids: list | None = None,
) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)

    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)

    tz = EMARSYS_TZ
    if normalized_start and normalized_end:
        event_time_filter = f"DATE(r.event_time, '{tz}') BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        partition_filter = f"DATE(r.partitiontime) BETWEEN DATE('{normalized_start}') AND CURRENT_DATE()"
    elif normalized_start:
        event_time_filter = f"DATE(r.event_time, '{tz}') >= DATE('{normalized_start}')"
        partition_filter = f"DATE(r.partitiontime) >= DATE('{normalized_start}')"
    elif normalized_end:
        event_time_filter = f"DATE(r.event_time, '{tz}') <= DATE('{normalized_end}')"
        partition_filter = f"DATE(r.partitiontime) <= CURRENT_DATE()"
    else:
        event_time_filter = f"DATE(r.event_time, '{tz}') >= DATE_SUB(CURRENT_DATE('{tz}'), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"
        partition_filter = f"r.partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS + 7} DAY)"

    return f"""
WITH per_order_channel AS (
  -- Agrupa por (order_id, canal) para evitar dupla contagem em pedidos que
  -- tiveram tratamentos de múltiplos canais com attributed_amount > 0.
  SELECT
    r.order_id,
    MAX(r.contact_id) AS contact_id,
    LOWER(t.channel) AS canal,
    ROUND(SUM(t.attributed_amount), 2) AS order_channel_attributed
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND r.event_time IS NOT NULL
    AND t.attributed_amount > 0
    AND {event_time_filter}
    AND {partition_filter}
    {_make_order_id_filter(canal_order_ids, "CAST(r.order_id AS STRING)")}
  GROUP BY r.order_id, canal
)
SELECT
  canal,
  ROUND(SUM(order_channel_attributed), 2) AS receita_atribuida,
  COUNT(DISTINCT order_id) AS pedidos_atribuidos,
  COUNT(DISTINCT contact_id) AS compradores_unicos
FROM per_order_channel
GROUP BY canal
ORDER BY canal
""".strip()


@router.get("/emarsys/monthly-revenue")
def emarsys_monthly_revenue(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    canal: str = Query(default=""),
) -> dict[str, Any]:
    canal_order_ids = _get_canal_order_ids(canal.upper().strip() if canal else "", start, end)
    try:
        sql_total = _build_monthly_revenue_sql(start, end, canal_order_ids)
        sql_canal = _build_monthly_revenue_by_channel_sql(start, end, canal_order_ids)
        records_total = run_bigquery_records(
            sql_total,
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
        )
        records_canal = run_bigquery_records(
            sql_canal,
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
        )
        items = _records_to_response_items(records_total)
        by_channel = _records_to_response_items(records_canal)
        total_receita = sum(float(r.get("receita_atribuida") or 0) for r in items)
        return {
            "items": items,
            "by_channel": by_channel,
            "total_meses": len(items),
            "total_receita_atribuida": round(total_receita, 2),
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
            "metric_definition": (
                "SUM(itens do pedido) de pedidos com atribuicao nativa Emarsys "
                "(email abertura / SMS envio / WhatsApp abertura), agrupado por mes do pedido"
            ),
            "source": "bigquery_emarsys_open_data_revenue_attribution",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao calcular receita mensal Emarsys: {exc}") from exc


@router.get("/emarsys/tables")
def emarsys_open_data_tables() -> dict[str, Any]:
    try:
        records = run_bigquery_records(
            _build_tables_sql(),
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
        )
        items = _records_to_response_items(records)
        return {
            "items": items,
            "total": len(items),
            "project_id": EMARSYS_OPEN_DATA_PROJECT_ID,
            "dataset": EMARSYS_OPEN_DATA_DATASET,
            "location": EMARSYS_OPEN_DATA_LOCATION or None,
            "source": "bigquery_emarsys_open_data_information_schema",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao listar tabelas Open Data: {exc}") from exc


@router.get("/emarsys/table-preview")
def emarsys_open_data_table_preview(
    table: str = Query(..., min_length=1),
    limit: int = Query(default=100, ge=1, le=500),
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        safe_table = _validate_table_name(table)
        columns = _get_table_columns(safe_table)
        sql = _build_table_preview_sql(safe_table, limit=limit, start_date=start, end_date=end, columns=columns)
        records = run_bigquery_records(
            sql,
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
        )
        items = _records_to_response_items(records)
        normalized_columns = [
            {
                "name": column.get("column_name"),
                "type": column.get("data_type"),
            }
            for column in columns
        ]
        return {
            "items": items,
            "columns": normalized_columns,
            "total": len(items),
            "table": safe_table,
            "dataset": EMARSYS_OPEN_DATA_DATASET,
            "project_id": EMARSYS_OPEN_DATA_PROJECT_ID,
            "location": EMARSYS_OPEN_DATA_LOCATION or None,
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
            "limit": limit,
            "partition_filter_applied": any(str(column.get("column_name") or "").lower() == "partitiontime" for column in columns),
            "source": "bigquery_emarsys_open_data_table_preview",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao consultar tabela Open Data: {exc}") from exc


def _build_sales_unit_contacts_sql(document_keys: list[str], start_date: str, end_date: str) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    contacts_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE)
    purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    key_values = ", ".join(_sql_string_literal(value) for value in document_keys)

    # Use UNNEST + INNER JOIN so BigQuery can broadcast the small key list and
    # avoid materialising the full si_contacts scan before filtering.
    return f"""
WITH key_list AS (
  SELECT DISTINCT key
  FROM UNNEST([{key_values}]) AS key
  WHERE key IS NOT NULL AND key != ''
),
matched_contacts AS (
  SELECT
    k.key AS normalized_external_id,
    c.external_id,
    COALESCE(
      JSON_EXTRACT_SCALAR(TO_JSON_STRING(c), '$.si_contact_id'),
      JSON_EXTRACT_SCALAR(TO_JSON_STRING(c), '$.id'),
      JSON_EXTRACT_SCALAR(TO_JSON_STRING(c), '$.contact_id')
    ) AS si_contact_id
  FROM key_list k
  INNER JOIN `{project_id}.{dataset}.{contacts_table}` c
    ON k.key = CASE
      WHEN REGEXP_CONTAINS(REGEXP_REPLACE(LOWER(CAST(c.external_id AS STRING)), r'[^0-9a-z]', ''), r'^[0-9]+$')
        AND LENGTH(REGEXP_REPLACE(LOWER(CAST(c.external_id AS STRING)), r'[^0-9a-z]', '')) < 11
      THEN LPAD(REGEXP_REPLACE(LOWER(CAST(c.external_id AS STRING)), r'[^0-9a-z]', ''), 11, '0')
      ELSE REGEXP_REPLACE(LOWER(CAST(c.external_id AS STRING)), r'[^0-9a-z]', '')
    END
  WHERE c.external_id IS NOT NULL
),
purchases_by_contact AS (
  SELECT
    CAST(si_contact_id AS STRING) AS si_contact_id,
    COUNT(DISTINCT order_id) AS pedidos_periodo,
    ROUND(SUM(COALESCE(sales_amount, 0)), 2) AS receita_periodo,
    DATE(MIN(purchase_date)) AS primeira_compra_periodo,
    DATE(MAX(purchase_date)) AS ultima_compra_periodo
  FROM `{project_id}.{dataset}.{purchases_table}`
  WHERE DATE(purchase_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND si_contact_id IS NOT NULL
  GROUP BY si_contact_id
)
SELECT
  mc.normalized_external_id,
  ARRAY_AGG(DISTINCT mc.external_id IGNORE NULLS LIMIT 5) AS external_ids,
  ARRAY_AGG(DISTINCT mc.si_contact_id IGNORE NULLS LIMIT 5) AS si_contact_ids,
  COUNT(DISTINCT mc.si_contact_id) AS contact_rows,
  COALESCE(SUM(p.pedidos_periodo), 0) AS pedidos_periodo,
  COALESCE(ROUND(SUM(p.receita_periodo), 2), 0.0) AS receita_periodo,
  MIN(p.primeira_compra_periodo) AS primeira_compra_periodo,
  MAX(p.ultima_compra_periodo) AS ultima_compra_periodo
FROM matched_contacts mc
LEFT JOIN purchases_by_contact p USING (si_contact_id)
GROUP BY mc.normalized_external_id
""".strip()


@router.get("/unidade-venda/contacts-match")
def unidade_venda_contacts_match(
    max_documents: int = Query(default=5000, ge=1, le=10000),
    sample_limit: int = Query(default=200, ge=1, le=1000),
    start: str = Query(default="2026-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str = Query(default="2026-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        start_date = _validate_optional_iso_date(start)
        end_date = _validate_optional_iso_date(end)
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="Informe data de inicio e fim.")
        if start_date > end_date:
            raise HTTPException(status_code=400, detail="A data de inicio deve ser menor ou igual a data de fim.")

        if not BASE_VENDAS_BQ_PROJECT:
            raise HTTPException(status_code=500, detail="BASE_VENDAS_BQ_PROJECT nao configurado.")

        bv_sql = _build_bv_rows_sql(start_date, end_date, limit=max_documents * 10)
        bv_records = run_bigquery_records(
            bv_sql,
            BASE_VENDAS_BQ_PROJECT,
            location=BASE_VENDAS_BQ_LOCATION or None,
            timeout=30,
        )
        if not bv_records:
            return {
                "items": [],
                "summary": {
                    "sheet_rows": 0,
                    "documents_with_value": 0,
                    "unique_documents": 0,
                    "documents_checked": 0,
                    "matched_documents": 0,
                    "unmatched_documents": 0,
                    "not_checked_documents": 0,
                    "match_rate": 0,
                    "ignored_documents": 0,
                    "source_sheet_rows": 0,
                    "sheet_rows_in_period": 0,
                    "invalid_date_rows": 0,
                    "matched_orders_period": 0,
                    "matched_revenue_period": 0,
                },
                "source": "bigquery_base_vendas_x_bigquery_si_contacts",
                "start_date": start_date,
                "end_date": end_date,
            }

        sheet_rows: list[dict[str, Any]] = []
        unique_document_keys: list[str] = []
        seen_keys: set[str] = set()
        source_sheet_rows = len(bv_records)

        for i, rec in enumerate(bv_records):
            normalized_document = str(rec.get("normalized_documento") or "").strip()
            if not normalized_document:
                continue
            if normalized_document not in seen_keys:
                seen_keys.add(normalized_document)
                unique_document_keys.append(normalized_document)
            sheet_rows.append(
                {
                    "row_index": i + 2,
                    "documento_cliente": str(rec.get("documento_cliente") or "").strip(),
                    "normalized_documento": normalized_document,
                    "canal": str(rec.get("canal") or "").strip() or None,
                    "unidade_negocio": str(rec.get("unidade_negocio") or "").strip() or None,
                    "codigo_filial": str(rec.get("codigo_filial") or "").strip() or None,
                }
            )

        invalid_date_rows = 0
        date_column = "data_completa"
        canal_column = "canal"
        unidade_negocio_column = "unidade_negocio"
        codigo_filial_column = "codigo_filial"
        document_column = "documento_cliente"

        documents_to_check = unique_document_keys[:max_documents]
        matches_by_key: dict[str, dict[str, Any]] = {}
        if documents_to_check:
            sql = _build_sales_unit_contacts_sql(documents_to_check, start_date, end_date)
            records = run_bigquery_records(
                sql,
                EMARSYS_OPEN_DATA_PROJECT_ID,
                location=EMARSYS_OPEN_DATA_LOCATION or None,
                timeout=25,
            )
            for record in records:
                key = str(record.get("normalized_external_id") or "")
                if key:
                    matches_by_key[key] = {
                        "external_ids": list(record.get("external_ids") or []),
                        "si_contact_ids": list(record.get("si_contact_ids") or []),
                        "contact_rows": int(record.get("contact_rows") or 0),
                        "pedidos_periodo": int(record.get("pedidos_periodo") or 0),
                        "receita_periodo": float(record.get("receita_periodo") or 0),
                        "primeira_compra_periodo": _normalize_open_data_value(record.get("primeira_compra_periodo")),
                        "ultima_compra_periodo": _normalize_open_data_value(record.get("ultima_compra_periodo")),
                    }

        checked_keys = set(documents_to_check)
        matched_keys = set(matches_by_key)
        not_checked_keys = set(unique_document_keys[max_documents:])
        unmatched_keys = checked_keys - matched_keys

        items: list[dict[str, Any]] = []
        for row in sheet_rows:
            key = row["normalized_documento"]
            match = matches_by_key.get(key)
            if key in not_checked_keys:
                status = "nao_consultado"
            elif match:
                status = "bateu"
            else:
                status = "nao_bateu"

            items.append(
                {
                    **row,
                    "status": status,
                    "external_ids": match["external_ids"] if match else [],
                    "si_contact_ids": match["si_contact_ids"] if match else [],
                    "contact_rows": match["contact_rows"] if match else 0,
                    "pedidos_periodo": match["pedidos_periodo"] if match else 0,
                    "receita_periodo": match["receita_periodo"] if match else 0,
                    "primeira_compra_periodo": match["primeira_compra_periodo"] if match else None,
                    "ultima_compra_periodo": match["ultima_compra_periodo"] if match else None,
                }
            )

        documents_with_value = sum(1 for row in sheet_rows if row["normalized_documento"])
        rows_in_period = len(sheet_rows)
        ignored_documents = 0
        match_rate = (len(matched_keys) / len(checked_keys) * 100) if checked_keys else 0
        matched_orders = sum(match["pedidos_periodo"] for match in matches_by_key.values())
        matched_revenue = sum(match["receita_periodo"] for match in matches_by_key.values())

        def _dim_breakdown(field: str) -> list[dict[str, Any]]:
            groups: dict[str, dict[str, Any]] = {}
            for item in items:
                if item["status"] != "bateu":
                    continue
                dim = item.get(field) or "(sem valor)"
                if dim not in groups:
                    groups[dim] = {"dimension": dim, "linhas": 0, "unique_docs": set(), "pedidos_periodo": 0, "receita_periodo": 0.0}
                groups[dim]["linhas"] += 1
                groups[dim]["unique_docs"].add(item["normalized_documento"])
                groups[dim]["pedidos_periodo"] += item.get("pedidos_periodo") or 0
                groups[dim]["receita_periodo"] += float(item.get("receita_periodo") or 0)
            return sorted(
                [{"dimension": g["dimension"], "linhas": g["linhas"], "unique_docs": len(g["unique_docs"]),
                  "pedidos_periodo": g["pedidos_periodo"], "receita_periodo": round(g["receita_periodo"], 2)}
                 for g in groups.values()],
                key=lambda x: -x["receita_periodo"],
            )

        return {
            "items": items[:sample_limit],
            "summary": {
                "sheet_rows": len(sheet_rows),
                "documents_with_value": documents_with_value,
                "unique_documents": len(unique_document_keys),
                "documents_checked": len(checked_keys),
                "matched_documents": len(matched_keys),
                "unmatched_documents": len(unmatched_keys),
                "not_checked_documents": len(not_checked_keys),
                "match_rate": round(match_rate, 2),
                "ignored_documents": ignored_documents,
                "source_sheet_rows": source_sheet_rows,
                "sheet_rows_in_period": rows_in_period,
                "invalid_date_rows": invalid_date_rows,
                "matched_orders_period": matched_orders,
                "matched_revenue_period": round(matched_revenue, 2),
            },
            "document_column": document_column,
            "date_column": date_column,
            "canal_column": canal_column,
            "unidade_negocio_column": unidade_negocio_column,
            "codigo_filial_column": codigo_filial_column,
            "date_filter_applied": True,
            "warning": None,
            "breakdown_canal": _dim_breakdown("canal"),
            "breakdown_unidade_negocio": _dim_breakdown("unidade_negocio"),
            "breakdown_codigo_filial": _dim_breakdown("codigo_filial"),
            "contacts_table": EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE,
            "purchases_table": EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE,
            "start_date": start_date,
            "end_date": end_date,
            "dataset": EMARSYS_OPEN_DATA_DATASET,
            "project_id": EMARSYS_OPEN_DATA_PROJECT_ID,
            "location": EMARSYS_OPEN_DATA_LOCATION or None,
            "max_documents": max_documents,
            "sample_limit": sample_limit,
            "total_items_returned": min(len(items), sample_limit),
            "source": "bigquery_base_vendas_x_bigquery_si_contacts",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao cruzar Base Vendas com si_contacts: {exc}") from exc


def _build_attribution_date_filters(
    start_date: str | None,
    end_date: str | None,
    table_alias: str = "r",
) -> tuple[str, str]:
    """Returns (event_time_filter, partition_filter) for revenue_attribution queries.

    event_time é UTC no BigQuery; convertemos para America/Sao_Paulo antes de comparar
    datas para coincidir com o fuso que o Emarsys usa na interface.
    """
    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)
    p = f"{table_alias}.partitiontime" if table_alias else "partitiontime"
    et_col = f"{table_alias}.event_time" if table_alias else "event_time"
    e = f"DATE({et_col}, '{EMARSYS_TZ}')"

    if normalized_start and normalized_end:
        event_time_filter = f"{e} BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        partition_filter = f"DATE({p}) BETWEEN DATE('{normalized_start}') AND CURRENT_DATE()"
    elif normalized_start:
        event_time_filter = f"{e} >= DATE('{normalized_start}')"
        partition_filter = f"DATE({p}) >= DATE('{normalized_start}')"
    elif normalized_end:
        event_time_filter = f"{e} <= DATE('{normalized_end}')"
        partition_filter = f"DATE({p}) <= CURRENT_DATE()"
    else:
        event_time_filter = f"{e} >= DATE_SUB(CURRENT_DATE('{EMARSYS_TZ}'), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"
        partition_filter = f"{p} >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS + 7} DAY)"

    return event_time_filter, partition_filter


def _build_audit_discrepancia_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    event_time_filter, partition_filter = _build_attribution_date_filters(start_date, end_date, "r")

    return f"""
SELECT
  r.order_id,
  r.contact_id,
  DATE(r.event_time) AS data_pedido,
  CAST(t.campaign_id AS STRING) AS campaign_id,
  LOWER(t.channel) AS canal,
  ROUND((SELECT COALESCE(SUM(i.price * i.quantity), 0) FROM UNNEST(r.items) AS i), 2) AS valor_pedido,
  ROUND(COALESCE(t.attributed_amount, 0), 2) AS valor_atribuido,
  LOWER(t.reason.type) AS tipo_engajamento
FROM `{project_id}.{dataset}.{revenue_table}` r
CROSS JOIN UNNEST(r.treatments) AS t
WHERE ARRAY_LENGTH(r.treatments) > 0
  AND (t.attributed_amount IS NULL OR t.attributed_amount = 0)
  AND (SELECT COALESCE(SUM(i.price * i.quantity), 0) FROM UNNEST(r.items) AS i) > 0
  AND {event_time_filter}
  AND {partition_filter}
ORDER BY data_pedido DESC
LIMIT 500
""".strip()


def _build_audit_janela_violada_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    event_time_filter, partition_filter = _build_attribution_date_filters(start_date, end_date, "r")

    return f"""
SELECT
  r.order_id,
  r.contact_id,
  DATE(r.event_time) AS data_pedido,
  CAST(t.campaign_id AS STRING) AS campaign_id,
  LOWER(t.channel) AS canal,
  LOWER(t.reason.type) AS tipo_engajamento,
  DATE(t.reason.event_time) AS data_engajamento,
  DATE_DIFF(DATE(r.event_time), DATE(t.reason.event_time), DAY) AS dias_apos_engajamento,
  ROUND(t.attributed_amount, 2) AS valor_atribuido
FROM `{project_id}.{dataset}.{revenue_table}` r
CROSS JOIN UNNEST(r.treatments) AS t
WHERE ARRAY_LENGTH(r.treatments) > 0
  AND t.reason.event_time IS NOT NULL
  AND DATE_DIFF(DATE(r.event_time), DATE(t.reason.event_time), DAY) > 7
  AND {event_time_filter}
  AND {partition_filter}
ORDER BY dias_apos_engajamento DESC
LIMIT 500
""".strip()


def _build_audit_receita_por_campanha_sql(start_date: str | None = None, end_date: str | None = None, canal_order_ids: list | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)
    event_time_filter, partition_filter = _build_attribution_date_filters(start_date, end_date, "r")
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS
    order_id_filter = _make_order_id_filter(canal_order_ids, "CAST(r.order_id AS STRING)")

    return f"""
WITH email_names AS (
  SELECT
    CAST(id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{email_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND id IS NOT NULL
  GROUP BY 1
),
sms_names AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{sms_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND campaign_id IS NOT NULL
  GROUP BY 1
),
revenue_by_campaign AS (
  SELECT
    CAST(t.campaign_id AS STRING) AS campaign_id,
    LOWER(t.channel) AS canal,
    COUNT(DISTINCT r.order_id) AS pedidos_atribuidos,
    COUNT(DISTINCT r.contact_id) AS compradores_unicos,
    ROUND(SUM(t.attributed_amount), 2) AS receita_atribuida
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND {event_time_filter}
    AND {partition_filter}
    {order_id_filter}
  GROUP BY 1, 2
)
SELECT
  rc.campaign_id,
  rc.canal,
  COALESCE(en.nome_campanha, sn.nome_campanha, CONCAT('Campanha #', rc.campaign_id)) AS nome_campanha,
  rc.pedidos_atribuidos,
  rc.compradores_unicos,
  rc.receita_atribuida,
  CASE
    WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')), r'^transacional_') THEN 'transacional'
    WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')), r'^0_at_') THEN 'servico'
    WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')), r'pesquisanps') THEN 'nps'
    WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')), r'^0_token-') THEN 'transacional'
    WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')), r'^00000000_pedido_') THEN 'transacional'
    WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')), r'fraudes|contrato-assinado') THEN 'transacional'
    ELSE 'marketing'
  END AS categoria
FROM revenue_by_campaign rc
LEFT JOIN email_names en ON rc.campaign_id = en.campaign_id
LEFT JOIN sms_names sn ON rc.campaign_id = sn.campaign_id
ORDER BY rc.receita_atribuida DESC
LIMIT 200
""".strip()


def _build_audit_receita_resumo_sql(start_date: str | None = None, end_date: str | None = None, canal_order_ids: list | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)
    event_time_filter, partition_filter = _build_attribution_date_filters(start_date, end_date, "r")
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS
    order_id_filter = _make_order_id_filter(canal_order_ids, "CAST(r.order_id AS STRING)")

    return f"""
WITH email_names AS (
  SELECT
    CAST(id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{email_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND id IS NOT NULL
  GROUP BY 1
),
sms_names AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{sms_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND campaign_id IS NOT NULL
  GROUP BY 1
),
revenue_by_campaign AS (
  SELECT
    CAST(t.campaign_id AS STRING) AS campaign_id,
    LOWER(t.channel) AS canal,
    COUNT(DISTINCT r.order_id) AS pedidos_atribuidos,
    COUNT(DISTINCT r.contact_id) AS compradores_unicos,
    ROUND(SUM(t.attributed_amount), 2) AS receita_atribuida
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND {event_time_filter}
    AND {partition_filter}
    {order_id_filter}
  GROUP BY 1, 2
)
SELECT
  CASE
    WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')), r'^transacional_') THEN 'transacional'
    WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')), r'^0_at_') THEN 'servico'
    WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')), r'pesquisanps') THEN 'nps'
    WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')), r'^0_token-') THEN 'transacional'
    WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')), r'^00000000_pedido_') THEN 'transacional'
    WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')), r'fraudes|contrato-assinado') THEN 'transacional'
    ELSE 'marketing'
  END AS categoria,
  COUNT(DISTINCT rc.campaign_id) AS num_campanhas,
  SUM(rc.pedidos_atribuidos) AS pedidos_totais,
  SUM(rc.compradores_unicos) AS compradores_totais,
  ROUND(SUM(rc.receita_atribuida), 2) AS receita_total
FROM revenue_by_campaign rc
LEFT JOIN email_names en ON rc.campaign_id = en.campaign_id
LEFT JOIN sms_names sn ON rc.campaign_id = sn.campaign_id
GROUP BY 1
ORDER BY receita_total DESC
""".strip()


@router.get("/emarsys/audit-discrepancia")
def emarsys_audit_discrepancia(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_audit_discrepancia_sql(start, end)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        items = _records_to_response_items(records)
        return {
            "items": items,
            "total": len(items),
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
            "source": "bigquery_emarsys_open_data_revenue_attribution",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha na auditoria de discrepância: {exc}") from exc


@router.get("/emarsys/audit-janela-violada")
def emarsys_audit_janela_violada(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_audit_janela_violada_sql(start, end)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        items = _records_to_response_items(records)
        return {
            "items": items,
            "total": len(items),
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
            "source": "bigquery_emarsys_open_data_revenue_attribution",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha na auditoria de janela violada: {exc}") from exc


def _build_audit_cruzamento_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    """Cross-reference si_purchases against revenue_attribution + email_opens + sms_sends.

    Categories:
      atribuida        — attributed_amount > 0 in revenue_attribution
      deveria_atribuir — not attributed, but contact had email open or SMS send within 7 days before purchase
      nao_crm          — not attributed and no CRM touchpoint in the window

    Returns per category:
      receita_pedidos   — net order value from si_purchases
      receita_atribuida — sum of attributed_amount from revenue_attribution (non-zero only for 'atribuida')
    """
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    email_opens_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE)
    sms_sends_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_SENDS_TABLE)

    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)

    # event_time_filter restricts revenue_attribution rows to purchases in the period
    # attr_partition_filter is wider (+7 days) to cover ingestion lag in partitioning
    # Both filters are required (same pattern as the working audit-receita-por-campanha SQL)
    if normalized_start and normalized_end:
        purchase_date_filter = f"DATE(p.purchase_date) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) BETWEEN DATE('{normalized_start}') AND CURRENT_DATE()"
        touch_partition_start = f"DATE_SUB(DATE('{normalized_start}'), INTERVAL 7 DAY)"
        touch_partition_end = f"DATE('{normalized_end}')"
    elif normalized_start:
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE('{normalized_start}')"
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE('{normalized_start}')"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE('{normalized_start}')"
        touch_partition_start = f"DATE_SUB(DATE('{normalized_start}'), INTERVAL 7 DAY)"
        touch_partition_end = "CURRENT_DATE()"
    elif normalized_end:
        purchase_date_filter = f"DATE(p.purchase_date) <= DATE('{normalized_end}')"
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') <= DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) <= CURRENT_DATE()"
        touch_partition_start = f"DATE_SUB(CURRENT_DATE(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS + 7} DAY)"
        touch_partition_end = f"DATE('{normalized_end}')"
    else:
        purchase_date_filter = "p.purchase_date IS NOT NULL"
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE_SUB(CURRENT_DATE('{EMARSYS_TZ}'), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS + 7} DAY)"
        touch_partition_start = f"DATE_SUB(CURRENT_DATE(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS + 7} DAY)"
        touch_partition_end = "CURRENT_DATE()"

    return f"""
WITH orders_net AS (
  -- Net order value per order_id; negatives = cancellations
  SELECT
    order_id,
    DATE(MIN(purchase_date)) AS purchase_date,
    ROUND(SUM(sales_amount), 2) AS receita_liquida
  FROM `{project_id}.{dataset}.{purchases_table}` p
  WHERE {purchase_date_filter}
  GROUP BY order_id
),
attribution_per_order AS (
  -- Attributed_amount and contact_id per order from revenue_attribution
  -- Uses both event_time (restrict to period purchases) and partitiontime (scan efficiency)
  SELECT
    order_id,
    MAX(contact_id) AS contact_id,
    ROUND(MAX(COALESCE(
      (SELECT SUM(t.attributed_amount)
       FROM UNNEST(r.treatments) AS t
       WHERE t.attributed_amount > 0),
      0
    )), 2) AS receita_atribuida
  FROM `{project_id}.{dataset}.{revenue_table}` r
  WHERE {attr_event_time_filter}
    AND {attr_partition_filter}
  GROUP BY order_id
),
order_contact AS (
  -- Base table: every order with its contact_id (from revenue_attribution) and attribution
  SELECT
    o.order_id,
    o.purchase_date,
    o.receita_liquida,
    a.contact_id,
    COALESCE(a.receita_atribuida, 0) AS receita_atribuida
  FROM orders_net o
  LEFT JOIN attribution_per_order a USING (order_id)
),
order_contact_ids AS (
  -- Distinct contacts linked to orders in this period (used to filter email/sms tables)
  SELECT DISTINCT contact_id
  FROM order_contact
  WHERE contact_id IS NOT NULL
),
crm_touches AS (
  -- Email opens within 7-day pre-purchase window for relevant contacts
  SELECT e.contact_id, DATE(e.event_time) AS touch_date
  FROM `{project_id}.{dataset}.{email_opens_table}` e
  INNER JOIN order_contact_ids oc ON oc.contact_id = e.contact_id
  WHERE DATE(e.partitiontime) BETWEEN {touch_partition_start} AND {touch_partition_end}
    AND DATE(e.event_time) BETWEEN {touch_partition_start} AND {touch_partition_end}

  UNION ALL

  -- SMS sends within 7-day pre-purchase window (send itself triggers attribution per Emarsys rules)
  SELECT s.contact_id, DATE(s.event_time) AS touch_date
  FROM `{project_id}.{dataset}.{sms_sends_table}` s
  INNER JOIN order_contact_ids oc ON oc.contact_id = s.contact_id
  WHERE DATE(s.partitiontime) BETWEEN {touch_partition_start} AND {touch_partition_end}
    AND DATE(s.event_time) BETWEEN {touch_partition_start} AND {touch_partition_end}
),
orders_with_crm_touch AS (
  -- Orders where the contact had at least one CRM touchpoint in the 7 days before purchase
  SELECT DISTINCT oc.order_id
  FROM order_contact oc
  INNER JOIN crm_touches ct ON ct.contact_id = oc.contact_id
    AND ct.touch_date BETWEEN DATE_SUB(oc.purchase_date, INTERVAL 7 DAY) AND oc.purchase_date
),
categorized AS (
  SELECT
    oc.order_id,
    oc.receita_liquida,
    oc.receita_atribuida,
    CASE
      WHEN oc.receita_atribuida > 0  THEN 'atribuida'
      WHEN owt.order_id IS NOT NULL  THEN 'deveria_atribuir'
      ELSE                                'nao_crm'
    END AS categoria
  FROM order_contact oc
  LEFT JOIN orders_with_crm_touch owt USING (order_id)
)
SELECT
  categoria,
  COUNT(DISTINCT order_id)          AS num_pedidos,
  ROUND(SUM(receita_liquida), 2)    AS receita_pedidos,
  ROUND(SUM(receita_atribuida), 2)  AS receita_atribuida
FROM categorized
GROUP BY categoria

UNION ALL

-- Direct attribution total (same pattern as Atribuída Reportada — no si_purchases join constraint)
SELECT
  'atribuida_direta'                           AS categoria,
  COUNT(DISTINCT r.order_id)                   AS num_pedidos,
  0                                            AS receita_pedidos,
  ROUND(SUM(t.attributed_amount), 2)           AS receita_atribuida
FROM `{project_id}.{dataset}.{revenue_table}` r
CROSS JOIN UNNEST(r.treatments) AS t
WHERE ARRAY_LENGTH(r.treatments) > 0
  AND t.attributed_amount > 0
  AND {attr_event_time_filter}
  AND {attr_partition_filter}

ORDER BY receita_pedidos DESC
""".strip()


def _build_si_purchases_total_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)

    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)

    if normalized_start and normalized_end:
        date_filter = f"DATE(purchase_date) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
    elif normalized_start:
        date_filter = f"DATE(purchase_date) >= DATE('{normalized_start}')"
    elif normalized_end:
        date_filter = f"DATE(purchase_date) <= DATE('{normalized_end}')"
    else:
        date_filter = "purchase_date IS NOT NULL"

    return f"""
SELECT ROUND(COALESCE(SUM(sales_amount), 0), 2) AS total_crm
FROM `{project_id}.{dataset}.{purchases_table}`
WHERE {date_filter}
""".strip()


@router.get("/emarsys/audit-receita-por-campanha")
def emarsys_audit_receita_por_campanha(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    canal: str = Query(default=""),
) -> dict[str, Any]:
    canal_order_ids = _get_canal_order_ids(canal.upper().strip() if canal else "", start, end)
    try:
        sql_detalhe = _build_audit_receita_por_campanha_sql(start, end, canal_order_ids)
        sql_resumo = _build_audit_receita_resumo_sql(start, end, canal_order_ids)
        sql_total_crm = _build_si_purchases_total_sql(start, end)

        records = run_bigquery_records(sql_detalhe, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        resumo_records = run_bigquery_records(sql_resumo, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        total_crm_records = run_bigquery_records(sql_total_crm, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)

        items = _records_to_response_items(records)
        resumo = _records_to_response_items(resumo_records)

        total_reportado = sum(float(r.get("receita_total") or 0) for r in resumo)
        total_marketing = sum(float(r.get("receita_total") or 0) for r in resumo if r.get("categoria") == "marketing")
        total_crm = float(total_crm_records[0].get("total_crm") or 0) if total_crm_records else 0.0

        return {
            "items": items,
            "total": len(items),
            "resumo_por_categoria": resumo,
            "totais": {
                "total_crm": round(total_crm, 2),
                "reportado": round(total_reportado, 2),
                "marketing": round(total_marketing, 2),
                "ruido": round(total_reportado - total_marketing, 2),
            },
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
            "source": "bigquery_emarsys_open_data_revenue_attribution",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha na auditoria de receita por campanha: {exc}") from exc


@router.get("/emarsys/audit-cruzamento")
def emarsys_audit_cruzamento(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_audit_cruzamento_sql(start, end)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        items = _records_to_response_items(records)

        cat_map = {r["categoria"]: r for r in items}

        def _pedidos(cat: str) -> float:
            return float(cat_map.get(cat, {}).get("receita_pedidos") or 0)

        def _atribuida_val(cat: str) -> float:
            return float(cat_map.get(cat, {}).get("receita_atribuida") or 0)

        def _orders(cat: str) -> int:
            return int(cat_map.get(cat, {}).get("num_pedidos") or 0)

        total_iplace = sum(float(r.get("receita_pedidos") or 0) for r in items)
        total_orders = sum(int(r.get("num_pedidos") or 0) for r in items)

        return {
            "categorias": items,
            "totais": {
                # Box 1 — total iPlace (all orders from si_purchases)
                "total_iplace": round(total_iplace, 2),
                "total_pedidos_iplace": total_orders,
                # Box 2 — attributed by Emarsys (direct from revenue_attribution, same logic as Atribuída Reportada)
                "atribuida_receita": round(_atribuida_val("atribuida_direta"), 2),
                "atribuida_pedidos_valor": round(_pedidos("atribuida"), 2),
                "atribuida_pedidos": _orders("atribuida"),
                # Box 3 — should have been attributed (had CRM touchpoint but not attributed)
                "deveria_atribuir": round(_pedidos("deveria_atribuir"), 2),
                "deveria_atribuir_pedidos": _orders("deveria_atribuir"),
                # Box 4 — genuinely not CRM (no touchpoint in attribution window)
                "nao_crm": round(_pedidos("nao_crm"), 2),
                "nao_crm_pedidos": _orders("nao_crm"),
            },
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
            "source": "bigquery_emarsys_open_data_cruzamento",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha no cruzamento de atribuição: {exc}") from exc


def _build_attribution_by_day_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    """Distribuição dos pedidos atribuídos pelo Emarsys por dia (0–7) após o touchpoint."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    event_time_filter, partition_filter = _build_attribution_date_filters(start_date, end_date, "r")

    return f"""
SELECT
  DATE_DIFF(DATE(r.event_time), DATE(t.reason.event_time), DAY) AS dia,
  COUNT(DISTINCT r.order_id) AS pedidos,
  ROUND(SUM(t.attributed_amount), 2) AS receita
FROM `{project_id}.{dataset}.{revenue_table}` r
CROSS JOIN UNNEST(r.treatments) AS t
WHERE ARRAY_LENGTH(r.treatments) > 0
  AND t.attributed_amount > 0
  AND t.reason.event_time IS NOT NULL
  AND DATE_DIFF(DATE(r.event_time), DATE(t.reason.event_time), DAY) BETWEEN 0 AND 7
  AND {event_time_filter}
  AND {partition_filter}
GROUP BY dia
ORDER BY dia
""".strip()


@router.get("/emarsys/audit-attribution-by-day")
def emarsys_attribution_by_day(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_attribution_by_day_sql(start, end)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        items = _records_to_response_items(records)
        return {
            "items": items,
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao calcular atribuição por dia: {exc}") from exc


def _build_audit_deveria_atribuir_detail_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    """Detail rows for orders that should have been attributed — had CRM touch in 7-day window but weren't attributed."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    email_opens_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE)
    sms_sends_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_SENDS_TABLE)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS

    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)

    if normalized_start and normalized_end:
        purchase_date_filter = f"DATE(p.purchase_date) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) BETWEEN DATE('{normalized_start}') AND CURRENT_DATE()"
        touch_partition_start = f"DATE_SUB(DATE('{normalized_start}'), INTERVAL 7 DAY)"
        touch_partition_end = f"DATE('{normalized_end}')"
    elif normalized_start:
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE('{normalized_start}')"
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE('{normalized_start}')"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE('{normalized_start}')"
        touch_partition_start = f"DATE_SUB(DATE('{normalized_start}'), INTERVAL 7 DAY)"
        touch_partition_end = "CURRENT_DATE()"
    elif normalized_end:
        purchase_date_filter = f"DATE(p.purchase_date) <= DATE('{normalized_end}')"
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') <= DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) <= CURRENT_DATE()"
        touch_partition_start = f"DATE_SUB(CURRENT_DATE(), INTERVAL {lookback + 7} DAY)"
        touch_partition_end = f"DATE('{normalized_end}')"
    else:
        purchase_date_filter = "p.purchase_date IS NOT NULL"
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE_SUB(CURRENT_DATE('{EMARSYS_TZ}'), INTERVAL {lookback} DAY)"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback + 7} DAY)"
        touch_partition_start = f"DATE_SUB(CURRENT_DATE(), INTERVAL {lookback + 7} DAY)"
        touch_partition_end = "CURRENT_DATE()"

    return f"""
WITH orders_net AS (
  SELECT order_id, DATE(MIN(purchase_date)) AS purchase_date,
    ROUND(SUM(sales_amount), 2) AS receita_liquida
  FROM `{project_id}.{dataset}.{purchases_table}` p
  WHERE {purchase_date_filter}
  GROUP BY order_id
),
attribution_per_order AS (
  SELECT order_id, MAX(contact_id) AS contact_id,
    ROUND(MAX(COALESCE(
      (SELECT SUM(t.attributed_amount) FROM UNNEST(r.treatments) AS t WHERE t.attributed_amount > 0), 0
    )), 2) AS receita_atribuida
  FROM `{project_id}.{dataset}.{revenue_table}` r
  WHERE {attr_event_time_filter}
    AND {attr_partition_filter}
  GROUP BY order_id
),
order_contact AS (
  SELECT o.order_id, o.purchase_date, o.receita_liquida,
    a.contact_id, COALESCE(a.receita_atribuida, 0) AS receita_atribuida
  FROM orders_net o LEFT JOIN attribution_per_order a USING (order_id)
),
unattributed AS (
  SELECT * FROM order_contact
  WHERE receita_atribuida = 0 AND contact_id IS NOT NULL
),
last_email AS (
  SELECT
    oc.order_id,
    MAX(e.event_time) AS email_open_datetime,
    CAST(ARRAY_AGG(e.campaign_id ORDER BY e.event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS STRING) AS email_campaign_id
  FROM unattributed oc
  JOIN `{project_id}.{dataset}.{email_opens_table}` e ON e.contact_id = oc.contact_id
    AND DATE(e.event_time) BETWEEN DATE_SUB(oc.purchase_date, INTERVAL 7 DAY) AND oc.purchase_date
    AND DATE(e.partitiontime) BETWEEN {touch_partition_start} AND {touch_partition_end}
  GROUP BY oc.order_id
),
last_sms AS (
  SELECT
    oc.order_id,
    MAX(s.event_time) AS sms_send_datetime,
    CAST(ARRAY_AGG(s.campaign_id ORDER BY s.event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS STRING) AS sms_campaign_id
  FROM unattributed oc
  JOIN `{project_id}.{dataset}.{sms_sends_table}` s ON s.contact_id = oc.contact_id
    AND DATE(s.event_time) BETWEEN DATE_SUB(oc.purchase_date, INTERVAL 7 DAY) AND oc.purchase_date
    AND DATE(s.partitiontime) BETWEEN {touch_partition_start} AND {touch_partition_end}
  GROUP BY oc.order_id
),
email_names AS (
  SELECT CAST(id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{email_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY) AND id IS NOT NULL
  GROUP BY 1
),
sms_names AS (
  SELECT CAST(campaign_id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{sms_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY) AND campaign_id IS NOT NULL
  GROUP BY 1
)
SELECT
  oc.contact_id,
  oc.order_id,
  oc.purchase_date                                                   AS data_compra,
  oc.receita_liquida                                                 AS valor_pedido,
  DATE(le.email_open_datetime)                                       AS email_open_date,
  le.email_campaign_id,
  COALESCE(en.nome_campanha,
    IF(le.email_campaign_id IS NOT NULL, CONCAT('Campanha #', le.email_campaign_id), NULL))  AS email_campanha,
  DATE(ls.sms_send_datetime)                                         AS sms_send_date,
  ls.sms_campaign_id,
  COALESCE(sn.nome_campanha,
    IF(ls.sms_campaign_id IS NOT NULL, CONCAT('Campanha #', ls.sms_campaign_id), NULL))     AS sms_campanha,
  CASE
    WHEN le.email_open_datetime IS NOT NULL AND ls.sms_send_datetime IS NOT NULL THEN
      CASE WHEN le.email_open_datetime >= ls.sms_send_datetime THEN 'email' ELSE 'sms' END
    WHEN le.email_open_datetime IS NOT NULL THEN 'email'
    WHEN ls.sms_send_datetime  IS NOT NULL THEN 'sms'
  END AS canal_deveria_atribuir,
  CASE
    WHEN le.email_open_datetime IS NOT NULL AND ls.sms_send_datetime IS NOT NULL THEN
      CASE
        WHEN le.email_open_datetime >= ls.sms_send_datetime
          THEN COALESCE(en.nome_campanha, CONCAT('Campanha #', le.email_campaign_id))
        ELSE COALESCE(sn.nome_campanha, CONCAT('Campanha #', ls.sms_campaign_id))
      END
    WHEN le.email_open_datetime IS NOT NULL THEN COALESCE(en.nome_campanha, CONCAT('Campanha #', le.email_campaign_id))
    WHEN ls.sms_send_datetime  IS NOT NULL THEN COALESCE(sn.nome_campanha, CONCAT('Campanha #', ls.sms_campaign_id))
  END AS campanha_deveria_atribuir
FROM unattributed oc
LEFT JOIN last_email le USING (order_id)
LEFT JOIN last_sms    ls USING (order_id)
LEFT JOIN email_names en ON en.campaign_id = le.email_campaign_id
LEFT JOIN sms_names   sn ON sn.campaign_id = ls.sms_campaign_id
WHERE le.email_open_datetime IS NOT NULL OR ls.sms_send_datetime IS NOT NULL
ORDER BY oc.receita_liquida DESC
LIMIT 1000
""".strip()


@router.get("/emarsys/audit-deveria-atribuir")
def emarsys_audit_deveria_atribuir(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_audit_deveria_atribuir_detail_sql(start, end)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        items = _records_to_response_items(records)
        return {
            "items": items,
            "total": len(items),
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
            "source": "bigquery_emarsys_open_data_deveria_atribuir",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha no detalhe de deveria atribuir: {exc}") from exc


def _build_sem_treatment_estados_sql() -> str:
    """Para cada order_id dos últimos 90 dias: aparece só sem treatment, só com, ou nas duas?"""
    project = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    return f"""
WITH order_states AS (
  SELECT
    order_id,
    COUNTIF(ARRAY_LENGTH(COALESCE(treatments, [])) = 0) > 0 AS tem_linha_sem_treatment,
    COUNTIF(ARRAY_LENGTH(COALESCE(treatments, [])) > 0) > 0 AS tem_linha_com_treatment,
    COUNT(*)                                                   AS total_linhas,
    MIN(DATE(partitiontime))                                   AS primeira_particao,
    MAX(DATE(partitiontime))                                   AS ultima_particao
  FROM `{project}.{dataset}.{revenue}`
  WHERE DATE(partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
    AND order_id IS NOT NULL
  GROUP BY order_id
)
SELECT
  COUNT(*)                                                                AS total_order_ids,
  COUNTIF(tem_linha_sem_treatment AND NOT tem_linha_com_treatment)        AS apenas_sem_treatment,
  COUNTIF(NOT tem_linha_sem_treatment AND tem_linha_com_treatment)        AS apenas_com_treatment,
  COUNTIF(tem_linha_sem_treatment AND tem_linha_com_treatment)            AS aparece_nas_duas_situacoes,
  ROUND(COUNTIF(tem_linha_sem_treatment AND NOT tem_linha_com_treatment)
    * 100.0 / COUNT(*), 1)                                               AS pct_apenas_sem,
  ROUND(COUNTIF(NOT tem_linha_sem_treatment AND tem_linha_com_treatment)
    * 100.0 / COUNT(*), 1)                                               AS pct_apenas_com,
  ROUND(COUNTIF(tem_linha_sem_treatment AND tem_linha_com_treatment)
    * 100.0 / COUNT(*), 1)                                               AS pct_aparece_nas_duas
FROM order_states
""".strip()


def _build_sem_treatment_cronologia_sql() -> str:
    """Para orders que aparecem com E sem treatment: o sem vem antes ou depois cronologicamente?"""
    project = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    return f"""
WITH both_states AS (
  SELECT
    order_id,
    MIN(CASE WHEN ARRAY_LENGTH(COALESCE(treatments, [])) = 0
             THEN DATE(partitiontime) END) AS primeira_particao_sem,
    MIN(CASE WHEN ARRAY_LENGTH(COALESCE(treatments, [])) > 0
             THEN DATE(partitiontime) END) AS primeira_particao_com,
    MAX(CASE WHEN ARRAY_LENGTH(COALESCE(treatments, [])) > 0
             THEN DATE(partitiontime) END) AS ultima_particao_com
  FROM `{project}.{dataset}.{revenue}`
  WHERE DATE(partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
    AND order_id IS NOT NULL
  GROUP BY order_id
  HAVING primeira_particao_sem IS NOT NULL AND primeira_particao_com IS NOT NULL
)
SELECT
  COUNT(*)                                                       AS total_ambos,
  COUNTIF(primeira_particao_sem < primeira_particao_com)         AS sem_aparece_antes_do_com,
  COUNTIF(primeira_particao_sem = primeira_particao_com)         AS sem_e_com_mesma_particao,
  COUNTIF(primeira_particao_sem > primeira_particao_com)         AS sem_aparece_depois_do_com,
  ROUND(COUNTIF(primeira_particao_sem < primeira_particao_com)
    * 100.0 / COUNT(*), 1)                                       AS pct_sem_antes,
  ROUND(COUNTIF(primeira_particao_sem = primeira_particao_com)
    * 100.0 / COUNT(*), 1)                                       AS pct_mesma_particao,
  ROUND(AVG(DATE_DIFF(primeira_particao_com, primeira_particao_sem, DAY)), 1)
                                                                 AS media_dias_ate_receber_treatment
FROM both_states
""".strip()


def _build_sem_treatment_si_purchases_sql() -> str:
    """Dos orders sem treatment, quantos existem em si_purchases (compra real vs ruído)?"""
    project = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    purchases = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    return f"""
WITH sem_treatment AS (
  SELECT DISTINCT order_id
  FROM `{project}.{dataset}.{revenue}`
  WHERE DATE(partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND order_id IS NOT NULL
    AND ARRAY_LENGTH(COALESCE(treatments, [])) = 0
),
com_treatment AS (
  SELECT DISTINCT order_id
  FROM `{project}.{dataset}.{revenue}`
  WHERE DATE(partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND order_id IS NOT NULL
    AND ARRAY_LENGTH(COALESCE(treatments, [])) > 0
),
so_sem AS (
  SELECT s.order_id
  FROM sem_treatment s
  LEFT JOIN com_treatment c USING (order_id)
  WHERE c.order_id IS NULL
),
purchases AS (
  SELECT DISTINCT order_id FROM `{project}.{dataset}.{purchases}` WHERE order_id IS NOT NULL
)
SELECT
  COUNT(so_sem.order_id)                                              AS total_apenas_sem_treatment,
  COUNTIF(p.order_id IS NOT NULL)                                     AS encontrados_em_si_purchases,
  COUNTIF(p.order_id IS NULL)                                         AS nao_encontrados_em_si_purchases,
  ROUND(COUNTIF(p.order_id IS NOT NULL) * 100.0 / COUNT(so_sem.order_id), 1)
                                                                      AS pct_em_si_purchases
FROM so_sem
LEFT JOIN purchases p USING (order_id)
""".strip()


@router.get("/emarsys/audit-sem-treatment")
def emarsys_audit_sem_treatment() -> dict[str, Any]:
    """Diagnostica os orders sem treatments em revenue_attribution: pendente vs não-CRM."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def run(sql: str) -> list[dict[str, Any]]:
        return run_bigquery_records(
            sql, EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None, timeout=120,
        )

    sqls = {
        "estados":     _build_sem_treatment_estados_sql(),
        "cronologia":  _build_sem_treatment_cronologia_sql(),
        "si_purchases": _build_sem_treatment_si_purchases_sql(),
    }

    results: dict[str, Any] = {}
    errors: dict[str, str] = {}

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(run, sql): key for key, sql in sqls.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    rows = future.result()
                    results[key] = _records_to_response_items(rows)[0] if rows else {}
                except Exception as exc:
                    errors[key] = str(exc)[:200]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha no diagnóstico sem-treatment: {exc}") from exc

    return {
        "estados":      results.get("estados", {}),
        "cronologia":   results.get("cronologia", {}),
        "si_purchases": results.get("si_purchases", {}),
        "errors": errors,
        "source": "bigquery_emarsys_sem_treatment_diagnostico",
    }


def _build_schema_diagnostico_contact_id_sql() -> str:
    """Pergunta 1 — distribuição de contact_id nulo em si_contacts."""
    project = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    contacts = _quote_identifier(EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE)
    return f"""
SELECT
  COUNT(*)                                                        AS total_rows,
  COUNTIF(contact_id IS NULL)                                     AS contact_id_null,
  COUNTIF(contact_id IS NOT NULL)                                 AS contact_id_preenchido,
  ROUND(COUNTIF(contact_id IS NULL) * 100.0 / COUNT(*), 1)        AS pct_null,
  COUNTIF(contact_id IS NULL AND external_id IS NOT NULL)         AS null_mas_tem_external_id,
  COUNTIF(contact_id IS NULL AND TRIM(COALESCE(external_id,''))='') AS null_e_sem_external_id,
  COUNT(DISTINCT CASE WHEN contact_id IS NULL THEN si_contact_id END) AS distinct_si_contact_sem_contact_id
FROM `{project}.{dataset}.{contacts}`
""".strip()


def _build_schema_diagnostico_order_id_sql() -> str:
    """Pergunta 2 — unicidade de order_id em revenue_attribution (últimos 30 dias)."""
    project = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    return f"""
WITH per_order AS (
  SELECT
    order_id,
    COUNT(*)                               AS linhas_por_order,
    SUM(ARRAY_LENGTH(COALESCE(treatments, []))) AS total_treatments,
    MAX(ARRAY_LENGTH(COALESCE(treatments, []))) AS max_treatments_numa_linha
  FROM `{project}.{dataset}.{revenue}`
  WHERE DATE(partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND order_id IS NOT NULL
  GROUP BY order_id
)
SELECT
  COUNT(*)                                     AS distinct_order_ids,
  COUNTIF(linhas_por_order = 1)                AS orders_uma_linha,
  COUNTIF(linhas_por_order > 1)                AS orders_multiplas_linhas,
  MAX(linhas_por_order)                        AS max_linhas_por_order,
  COUNTIF(total_treatments > 1)                AS orders_com_multiplos_treatments,
  MAX(total_treatments)                        AS max_treatments_por_order,
  ROUND(AVG(total_treatments), 2)              AS media_treatments_por_order
FROM per_order
""".strip()


def _build_schema_diagnostico_attributed_vs_sales_sql() -> str:
    """Pergunta 3 — attributed_amount vs SUM(sales_amount) por order_id (últimos 30 dias)."""
    project = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    purchases = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    return f"""
WITH attr AS (
  SELECT
    r.order_id,
    ROUND(SUM(t.attributed_amount), 2)       AS valor_atribuido,
    COUNT(DISTINCT t.campaign_id)             AS campanhas_distintas
  FROM `{project}.{dataset}.{revenue}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND t.attributed_amount > 0
    AND r.order_id IS NOT NULL
  GROUP BY r.order_id
),
sales AS (
  SELECT
    order_id,
    ROUND(SUM(COALESCE(sales_amount, 0)), 2) AS valor_total
  FROM `{project}.{dataset}.{purchases}`
  WHERE order_id IS NOT NULL
  GROUP BY order_id
),
joined AS (
  SELECT
    a.order_id,
    a.valor_atribuido,
    a.campanhas_distintas,
    s.valor_total,
    ROUND(ABS(a.valor_atribuido - COALESCE(s.valor_total, 0)), 2) AS diferenca_abs
  FROM attr a
  LEFT JOIN sales s USING (order_id)
)
SELECT
  COUNT(*)                                                AS total_orders,
  COUNTIF(campanhas_distintas > 1)                        AS orders_multi_campanha,
  MAX(campanhas_distintas)                                AS max_campanhas_por_order,
  COUNTIF(diferenca_abs < 0.02)                           AS attributed_igual_total,
  COUNTIF(diferenca_abs BETWEEN 0.02 AND valor_total * 0.05) AS attributed_parcial_ate_5pct,
  COUNTIF(diferenca_abs > valor_total * 0.05)             AS attributed_difere_mais_5pct,
  COUNTIF(valor_total IS NULL)                            AS orders_sem_si_purchases,
  ROUND(AVG(valor_atribuido), 2)                          AS media_valor_atribuido,
  ROUND(AVG(valor_total), 2)                              AS media_valor_total,
  ROUND(AVG(SAFE_DIVIDE(valor_atribuido, valor_total)) * 100, 1) AS media_pct_atribuido_vs_total
FROM joined
""".strip()


@router.get("/emarsys/schema-diagnostico")
def emarsys_schema_diagnostico() -> dict[str, Any]:
    """Roda 3 queries de diagnóstico de schema: contact_id nulo, unicidade order_id, attributed vs sales."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def run(sql: str) -> list[dict[str, Any]]:
        return run_bigquery_records(
            sql, EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None, timeout=120,
        )

    sqls = {
        "contact_id": _build_schema_diagnostico_contact_id_sql(),
        "order_id":   _build_schema_diagnostico_order_id_sql(),
        "attributed": _build_schema_diagnostico_attributed_vs_sales_sql(),
    }

    results: dict[str, Any] = {}
    errors: dict[str, str] = {}

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(run, sql): key for key, sql in sqls.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    rows = future.result()
                    results[key] = _records_to_response_items(rows)[0] if rows else {}
                except Exception as exc:
                    errors[key] = str(exc)[:200]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha no diagnóstico: {exc}") from exc

    return {
        "contact_id_diagnostico": results.get("contact_id", {}),
        "order_id_diagnostico":   results.get("order_id", {}),
        "attributed_diagnostico": results.get("attributed", {}),
        "errors": errors,
        "source": "bigquery_emarsys_schema_diagnostico",
    }


def _build_audit_order_cruzamento_emarsys_sql(start_date: str, end_date: str, limit: int) -> str:
    """Retorna order_id + valor_atribuido + valor_total (si_purchases) para pedidos atribuídos no período."""
    project = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    purchases = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    tz = EMARSYS_TZ

    return f"""
WITH atribuidos AS (
  SELECT
    r.order_id,
    DATE(MIN(r.event_time), '{tz}') AS data_atribuicao,
    ROUND(SUM(t.attributed_amount), 2) AS valor_atribuido
  FROM `{project}.{dataset}.{revenue}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND DATE(r.event_time, '{tz}') BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND DATE(r.partitiontime) BETWEEN DATE('{start_date}') AND CURRENT_DATE()
    AND r.order_id IS NOT NULL
  GROUP BY r.order_id
),
compras AS (
  SELECT
    order_id,
    ROUND(SUM(COALESCE(sales_amount, 0)), 2) AS valor_total,
    DATE(MIN(purchase_date)) AS data_compra
  FROM `{project}.{dataset}.{purchases}`
  WHERE order_id IS NOT NULL
  GROUP BY order_id
)
SELECT
  a.order_id,
  a.data_atribuicao,
  a.valor_atribuido,
  COALESCE(c.valor_total, 0) AS valor_total,
  c.data_compra
FROM atribuidos a
LEFT JOIN compras c ON a.order_id = c.order_id
ORDER BY a.valor_atribuido DESC
LIMIT {limit}
""".strip()


def _build_audit_order_cruzamento_vendas_sql(order_ids: list[str]) -> str:
    """Retorna Vlr_Pedidos_Captados + Canal + Status por Numero_Pedido na vendas_iplace."""
    if not BASE_VENDAS_BQ_PROJECT:
        return ""
    project = _quote_identifier(BASE_VENDAS_BQ_PROJECT)
    dataset = _quote_identifier(VENDAS_BQ_DATASET)
    table = _quote_identifier(VENDAS_BQ_TABLE)
    safe_ids = sorted({str(i).replace("'", "''") for i in order_ids if i})
    ids_values = ", ".join(f"'{i}'" for i in safe_ids) if safe_ids else "'__no_match__'"

    return f"""
SELECT
  Numero_Pedido AS order_id,
  COALESCE(NULLIF(TRIM(ANY_VALUE(Canal)), ''), '(sem canal)') AS canal,
  ANY_VALUE(Status_Pedidos) AS status_pedido,
  ROUND(
    SUM(COALESCE(SAFE_CAST(REGEXP_REPLACE(COALESCE(TRIM(Vlr_Pedidos_Captados), ''), r'[^0-9\\.]', '') AS FLOAT64), 0)),
    2
  ) AS vlr_captados
FROM `{project}.{dataset}.{table}`
WHERE Numero_Pedido IN UNNEST([{ids_values}])
  AND Numero_Pedido IS NOT NULL
  AND TRIM(Numero_Pedido) != ''
GROUP BY Numero_Pedido
""".strip()


@router.get("/emarsys/audit-order-cruzamento")
def emarsys_audit_order_cruzamento(
    start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(default=1000, ge=1, le=5000),
) -> dict[str, Any]:
    try:
        s = _validate_optional_iso_date(start) or start
        e = _validate_optional_iso_date(end) or end

        # Passo 1 — Emarsys (EU): order_id + valor_atribuido + valor_total
        sql_emarsys = _build_audit_order_cruzamento_emarsys_sql(s, e, limit)
        emarsys_records = run_bigquery_records(
            sql_emarsys, EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None, timeout=60,
        )

        if not emarsys_records:
            return {
                "items": [], "total": 0, "cruzados": 0,
                "total_valor_atribuido": 0.0, "total_valor_total": 0.0, "total_vlr_captados": 0.0,
                "start_date": s, "end_date": e, "limit": limit,
            }

        # Passo 2 — vendas_iplace (SA): Vlr_Pedidos_Captados + Canal
        order_ids = [str(r["order_id"]) for r in emarsys_records if r.get("order_id")]
        vendas_map: dict[str, Any] = {}
        if order_ids and BASE_VENDAS_BQ_PROJECT:
            sql_vendas = _build_audit_order_cruzamento_vendas_sql(order_ids)
            vendas_records = run_bigquery_records(
                sql_vendas, BASE_VENDAS_BQ_PROJECT,
                location=BASE_VENDAS_BQ_LOCATION or None, timeout=30,
            )
            vendas_map = {str(r["order_id"]): r for r in vendas_records if r.get("order_id")}

        # Passo 3 — join Python
        items: list[dict[str, Any]] = []
        for r in emarsys_records:
            oid = str(r.get("order_id") or "")
            vendas = vendas_map.get(oid, {})
            items.append({
                "order_id": oid,
                "data_atribuicao": _normalize_open_data_value(r.get("data_atribuicao")),
                "data_compra": _normalize_open_data_value(r.get("data_compra")),
                "valor_atribuido": round(float(r.get("valor_atribuido") or 0), 2),
                "valor_total": round(float(r.get("valor_total") or 0), 2),
                "vlr_captados": round(float(vendas.get("vlr_captados") or 0), 2),
                "canal": vendas.get("canal") or "",
                "status_pedido": vendas.get("status_pedido") or "",
                "cruzado": bool(vendas),
            })

        cruzados = sum(1 for i in items if i["cruzado"])
        return {
            "items": items,
            "total": len(items),
            "cruzados": cruzados,
            "total_valor_atribuido": round(sum(i["valor_atribuido"] for i in items), 2),
            "total_valor_total": round(sum(i["valor_total"] for i in items), 2),
            "total_vlr_captados": round(sum(i["vlr_captados"] for i in items), 2),
            "start_date": s,
            "end_date": e,
            "limit": limit,
            "source": "bigquery_emarsys_x_vendas_iplace",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha no cruzamento order-id: {exc}") from exc


def _build_receita_teste_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    """Mirrors Auditoria 'atribuida_direta' logic but splits by transactional vs marketing campaign."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)
    si_purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS

    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)

    if normalized_start and normalized_end:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) BETWEEN DATE('{normalized_start}') AND CURRENT_DATE()"
        purchase_date_filter = f"DATE(p.purchase_date) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
    elif normalized_start:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE('{normalized_start}')"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE('{normalized_start}')"
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE('{normalized_start}')"
    elif normalized_end:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') <= DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) <= CURRENT_DATE()"
        purchase_date_filter = f"DATE(p.purchase_date) <= DATE('{normalized_end}')"
    else:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE_SUB(CURRENT_DATE('{EMARSYS_TZ}'), INTERVAL {lookback} DAY)"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback + 7} DAY)"
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)"

    return f"""
WITH
email_names AS (
  SELECT
    CAST(id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{email_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND id IS NOT NULL
  GROUP BY 1
),
sms_names AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{sms_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND campaign_id IS NOT NULL
  GROUP BY 1
),
treatments_classified AS (
  -- Same base as Auditoria atribuida_direta: revenue_attribution treatments with attributed_amount > 0
  -- Each treatment is classified as transacional or marketing by campaign name
  SELECT
    r.order_id,
    CAST(t.campaign_id AS STRING) AS campaign_id,
    t.attributed_amount,
    COALESCE(en.nome_campanha, sn.nome_campanha, CONCAT('Campanha #', CAST(t.campaign_id AS STRING))) AS campaign_name,
    CASE
      WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')),
        r'^transacional_|^0_token-|^token-|^00000000_pedido_|fraudes|contrato-assinado|^0_at_|^0_cartaopresente|^0_lrautomatica|^0_produto_transito|pesquisanps')
      THEN 'transacional'
      ELSE 'marketing'
    END AS categoria
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  LEFT JOIN email_names en ON CAST(t.campaign_id AS STRING) = en.campaign_id
  LEFT JOIN sms_names sn ON CAST(t.campaign_id AS STRING) = sn.campaign_id
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND {attr_event_time_filter}
    AND {attr_partition_filter}
),
marketing_orders AS (
  SELECT DISTINCT order_id
  FROM treatments_classified
  WHERE categoria = 'marketing'
),
transactional_only_orders AS (
  -- Orders with only transactional treatments (no marketing treatment at all)
  SELECT DISTINCT order_id
  FROM treatments_classified
  WHERE order_id NOT IN (SELECT order_id FROM marketing_orders)
),
si_mkt AS (
  SELECT ROUND(SUM(p.sales_amount), 2) AS total
  FROM `{project_id}.{dataset}.{si_purchases_table}` p
  INNER JOIN marketing_orders mo ON mo.order_id = p.order_id
  WHERE {purchase_date_filter}
),
si_trans AS (
  SELECT ROUND(SUM(p.sales_amount), 2) AS total
  FROM `{project_id}.{dataset}.{si_purchases_table}` p
  INNER JOIN transactional_only_orders tro ON tro.order_id = p.order_id
  WHERE {purchase_date_filter}
)
SELECT
  ROUND(COALESCE((SELECT SUM(attributed_amount) FROM treatments_classified WHERE categoria = 'marketing'), 0), 2) AS receita_atribuida,
  ROUND(COALESCE((SELECT total FROM si_mkt), 0), 2) AS valor_dos_pedidos,
  (SELECT COUNT(DISTINCT order_id) FROM marketing_orders) AS pedidos_atribuidos,
  ROUND(COALESCE((SELECT total FROM si_trans), 0), 2) AS receita_desconsiderada,
  (SELECT COUNT(DISTINCT order_id) FROM transactional_only_orders) AS pedidos_desconsiderados,
  ARRAY(
    SELECT DISTINCT campaign_name
    FROM treatments_classified
    WHERE categoria = 'marketing' AND campaign_name IS NOT NULL
    ORDER BY campaign_name
  ) AS campanhas_incluidas,
  ARRAY(
    SELECT DISTINCT campaign_name
    FROM treatments_classified
    WHERE categoria = 'transacional' AND campaign_name IS NOT NULL
    ORDER BY campaign_name
  ) AS campanhas_excluidas
""".strip()


@router.get("/receita-teste")
def receita_teste(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_receita_teste_sql(start, end)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        if not records:
            return {
                "receita_atribuida": 0.0,
                "pedidos_atribuidos": 0,
                "campanhas_incluidas": [],
                "campanhas_excluidas": [],
                "start_date": _validate_optional_iso_date(start),
                "end_date": _validate_optional_iso_date(end),
            }
        row = records[0]
        return {
            "receita_atribuida": float(row.get("receita_atribuida") or 0),
            "valor_dos_pedidos": float(row.get("valor_dos_pedidos") or 0),
            "pedidos_atribuidos": int(row.get("pedidos_atribuidos") or 0),
            "receita_desconsiderada": float(row.get("receita_desconsiderada") or 0),
            "pedidos_desconsiderados": int(row.get("pedidos_desconsiderados") or 0),
            "campanhas_incluidas": list(row.get("campanhas_incluidas") or []),
            "campanhas_excluidas": list(row.get("campanhas_excluidas") or []),
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao calcular receita teste: {exc}") from exc


def _build_receita_influenciada_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    """Quatro métricas de influência CRM: Total iPlace, Atribuída (marketing), Gap (sem atribuição com toque marketing), Influenciada (Atribuída + Gap)."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)
    email_opens_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE)
    sms_sends_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_SENDS_TABLE)
    si_purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS

    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)

    if normalized_start and normalized_end:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) BETWEEN DATE('{normalized_start}') AND CURRENT_DATE()"
        purchase_date_filter = f"DATE(p.purchase_date) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        touch_partition_start = f"DATE_SUB(DATE('{normalized_start}'), INTERVAL 7 DAY)"
        touch_partition_end = f"DATE('{normalized_end}')"
    elif normalized_start:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE('{normalized_start}')"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE('{normalized_start}')"
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE('{normalized_start}')"
        touch_partition_start = f"DATE_SUB(DATE('{normalized_start}'), INTERVAL 7 DAY)"
        touch_partition_end = "CURRENT_DATE()"
    elif normalized_end:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') <= DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) <= CURRENT_DATE()"
        purchase_date_filter = f"DATE(p.purchase_date) <= DATE('{normalized_end}')"
        touch_partition_start = f"DATE_SUB(CURRENT_DATE(), INTERVAL {lookback + 7} DAY)"
        touch_partition_end = f"DATE('{normalized_end}')"
    else:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE_SUB(CURRENT_DATE('{EMARSYS_TZ}'), INTERVAL {lookback} DAY)"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback + 7} DAY)"
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)"
        touch_partition_start = f"DATE_SUB(CURRENT_DATE(), INTERVAL {lookback + 7} DAY)"
        touch_partition_end = "CURRENT_DATE()"

    return f"""
WITH
email_names AS (
  SELECT
    CAST(id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{email_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND id IS NOT NULL
  GROUP BY 1
),
sms_names AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{sms_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND campaign_id IS NOT NULL
  GROUP BY 1
),
orders_period AS (
  SELECT
    p.order_id,
    MAX(p.si_contact_id) AS si_contact_id,
    DATE(MIN(p.purchase_date)) AS purchase_date,
    ROUND(SUM(p.sales_amount), 2) AS receita_pedido
  FROM `{project_id}.{dataset}.{si_purchases_table}` p
  WHERE {purchase_date_filter}
  GROUP BY p.order_id
  HAVING SUM(p.sales_amount) > 0
),
attribution_contacts AS (
  -- contact_id da revenue_attribution é mais confiável que si_purchases.si_contact_id
  SELECT order_id, MAX(contact_id) AS contact_id
  FROM `{project_id}.{dataset}.{revenue_table}` r
  WHERE {attr_partition_filter}
  GROUP BY order_id
),
attributed_order_ids AS (
  -- Todos os pedidos com qualquer atribuição no período (todas as campanhas)
  SELECT DISTINCT r.order_id
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND {attr_event_time_filter}
    AND {attr_partition_filter}
),
agg_total AS (
  SELECT ROUND(SUM(receita_pedido), 2) AS total_receita, COUNT(DISTINCT order_id) AS total_pedidos
  FROM orders_period
),
agg_atribuida AS (
  -- Mesma lógica de deduplicação do Executivo (monthly-revenue): MAX por order_id
  SELECT
    ROUND(SUM(order_attributed), 2) AS atribuida_receita,
    COUNT(DISTINCT order_id)        AS atribuida_pedidos
  FROM (
    SELECT
      r.order_id,
      MAX(COALESCE(
        (SELECT ROUND(SUM(t.attributed_amount), 2)
         FROM UNNEST(r.treatments) AS t WHERE t.attributed_amount > 0), 0
      )) AS order_attributed
    FROM `{project_id}.{dataset}.{revenue_table}` r
    WHERE r.event_time IS NOT NULL
      AND {attr_event_time_filter}
      AND {attr_partition_filter}
    GROUP BY r.order_id
  )
  WHERE order_attributed > 0
),
agg_atribuida_full AS (
  -- Receita total dos pedidos atribuídos: espelha a Auditoria (orders_net sem HAVING, purchase_date_filter)
  SELECT
    ROUND(SUM(receita_pedido), 2) AS atribuida_full_receita,
    COUNT(DISTINCT order_id)      AS atribuida_full_pedidos
  FROM (
    SELECT p.order_id, ROUND(SUM(p.sales_amount), 2) AS receita_pedido
    FROM `{project_id}.{dataset}.{si_purchases_table}` p
    WHERE {purchase_date_filter}
    GROUP BY p.order_id
  ) op
  INNER JOIN attributed_order_ids a USING (order_id)
),
unattributed AS (
  -- Pedidos sem nenhuma atribuição; contact_id preferencial da revenue_attribution (fallback: si_contact_id)
  SELECT
    op.order_id,
    COALESCE(ac.contact_id, op.si_contact_id) AS contact_id,
    op.purchase_date,
    op.receita_pedido
  FROM orders_period op
  LEFT JOIN attribution_contacts ac USING (order_id)
  WHERE op.order_id NOT IN (SELECT order_id FROM attributed_order_ids)
    AND COALESCE(ac.contact_id, op.si_contact_id) IS NOT NULL
),
email_mkt_touch AS (
  SELECT DISTINCT u.order_id
  FROM unattributed u
  JOIN `{project_id}.{dataset}.{email_opens_table}` e
    ON e.contact_id = u.contact_id
    AND DATE(e.event_time) BETWEEN DATE_SUB(u.purchase_date, INTERVAL 7 DAY) AND u.purchase_date
    AND DATE(e.partitiontime) BETWEEN {touch_partition_start} AND {touch_partition_end}
  LEFT JOIN email_names en ON CAST(e.campaign_id AS STRING) = en.campaign_id
  WHERE NOT REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, '')),
    r'^transacional_|^0_token-|^token-|^00000000_pedido_|fraudes|contrato-assinado|^0_at_|^0_cartaopresente|^0_lrautomatica|^0_produto_transito|pesquisanps')
),
sms_mkt_touch AS (
  SELECT DISTINCT u.order_id
  FROM unattributed u
  JOIN `{project_id}.{dataset}.{sms_sends_table}` s
    ON s.contact_id = u.contact_id
    AND DATE(s.event_time) BETWEEN DATE_SUB(u.purchase_date, INTERVAL 7 DAY) AND u.purchase_date
    AND DATE(s.partitiontime) BETWEEN {touch_partition_start} AND {touch_partition_end}
  LEFT JOIN sms_names sn ON CAST(s.campaign_id AS STRING) = sn.campaign_id
  WHERE NOT REGEXP_CONTAINS(LOWER(COALESCE(sn.nome_campanha, '')),
    r'^transacional_|^0_token-|^token-|^00000000_pedido_|fraudes|contrato-assinado|^0_at_|^0_cartaopresente|^0_lrautomatica|^0_produto_transito|pesquisanps')
),
gap_orders AS (
  SELECT order_id FROM email_mkt_touch
  UNION DISTINCT
  SELECT order_id FROM sms_mkt_touch
),
agg_gap AS (
  SELECT ROUND(SUM(u.receita_pedido), 2) AS gap_receita, COUNT(DISTINCT u.order_id) AS gap_pedidos
  FROM unattributed u
  INNER JOIN gap_orders g USING (order_id)
),
marketing_attributed_orders AS (
  -- Pedidos com ao menos um treatment de campanha de marketing no período
  SELECT DISTINCT r.order_id
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  LEFT JOIN email_names en ON CAST(t.campaign_id AS STRING) = en.campaign_id
  LEFT JOIN sms_names sn ON CAST(t.campaign_id AS STRING) = sn.campaign_id
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND {attr_event_time_filter}
    AND {attr_partition_filter}
    AND NOT REGEXP_CONTAINS(
      LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')),
      r'^transacional_|^0_token-|^token-|^00000000_pedido_|fraudes|contrato-assinado|^0_at_|^0_cartaopresente|^0_lrautomatica|^0_produto_transito|pesquisanps'
    )
),
transacional_order_ids AS (
  -- Atribuídos pelo Emarsys mas apenas via campanhas transacionais (sem nenhuma de marketing)
  SELECT order_id FROM attributed_order_ids
  EXCEPT DISTINCT
  SELECT order_id FROM marketing_attributed_orders
),
agg_transacional AS (
  -- Receita completa dos pedidos transacional-only atribuídos pelo Emarsys
  SELECT
    ROUND(SUM(receita_pedido), 2) AS transacional_receita,
    COUNT(DISTINCT order_id)      AS transacional_pedidos
  FROM (
    SELECT p.order_id, ROUND(SUM(p.sales_amount), 2) AS receita_pedido
    FROM `{project_id}.{dataset}.{si_purchases_table}` p
    WHERE {purchase_date_filter}
    GROUP BY p.order_id
  ) op
  INNER JOIN transacional_order_ids t USING (order_id)
)
SELECT
  COALESCE((SELECT total_receita           FROM agg_total),          0) AS total_receita,
  COALESCE((SELECT total_pedidos           FROM agg_total),          0) AS total_pedidos,
  COALESCE((SELECT atribuida_receita       FROM agg_atribuida),      0) AS atribuida_receita,
  COALESCE((SELECT atribuida_pedidos       FROM agg_atribuida),      0) AS atribuida_pedidos,
  COALESCE((SELECT atribuida_full_receita  FROM agg_atribuida_full), 0) AS atribuida_full_receita,
  COALESCE((SELECT atribuida_full_pedidos  FROM agg_atribuida_full), 0) AS atribuida_full_pedidos,
  COALESCE((SELECT gap_receita             FROM agg_gap),            0) AS gap_receita,
  COALESCE((SELECT gap_pedidos             FROM agg_gap),            0) AS gap_pedidos,
  COALESCE((SELECT atribuida_full_receita  FROM agg_atribuida_full), 0) AS influenciada_receita,
  COALESCE((SELECT atribuida_full_pedidos  FROM agg_atribuida_full), 0) AS influenciada_pedidos,
  COALESCE((SELECT transacional_receita    FROM agg_transacional),   0) AS transacional_receita,
  COALESCE((SELECT transacional_pedidos    FROM agg_transacional),   0) AS transacional_pedidos,
  ROUND(
    COALESCE((SELECT atribuida_full_receita FROM agg_atribuida_full), 0) +
    COALESCE((SELECT gap_receita            FROM agg_gap),            0) -
    COALESCE((SELECT transacional_receita   FROM agg_transacional),   0), 2
  ) AS receita_final
""".strip()


@router.get("/emarsys/receita-influenciada")
def emarsys_receita_influenciada(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_receita_influenciada_sql(start, end)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        if not records:
            return {
                "total_receita": 0.0,
                "total_pedidos": 0,
                "atribuida_receita": 0.0,
                "atribuida_pedidos": 0,
                "atribuida_full_receita": 0.0,
                "atribuida_full_pedidos": 0,
                "gap_receita": 0.0,
                "gap_pedidos": 0,
                "influenciada_receita": 0.0,
                "influenciada_pedidos": 0,
                "transacional_receita": 0.0,
                "transacional_pedidos": 0,
                "receita_final": 0.0,
                "start_date": _validate_optional_iso_date(start),
                "end_date": _validate_optional_iso_date(end),
            }
        row = records[0]
        return {
            "total_receita": float(row.get("total_receita") or 0),
            "total_pedidos": int(row.get("total_pedidos") or 0),
            "atribuida_receita": float(row.get("atribuida_receita") or 0),
            "atribuida_pedidos": int(row.get("atribuida_pedidos") or 0),
            "atribuida_full_receita": float(row.get("atribuida_full_receita") or 0),
            "atribuida_full_pedidos": int(row.get("atribuida_full_pedidos") or 0),
            "gap_receita": float(row.get("gap_receita") or 0),
            "gap_pedidos": int(row.get("gap_pedidos") or 0),
            "influenciada_receita": float(row.get("influenciada_receita") or 0),
            "influenciada_pedidos": int(row.get("influenciada_pedidos") or 0),
            "transacional_receita": float(row.get("transacional_receita") or 0),
            "transacional_pedidos": int(row.get("transacional_pedidos") or 0),
            "receita_final": float(row.get("receita_final") or 0),
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao calcular receita influenciada: {exc}") from exc


def _build_gap_orders_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    """Returns individual gap orders (not in revenue_attribution but with mkt touch) for download."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)
    email_opens_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE)
    sms_sends_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_SENDS_TABLE)
    si_purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS

    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)

    if normalized_start and normalized_end:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) BETWEEN DATE('{normalized_start}') AND CURRENT_DATE()"
        purchase_date_filter = f"DATE(p.purchase_date) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        touch_partition_start = f"DATE_SUB(DATE('{normalized_start}'), INTERVAL 7 DAY)"
        touch_partition_end = f"DATE('{normalized_end}')"
    elif normalized_start:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE('{normalized_start}')"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE('{normalized_start}')"
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE('{normalized_start}')"
        touch_partition_start = f"DATE_SUB(DATE('{normalized_start}'), INTERVAL 7 DAY)"
        touch_partition_end = "CURRENT_DATE()"
    elif normalized_end:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') <= DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) <= CURRENT_DATE()"
        purchase_date_filter = f"DATE(p.purchase_date) <= DATE('{normalized_end}')"
        touch_partition_start = f"DATE_SUB(CURRENT_DATE(), INTERVAL {lookback + 7} DAY)"
        touch_partition_end = f"DATE('{normalized_end}')"
    else:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE_SUB(CURRENT_DATE('{EMARSYS_TZ}'), INTERVAL {lookback} DAY)"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback + 7} DAY)"
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)"
        touch_partition_start = f"DATE_SUB(CURRENT_DATE(), INTERVAL {lookback + 7} DAY)"
        touch_partition_end = "CURRENT_DATE()"

    transactional_regex = r"'^transacional_|^0_token-|^token-|^00000000_pedido_|fraudes|contrato-assinado|^0_at_|^0_cartaopresente|^0_lrautomatica|^0_produto_transito|pesquisanps'"

    return f"""
WITH
email_names AS (
  SELECT CAST(id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{email_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY) AND id IS NOT NULL
  GROUP BY 1
),
sms_names AS (
  SELECT CAST(campaign_id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{sms_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY) AND campaign_id IS NOT NULL
  GROUP BY 1
),
orders_period AS (
  SELECT p.order_id, MAX(p.si_contact_id) AS si_contact_id,
    DATE(MIN(p.purchase_date)) AS purchase_date,
    ROUND(SUM(p.sales_amount), 2) AS receita_pedido
  FROM `{project_id}.{dataset}.{si_purchases_table}` p
  WHERE {purchase_date_filter}
  GROUP BY p.order_id
  HAVING SUM(p.sales_amount) > 0
),
attribution_contacts AS (
  SELECT order_id, MAX(contact_id) AS contact_id
  FROM `{project_id}.{dataset}.{revenue_table}` r
  WHERE {attr_partition_filter}
  GROUP BY order_id
),
attributed_order_ids AS (
  SELECT DISTINCT r.order_id
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE ARRAY_LENGTH(r.treatments) > 0 AND t.attributed_amount > 0
    AND {attr_event_time_filter} AND {attr_partition_filter}
),
unattributed AS (
  SELECT op.order_id,
    COALESCE(ac.contact_id, op.si_contact_id) AS contact_id,
    op.si_contact_id,
    op.purchase_date,
    op.receita_pedido
  FROM orders_period op
  LEFT JOIN attribution_contacts ac USING (order_id)
  WHERE op.order_id NOT IN (SELECT order_id FROM attributed_order_ids)
    AND COALESCE(ac.contact_id, op.si_contact_id) IS NOT NULL
),
email_mkt_touch AS (
  SELECT u.order_id,
    ARRAY_AGG(
      STRUCT(
        COALESCE(en.nome_campanha, CAST(e.campaign_id AS STRING)) AS nome_campanha,
        DATE(e.event_time) AS data_toque
      )
      ORDER BY e.event_time DESC LIMIT 1
    )[SAFE_OFFSET(0)] AS toque
  FROM unattributed u
  JOIN `{project_id}.{dataset}.{email_opens_table}` e
    ON e.contact_id = u.contact_id
    AND DATE(e.event_time) BETWEEN DATE_SUB(u.purchase_date, INTERVAL 7 DAY) AND u.purchase_date
    AND DATE(e.partitiontime) BETWEEN {touch_partition_start} AND {touch_partition_end}
  LEFT JOIN email_names en ON CAST(e.campaign_id AS STRING) = en.campaign_id
  WHERE NOT REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, '')), {transactional_regex})
  GROUP BY u.order_id
),
sms_mkt_touch AS (
  SELECT u.order_id,
    ARRAY_AGG(
      STRUCT(
        COALESCE(sn.nome_campanha, CAST(s.campaign_id AS STRING)) AS nome_campanha,
        DATE(s.event_time) AS data_toque
      )
      ORDER BY s.event_time DESC LIMIT 1
    )[SAFE_OFFSET(0)] AS toque
  FROM unattributed u
  JOIN `{project_id}.{dataset}.{sms_sends_table}` s
    ON s.contact_id = u.contact_id
    AND DATE(s.event_time) BETWEEN DATE_SUB(u.purchase_date, INTERVAL 7 DAY) AND u.purchase_date
    AND DATE(s.partitiontime) BETWEEN {touch_partition_start} AND {touch_partition_end}
  LEFT JOIN sms_names sn ON CAST(s.campaign_id AS STRING) = sn.campaign_id
  WHERE NOT REGEXP_CONTAINS(LOWER(COALESCE(sn.nome_campanha, '')), {transactional_regex})
  GROUP BY u.order_id
),
gap_orders AS (
  SELECT
    COALESCE(em.order_id, sm.order_id) AS order_id,
    CASE WHEN em.order_id IS NOT NULL THEN 'email' ELSE 'sms' END AS tipo_toque,
    COALESCE(em.toque.nome_campanha, sm.toque.nome_campanha) AS nome_campanha,
    COALESCE(em.toque.data_toque, sm.toque.data_toque) AS data_toque
  FROM email_mkt_touch em
  FULL OUTER JOIN sms_mkt_touch sm USING (order_id)
)
SELECT
  u.order_id,
  CAST(u.contact_id AS STRING) AS contact_id,
  CAST(u.si_contact_id AS STRING) AS si_contact_id,
  u.purchase_date,
  u.receita_pedido AS valor_pedido,
  g.nome_campanha,
  CAST(g.data_toque AS STRING) AS data_toque,
  g.tipo_toque
FROM unattributed u
INNER JOIN gap_orders g USING (order_id)
ORDER BY u.receita_pedido DESC
""".strip()


def _build_contact_external_id_sql(si_contact_ids: list[str]) -> str:
    """UNNEST lookup: si_contact_id → external_id (CPF) from si_contacts."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    contacts_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE)
    key_values = ", ".join(_sql_string_literal(cid) for cid in si_contact_ids)
    return f"""
WITH key_list AS (
  SELECT key FROM UNNEST([{key_values}]) AS key WHERE key IS NOT NULL AND key != ''
)
SELECT
  k.key AS si_contact_id,
  CAST(c.external_id AS STRING) AS external_id
FROM key_list k
INNER JOIN `{project_id}.{dataset}.{contacts_table}` c
  ON k.key = CAST(c.si_contact_id AS STRING)
WHERE c.external_id IS NOT NULL
""".strip()


@router.get("/emarsys/gap-orders")
def emarsys_gap_orders(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        # Step 1: gap order rows (order_id, contact_id, purchase_date, valor_pedido)
        sql = _build_gap_orders_sql(start, end)
        records = run_bigquery_records(
            sql,
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
            timeout=55,
        )

        if not records:
            return {"items": [], "total": 0,
                    "start_date": _validate_optional_iso_date(start),
                    "end_date": _validate_optional_iso_date(end)}

        # Step 2: resolve external_id (CPF) using si_contact_id (SI ID, 7 digits)
        # contact_id is the Emarsys ID (9 digits) used for email/SMS touch matching
        # si_contact_id is the Smart Insight ID (7 digits) that matches si_contacts.si_contact_id
        unique_si_contact_ids = list({str(r.get("si_contact_id") or "") for r in records if r.get("si_contact_id")})
        ext_id_map: dict[str, str] = {}
        if unique_si_contact_ids:
            contact_sql = _build_contact_external_id_sql(unique_si_contact_ids)
            contact_records = run_bigquery_records(
                contact_sql,
                EMARSYS_OPEN_DATA_PROJECT_ID,
                location=EMARSYS_OPEN_DATA_LOCATION or None,
                timeout=25,
            )
            ext_id_map = {
                str(r.get("si_contact_id") or ""): str(r.get("external_id") or "")
                for r in contact_records
                if r.get("si_contact_id")
            }

        items = [
            {
                "order_id": str(r.get("order_id") or ""),
                "contact_id": str(r.get("contact_id") or ""),
                "external_id": ext_id_map.get(str(r.get("si_contact_id") or ""), ""),
                "purchase_date": _normalize_open_data_value(r.get("purchase_date")),
                "valor_pedido": float(r.get("valor_pedido") or 0),
                "nome_campanha": str(r.get("nome_campanha") or ""),
                "data_toque": str(r.get("data_toque") or ""),
                "tipo_toque": str(r.get("tipo_toque") or ""),
            }
            for r in records
        ]
        return {
            "items": items,
            "total": len(items),
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao buscar pedidos do gap: {exc}") from exc


def _build_atribuida_orders_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    """Returns individual attributed orders (attributed_amount > 0) for download.
    Includes external_id (CPF) via si_contacts join — no second BigQuery call needed.
    """
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)
    si_purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    si_contacts_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS

    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)

    if normalized_start and normalized_end:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) BETWEEN DATE('{normalized_start}') AND CURRENT_DATE()"
        purchase_date_filter = f"DATE(p.purchase_date) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
    elif normalized_start:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE('{normalized_start}')"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE('{normalized_start}')"
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE('{normalized_start}')"
    elif normalized_end:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') <= DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) <= CURRENT_DATE()"
        purchase_date_filter = f"DATE(p.purchase_date) <= DATE('{normalized_end}')"
    else:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE_SUB(CURRENT_DATE('{EMARSYS_TZ}'), INTERVAL {lookback} DAY)"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback + 7} DAY)"
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)"

    return f"""
WITH
email_names AS (
  SELECT CAST(id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{email_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY) AND id IS NOT NULL
  GROUP BY 1
),
sms_names AS (
  SELECT CAST(campaign_id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{sms_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY) AND campaign_id IS NOT NULL
  GROUP BY 1
),
attributed_treatments AS (
  SELECT
    r.order_id,
    MAX(r.contact_id) AS contact_id,
    ARRAY_AGG(
      STRUCT(CAST(t.campaign_id AS STRING) AS campaign_id, t.attributed_amount)
      ORDER BY t.attributed_amount DESC LIMIT 1
    )[SAFE_OFFSET(0)] AS top_treatment,
    ROUND(SUM(t.attributed_amount), 2) AS valor_atribuido
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE t.attributed_amount > 0
    AND {attr_event_time_filter}
    AND {attr_partition_filter}
  GROUP BY r.order_id
),
orders_period AS (
  SELECT
    p.order_id,
    MAX(p.si_contact_id) AS si_contact_id,
    DATE(MIN(p.purchase_date)) AS purchase_date,
    ROUND(SUM(p.sales_amount), 2) AS valor_pedido
  FROM `{project_id}.{dataset}.{si_purchases_table}` p
  INNER JOIN (SELECT DISTINCT order_id FROM attributed_treatments) attr_ids USING (order_id)
  WHERE {purchase_date_filter}
  GROUP BY p.order_id
  HAVING SUM(p.sales_amount) > 0
),
si_contact_cpf AS (
  SELECT
    CAST(c.si_contact_id AS STRING) AS si_contact_id,
    ARRAY_AGG(CAST(c.external_id AS STRING) IGNORE NULLS ORDER BY c.external_id LIMIT 1)[SAFE_OFFSET(0)] AS external_id
  FROM `{project_id}.{dataset}.{si_contacts_table}` c
  INNER JOIN orders_period op ON CAST(c.si_contact_id AS STRING) = CAST(op.si_contact_id AS STRING)
  WHERE c.external_id IS NOT NULL AND TRIM(CAST(c.external_id AS STRING)) != ''
  GROUP BY c.si_contact_id
)
SELECT
  atr.order_id,
  CAST(atr.contact_id AS STRING)                                               AS contact_id,
  COALESCE(sc.external_id, '')                                                 AS external_id,
  op.purchase_date,
  op.valor_pedido,
  atr.valor_atribuido,
  COALESCE(en.nome_campanha, sn.nome_campanha, atr.top_treatment.campaign_id)  AS nome_campanha,
  '' AS data_toque,
  CASE
    WHEN en.campaign_id IS NOT NULL THEN 'email'
    WHEN sn.campaign_id IS NOT NULL THEN 'sms'
    ELSE ''
  END AS tipo_toque
FROM attributed_treatments atr
INNER JOIN orders_period op USING (order_id)
LEFT JOIN si_contact_cpf sc ON sc.si_contact_id = CAST(op.si_contact_id AS STRING)
LEFT JOIN email_names en ON en.campaign_id = atr.top_treatment.campaign_id
LEFT JOIN sms_names sn ON sn.campaign_id = atr.top_treatment.campaign_id
ORDER BY op.valor_pedido DESC
""".strip()


@router.get("/emarsys/atribuida-orders")
def emarsys_atribuida_orders(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_atribuida_orders_sql(start, end)
        records = run_bigquery_records(
            sql,
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
            timeout=25,
        )

        if not records:
            return {"items": [], "total": 0,
                    "start_date": _validate_optional_iso_date(start),
                    "end_date": _validate_optional_iso_date(end)}

        items = [
            {
                "order_id": str(r.get("order_id") or ""),
                "contact_id": str(r.get("contact_id") or ""),
                "external_id": str(r.get("external_id") or ""),
                "purchase_date": _normalize_open_data_value(r.get("purchase_date")),
                "valor_pedido": float(r.get("valor_pedido") or 0),
                "valor_atribuido": float(r.get("valor_atribuido") or 0),
                "nome_campanha": str(r.get("nome_campanha") or ""),
                "data_toque": str(r.get("data_toque") or ""),
                "tipo_toque": str(r.get("tipo_toque") or ""),
            }
            for r in records
        ]
        return {
            "items": items,
            "total": len(items),
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao buscar pedidos atribuídos: {exc}") from exc


@router.get("/base-vendas/canal-breakdown")
def base_vendas_canal_breakdown(
    start: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    """Canal/filial breakdown da Base Vendas via BigQuery."""
    try:
        start_date = _validate_optional_iso_date(start)
        end_date = _validate_optional_iso_date(end)
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="Informe data de inicio e fim.")
        if not BASE_VENDAS_BQ_PROJECT:
            raise HTTPException(status_code=500, detail="BASE_VENDAS_BQ_PROJECT nao configurado.")

        sql = _build_bv_canal_filial_sql(start_date, end_date)
        records = run_bigquery_records(
            sql, BASE_VENDAS_BQ_PROJECT,
            location=BASE_VENDAS_BQ_LOCATION or None, timeout=30,
        )
        canal_groups: dict[str, dict[str, Any]] = {}
        filial_list = []
        period_rows = 0
        for r in records:
            canal = str(r.get("canal") or "(sem canal)").strip() or "(sem canal)"
            filial = str(r.get("codigo_filial") or "(sem filial)").strip() or "(sem filial)"
            linhas = int(r.get("linhas") or 0)
            receita = float(r.get("receita") or 0)
            period_rows += linhas
            if canal not in canal_groups:
                canal_groups[canal] = {"canal": canal, "linhas": 0, "receita": 0.0}
            canal_groups[canal]["linhas"] += linhas
            canal_groups[canal]["receita"] += receita
            filial_list.append({"canal": canal, "codigo_filial": filial, "linhas": linhas, "receita": receita})
        canal_list = sorted(
            [{"canal": g["canal"], "linhas": g["linhas"], "receita": round(g["receita"], 2)}
             for g in canal_groups.values()],
            key=lambda x: -x["receita"] if x["receita"] else -x["linhas"],
        )
        filial_list.sort(key=lambda x: -x["receita"] if x["receita"] else -x["linhas"])
        return {
            "canal": canal_list,
            "filial": filial_list,
            "period_rows": period_rows,
            "revenue_column": "valor_faturamento_liquido",
            "start_date": start_date,
            "end_date": end_date,
            "source": "bigquery_base_vendas",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao calcular breakdown de canal: {exc}") from exc


def _build_comparativo_crm_sql(start_date: str | None = None, end_date: str | None = None, canal_order_ids: list | None = None) -> str:
    """Atribuição vs Influência usando a mesma base de pedidos.

    Base: order_id de revenue_attribution onde attributed_amount > 0.
    Modelo 1 (Atribuição): SUM(attributed_amount) — crédito parcial Emarsys.
    Modelo 2 (Influência): SUM(sales_amount) via si_purchases — 100% do pedido.
    """
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)
    si_purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS

    if canal_order_ids is not None:
        if canal_order_ids:
            ids_literal = ", ".join(f"'{str(oid).replace(chr(39), '')}'" for oid in canal_order_ids)
            order_id_filter = f"AND CAST(r.order_id AS STRING) IN UNNEST([{ids_literal}])"
        else:
            order_id_filter = "AND FALSE"
    else:
        order_id_filter = ""

    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)

    if normalized_start and normalized_end:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) BETWEEN DATE('{normalized_start}') AND CURRENT_DATE()"
        purchase_date_filter = f"DATE(p.purchase_date) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
    elif normalized_start:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE('{normalized_start}')"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE('{normalized_start}')"
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE('{normalized_start}')"
    elif normalized_end:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') <= DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) <= CURRENT_DATE()"
        purchase_date_filter = f"DATE(p.purchase_date) <= DATE('{normalized_end}')"
    else:
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE_SUB(CURRENT_DATE('{EMARSYS_TZ}'), INTERVAL {lookback} DAY)"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback + 7} DAY)"
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)"

    return f"""
WITH
email_names AS (
  SELECT
    CAST(id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{email_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND id IS NOT NULL
  GROUP BY 1
),
sms_names AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{sms_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND campaign_id IS NOT NULL
  GROUP BY 1
),
treatments_classified AS (
  -- Base: todo treatment com attributed_amount > 0, classificado por tipo de campanha
  SELECT
    r.order_id,
    t.attributed_amount,
    CASE
      WHEN REGEXP_CONTAINS(LOWER(COALESCE(en.nome_campanha, sn.nome_campanha, '')),
        r'^transacional_|^0_token-|^token-|^00000000_pedido_|fraudes|contrato-assinado|^0_at_|^0_cartaopresente|^0_lrautomatica|^0_produto_transito|pesquisanps')
      THEN 'transacional'
      ELSE 'marketing'
    END AS categoria
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  LEFT JOIN email_names en ON CAST(t.campaign_id AS STRING) = en.campaign_id
  LEFT JOIN sms_names sn ON CAST(t.campaign_id AS STRING) = sn.campaign_id
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND {attr_event_time_filter}
    AND {attr_partition_filter}
    {order_id_filter}
),
attributed_orders AS (
  SELECT order_id, ROUND(SUM(attributed_amount), 2) AS attributed_amount
  FROM treatments_classified
  GROUP BY order_id
),
marketing_orders AS (
  SELECT DISTINCT order_id FROM treatments_classified WHERE categoria = 'marketing'
),
transactional_only_orders AS (
  -- Pedidos sem nenhuma campanha de marketing (somente transacionais)
  SELECT DISTINCT order_id FROM treatments_classified
  WHERE order_id NOT IN (SELECT order_id FROM marketing_orders)
),
sales_all AS (
  SELECT p.order_id, ROUND(SUM(p.sales_amount), 2) AS sales_amount
  FROM `{project_id}.{dataset}.{si_purchases_table}` p
  INNER JOIN attributed_orders ao ON ao.order_id = p.order_id
  WHERE {purchase_date_filter}
  GROUP BY p.order_id
),
sales_trans AS (
  SELECT ROUND(SUM(p.sales_amount), 2) AS total
  FROM `{project_id}.{dataset}.{si_purchases_table}` p
  INNER JOIN transactional_only_orders tro ON tro.order_id = p.order_id
  WHERE {purchase_date_filter}
)
SELECT
  COUNT(DISTINCT ao.order_id)                                                         AS pedidos,
  ROUND(SUM(ao.attributed_amount), 2)                                                 AS receita_atribuicao,
  ROUND(COALESCE(SUM(sa.sales_amount), 0), 2)                                         AS valor_pedidos,
  (SELECT COUNT(DISTINCT order_id) FROM transactional_only_orders)                    AS pedidos_transacional,
  ROUND(COALESCE((SELECT total FROM sales_trans), 0), 2)                              AS receita_transacional
FROM attributed_orders ao
LEFT JOIN sales_all sa USING (order_id)
""".strip()


@router.get("/comparativo-crm")
def comparativo_crm(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    canal: str = Query(default=""),
) -> dict[str, Any]:
    try:
        canal_filter = canal.upper().strip() if canal.strip() in ("VAREJO", "ECOMMERCE") else ""
        canal_order_ids: list | None = None
        if canal_filter and BASE_VENDAS_BQ_PROJECT:
            s = _validate_optional_iso_date(start) or start or ""
            e = _validate_optional_iso_date(end) or end or ""
            safe_canal = canal_filter.replace("'", "''")
            date_clause = f"AND Data_Completa BETWEEN '{s}' AND '{e}'" if s and e else ""
            sql_canal = f"""
SELECT DISTINCT CAST(Numero_Pedido AS STRING) AS order_id
FROM `{BASE_VENDAS_BQ_PROJECT}.{VENDAS_BQ_DATASET}.{VENDAS_BQ_TABLE}`
WHERE UPPER(TRIM(Canal)) = '{safe_canal}'
{date_clause}
"""
            canal_records = run_bigquery_records(sql_canal, BASE_VENDAS_BQ_PROJECT, location=None)
            canal_order_ids = [str(r["order_id"]) for r in canal_records if r.get("order_id")]
        sql = _build_comparativo_crm_sql(start, end, canal_order_ids)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        if not records:
            return {
                "pedidos": 0,
                "receita_atribuicao": 0.0,
                "valor_pedidos": 0.0,
                "pedidos_transacional": 0,
                "receita_transacional": 0.0,
                "start_date": _validate_optional_iso_date(start),
                "end_date": _validate_optional_iso_date(end),
            }
        row = records[0]
        return {
            "pedidos": int(row.get("pedidos") or 0),
            "receita_atribuicao": float(row.get("receita_atribuicao") or 0),
            "valor_pedidos": float(row.get("valor_pedidos") or 0),
            "pedidos_transacional": int(row.get("pedidos_transacional") or 0),
            "receita_transacional": float(row.get("receita_transacional") or 0),
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao calcular comparativo CRM: {exc}") from exc


def _sanitize_campanha_nome(value: str) -> str:
    return value.replace("'", "''").replace("\\", "\\\\").strip()[:200]


def _build_campanha_detalhe_sql(
    nome: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    email_opens_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE)
    email_sends_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_SENDS_TABLE)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)
    sms_sends_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_SENDS_TABLE)
    si_purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS
    safe_nome = _sanitize_campanha_nome(nome)

    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)

    if normalized_start and normalized_end:
        period_filter = f"DATE(partitiontime) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) BETWEEN DATE('{normalized_start}') AND CURRENT_DATE()"
        purchase_date_filter = f"DATE(p.purchase_date) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
    elif normalized_start:
        period_filter = f"DATE(partitiontime) >= DATE('{normalized_start}')"
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE('{normalized_start}')"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE('{normalized_start}')"
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE('{normalized_start}')"
    elif normalized_end:
        period_filter = f"DATE(partitiontime) <= DATE('{normalized_end}')"
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') <= DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) <= CURRENT_DATE()"
        purchase_date_filter = f"DATE(p.purchase_date) <= DATE('{normalized_end}')"
    else:
        period_filter = f"DATE(partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)"
        attr_event_time_filter = f"DATE(r.event_time, '{EMARSYS_TZ}') >= DATE_SUB(CURRENT_DATE('{EMARSYS_TZ}'), INTERVAL {lookback} DAY)"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback + 7} DAY)"
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)"

    return f"""
WITH
email_camp AS (
  SELECT
    CAST(id AS STRING) AS campaign_id,
    'email' AS canal,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{email_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND id IS NOT NULL
    AND LOWER(name) LIKE LOWER('%{safe_nome}%')
  GROUP BY 1, 2
),
sms_camp AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    'sms' AS canal,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{sms_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND campaign_id IS NOT NULL
    AND LOWER(name) LIKE LOWER('%{safe_nome}%')
  GROUP BY 1, 2
),
all_camp AS (
  SELECT * FROM email_camp
  UNION ALL
  SELECT * FROM sms_camp
),
email_sends_agg AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    COUNT(DISTINCT message_id) AS enviados
  FROM `{project_id}.{dataset}.{email_sends_table}`
  WHERE {period_filter}
    AND campaign_id IS NOT NULL
    AND message_id IS NOT NULL
  GROUP BY 1
),
email_opens_agg AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    COUNT(DISTINCT message_id) AS aberturas
  FROM `{project_id}.{dataset}.{email_opens_table}`
  WHERE {period_filter}
    AND campaign_id IS NOT NULL
    AND message_id IS NOT NULL
  GROUP BY 1
),
sms_sends_agg AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    COUNT(DISTINCT contact_id) AS enviados
  FROM `{project_id}.{dataset}.{sms_sends_table}`
  WHERE {period_filter}
    AND campaign_id IS NOT NULL
  GROUP BY 1
),
attr_base AS (
  SELECT DISTINCT
    CAST(t.campaign_id AS STRING) AS campaign_id,
    r.order_id,
    t.attributed_amount
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND {attr_event_time_filter}
    AND {attr_partition_filter}
),
si_orders AS (
  SELECT p.order_id, ROUND(SUM(p.sales_amount), 2) AS sales_amount
  FROM `{project_id}.{dataset}.{si_purchases_table}` p
  INNER JOIN (SELECT DISTINCT order_id FROM attr_base) ab USING (order_id)
  WHERE {purchase_date_filter}
  GROUP BY p.order_id
),
attr_agg AS (
  SELECT
    ab.campaign_id,
    COUNT(DISTINCT ab.order_id)         AS pedidos_atribuidos,
    ROUND(SUM(ab.attributed_amount), 2) AS receita_atribuida,
    ROUND(COALESCE(SUM(so.sales_amount), 0), 2) AS receita_influenciada
  FROM attr_base ab
  LEFT JOIN si_orders so USING (order_id)
  GROUP BY 1
)
SELECT
  ac.canal,
  ac.nome_campanha,
  ac.campaign_id,
  CASE WHEN ac.canal = 'email' THEN COALESCE(es.enviados, 0) ELSE COALESCE(ss.enviados, 0) END AS enviados,
  CASE WHEN ac.canal = 'email' THEN COALESCE(eo.aberturas, 0)                                  ELSE NULL END AS aberturas,
  CASE
    WHEN ac.canal = 'email' AND COALESCE(es.enviados, 0) > 0
    THEN ROUND(100.0 * COALESCE(eo.aberturas, 0) / es.enviados, 2)
    ELSE NULL
  END AS taxa_abertura,
  COALESCE(aa.pedidos_atribuidos, 0)    AS pedidos_atribuidos,
  COALESCE(aa.receita_atribuida, 0)     AS receita_atribuida,
  COALESCE(aa.receita_influenciada, 0)  AS receita_influenciada
FROM all_camp ac
LEFT JOIN email_sends_agg es ON ac.canal = 'email' AND ac.campaign_id = es.campaign_id
LEFT JOIN email_opens_agg eo ON ac.canal = 'email' AND ac.campaign_id = eo.campaign_id
LEFT JOIN sms_sends_agg   ss ON ac.canal = 'sms'   AND ac.campaign_id = ss.campaign_id
LEFT JOIN attr_agg        aa ON ac.campaign_id = aa.campaign_id
WHERE ac.nome_campanha IS NOT NULL
ORDER BY aa.receita_atribuida DESC NULLS LAST, ac.nome_campanha
""".strip()


def _build_sms_apuracao_sql(nome: str) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)
    sms_sends_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_SENDS_TABLE)
    si_purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS
    safe_nome = _sanitize_campanha_nome(nome)

    return f"""
WITH
sms_camp AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{sms_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND campaign_id IS NOT NULL
    AND LOWER(name) LIKE LOWER('%{safe_nome}%')
  GROUP BY 1
),
sms_sends_camp AS (
  SELECT DISTINCT
    CAST(ss.campaign_id AS STRING) AS campaign_id,
    ss.contact_id,
    DATE(ss.event_time) AS send_date
  FROM `{project_id}.{dataset}.{sms_sends_table}` ss
  INNER JOIN sms_camp sc ON CAST(ss.campaign_id AS STRING) = sc.campaign_id
  WHERE DATE(ss.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)
),
sms_sends_agg AS (
  SELECT campaign_id, COUNT(DISTINCT contact_id) AS enviados, MIN(send_date) AS dispatch_date
  FROM sms_sends_camp
  GROUP BY 1
),
attr_base AS (
  SELECT DISTINCT
    CAST(t.campaign_id AS STRING) AS campaign_id,
    r.order_id,
    t.attributed_amount
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)
),
attr_agg AS (
  SELECT
    campaign_id,
    COUNT(DISTINCT order_id)         AS pedidos_atribuidos,
    ROUND(SUM(attributed_amount), 2) AS receita_atribuida
  FROM attr_base
  GROUP BY 1
),
post_send_orders AS (
  SELECT DISTINCT ssc.campaign_id, r.order_id
  FROM sms_sends_camp ssc
  INNER JOIN `{project_id}.{dataset}.{revenue_table}` r ON r.contact_id = ssc.contact_id
    AND DATE(r.event_time) BETWEEN ssc.send_date AND DATE_ADD(ssc.send_date, INTERVAL 7 DAY)
  WHERE DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)
),
influencia_agg AS (
  SELECT
    pso.campaign_id,
    COUNT(DISTINCT pso.order_id) AS pedidos_influenciados,
    ROUND(COALESCE(SUM(p.sales_amount), 0), 2) AS receita_influenciada
  FROM post_send_orders pso
  LEFT JOIN `{project_id}.{dataset}.{si_purchases_table}` p ON p.order_id = pso.order_id
    AND DATE(p.purchase_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)
  GROUP BY 1
)
SELECT
  sc.nome_campanha,
  sc.campaign_id,
  COALESCE(ss.enviados, 0)             AS enviados,
  CAST(ss.dispatch_date AS STRING)     AS dispatch_date,
  COALESCE(aa.pedidos_atribuidos, 0)   AS pedidos_atribuidos,
  COALESCE(aa.receita_atribuida, 0)    AS receita_atribuida,
  COALESCE(ia.receita_influenciada, 0) AS receita_influenciada
FROM sms_camp sc
LEFT JOIN sms_sends_agg  ss ON sc.campaign_id = ss.campaign_id
LEFT JOIN attr_agg       aa ON sc.campaign_id = aa.campaign_id
LEFT JOIN influencia_agg ia ON sc.campaign_id = ia.campaign_id
WHERE sc.nome_campanha IS NOT NULL
ORDER BY aa.receita_atribuida DESC NULLS LAST, sc.nome_campanha
""".strip()


def _build_email_apuracao_sql(nome: str) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    email_sends_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_SENDS_TABLE)
    email_opens_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE)
    si_purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS
    safe_nome = _sanitize_campanha_nome(nome)

    return f"""
WITH
email_camp AS (
  SELECT
    CAST(id AS STRING) AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome_campanha
  FROM `{project_id}.{dataset}.{email_campaigns_table}`
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback} DAY)
    AND id IS NOT NULL
    AND LOWER(name) LIKE LOWER('%{safe_nome}%')
  GROUP BY 1
),
email_sends_agg AS (
  SELECT
    CAST(campaign_id AS STRING) AS campaign_id,
    COUNT(DISTINCT message_id) AS enviados,
    CAST(MIN(DATE(partitiontime)) AS STRING) AS start_date,
    CAST(MAX(DATE(partitiontime)) AS STRING) AS end_date
  FROM `{project_id}.{dataset}.{email_sends_table}`
  WHERE DATE(partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)
    AND campaign_id IS NOT NULL AND message_id IS NOT NULL
  GROUP BY 1
),
email_opens_agg AS (
  SELECT CAST(campaign_id AS STRING) AS campaign_id, COUNT(DISTINCT message_id) AS aberturas
  FROM `{project_id}.{dataset}.{email_opens_table}`
  WHERE DATE(partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)
    AND campaign_id IS NOT NULL AND message_id IS NOT NULL
  GROUP BY 1
),
attr_base AS (
  SELECT DISTINCT
    CAST(t.campaign_id AS STRING) AS campaign_id,
    r.order_id,
    t.attributed_amount
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)
),
attr_agg AS (
  SELECT
    campaign_id,
    COUNT(DISTINCT order_id)         AS pedidos_atribuidos,
    ROUND(SUM(attributed_amount), 2) AS receita_atribuida
  FROM attr_base
  GROUP BY 1
),
items_pre AS (
  SELECT
    ab.campaign_id,
    p.product_name,
    p.sales_amount,
    ab.attributed_amount,
    SUM(p.sales_amount) OVER (PARTITION BY ab.campaign_id, p.order_id) AS total_order_sales
  FROM attr_base ab
  INNER JOIN `{project_id}.{dataset}.{si_purchases_table}` p ON p.order_id = ab.order_id
  WHERE DATE(p.purchase_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)
    AND p.sales_amount > 0
),
items_agg AS (
  SELECT
    campaign_id,
    COUNT(*)                                                         AS total_itens,
    COUNTIF(LOWER(COALESCE(product_name, '')) LIKE '%apple%')        AS itens_apple,
    COUNTIF(LOWER(COALESCE(product_name, '')) NOT LIKE '%apple%')    AS itens_nao_apple,
    ROUND(SUM(
      attributed_amount *
      SAFE_DIVIDE(
        CASE WHEN LOWER(COALESCE(product_name, '')) LIKE '%apple%' THEN sales_amount ELSE 0 END,
        total_order_sales
      )
    ), 2) AS receita_apple,
    ROUND(SUM(
      attributed_amount *
      SAFE_DIVIDE(
        CASE WHEN LOWER(COALESCE(product_name, '')) NOT LIKE '%apple%' THEN sales_amount ELSE 0 END,
        total_order_sales
      )
    ), 2) AS receita_nao_apple
  FROM items_pre
  GROUP BY 1
),
apple_prod AS (
  SELECT
    COALESCE(NULLIF(TRIM(ip.product_name), ''), 'Sem nome') AS nome,
    COUNT(*)                                                 AS qtd,
    ROUND(SUM(ip.sales_amount), 2)                          AS receita
  FROM items_pre ip
  INNER JOIN email_camp ec ON ec.campaign_id = ip.campaign_id
  WHERE LOWER(COALESCE(ip.product_name, '')) LIKE '%apple%'
  GROUP BY 1
),
nao_apple_prod AS (
  SELECT
    COALESCE(NULLIF(TRIM(ip.product_name), ''), 'Sem nome') AS nome,
    COUNT(*)                                                 AS qtd,
    ROUND(SUM(ip.sales_amount), 2)                          AS receita
  FROM items_pre ip
  INNER JOIN email_camp ec ON ec.campaign_id = ip.campaign_id
  WHERE LOWER(COALESCE(ip.product_name, '')) NOT LIKE '%apple%'
  GROUP BY 1
),
top_apple_json_cte AS (
  SELECT TO_JSON_STRING(
    ARRAY_AGG(STRUCT(nome, qtd, receita) ORDER BY qtd DESC LIMIT 10)
  ) AS top_apple
  FROM apple_prod
),
top_nao_apple_json_cte AS (
  SELECT TO_JSON_STRING(
    ARRAY_AGG(STRUCT(nome, qtd, receita) ORDER BY qtd DESC LIMIT 10)
  ) AS top_nao_apple
  FROM nao_apple_prod
),
opens_contacts AS (
  SELECT DISTINCT
    CAST(campaign_id AS STRING) AS campaign_id,
    contact_id,
    DATE(event_time) AS open_date
  FROM `{project_id}.{dataset}.{email_opens_table}`
  WHERE DATE(partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)
    AND campaign_id IS NOT NULL AND contact_id IS NOT NULL
),
post_open_orders AS (
  SELECT DISTINCT oc.campaign_id, r.order_id
  FROM opens_contacts oc
  INNER JOIN `{project_id}.{dataset}.{revenue_table}` r ON r.contact_id = oc.contact_id
    AND DATE(r.event_time) BETWEEN oc.open_date AND DATE_ADD(oc.open_date, INTERVAL 7 DAY)
  WHERE DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)
),
influencia_agg AS (
  SELECT
    poo.campaign_id,
    COUNT(DISTINCT poo.order_id) AS pedidos_influenciados,
    ROUND(COALESCE(SUM(p.sales_amount), 0), 2) AS receita_influenciada
  FROM post_open_orders poo
  LEFT JOIN `{project_id}.{dataset}.{si_purchases_table}` p ON p.order_id = poo.order_id
    AND DATE(p.purchase_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)
  GROUP BY 1
)
SELECT
  ec.nome_campanha,
  ec.campaign_id,
  COALESCE(es.enviados, 0)             AS enviados,
  COALESCE(eo.aberturas, 0)            AS aberturas,
  CASE
    WHEN COALESCE(es.enviados, 0) > 0
    THEN ROUND(100.0 * COALESCE(eo.aberturas, 0) / es.enviados, 2)
    ELSE NULL
  END AS taxa_abertura,
  COALESCE(aa.pedidos_atribuidos, 0)   AS pedidos_atribuidos,
  COALESCE(aa.receita_atribuida, 0)    AS receita_atribuida,
  COALESCE(ia.receita_influenciada, 0) AS receita_influenciada,
  COALESCE(itm.total_itens, 0)         AS total_itens,
  COALESCE(itm.itens_apple, 0)         AS itens_apple,
  COALESCE(itm.itens_nao_apple, 0)     AS itens_nao_apple,
  COALESCE(itm.receita_apple, 0)       AS receita_apple,
  COALESCE(itm.receita_nao_apple, 0)   AS receita_nao_apple,
  (SELECT top_apple    FROM top_apple_json_cte)     AS top_apple_json,
  (SELECT top_nao_apple FROM top_nao_apple_json_cte) AS top_nao_apple_json
FROM email_camp ec
LEFT JOIN email_sends_agg es  ON ec.campaign_id = es.campaign_id
LEFT JOIN email_opens_agg eo  ON ec.campaign_id = eo.campaign_id
LEFT JOIN attr_agg        aa  ON ec.campaign_id = aa.campaign_id
LEFT JOIN influencia_agg  ia  ON ec.campaign_id = ia.campaign_id
LEFT JOIN items_agg       itm ON ec.campaign_id = itm.campaign_id
WHERE ec.nome_campanha IS NOT NULL
ORDER BY aa.receita_atribuida DESC NULLS LAST, ec.nome_campanha
""".strip()


@router.get("/sms-apuracao")
def sms_apuracao(
    nome: str = Query(..., min_length=2, max_length=200),
) -> dict[str, Any]:
    try:
        sql = _build_sms_apuracao_sql(nome)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        items = [
            {
                "nome_campanha": str(row.get("nome_campanha") or ""),
                "campaign_id": str(row.get("campaign_id") or ""),
                "dispatch_date": str(row.get("dispatch_date") or ""),
                "enviados": int(row.get("enviados") or 0),
                "pedidos_atribuidos": int(row.get("pedidos_atribuidos") or 0),
                "receita_atribuida": float(row.get("receita_atribuida") or 0),
                "receita_influenciada": float(row.get("receita_influenciada") or 0),
            }
            for row in records
        ]
        return {"items": items, "total": len(items), "nome": nome}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao apurar SMS: {exc}") from exc


@router.get("/email-apuracao")
def email_apuracao(
    nome: str = Query(..., min_length=2, max_length=200),
) -> dict[str, Any]:
    try:
        import json as _json
        sql = _build_email_apuracao_sql(nome)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        items = [
            {
                "nome_campanha": str(row.get("nome_campanha") or ""),
                "campaign_id": str(row.get("campaign_id") or ""),
                "start_date": str(row.get("start_date") or ""),
                "end_date": str(row.get("end_date") or ""),
                "enviados": int(row.get("enviados") or 0),
                "aberturas": int(row.get("aberturas") or 0),
                "taxa_abertura": float(row.get("taxa_abertura") or 0) if row.get("taxa_abertura") is not None else None,
                "pedidos_atribuidos": int(row.get("pedidos_atribuidos") or 0),
                "receita_atribuida": float(row.get("receita_atribuida") or 0),
                "receita_influenciada": float(row.get("receita_influenciada") or 0),
                "total_itens": int(row.get("total_itens") or 0),
                "itens_apple": int(row.get("itens_apple") or 0),
                "itens_nao_apple": int(row.get("itens_nao_apple") or 0),
                "receita_apple": float(row.get("receita_apple") or 0),
                "receita_nao_apple": float(row.get("receita_nao_apple") or 0),
            }
            for row in records
        ]

        first = records[0] if records else {}
        top_apple = _json.loads(first.get("top_apple_json") or "[]")
        top_nao_apple = _json.loads(first.get("top_nao_apple_json") or "[]")

        return {"items": items, "total": len(items), "nome": nome, "top_apple": top_apple, "top_nao_apple": top_nao_apple}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao apurar e-mail: {exc}") from exc


@router.get("/campanha-detalhe")
def campanha_detalhe(
    nome: str = Query(..., min_length=2, max_length=200),
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_campanha_detalhe_sql(nome, start, end)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        items = []
        for row in records:
            items.append({
                "canal": str(row.get("canal") or ""),
                "nome_campanha": str(row.get("nome_campanha") or ""),
                "campaign_id": str(row.get("campaign_id") or ""),
                "enviados": int(row.get("enviados") or 0),
                "aberturas": int(row.get("aberturas") or 0) if row.get("aberturas") is not None else None,
                "taxa_abertura": float(row.get("taxa_abertura") or 0) if row.get("taxa_abertura") is not None else None,
                "pedidos_atribuidos": int(row.get("pedidos_atribuidos") or 0),
                "receita_atribuida": float(row.get("receita_atribuida") or 0),
                "receita_influenciada": float(row.get("receita_influenciada") or 0),
            })
        return {
            "items": items,
            "total": len(items),
            "nome": nome,
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao apurar campanha: {exc}") from exc


def _build_daily_revenue_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    """Receita total iPlace e receita atribuída Emarsys agrupadas por dia."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)

    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)

    if normalized_start and normalized_end:
        purchase_date_filter = f"DATE(p.purchase_date) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
    elif normalized_start:
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE('{normalized_start}')"
    elif normalized_end:
        purchase_date_filter = f"DATE(p.purchase_date) <= DATE('{normalized_end}')"
    else:
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"

    attr_event_time_filter, attr_partition_filter = _build_attribution_date_filters(normalized_start, normalized_end, "r")

    return f"""
WITH orders_net AS (
  SELECT
    order_id,
    DATE(MIN(purchase_date)) AS purchase_date,
    ROUND(SUM(sales_amount), 2) AS receita_liquida
  FROM `{project_id}.{dataset}.{purchases_table}` p
  WHERE {purchase_date_filter}
  GROUP BY order_id
),
attribution_per_order AS (
  SELECT
    order_id,
    ROUND(MAX(COALESCE(
      (SELECT SUM(t.attributed_amount)
       FROM UNNEST(r.treatments) AS t
       WHERE t.attributed_amount > 0),
      0
    )), 2) AS receita_atribuida
  FROM `{project_id}.{dataset}.{revenue_table}` r
  WHERE {attr_event_time_filter}
    AND {attr_partition_filter}
  GROUP BY order_id
)
SELECT
  o.purchase_date                              AS dia,
  COUNT(DISTINCT o.order_id)                   AS pedidos,
  ROUND(SUM(o.receita_liquida), 2)             AS total_iplace,
  ROUND(SUM(COALESCE(a.receita_atribuida, 0)), 2) AS receita_atribuida
FROM orders_net o
LEFT JOIN attribution_per_order a USING (order_id)
GROUP BY o.purchase_date
ORDER BY o.purchase_date
"""


@router.get("/emarsys/daily-revenue")
def emarsys_daily_revenue(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_daily_revenue_sql(start, end)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        items = []
        for row in records:
            dia = row.get("dia")
            items.append({
                "dia": str(dia) if dia is not None else None,
                "pedidos": int(row.get("pedidos") or 0),
                "total_iplace": float(row.get("total_iplace") or 0),
                "receita_atribuida": float(row.get("receita_atribuida") or 0),
            })
        return {
            "items": items,
            "start_date": _validate_optional_iso_date(start),
            "end_date": _validate_optional_iso_date(end),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao carregar receita diária: {exc}") from exc


# ---------------------------------------------------------------------------
# Perfil do Cliente — visão macro da base
# ---------------------------------------------------------------------------

def _build_perfil_summary_sql(start_date: str, end_date: str) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    t = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    return f"""
WITH
orders_period AS (
  SELECT
    si_contact_id,
    order_id,
    DATE(MIN(purchase_date)) AS purchase_date,
    SUM(sales_amount) AS order_value
  FROM `{project_id}.{dataset}.{t}`
  WHERE sales_amount > 0
    AND DATE(purchase_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
  GROUP BY si_contact_id, order_id
),
global_first AS (
  SELECT si_contact_id, DATE(MIN(purchase_date)) AS first_ever
  FROM `{project_id}.{dataset}.{t}`
  WHERE sales_amount > 0
    AND DATE(purchase_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 5 YEAR)
  GROUP BY si_contact_id
),
customer_metrics AS (
  SELECT
    op.si_contact_id,
    COUNT(DISTINCT op.order_id) AS freq,
    ROUND(SUM(op.order_value), 2) AS monetary,
    ROUND(AVG(op.order_value), 2) AS avg_ticket,
    DATE_DIFF(DATE('{end_date}'), MAX(op.purchase_date), DAY) AS recency_days,
    MIN(op.purchase_date) AS first_in_period,
    gf.first_ever,
    DATE_DIFF(DATE('{end_date}'), gf.first_ever, DAY) AS days_as_customer
  FROM orders_period op
  LEFT JOIN global_first gf USING (si_contact_id)
  GROUP BY op.si_contact_id, gf.first_ever
),
rfm_scores AS (
  SELECT *,
    NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,
    NTILE(5) OVER (ORDER BY freq ASC)           AS f_score,
    NTILE(5) OVER (ORDER BY monetary ASC)       AS m_score
  FROM customer_metrics
),
rfm_segments AS (
  SELECT *,
    CASE
      WHEN r_score = 5 AND f_score >= 4                        THEN 'Campeoes'
      WHEN f_score >= 4 AND r_score >= 3                       THEN 'Clientes Fieis'
      WHEN r_score = 5 AND f_score <= 2                        THEN 'Clientes Recentes'
      WHEN r_score <= 2 AND f_score >= 3 AND m_score >= 3      THEN 'Em Risco'
      WHEN r_score = 1                                         THEN 'Inativos'
      ELSE 'Regulares'
    END AS segmento
  FROM rfm_scores
)
SELECT
  COUNT(*)                                                     AS total_clientes,
  COUNTIF(first_in_period = first_ever)                        AS novos_clientes,
  ROUND(AVG(avg_ticket), 2)                                    AS ticket_medio,
  ROUND(AVG(freq), 2)                                          AS freq_media,
  ROUND(SUM(monetary), 2)                                      AS receita_total,
  COUNTIF(days_as_customer IS NULL OR days_as_customer < 90)   AS mat_3m,
  COUNTIF(days_as_customer BETWEEN 90 AND 364)                 AS mat_3m_1a,
  COUNTIF(days_as_customer BETWEEN 365 AND 1094)               AS mat_1a_3a,
  COUNTIF(days_as_customer >= 1095)                            AS mat_3a_mais,
  COUNTIF(recency_days <= 30)                                  AS rec_30d,
  COUNTIF(recency_days BETWEEN 31 AND 60)                      AS rec_60d,
  COUNTIF(recency_days BETWEEN 61 AND 90)                      AS rec_90d,
  COUNTIF(recency_days BETWEEN 91 AND 180)                     AS rec_180d,
  COUNTIF(recency_days > 180)                                  AS rec_mais180,
  COUNTIF(segmento = 'Campeoes')                               AS rfm_campeoes,
  COUNTIF(segmento = 'Clientes Fieis')                         AS rfm_fieis,
  COUNTIF(segmento = 'Clientes Recentes')                      AS rfm_recentes,
  COUNTIF(segmento = 'Em Risco')                               AS rfm_em_risco,
  COUNTIF(segmento = 'Inativos')                               AS rfm_inativos,
  COUNTIF(segmento = 'Regulares')                              AS rfm_regulares
FROM rfm_segments
""".strip()


def _build_perfil_produtos_sql(start_date: str, end_date: str) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    t = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    return f"""
SELECT
  COALESCE(NULLIF(TRIM(product_name), ''), 'Sem nome') AS produto,
  COUNT(DISTINCT order_id)                             AS pedidos,
  ROUND(SUM(sales_amount), 2)                          AS receita
FROM `{project_id}.{dataset}.{t}`
WHERE sales_amount > 0
  AND DATE(purchase_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
GROUP BY 1
ORDER BY receita DESC
LIMIT 30
""".strip()


def _build_perfil_categorias_sql(start_date: str, end_date: str) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    t = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    return f"""
WITH categorized AS (
  SELECT
    CASE
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(product_name,'')), r'IPHONE')                        THEN 'iPhone'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(product_name,'')), r'IPAD')                          THEN 'iPad'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(product_name,'')), r'MACBOOK|IMAC|MAC MINI|MAC PRO|MAC STUDIO') THEN 'Mac'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(product_name,'')), r'APPLE WATCH')                   THEN 'Apple Watch'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(product_name,'')), r'AIRPOD')                        THEN 'AirPods'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(product_name,'')), r'APPLE TV|APPLETV|HOMEPOD')      THEN 'Apple TV / HomePod'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(product_name,'')), r'SAMSUNG')                       THEN 'Samsung'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(product_name,'')), r'XIAOMI|MOTOROLA|LG |SONY|PHILIPS|BOSE|BEATS|JABRA|JBL') THEN 'Outras Marcas'
      ELSE 'Acessórios / Outros'
    END AS categoria,
    order_id,
    sales_amount
  FROM `{project_id}.{dataset}.{t}`
  WHERE sales_amount > 0
    AND DATE(purchase_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
)
SELECT
  categoria,
  COUNT(DISTINCT order_id)  AS pedidos,
  ROUND(SUM(sales_amount), 2) AS receita
FROM categorized
GROUP BY 1
ORDER BY receita DESC
""".strip()


@router.get("/perfil-cliente")
def perfil_cliente(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    end_date = _validate_optional_iso_date(end) or str(date.today())
    start_date = _validate_optional_iso_date(start) or str(date.today() - timedelta(days=89))

    try:
        summary_sql = _build_perfil_summary_sql(start_date, end_date)
        produtos_sql = _build_perfil_produtos_sql(start_date, end_date)
        categorias_sql = _build_perfil_categorias_sql(start_date, end_date)

        loc = EMARSYS_OPEN_DATA_LOCATION or None
        proj = EMARSYS_OPEN_DATA_PROJECT_ID

        with ThreadPoolExecutor(max_workers=3) as pool:
            f_summary = pool.submit(run_bigquery_records, summary_sql, proj, location=loc, timeout=55)
            f_produtos = pool.submit(run_bigquery_records, produtos_sql, proj, location=loc, timeout=25)
            f_categorias = pool.submit(run_bigquery_records, categorias_sql, proj, location=loc, timeout=25)
            summary_records = f_summary.result()
            produtos_records = f_produtos.result()
            categorias_records = f_categorias.result()

        s = summary_records[0] if summary_records else {}
        total = int(s.get("total_clientes") or 0)
        novos = int(s.get("novos_clientes") or 0)

        all_produtos = [
            {
                "produto": str(r.get("produto") or ""),
                "pedidos": int(r.get("pedidos") or 0),
                "receita": float(r.get("receita") or 0),
            }
            for r in produtos_records
        ]
        top_por_receita = sorted(all_produtos, key=lambda x: x["receita"], reverse=True)[:15]
        top_por_quantidade = sorted(all_produtos, key=lambda x: x["pedidos"], reverse=True)[:15]

        return {
            "start_date": start_date,
            "end_date": end_date,
            "resumo": {
                "total_clientes": total,
                "novos_clientes": novos,
                "recorrentes": total - novos,
                "ticket_medio": float(s.get("ticket_medio") or 0),
                "freq_media": float(s.get("freq_media") or 0),
                "receita_total": float(s.get("receita_total") or 0),
            },
            "maturidade": [
                {"faixa": "< 3 meses",   "qtd": int(s.get("mat_3m") or 0)},
                {"faixa": "3m - 1 ano",  "qtd": int(s.get("mat_3m_1a") or 0)},
                {"faixa": "1 - 3 anos",  "qtd": int(s.get("mat_1a_3a") or 0)},
                {"faixa": "> 3 anos",    "qtd": int(s.get("mat_3a_mais") or 0)},
            ],
            "recencia": [
                {"faixa": "Últimos 30d",  "qtd": int(s.get("rec_30d") or 0)},
                {"faixa": "31-60 dias",   "qtd": int(s.get("rec_60d") or 0)},
                {"faixa": "61-90 dias",   "qtd": int(s.get("rec_90d") or 0)},
                {"faixa": "91-180 dias",  "qtd": int(s.get("rec_180d") or 0)},
                {"faixa": "> 180 dias",   "qtd": int(s.get("rec_mais180") or 0)},
            ],
            "rfm": [
                {"segmento": "Campeões",          "qtd": int(s.get("rfm_campeoes") or 0)},
                {"segmento": "Clientes Fiéis",    "qtd": int(s.get("rfm_fieis") or 0)},
                {"segmento": "Clientes Recentes", "qtd": int(s.get("rfm_recentes") or 0)},
                {"segmento": "Em Risco",          "qtd": int(s.get("rfm_em_risco") or 0)},
                {"segmento": "Inativos",          "qtd": int(s.get("rfm_inativos") or 0)},
                {"segmento": "Regulares",         "qtd": int(s.get("rfm_regulares") or 0)},
            ],
            "top_produtos": top_por_receita,
            "top_produtos_quantidade": top_por_quantidade,
            "top_categorias": [
                {
                    "categoria": str(r.get("categoria") or ""),
                    "pedidos": int(r.get("pedidos") or 0),
                    "receita": float(r.get("receita") or 0),
                }
                for r in categorias_records
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao carregar perfil do cliente: {exc}") from exc


# ---------------------------------------------------------------------------
# Top Produtos e Categorias — Pedidos atribuídos
# ---------------------------------------------------------------------------

def _attributed_orders_cte(start_date: str, end_date: str, canal_order_ids: list | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    tz = EMARSYS_TZ
    order_id_filter = _make_order_id_filter(canal_order_ids, "CAST(r.order_id AS STRING)")
    return f"""attributed AS (
  SELECT DISTINCT r.order_id
  FROM `{project_id}.{dataset}.{revenue_table}` r
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND DATE(r.event_time, '{tz}') BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND DATE(r.partitiontime) BETWEEN DATE_SUB(DATE('{start_date}'), INTERVAL 1 DAY)
                                   AND DATE_ADD(DATE('{end_date}'), INTERVAL 1 DAY)
    AND r.order_id IS NOT NULL
    {order_id_filter}
)"""


def _build_atribuida_top_produtos_sql(start_date: str, end_date: str, canal_order_ids: list | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    order_id_filter = _make_order_id_filter(canal_order_ids, "CAST(p.order_id AS STRING)")
    return f"""
WITH purchases_deduped AS (
  -- Deduplica por (order_id, product_name): evita reprocessamentos do Emarsys
  -- e colisão de filial caso o order_id não seja globalmente único
  SELECT
    CAST(p.order_id AS STRING)                            AS order_id,
    COALESCE(NULLIF(TRIM(p.product_name), ''), 'Sem nome') AS product_name,
    MAX(p.sales_amount)                                   AS sales_amount
  FROM `{project_id}.{dataset}.{purchases_table}` p
  WHERE p.sales_amount > 0
    AND DATE(p.purchase_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    {order_id_filter}
  GROUP BY 1, 2
)
SELECT
  product_name                     AS produto,
  COUNT(DISTINCT order_id)         AS pedidos,
  ROUND(SUM(sales_amount), 2)      AS receita
FROM purchases_deduped
GROUP BY 1
ORDER BY receita DESC
LIMIT 10
""".strip()


def _build_atribuida_top_categorias_sql(start_date: str, end_date: str, canal_order_ids: list | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    order_id_filter = _make_order_id_filter(canal_order_ids, "CAST(p.order_id AS STRING)")
    return f"""
WITH
purchases_deduped AS (
  -- Deduplica por (order_id, product_name) antes de categorizar
  SELECT
    CAST(p.order_id AS STRING)                            AS order_id,
    COALESCE(NULLIF(TRIM(p.product_name), ''), 'Sem nome') AS product_name,
    MAX(p.sales_amount)                                   AS sales_amount
  FROM `{project_id}.{dataset}.{purchases_table}` p
  WHERE p.sales_amount > 0
    AND DATE(p.purchase_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    {order_id_filter}
  GROUP BY 1, 2
),
categorized AS (
  SELECT
    CASE
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'IPHONE')                        THEN 'iPhone'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'IPAD')                          THEN 'iPad'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'MACBOOK|IMAC|MAC MINI|MAC PRO|MAC STUDIO') THEN 'Mac'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'APPLE WATCH')                   THEN 'Apple Watch'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'AIRPOD')                        THEN 'AirPods'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'APPLE TV|APPLETV|HOMEPOD')      THEN 'Apple TV / HomePod'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'SAMSUNG')                       THEN 'Samsung'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'XIAOMI|MOTOROLA|LG |SONY|PHILIPS|BOSE|BEATS|JABRA|JBL') THEN 'Outras Marcas'
      ELSE 'Acessórios / Outros'
    END AS categoria,
    order_id,
    sales_amount
  FROM purchases_deduped
)
SELECT
  categoria,
  COUNT(DISTINCT order_id)    AS pedidos,
  ROUND(SUM(sales_amount), 2) AS receita
FROM categorized
GROUP BY 1
ORDER BY receita DESC
""".strip()


@router.get("/emarsys/atribuida-top-produtos")
def atribuida_top_produtos(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    canal: str = Query(default=""),
) -> list[dict]:
    start_date = _validate_optional_iso_date(start) or str(date.today())
    end_date = _validate_optional_iso_date(end) or start_date
    canal_order_ids = _get_canal_order_ids(canal.upper().strip() if canal else "", start_date, end_date)
    try:
        sql = _build_atribuida_top_produtos_sql(start_date, end_date, canal_order_ids)
        records = run_bigquery_records(
            sql, EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None, timeout=40,
        )
        return [
            {"produto": str(r.get("produto") or ""), "pedidos": int(r.get("pedidos") or 0), "receita": float(r.get("receita") or 0)}
            for r in records
        ]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao carregar top produtos atribuídos: {exc}") from exc


@router.get("/emarsys/atribuida-top-categorias")
def atribuida_top_categorias(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    canal: str = Query(default=""),
) -> list[dict]:
    start_date = _validate_optional_iso_date(start) or str(date.today())
    end_date = _validate_optional_iso_date(end) or start_date
    canal_order_ids = _get_canal_order_ids(canal.upper().strip() if canal else "", start_date, end_date)
    try:
        sql = _build_atribuida_top_categorias_sql(start_date, end_date, canal_order_ids)
        records = run_bigquery_records(
            sql, EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None, timeout=40,
        )
        return [
            {"categoria": str(r.get("categoria") or ""), "pedidos": int(r.get("pedidos") or 0), "receita": float(r.get("receita") or 0)}
            for r in records
        ]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao carregar top categorias atribuídas: {exc}") from exc


# ---------------------------------------------------------------------------
# Receita Atribuída × Canal (Base Vendas via CPF)
# ---------------------------------------------------------------------------

def _build_attributed_cpfs_sql(start_date: str, end_date: str) -> str:
    """Retorna CPFs normalizados dos clientes com pedidos atribuídos no período."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    si_purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    contacts_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE)
    tz = EMARSYS_TZ
    return f"""
WITH
attributed_orders AS (
  SELECT DISTINCT r.order_id
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND DATE(r.event_time, '{tz}') BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND DATE(r.partitiontime) BETWEEN DATE('{start_date}') AND CURRENT_DATE()
),
attributed_si_contacts AS (
  SELECT DISTINCT CAST(p.si_contact_id AS STRING) AS si_contact_id
  FROM `{project_id}.{dataset}.{si_purchases_table}` p
  INNER JOIN attributed_orders ao ON p.order_id = ao.order_id
  WHERE p.si_contact_id IS NOT NULL
    AND DATE(p.purchase_date) BETWEEN DATE_SUB(DATE('{start_date}'), INTERVAL 7 DAY)
                                  AND DATE_ADD(DATE('{end_date}'), INTERVAL 7 DAY)
),
-- Um CPF por si_contact_id (si_contacts pode ter múltiplas linhas por contato)
one_cpf_per_contact AS (
  SELECT
    CAST(c.si_contact_id AS STRING) AS si_contact_id,
    ARRAY_AGG(
      CASE
        WHEN REGEXP_CONTAINS(REGEXP_REPLACE(LOWER(CAST(c.external_id AS STRING)), r'[^0-9a-z]', ''), r'^[0-9]+$')
          AND LENGTH(REGEXP_REPLACE(LOWER(CAST(c.external_id AS STRING)), r'[^0-9a-z]', '')) < 11
        THEN LPAD(REGEXP_REPLACE(LOWER(CAST(c.external_id AS STRING)), r'[^0-9a-z]', ''), 11, '0')
        ELSE REGEXP_REPLACE(LOWER(CAST(c.external_id AS STRING)), r'[^0-9a-z]', '')
      END
      IGNORE NULLS ORDER BY c.external_id LIMIT 1
    )[SAFE_OFFSET(0)] AS cpf_normalized
  FROM `{project_id}.{dataset}.{contacts_table}` c
  INNER JOIN attributed_si_contacts a ON CAST(c.si_contact_id AS STRING) = a.si_contact_id
  WHERE c.external_id IS NOT NULL AND TRIM(CAST(c.external_id AS STRING)) != ''
  GROUP BY c.si_contact_id
)
SELECT cpf_normalized
FROM one_cpf_per_contact
WHERE cpf_normalized IS NOT NULL AND cpf_normalized != ''
""".strip()


@router.get("/emarsys/data-delay")
def emarsys_data_delay() -> dict[str, Any]:
    """Retorna a última data de evento disponível no BigQuery (para exibir aviso de delay)."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    tz = EMARSYS_TZ
    sql = f"""
SELECT
  MAX(DATE(partitiontime))                        AS ultima_carga,
  MAX(DATE(event_time, '{tz}'))                   AS ultimo_evento
FROM `{project_id}.{dataset}.{revenue_table}`
WHERE DATE(partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 5 DAY)
""".strip()
    try:
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None, timeout=15)
        row = records[0] if records else {}
        return {
            "ultima_carga": str(row.get("ultima_carga") or ""),
            "ultimo_evento": str(row.get("ultimo_evento") or ""),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao verificar delay: {exc}") from exc


@router.get("/emarsys/receita-atribuida-canal")
def receita_atribuida_canal(
    start: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    """Canal/filial breakdown da receita atribuída — cruzamento order_id × vendas_iplace."""
    start_date = _validate_optional_iso_date(start)
    end_date = _validate_optional_iso_date(end)
    if not start_date or not end_date:
        raise HTTPException(status_code=400, detail="Informe data de inicio e fim.")

    if not BASE_VENDAS_BQ_PROJECT:
        raise HTTPException(status_code=500, detail="BASE_VENDAS_BQ_PROJECT nao configurado.")

    try:
        # Step 1: order_id + attributed_amount do Emarsys (com cache)
        cache_key = f"canal_orders:{start_date}:{end_date}"
        order_amounts: dict[str, float] | None = _cpf_cache_get(cache_key)  # type: ignore[assignment]
        if order_amounts is None:
            sql = _build_attributed_orders_amounts_sql(start_date, end_date)
            records = run_bigquery_records(
                sql,
                EMARSYS_OPEN_DATA_PROJECT_ID,
                location=EMARSYS_OPEN_DATA_LOCATION or None,
                timeout=25,
            )
            order_amounts = {
                str(r["order_id"]): float(r.get("attributed_amount") or 0)
                for r in records
                if r.get("order_id")
            }
            _cpf_cache_set(cache_key, order_amounts)  # type: ignore[arg-type]

        if not order_amounts:
            return {"canal": [], "filial": [], "total_pedidos_crm": 0,
                    "matched_rows": 0, "start_date": start_date, "end_date": end_date}

        # Step 2: canal/filial de cada pedido em vendas_iplace
        bv_sql = _build_vendas_canal_filial_sql(set(order_amounts.keys()))
        bv_records = run_bigquery_records(
            bv_sql, BASE_VENDAS_BQ_PROJECT,
            location=BASE_VENDAS_BQ_LOCATION or None, timeout=30,
        )

        # Step 3: agrupa candidatos por order_id (pode ter >1 linha quando mesmo número
        # existe em filiais/canais diferentes) e desambigua pelo valor mais próximo
        from collections import defaultdict
        candidates: dict[str, list[dict]] = defaultdict(list)
        for r in bv_records:
            oid = str(r.get("order_id") or "")
            if not oid:
                continue
            candidates[oid].append({
                "canal": str(r.get("canal") or "Pendente de Atribuição").strip() or "Pendente de Atribuição",
                "filial": str(r.get("codigo_filial") or "(sem filial)").strip() or "(sem filial)",
                "vlr_captados": float(r.get("vlr_captados") or 0),
            })

        canal_groups: dict[str, dict[str, Any]] = {}
        filial_groups: dict[str, dict[str, Any]] = {}
        matched_order_ids: set[str] = set()

        for order_id, cands in candidates.items():
            amount = order_amounts.get(order_id, 0.0)
            best = cands[0] if len(cands) == 1 else min(cands, key=lambda c: abs(c["vlr_captados"] - amount))
            canal = best["canal"]
            filial = best["filial"]
            matched_order_ids.add(order_id)

            if canal not in canal_groups:
                canal_groups[canal] = {"canal": canal, "linhas": 0, "receita": 0.0}
            canal_groups[canal]["linhas"] += 1
            canal_groups[canal]["receita"] += amount

            filial_key = f"{canal}|{filial}"
            if filial_key not in filial_groups:
                store_info = FILIAL_REGIONAL_MAP.get(filial)
                filial_groups[filial_key] = {
                    "canal": canal,
                    "codigo_filial": filial,
                    "centro_sap": store_info["centro_sap"] if store_info else f"LJ{filial.zfill(3)}",
                    "nome": store_info["nome"] if store_info else "",
                    "regional": store_info["regional"] if store_info else "Outros",
                    "linhas": 0,
                    "receita": 0.0,
                }
            filial_groups[filial_key]["linhas"] += 1
            filial_groups[filial_key]["receita"] += amount

        # Pedidos sem match em vendas_iplace: soma em canal/filial "desconhecido"
        for order_id, amount in order_amounts.items():
            if order_id in matched_order_ids:
                continue
            canal_groups.setdefault("Pendente de Atribuição", {"canal": "Pendente de Atribuição", "linhas": 0, "receita": 0.0})
            canal_groups["Pendente de Atribuição"]["linhas"] += 1
            canal_groups["Pendente de Atribuição"]["receita"] += amount
            fk = "Pendente de Atribuição|(sem filial)"
            if fk not in filial_groups:
                filial_groups[fk] = {"canal": "Pendente de Atribuição", "codigo_filial": "(sem filial)",
                                     "centro_sap": "", "nome": "", "regional": "Outros",
                                     "linhas": 0, "receita": 0.0}
            filial_groups[fk]["linhas"] += 1
            filial_groups[fk]["receita"] += amount

        canal_list = sorted(
            [{"canal": g["canal"], "linhas": g["linhas"], "receita": round(g["receita"], 2)}
             for g in canal_groups.values()],
            key=lambda x: -x["receita"] if x["receita"] else -x["linhas"],
        )
        filial_list = sorted(
            [{**g, "receita": round(g["receita"], 2)} for g in filial_groups.values()],
            key=lambda x: -x["receita"] if x["receita"] else -x["linhas"],
        )

        return {
            "canal": canal_list,
            "filial": filial_list,
            "total_pedidos_crm": len(order_amounts),
            "matched_rows": len(matched_order_ids),
            "start_date": start_date,
            "end_date": end_date,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao calcular canal da receita atribuida: {exc}") from exc


@router.get("/emarsys/receita-atribuida-canal/sem-canal")
def receita_atribuida_sem_canal(
    start: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> list[dict[str, Any]]:
    """Pedidos atribuídos no período que não encontraram match em vendas_iplace."""
    start_date = _validate_optional_iso_date(start)
    end_date = _validate_optional_iso_date(end)
    if not start_date or not end_date:
        raise HTTPException(status_code=400, detail="Informe data de inicio e fim.")
    if not BASE_VENDAS_BQ_PROJECT:
        raise HTTPException(status_code=500, detail="BASE_VENDAS_BQ_PROJECT nao configurado.")

    try:
        project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
        dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
        revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
        contacts_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE)
        tz = EMARSYS_TZ

        # Step 1: busca pedidos atribuídos com dados completos + external_id via si_contacts
        detail_sql = f"""
WITH attr_orders AS (
  SELECT
    r.order_id,
    r.contact_id,
    MIN(DATE(r.event_time, '{tz}'))          AS purchase_date,
    ROUND(SUM(t.attributed_amount), 2)       AS attributed_amount,
    STRING_AGG(DISTINCT LOWER(t.channel)
      ORDER BY LOWER(t.channel))             AS channels,
    STRING_AGG(DISTINCT CAST(t.campaign_id AS STRING)
      ORDER BY CAST(t.campaign_id AS STRING)) AS campaign_ids
  FROM `{project_id}.{dataset}.{revenue_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND DATE(r.event_time, '{tz}') BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND DATE(r.partitiontime) BETWEEN DATE('{start_date}') AND CURRENT_DATE()
    AND r.order_id IS NOT NULL
  GROUP BY r.order_id, r.contact_id
),
contacts AS (
  SELECT contact_id, ANY_VALUE(external_id) AS external_id
  FROM `{project_id}.{dataset}.{contacts_table}`
  WHERE contact_id IS NOT NULL
  GROUP BY contact_id
)
SELECT
  ao.order_id,
  ao.contact_id,
  c.external_id,
  ao.purchase_date,
  ao.attributed_amount,
  ao.channels,
  ao.campaign_ids
FROM attr_orders ao
LEFT JOIN contacts c ON c.contact_id = ao.contact_id
ORDER BY ao.attributed_amount DESC
""".strip()

        detail_records = run_bigquery_records(
            detail_sql, EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None, timeout=35,
        )

        # Step 2: quais order_ids têm match em vendas_iplace?
        all_order_ids = {str(r["order_id"]) for r in detail_records if r.get("order_id")}
        if not all_order_ids:
            return []

        bv_sql = _build_vendas_canal_filial_sql(all_order_ids)
        bv_records = run_bigquery_records(
            bv_sql, BASE_VENDAS_BQ_PROJECT,
            location=BASE_VENDAS_BQ_LOCATION or None, timeout=30,
        )
        matched_ids = {str(r["order_id"]) for r in bv_records if r.get("order_id")}

        # Step 3: retorna apenas os sem match
        result = []
        for r in detail_records:
            oid = str(r.get("order_id") or "")
            if oid in matched_ids:
                continue
            result.append({
                "order_id":         oid,
                "contact_id":       r.get("contact_id"),
                "external_id":      r.get("external_id"),
                "purchase_date":    str(r.get("purchase_date") or ""),
                "attributed_amount": float(r.get("attributed_amount") or 0),
                "channels":         r.get("channels"),
                "campaign_ids":     r.get("campaign_ids"),
            })
        return result

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao exportar sem-canal: {exc}") from exc


@router.get("/emarsys/conversao-7dias")
def conversao_7dias(
    start: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> list[dict[str, Any]]:
    """Curva de conversão: pedidos atribuídos agrupados por dias após o gatilho CRM (1-7)."""
    start_date = _validate_optional_iso_date(start)
    end_date = _validate_optional_iso_date(end)
    if not start_date or not end_date:
        raise HTTPException(status_code=400, detail="Informe data de inicio e fim.")

    try:
        project_id   = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
        dataset      = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
        rev_table    = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
        sms_table    = _quote_identifier(EMARSYS_OPEN_DATA_SMS_SENDS_TABLE)
        email_table  = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE)
        tz           = EMARSYS_TZ

        sql = f"""
WITH
-- Todos os treatments atribuídos, sem QUALIFY — um pedido pode ter SMS e email
all_treatments AS (
  SELECT
    r.order_id,
    r.contact_id,
    DATE(r.event_time, '{tz}')    AS purchase_date,
    CAST(t.campaign_id AS STRING) AS campaign_id,
    LOWER(t.channel)              AS channel,
    ROUND(t.attributed_amount, 2) AS attributed_amount
  FROM `{project_id}.{dataset}.{rev_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND DATE(r.event_time, '{tz}') BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND DATE(r.partitiontime) BETWEEN DATE('{start_date}') AND CURRENT_DATE()
    AND r.order_id IS NOT NULL
    AND LOWER(t.channel) IN ('sms', 'email')
),
-- Receita total por pedido (soma todos os treatments)
order_receita AS (
  SELECT r.order_id,
    MAX(DATE(r.event_time, '{tz}'))               AS purchase_date,
    MAX(r.contact_id)                              AS contact_id,
    ROUND(SUM(t.attributed_amount), 2)             AS attributed_amount
  FROM `{project_id}.{dataset}.{rev_table}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND t.attributed_amount > 0
    AND DATE(r.event_time, '{tz}') BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND DATE(r.partitiontime) BETWEEN DATE('{start_date}') AND CURRENT_DATE()
    AND r.order_id IS NOT NULL
  GROUP BY r.order_id
),
-- Melhor gatilho SMS por (pedido, campanha): mais recente dentro de 1-7 dias
sms_trigger AS (
  SELECT a.order_id, MAX(DATE(ss.event_time)) AS trigger_date
  FROM all_treatments a
  JOIN `{project_id}.{dataset}.{sms_table}` ss
    ON ss.contact_id = a.contact_id
    AND CAST(ss.campaign_id AS STRING) = a.campaign_id
    AND a.channel = 'sms'
    AND DATE_DIFF(a.purchase_date, DATE(ss.event_time), DAY) BETWEEN 1 AND 7
    AND DATE(ss.partitiontime)
        BETWEEN DATE_SUB(DATE('{start_date}'), INTERVAL 8 DAY)
            AND DATE_ADD(DATE('{end_date}'), INTERVAL 1 DAY)
  GROUP BY a.order_id
),
-- Melhor gatilho email por pedido
email_trigger AS (
  SELECT a.order_id, MAX(DATE(eo.event_time)) AS trigger_date
  FROM all_treatments a
  JOIN `{project_id}.{dataset}.{email_table}` eo
    ON eo.contact_id = a.contact_id
    AND CAST(eo.campaign_id AS STRING) = a.campaign_id
    AND a.channel = 'email'
    AND DATE_DIFF(a.purchase_date, DATE(eo.event_time), DAY) BETWEEN 1 AND 7
    AND DATE(eo.partitiontime)
        BETWEEN DATE_SUB(DATE('{start_date}'), INTERVAL 8 DAY)
            AND DATE_ADD(DATE('{end_date}'), INTERVAL 1 DAY)
  GROUP BY a.order_id
)
SELECT
  DATE_DIFF(o.purchase_date,
            COALESCE(st.trigger_date, et.trigger_date), DAY) AS dia,
  COUNT(DISTINCT o.order_id)                                  AS pedidos,
  ROUND(SUM(o.attributed_amount), 2)                          AS receita
FROM order_receita o
LEFT JOIN sms_trigger   st ON st.order_id = o.order_id
LEFT JOIN email_trigger et ON et.order_id = o.order_id
WHERE COALESCE(st.trigger_date, et.trigger_date) IS NOT NULL
GROUP BY dia
HAVING dia BETWEEN 1 AND 7
ORDER BY dia
""".strip()

        records = run_bigquery_records(
            sql, EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None, timeout=45,
        )

        # Garante todos os dias 1-7, mesmo sem pedidos
        by_dia = {int(r["dia"]): r for r in records if r.get("dia")}
        return [
            {
                "dia":     d,
                "label":   f"Dia {d}",
                "pedidos": int(by_dia[d]["pedidos"]) if d in by_dia else 0,
                "receita": float(by_dia[d]["receita"]) if d in by_dia else 0.0,
            }
            for d in range(1, 8)
        ]

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao calcular conversao 7 dias: {exc}") from exc


# ---------------------------------------------------------------------------
# Filial → Regional mapping (from Filiais e numero sap iPlace lojas.csv)
# Key = codigo_filial as stored in Base Vendas (LJ number without leading zeros)
# ---------------------------------------------------------------------------
_FILIAL_CSV = [
    ("LJ084","IGUATEMI CAXIAS - RS","R1"),("LJ085","IGUATEMI POA - RS","R1"),
    ("LJ090","VILLA ROMANA - SC","R1"),("LJ093","PARK SHOPP BRASILIA - DF","R6"),
    ("LJ096","BH SHOPPING - MG","R2"),("LJ094","BARRA SUL POA - RS","R1"),
    ("LJ102","BOURBON - SP","R5"),("LJ106","SAO CAETANO - SP","R4"),
    ("LJ107","CAMPO GRANDE - MS","R6"),("LJ109","SP MOOCA - SP","R5"),
    ("LJ158","SP VILLA LOBOS - SP","R5"),("LJ157","SP IBIRAPUERA - SP","R5"),
    ("LJ155","IGUATEMI CAMPINAS - SP","R2"),("LJ156","SP ELDORADO - SP","R5"),
    ("LJ163","SP ANALIA FRANCO - SP","R5"),("LJ161","IGUATEMI ALPHAVILLE - SP","R4"),
    ("LJ110","SP IGUATEMI JK - SP","R5"),("LJ111","BRASILIA SHOPPING - DF","R6"),
    ("LJ117","BELEM - PA","R6"),("LJ119","JOAO PESSOA - PB","R3"),
    ("LJ118","SP CENTER NORTE - SP","R5"),("LJ120","MANAUS - AM","R6"),
    ("LJ124","NATAL - RN","R3"),("LJ121","FORTALEZA - CE","R3"),
    ("LJ126","NITEROI - RJ","R7"),("LJ165","R JANEIRO BOTAFOGO - RJ","R7"),
    ("LJ198","BH PATIO SAVASSI - MG","R2"),("LJ185","RJ SHOPP TIJUCA - RJ","R7"),
    ("LJ209","CURITIBA - PR","R1"),("LJ219","FORTALEZA - CE","R3"),
    ("LJ231","SANTOS - SP","R4"),("LJ233","RIO DE JANEIRO - RJ","R7"),
    ("LJ234","SHOPP CIDADE SAO PAULO - SP","R5"),("LJ235","SHOPP BARRA SALVADOR - BA","R3"),
    ("LJ245","BELEM - PA","R6"),("LJ242","MANAUS - AM","R6"),
    ("LJ244","CUIABA - MT","R6"),("LJ248","RIO DE JANEIRO - RJ","R7"),
    ("LJ249","FLORIANOPOLIS - SC","R1"),("LJ254","JOINVILLE - SC","R1"),
    ("LJ262","ARACAJU - SE","R3"),("LJ239","PARK SHOPPING CANOAS - RS","R1"),
    ("LJ258","OSASCO - SP","R4"),("LJ266","ANANINDEUA - PA","R6"),
    ("LJ285","SHOPPING DA BAHIA - BA","R3"),("LJ284","FLAMBOYANT - GO","R6"),
    ("LJ291","SALVADOR SHOPPING - BA","R3"),("LJ288","SHOPPING RECIFE - PE","R3"),
    ("LJ286","SHOPPING VITORIA - ES","R7"),("LJ283","RIOMAR - PE","R3"),
    ("LJ287","BARRA SHOPPING - RJ","R7"),("LJ293","PONTA NEGRA - AM","R6"),
    ("LJ127","MYSTORE S.J. RIO PRETO - SP","R4"),("LJ141","MYSTORE S.J. CAMPOS - SP","R2"),
    ("LJ146","MYSTORE RIBEIRAO SHOPPING - SP","R2"),("LJ143","MYSTORE VOTORANTIM - SP","R4"),
    ("LJ145","MYSTORE SAO PAULO TIETE - SP","R5"),("LJ151","MYSTORE SP PLAZA SUL - SP","R5"),
    ("LJ153","MYSTORE SHOPPING ABC - SP","R4"),("LJ152","MYSTORE PRAIA DE BELAS POA - RS","R1"),
    ("LJ160","MYSTORE DOM PEDRO CAMPINAS - SP","R2"),("LJ168","MYSTORE SP BARUERI - SP","R5"),
    ("LJ172","MYSTORE SAO LUIS SHOPP ILHA - MA","R6"),("LJ171","MYSTORE BALNEARIO CAMBORIU - SC","R1"),
    ("LJ213","MYSTORE CONTAGEM - MG","R2"),("LJ187","MYSTORE SP METRO TATUAPE - SP","R5"),
    ("LJ228","MYSTORE MACEIO - AL","R3"),("LJ186","MYSTORE CARUARU - PE","R3"),
    ("LJ188","MYSTORE S.J.DE MERITI - RJ","R7"),("LJ194","MYSTORE RECIFE TACARUNA - PE","R3"),
    ("LJ191","MYSTORE RECIFE CASA FORTE - PE","R3"),("LJ211","MYSTORE CURITIBA - PR","R1"),
    ("LJ192","MYSTORE J GUARARAPES - PE","R3"),("LJ184","MYSTORE RJ WEST SHOPPING - RJ","R7"),
    ("LJ189","MYSTORE RJ NORTE SHOPPING - RJ","R7"),("LJ207","MYSTORE SP INTERLAGOS - SP","R4"),
    ("LJ202","MYSTORE PELOTAS - RS","R1"),("LJ215","MYSTORE SAO PAULO - SP","R5"),
    ("LJ212","MYSTORE NOVO HAMBURGO - RS","R1"),("LJ216","MYSTORE GUARULHOS - SP","R2"),
    ("LJ229","MYSTORE M. DAS CRUZES - SP","R2"),("LJ246","RIO DE JANEIRO - RJ","R7"),
    ("LJ238","IPLACE MOBILE SANTA MARIA - RS","R1"),("LJ255","SANTA BARBARA D OESTE - SP","R4"),
    ("LJ273","OLINDA - PE","R3"),("LJ269","PASSO FUNDO - RS","R1"),
    ("LJ274","GUARULHOS - SP","R2"),("LJ282","IPLACE MOBILE JOC PLAZA - PR","R1"),
    ("LJ319","ESTACAO CUIABA - MT","R6"),
]
FILIAL_REGIONAL_MAP: dict[str, dict[str, str]] = {
    str(int(lj[2:])): {"centro_sap": lj, "nome": nome, "regional": regional}
    for lj, nome, regional in _FILIAL_CSV
}


def _build_attributed_orders_amounts_sql(start_date: str, end_date: str) -> str:
    """Retorna order_id + attributed_amount total por pedido no período."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    tz = EMARSYS_TZ
    return f"""
SELECT
  r.order_id,
  SUM(t.attributed_amount) AS attributed_amount
FROM `{project_id}.{dataset}.{revenue_table}` r
CROSS JOIN UNNEST(r.treatments) AS t
WHERE ARRAY_LENGTH(r.treatments) > 0
  AND t.attributed_amount > 0
  AND DATE(r.event_time, '{tz}') BETWEEN DATE('{start_date}') AND DATE('{end_date}')
  AND DATE(r.partitiontime) BETWEEN DATE('{start_date}') AND CURRENT_DATE()
  AND r.order_id IS NOT NULL
GROUP BY r.order_id
""".strip()


def _build_vendas_canal_filial_sql(order_ids: set[str]) -> str:
    """Canal/filial+vlr por (Numero_Pedido, Cod_Filial, Canal) para desambiguação por valor."""
    if not BASE_VENDAS_BQ_PROJECT:
        raise HTTPException(status_code=500, detail="BASE_VENDAS_BQ_PROJECT nao configurado.")
    project = _quote_identifier(BASE_VENDAS_BQ_PROJECT)
    dataset = _quote_identifier(VENDAS_BQ_DATASET)
    table = _quote_identifier(VENDAS_BQ_TABLE)
    safe_ids = sorted({str(i).replace("'", "''") for i in order_ids if i})
    ids_values = ", ".join(f"'{i}'" for i in safe_ids) if safe_ids else "'__no_match__'"
    return f"""
SELECT
  Numero_Pedido AS order_id,
  COALESCE(NULLIF(TRIM(Canal), ''), 'Pendente de Atribuição') AS canal,
  CAST(SAFE_CAST(REGEXP_REPLACE(COALESCE(Cod_Filial, ''), r'[^0-9]', '') AS INT64) AS STRING) AS codigo_filial,
  ROUND(SUM(COALESCE(SAFE_CAST(REGEXP_REPLACE(COALESCE(TRIM(Vlr_Pedidos_Captados), ''), r'[^0-9.]', '') AS FLOAT64), 0)), 2) AS vlr_captados
FROM `{project}.{dataset}.{table}`
WHERE Numero_Pedido IN UNNEST([{ids_values}])
  AND Numero_Pedido IS NOT NULL
  AND TRIM(Numero_Pedido) != ''
GROUP BY Numero_Pedido, Cod_Filial, Canal
""".strip()


def _bv_normalize_cpf_sql(field: str) -> str:
    """Expressão SQL que replica _normalize_match_key para documento_cliente da view."""
    cleaned = f"REGEXP_REPLACE(LOWER({field}), r'[^0-9A-Za-z]', '')"
    return (
        f"CASE WHEN REGEXP_CONTAINS({cleaned}, r'^[0-9]+$') "
        f"AND LENGTH({cleaned}) BETWEEN 1 AND 10 "
        f"THEN LPAD({cleaned}, 11, '0') "
        f"ELSE {cleaned} END"
    )


def _build_bv_canal_filial_sql(start_date: str, end_date: str) -> str:
    """Agrega canal/filial/linhas/receita da view Base Vendas sem filtro de CPF."""
    if not BASE_VENDAS_BQ_PROJECT:
        raise HTTPException(status_code=500, detail="BASE_VENDAS_BQ_PROJECT nao configurado.")
    project = _quote_identifier(BASE_VENDAS_BQ_PROJECT)
    dataset = _quote_identifier(BASE_VENDAS_BQ_DATASET)
    view = _quote_identifier(BASE_VENDAS_BQ_TABLE)
    return f"""
SELECT
  canal,
  CAST(codigo_filial AS STRING) AS codigo_filial,
  COUNT(*) AS linhas,
  ROUND(SUM(COALESCE(valor_faturamento_liquido, 0)), 2) AS receita
FROM `{project}.{dataset}.{view}`
WHERE data_completa BETWEEN DATE('{start_date}') AND DATE('{end_date}')
GROUP BY canal, codigo_filial
ORDER BY receita DESC
""".strip()


def _build_bv_rows_sql(start_date: str, end_date: str, limit: int = 50000) -> str:
    """Retorna linhas individuais da view Base Vendas (para cruzamento com Emarsys)."""
    if not BASE_VENDAS_BQ_PROJECT:
        raise HTTPException(status_code=500, detail="BASE_VENDAS_BQ_PROJECT nao configurado.")
    project = _quote_identifier(BASE_VENDAS_BQ_PROJECT)
    dataset = _quote_identifier(BASE_VENDAS_BQ_DATASET)
    view = _quote_identifier(BASE_VENDAS_BQ_TABLE)
    norm_cpf = _bv_normalize_cpf_sql("documento_cliente")
    return f"""
SELECT
  documento_cliente,
  {norm_cpf} AS normalized_documento,
  canal,
  unidade_negocio,
  CAST(codigo_filial AS STRING) AS codigo_filial
FROM `{project}.{dataset}.{view}`
WHERE data_completa BETWEEN DATE('{start_date}') AND DATE('{end_date}')
  AND documento_cliente IS NOT NULL
LIMIT {limit}
""".strip()


def _build_bv_breakdown_sql(cpfs: set[str], start_date: str, end_date: str) -> str:
    """Cruza CPFs com a view vw_performance_vendas; retorna canal/filial/linhas/receita."""
    if not BASE_VENDAS_BQ_PROJECT:
        raise HTTPException(status_code=500, detail="BASE_VENDAS_BQ_PROJECT nao configurado.")
    project = _quote_identifier(BASE_VENDAS_BQ_PROJECT)
    dataset = _quote_identifier(BASE_VENDAS_BQ_DATASET)
    view = _quote_identifier(BASE_VENDAS_BQ_TABLE)
    norm_cpf = _bv_normalize_cpf_sql("documento_cliente")
    safe_cpfs = sorted({c.replace("'", "''") for c in cpfs if c})
    cpf_values = ", ".join(f"'{c}'" for c in safe_cpfs) if safe_cpfs else "'__no_match__'"
    return f"""
WITH
cpf_set AS (SELECT cpf FROM UNNEST([{cpf_values}]) AS cpf),
bv AS (
  SELECT
    {norm_cpf} AS cpf_norm,
    canal,
    CAST(codigo_filial AS STRING) AS codigo_filial,
    valor_faturamento_liquido AS receita
  FROM `{project}.{dataset}.{view}`
  WHERE data_completa BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND documento_cliente IS NOT NULL
)
SELECT
  bv.canal,
  bv.codigo_filial,
  COUNT(*) AS linhas,
  ROUND(SUM(COALESCE(bv.receita, 0)), 2) AS receita
FROM bv
INNER JOIN cpf_set ON bv.cpf_norm = cpf_set.cpf
WHERE bv.cpf_norm IS NOT NULL AND bv.cpf_norm != ''
GROUP BY bv.canal, bv.codigo_filial
ORDER BY receita DESC
""".strip()


def _sanitize_campaign_id(value: str) -> str:
    """Validate that campaign_id is purely numeric (Emarsys IDs are numeric)."""
    cleaned = re.sub(r"[^0-9]", "", value)
    if not cleaned:
        raise HTTPException(status_code=400, detail="campaign_id deve ser numerico.")
    return cleaned


def _build_influenced_order_ids_sms_sql(campaign_id: str, dispatch_date: str) -> str:
    """Retorna order_id + attributed_amount de revenue_attribution para a campanha SMS.
    Usa a mesma fonte e lógica do cabeçalho (receita_atribuida), garantindo que o
    total regional some exatamente o valor exibido na linha da campanha."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    d = dispatch_date
    cid = _sanitize_campaign_id(campaign_id)
    return f"""
SELECT
  r.order_id,
  ROUND(SUM(t.attributed_amount), 2) AS receita
FROM `{project_id}.{dataset}.{revenue_table}` r
CROSS JOIN UNNEST(r.treatments) AS t
WHERE CAST(t.campaign_id AS STRING) = '{cid}'
  AND t.attributed_amount > 0
  AND DATE(r.event_time) BETWEEN DATE('{d}') AND DATE_ADD(DATE('{d}'), INTERVAL 7 DAY)
  AND DATE(r.partitiontime) BETWEEN DATE('{d}') AND DATE_ADD(DATE('{d}'), INTERVAL 8 DAY)
  AND r.order_id IS NOT NULL
GROUP BY r.order_id
""".strip()


def _build_influenced_order_ids_email_sql(campaign_id: str, start_date: str, end_date: str) -> str:
    """Retorna order_id + attributed_amount de revenue_attribution para a campanha de email.
    Usa a mesma fonte e lógica do cabeçalho (receita_atribuida), garantindo que o
    total regional some exatamente o valor exibido na linha da campanha."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    s, e = start_date, end_date
    cid = _sanitize_campaign_id(campaign_id)
    return f"""
SELECT
  r.order_id,
  ROUND(SUM(t.attributed_amount), 2) AS receita
FROM `{project_id}.{dataset}.{revenue_table}` r
CROSS JOIN UNNEST(r.treatments) AS t
WHERE CAST(t.campaign_id AS STRING) = '{cid}'
  AND t.attributed_amount > 0
  AND DATE(r.event_time) BETWEEN DATE('{s}') AND DATE_ADD(DATE('{e}'), INTERVAL 7 DAY)
  AND DATE(r.partitiontime) BETWEEN DATE('{s}') AND DATE_ADD(DATE('{e}'), INTERVAL 8 DAY)
  AND r.order_id IS NOT NULL
GROUP BY r.order_id
""".strip()


def _build_vendas_filial_by_orders_sql(order_ids: set[str]) -> str:
    """Retorna filial+vlr por (Numero_Pedido, Cod_Filial) para desambiguação por valor."""
    if not BASE_VENDAS_BQ_PROJECT:
        raise HTTPException(status_code=500, detail="BASE_VENDAS_BQ_PROJECT nao configurado.")
    project = _quote_identifier(BASE_VENDAS_BQ_PROJECT)
    dataset = _quote_identifier(VENDAS_BQ_DATASET)
    table = _quote_identifier(VENDAS_BQ_TABLE)
    safe_ids = sorted({str(i).replace("'", "''") for i in order_ids if i})
    ids_values = ", ".join(f"'{i}'" for i in safe_ids) if safe_ids else "'__no_match__'"
    return f"""
SELECT
  Numero_Pedido AS order_id,
  CAST(SAFE_CAST(REGEXP_REPLACE(COALESCE(Cod_Filial, ''), r'[^0-9]', '') AS INT64) AS STRING) AS codigo_filial,
  ROUND(SUM(COALESCE(SAFE_CAST(REGEXP_REPLACE(COALESCE(TRIM(Vlr_Pedidos_Captados), ''), r'[^0-9.]', '') AS FLOAT64), 0)), 2) AS vlr_captados
FROM `{project}.{dataset}.{table}`
WHERE Numero_Pedido IN UNNEST([{ids_values}])
  AND Numero_Pedido IS NOT NULL
  AND TRIM(Numero_Pedido) != ''
GROUP BY Numero_Pedido, Cod_Filial
""".strip()


def _cross_orders_regional(order_amounts: dict[str, float]) -> dict[str, Any]:
    """Cruza order_ids com vendas_iplace; desambigua filial por order_id+valor quando há duplicatas."""
    if not order_amounts:
        return {"regionais": [], "total_cruzado": 0, "total_orders": 0}

    if not BASE_VENDAS_BQ_PROJECT:
        raise HTTPException(status_code=500, detail="BASE_VENDAS_BQ_PROJECT nao configurado.")

    sql = _build_vendas_filial_by_orders_sql(set(order_amounts.keys()))
    records = run_bigquery_records(
        sql, BASE_VENDAS_BQ_PROJECT,
        location=BASE_VENDAS_BQ_LOCATION or None, timeout=30,
    )

    # Agrupa candidatos por order_id (pode ter >1 quando mesmo número existe em filiais diferentes)
    from collections import defaultdict
    candidates: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        oid = str(r.get("order_id") or "")
        if not oid:
            continue
        candidates[oid].append({
            "filial": str(r.get("codigo_filial") or "(sem filial)").strip() or "(sem filial)",
            "vlr_captados": float(r.get("vlr_captados") or 0),
        })

    # Escolhe melhor filial: única candidata ou a de valor mais próximo ao do Emarsys
    matched = 0
    regional_data: dict[str, dict[str, Any]] = {}
    for order_id, cands in candidates.items():
        receita = order_amounts.get(order_id, 0.0)
        best = cands[0] if len(cands) == 1 else min(cands, key=lambda c: abs(c["vlr_captados"] - receita))
        filial = best["filial"]
        matched += 1

        store_info = FILIAL_REGIONAL_MAP.get(filial)
        regional = store_info["regional"] if store_info else "Outros"
        nome_loja = store_info["nome"] if store_info else f"LJ{str(filial).zfill(3)}"
        centro_sap = store_info["centro_sap"] if store_info else f"LJ{str(filial).zfill(3)}"

        if regional not in regional_data:
            regional_data[regional] = {"regional": regional, "linhas": 0, "receita": 0.0, "lojas": []}
        regional_data[regional]["linhas"] += 1
        regional_data[regional]["receita"] += receita
        regional_data[regional]["lojas"].append({
            "codigo_filial": filial,
            "centro_sap": centro_sap,
            "nome": nome_loja,
            "linhas": 1,
            "receita": round(receita, 2),
        })

    # Pedidos sem match em vendas_iplace: soma em "Outros" para fechar o total
    matched_order_ids = set(candidates.keys())
    for order_id, receita in order_amounts.items():
        if order_id in matched_order_ids:
            continue
        outros = regional_data.setdefault("Outros", {"regional": "Outros", "linhas": 0, "receita": 0.0, "lojas": []})
        outros["linhas"] += 1
        outros["receita"] += receita

    for rdata in regional_data.values():
        rdata["lojas"].sort(key=lambda x: -x["receita"])
        rdata["receita"] = round(rdata["receita"], 2)

    return {
        "regionais": sorted(regional_data.values(), key=lambda x: -x["receita"]),
        "total_cruzado": matched,
        "total_orders": len(order_amounts),
    }


def _build_influenced_cpfs_sms_sql(campaign_id: str, dispatch_date: str) -> str:
    """Retorna DISTINCT cpf dos contatos com pedidos influenciados pelo SMS."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    sms_sends_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_SENDS_TABLE)
    si_purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    si_contacts_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    d = dispatch_date
    cid = _sanitize_campaign_id(campaign_id)
    return f"""
WITH
sms_sends_camp AS (
  SELECT DISTINCT ss.contact_id, DATE(ss.event_time) AS send_date
  FROM `{project_id}.{dataset}.{sms_sends_table}` ss
  WHERE CAST(ss.campaign_id AS STRING) = '{cid}'
    AND DATE(ss.event_time) = DATE('{d}')
    AND DATE(ss.partitiontime) BETWEEN DATE_SUB(DATE('{d}'), INTERVAL 1 DAY)
                                   AND DATE_ADD(DATE('{d}'), INTERVAL 1 DAY)
),
influenced_orders AS (
  SELECT DISTINCT r.order_id
  FROM sms_sends_camp ssc
  INNER JOIN `{project_id}.{dataset}.{revenue_table}` r
    ON r.contact_id = ssc.contact_id
    AND DATE(r.event_time) BETWEEN ssc.send_date AND DATE_ADD(ssc.send_date, INTERVAL 7 DAY)
    AND DATE(r.partitiontime) BETWEEN DATE('{d}') AND DATE_ADD(DATE('{d}'), INTERVAL 8 DAY)
),
order_si_contact AS (
  SELECT p.order_id, ANY_VALUE(p.si_contact_id) AS si_contact_id
  FROM `{project_id}.{dataset}.{si_purchases_table}` p
  INNER JOIN influenced_orders io USING (order_id)
  WHERE DATE(p.purchase_date) BETWEEN DATE('{d}') AND DATE_ADD(DATE('{d}'), INTERVAL 7 DAY)
  GROUP BY p.order_id
),
cpfs AS (
  SELECT ANY_VALUE(CAST(c.external_id AS STRING)) AS cpf
  FROM order_si_contact osc
  INNER JOIN `{project_id}.{dataset}.{si_contacts_table}` c
    ON CAST(c.si_contact_id AS STRING) = CAST(osc.si_contact_id AS STRING)
  WHERE c.external_id IS NOT NULL AND TRIM(CAST(c.external_id AS STRING)) != ''
  GROUP BY osc.order_id
)
SELECT DISTINCT cpf FROM cpfs WHERE cpf IS NOT NULL AND cpf != ''
""".strip()


def _build_influenced_cpfs_email_sql(campaign_id: str, start_date: str, end_date: str) -> str:
    """Retorna DISTINCT cpf dos contatos com pedidos influenciados pelo email."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    email_opens_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE)
    si_purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    si_contacts_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    s, e = start_date, end_date
    cid = _sanitize_campaign_id(campaign_id)
    return f"""
WITH
email_opens_camp AS (
  SELECT DISTINCT eo.contact_id, DATE(eo.event_time) AS open_date
  FROM `{project_id}.{dataset}.{email_opens_table}` eo
  WHERE CAST(eo.campaign_id AS STRING) = '{cid}'
    AND DATE(eo.partitiontime) BETWEEN DATE('{s}') AND DATE('{e}')
    AND DATE(eo.event_time) BETWEEN DATE('{s}') AND DATE('{e}')
    AND eo.contact_id IS NOT NULL
),
influenced_orders AS (
  SELECT DISTINCT r.order_id
  FROM email_opens_camp eoc
  INNER JOIN `{project_id}.{dataset}.{revenue_table}` r
    ON r.contact_id = eoc.contact_id
    AND DATE(r.event_time) BETWEEN eoc.open_date AND DATE_ADD(eoc.open_date, INTERVAL 7 DAY)
  WHERE DATE(r.partitiontime) BETWEEN DATE('{s}') AND DATE_ADD(DATE('{e}'), INTERVAL 8 DAY)
),
order_si_contact AS (
  SELECT p.order_id, ANY_VALUE(p.si_contact_id) AS si_contact_id
  FROM `{project_id}.{dataset}.{si_purchases_table}` p
  INNER JOIN influenced_orders io USING (order_id)
  WHERE DATE(p.purchase_date) BETWEEN DATE('{s}') AND DATE_ADD(DATE('{e}'), INTERVAL 7 DAY)
  GROUP BY p.order_id
),
cpfs AS (
  SELECT ANY_VALUE(CAST(c.external_id AS STRING)) AS cpf
  FROM order_si_contact osc
  INNER JOIN `{project_id}.{dataset}.{si_contacts_table}` c
    ON CAST(c.si_contact_id AS STRING) = CAST(osc.si_contact_id AS STRING)
  WHERE c.external_id IS NOT NULL AND TRIM(CAST(c.external_id AS STRING)) != ''
  GROUP BY osc.order_id
)
SELECT DISTINCT cpf FROM cpfs WHERE cpf IS NOT NULL AND cpf != ''
""".strip()


def _cross_cpfs_regional(
    cpfs: set[str],
    start_date: str,
    end_date: str,
    total_influenciada: float = 0.0,
) -> dict[str, Any]:
    """Cruza CPFs contra Base Vendas (BigQuery) e distribui receita proporcionalmente por linhas."""
    if not cpfs:
        return {"regionais": [], "total_cruzado": 0, "total_cpfs": 0}

    if not BASE_VENDAS_BQ_PROJECT:
        raise HTTPException(status_code=500, detail="BASE_VENDAS_BQ_PROJECT nao configurado.")

    bv_sql = _build_bv_breakdown_sql(cpfs, start_date, end_date)
    records = run_bigquery_records(
        bv_sql, BASE_VENDAS_BQ_PROJECT,
        location=BASE_VENDAS_BQ_LOCATION or None, timeout=30,
    )
    filial_linhas = {
        str(r.get("codigo_filial") or "(sem filial)").strip() or "(sem filial)": int(r.get("linhas") or 0)
        for r in records
    }

    total_matched = sum(filial_linhas.values()) or 1
    matched = sum(filial_linhas.values())

    regional_data: dict[str, dict[str, Any]] = {}
    for filial, linhas in filial_linhas.items():
        store_info = FILIAL_REGIONAL_MAP.get(filial)
        regional = store_info["regional"] if store_info else "Outros"
        nome_loja = store_info["nome"] if store_info else f"LJ{str(filial).zfill(3)}"
        centro_sap = store_info["centro_sap"] if store_info else f"LJ{str(filial).zfill(3)}"
        pct = linhas / total_matched
        receita_est = round(total_influenciada * pct, 2)

        if regional not in regional_data:
            regional_data[regional] = {"regional": regional, "linhas": 0, "receita": 0.0, "lojas": []}
        regional_data[regional]["linhas"] += linhas
        regional_data[regional]["receita"] += receita_est
        regional_data[regional]["lojas"].append({
            "codigo_filial": filial,
            "centro_sap": centro_sap,
            "nome": nome_loja,
            "linhas": linhas,
            "receita": receita_est,
        })

    for rdata in regional_data.values():
        rdata["lojas"].sort(key=lambda x: -x["receita"])
        rdata["receita"] = round(rdata["receita"], 2)

    return {
        "regionais": sorted(regional_data.values(), key=lambda x: -x["receita"]),
        "total_cruzado": matched,
        "total_cpfs": len(cpfs),
    }


@router.get("/sms-apuracao-regional")
def sms_apuracao_regional(
    campaign_id: str = Query(..., min_length=1, max_length=30),
    date_param: str = Query(alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    receita_influenciada: float = Query(default=0.0),
) -> dict[str, Any]:
    cid = _sanitize_campaign_id(campaign_id)
    d = _validate_optional_iso_date(date_param) or date_param
    cache_key = f"sms_orders:{cid}:{d}"
    try:
        order_amounts: dict[str, float] | None = _cpf_cache_get(cache_key)  # type: ignore[assignment]
        if order_amounts is None:
            sql = _build_influenced_order_ids_sms_sql(cid, d)
            records = run_bigquery_records(
                sql, EMARSYS_OPEN_DATA_PROJECT_ID,
                location=EMARSYS_OPEN_DATA_LOCATION or None, timeout=30,
            )
            order_amounts = {
                str(r["order_id"]): float(r.get("receita") or 0)
                for r in records if r.get("order_id")
            }
            _cpf_cache_set(cache_key, order_amounts)  # type: ignore[arg-type]
        result = _cross_orders_regional(order_amounts)
        return {**result, "campaign_id": cid, "dispatch_date": d, "from_cache": _cpf_cache_get(cache_key) is not None}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao carregar regional SMS: {exc}") from exc


@router.get("/email-apuracao-regional")
def email_apuracao_regional(
    campaign_id: str = Query(..., min_length=1, max_length=30),
    start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    receita_influenciada: float = Query(default=0.0),
) -> dict[str, Any]:
    cid = _sanitize_campaign_id(campaign_id)
    s = _validate_optional_iso_date(start) or start
    e = _validate_optional_iso_date(end) or end
    cache_key = f"email_orders:{cid}:{s}:{e}"
    try:
        order_amounts: dict[str, float] | None = _cpf_cache_get(cache_key)  # type: ignore[assignment]
        if order_amounts is None:
            sql = _build_influenced_order_ids_email_sql(cid, s, e)
            records = run_bigquery_records(
                sql, EMARSYS_OPEN_DATA_PROJECT_ID,
                location=EMARSYS_OPEN_DATA_LOCATION or None, timeout=30,
            )
            order_amounts = {
                str(r["order_id"]): float(r.get("receita") or 0)
                for r in records if r.get("order_id")
            }
            _cpf_cache_set(cache_key, order_amounts)  # type: ignore[arg-type]
        result = _cross_orders_regional(order_amounts)
        return {**result, "campaign_id": cid, "start_date": s, "end_date": e, "from_cache": _cpf_cache_get(cache_key) is not None}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao carregar regional e-mail: {exc}") from exc


# ---------------------------------------------------------------------------
# Apple Lover — contagem agregada de contatos Apple no Emarsys
# ---------------------------------------------------------------------------

_APPLE_PRODUCT_FILTER = """(
    STARTS_WITH(LOWER(COALESCE(p.product_name, '')), 'apple')
    OR STARTS_WITH(LOWER(COALESCE(p.product_name, '')), 'iphone')
    OR STARTS_WITH(LOWER(COALESCE(p.product_name, '')), 'ipad')
    OR STARTS_WITH(LOWER(COALESCE(p.product_name, '')), 'macbook')
    OR STARTS_WITH(LOWER(COALESCE(p.product_name, '')), 'airpods')
    OR STARTS_WITH(LOWER(COALESCE(p.product_name, '')), 'imac')
    OR STARTS_WITH(LOWER(COALESCE(p.product_name, '')), 'mac mini')
    OR STARTS_WITH(LOWER(COALESCE(p.product_name, '')), 'mac pro')
    OR STARTS_WITH(LOWER(COALESCE(p.product_name, '')), 'apple watch')
    OR LOWER(COALESCE(p.product_name, '')) LIKE '%apple watch%'
  )"""

_APPLE_CATEGORY_FILTER = """(
    STARTS_WITH(category, 'iPhone')
    OR STARTS_WITH(category, 'AirPods')
    OR STARTS_WITH(category, 'Mac')
    OR STARTS_WITH(category, 'iPad')
    OR STARTS_WITH(category, 'Watch')
    OR STARTS_WITH(category, 'Apple')
  )"""


def _build_apple_lover_summary_sql(lookback_days: int) -> str:
    project = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    purchases = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    contacts = _quote_identifier(EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE)
    session_cat = _quote_identifier(EMARSYS_OPEN_DATA_SESSION_CATEGORIES_TABLE)
    client_upd = _quote_identifier(EMARSYS_OPEN_DATA_CLIENT_UPDATES_TABLE)
    apple_prod = _APPLE_PRODUCT_FILTER
    apple_cat = _APPLE_CATEGORY_FILTER

    return f"""
WITH buyers AS (
  SELECT DISTINCT c.contact_id
  FROM `{project}.{dataset}.{purchases}` p
  JOIN `{project}.{dataset}.{contacts}` c ON c.si_contact_id = p.si_contact_id
  WHERE c.contact_id IS NOT NULL
    AND p.purchase_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
    AND {apple_prod}
),
visitors AS (
  SELECT DISTINCT contact_id
  FROM `{project}.{dataset}.{session_cat}`
  WHERE contact_id IS NOT NULL
    AND partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_days} DAY)
    AND {apple_cat}
),
apple_spend_agg AS (
  SELECT
    ROUND(SUM(COALESCE(p.sales_amount, 0)), 2) AS total_spend,
    COUNT(DISTINCT p.order_id) AS pedidos_apple
  FROM `{project}.{dataset}.{purchases}` p
  WHERE p.purchase_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
    AND {apple_prod}
),
ios_devices_agg AS (
  SELECT COUNT(*) AS ios_count
  FROM `{project}.{dataset}.{client_upd}`
  WHERE LOWER(COALESCE(platform, '')) = 'ios'
    AND partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_days} DAY)
)
SELECT
  (SELECT COUNT(*) FROM buyers) AS buyers_count,
  (SELECT COUNT(*) FROM visitors) AS visitors_count,
  (SELECT COUNT(*) FROM (
    SELECT contact_id FROM buyers
    INTERSECT DISTINCT
    SELECT contact_id FROM visitors
  )) AS both_count,
  (SELECT COUNT(*) FROM (
    SELECT contact_id FROM buyers
    UNION DISTINCT
    SELECT contact_id FROM visitors
  )) AS total_apple_lovers,
  (SELECT total_spend FROM apple_spend_agg) AS total_apple_spend,
  (SELECT pedidos_apple FROM apple_spend_agg) AS pedidos_apple,
  (SELECT ios_count FROM ios_devices_agg) AS ios_devices_count
""".strip()


@router.get("/apple-lover/summary")
def apple_lover_summary(
    lookback_days: int = Query(default=90, ge=1, le=365),
) -> dict[str, Any]:
    try:
        sql = _build_apple_lover_summary_sql(lookback_days)
        records = run_bigquery_records(
            sql,
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
            timeout=120,
        )
        if not records:
            return {
                "buyers_count": 0,
                "visitors_count": 0,
                "both_count": 0,
                "total_apple_lovers": 0,
                "total_apple_spend": 0.0,
                "pedidos_apple": 0,
                "ios_devices_count": 0,
                "lookback_days": lookback_days,
            }
        row = records[0]
        buyers = int(row.get("buyers_count") or 0)
        visitors = int(row.get("visitors_count") or 0)
        both = int(row.get("both_count") or 0)
        total = int(row.get("total_apple_lovers") or 0)
        spend = float(row.get("total_apple_spend") or 0)
        pedidos = int(row.get("pedidos_apple") or 0)
        ios = int(row.get("ios_devices_count") or 0)
        avg_ticket = round(spend / buyers, 2) if buyers > 0 else 0.0
        return {
            "buyers_count": buyers,
            "visitors_count": visitors,
            "both_count": both,
            "total_apple_lovers": total,
            "total_apple_spend": spend,
            "avg_ticket": avg_ticket,
            "pedidos_apple": pedidos,
            "ios_devices_count": ios,
            "lookback_days": lookback_days,
            "source": "bigquery_emarsys_open_data",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao calcular Apple Lover: {exc}") from exc


def _build_apple_lover_tiers_sql(start_date: str, end_date: str) -> str:
    project = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    purchases = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    contacts = _quote_identifier(EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE)
    session_cat = _quote_identifier(EMARSYS_OPEN_DATA_SESSION_CATEGORIES_TABLE)
    snapshots = _quote_identifier(EMARSYS_OPEN_DATA_CLIENT_SNAPSHOTS_TABLE)

    return f"""
WITH

-- Contatos que usaram dispositivo Apple (Mac ou iPhone) — via client_snapshots
-- Filtra por last_event_time para evitar full scan em períodos longos
apple_devices AS (
  SELECT DISTINCT identified_contact_id AS contact_id
  FROM `{project}.{dataset}.{snapshots}`
  WHERE identified_contact_id IS NOT NULL
    AND last_event_time BETWEEN TIMESTAMP(DATE_SUB(DATE('{start_date}'), INTERVAL 60 DAY))
                            AND TIMESTAMP(DATE_ADD(DATE('{end_date}'), INTERVAL 1 DAY))
    AND REGEXP_CONTAINS(COALESCE(model, ''), r'Macintosh|iPhone\\d+,\\d+|iPhone; CPU iPhone OS')
),

-- Compras Apple no período: categorias distintas, pedidos, receita e última data
apple_purchases AS (
  SELECT
    c.contact_id,
    COUNT(DISTINCT p.order_id) AS qtd_pedidos,
    COUNT(DISTINCT
      CASE
        WHEN REGEXP_CONTAINS(UPPER(COALESCE(p.product_name,'')), r'IPHONE')        THEN 'iPhone'
        WHEN REGEXP_CONTAINS(UPPER(COALESCE(p.product_name,'')), r'IPAD')          THEN 'iPad'
        WHEN REGEXP_CONTAINS(UPPER(COALESCE(p.product_name,'')), r'MACBOOK|IMAC|MAC MINI|MAC PRO|MAC STUDIO') THEN 'Mac'
        WHEN REGEXP_CONTAINS(UPPER(COALESCE(p.product_name,'')), r'APPLE WATCH')   THEN 'Apple Watch'
        WHEN REGEXP_CONTAINS(UPPER(COALESCE(p.product_name,'')), r'AIRPOD')        THEN 'AirPods'
        ELSE 'Outros'
      END
    ) AS qtd_categorias_compradas,
    ROUND(SUM(SAFE_CAST(p.sales_amount AS NUMERIC)), 2) AS total_apple_spend,
    MAX(DATE(p.purchase_date)) AS last_apple_purchase_date
  FROM `{project}.{dataset}.{purchases}` p
  JOIN `{project}.{dataset}.{contacts}` c ON c.si_contact_id = p.si_contact_id
  WHERE c.contact_id IS NOT NULL
    AND DATE(p.purchase_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND {_APPLE_PRODUCT_FILTER}
  GROUP BY c.contact_id
),

-- Categorias Apple visitadas no site no período
apple_sessions AS (
  SELECT
    contact_id,
    TRUE AS visited_apple_category,
    COUNT(DISTINCT
      CASE
        WHEN STARTS_WITH(category, 'iPhone') THEN 'iPhone'
        WHEN STARTS_WITH(category, 'iPad')   THEN 'iPad'
        WHEN STARTS_WITH(category, 'Mac')    THEN 'Mac'
        WHEN STARTS_WITH(category, 'AirPod') THEN 'AirPods'
        WHEN STARTS_WITH(category, 'Watch') OR STARTS_WITH(category, 'Apple Watch') THEN 'Watch'
        ELSE NULL
      END
    ) AS qtd_categorias_visitadas
  FROM `{project}.{dataset}.{session_cat}`
  WHERE contact_id IS NOT NULL
    AND {_APPLE_CATEGORY_FILTER}
    AND DATE(partitiontime) BETWEEN DATE_SUB(DATE('{start_date}'), INTERVAL 1 DAY)
                                 AND DATE_ADD(DATE('{end_date}'), INTERVAL 1 DAY)
  GROUP BY contact_id
),

-- Perfil base dos contatos (ticket médio, spend futuro, status)
base_contacts AS (
  SELECT
    contact_id,
    external_id,
    SAFE_CAST(average_order_value AS NUMERIC) AS average_order_value,
    SAFE_CAST(average_future_spend AS NUMERIC) AS average_future_spend,
    buyer_status
  FROM `{project}.{dataset}.{contacts}`
  WHERE contact_id IS NOT NULL
),

-- Pontuação e união de todas as fontes
scored AS (
  SELECT
    bc.contact_id,
    bc.external_id,
    COALESCE(ap.qtd_pedidos,              0) AS qtd_apple_purchases,
    COALESCE(ap.qtd_categorias_compradas, 0) AS qtd_apple_categories_bought,
    COALESCE(ap.total_apple_spend,        0) AS total_apple_spend,
    ap.last_apple_purchase_date,
    COALESCE(s.visited_apple_category, FALSE) AS visited_apple_category,
    COALESCE(s.qtd_categorias_visitadas, 0)   AS qtd_apple_categories_visited,
    COALESCE(ad.contact_id IS NOT NULL, FALSE) AS uses_apple_device,
    bc.average_order_value,
    bc.average_future_spend,
    bc.buyer_status,
    -- Score 0-5
    (
      CASE WHEN COALESCE(ap.qtd_categorias_compradas, 0) >= 2 THEN 2 ELSE 0 END
      + CASE WHEN COALESCE(ap.qtd_pedidos, 0)              >= 2 THEN 1 ELSE 0 END
      + CASE WHEN SAFE_CAST(bc.average_order_value AS NUMERIC) >= 2000 THEN 1 ELSE 0 END
      + CASE WHEN ad.contact_id IS NOT NULL THEN 1 ELSE 0 END
    ) AS apple_lover_score
  FROM base_contacts bc
  LEFT JOIN apple_purchases ap ON ap.contact_id = bc.contact_id
  LEFT JOIN apple_sessions   s  ON s.contact_id  = bc.contact_id
  LEFT JOIN apple_devices    ad ON ad.contact_id  = bc.contact_id
  WHERE ap.contact_id IS NOT NULL
     OR s.contact_id  IS NOT NULL
     OR ad.contact_id IS NOT NULL
)

-- Classificação final por tier
-- T1: ≥2 categorias compradas E ≥2 pedidos Apple E usa dispositivo Apple
-- T2: ≥2 de (comprou Apple / ticket ≥ 2000 / ≥2 categorias visitadas)
-- T3: visitou categoria Apple OU usa dispositivo Apple
SELECT
  contact_id,
  COALESCE(external_id, '') AS external_id,
  CASE
    WHEN qtd_apple_categories_bought >= 2 AND qtd_apple_purchases >= 2 AND uses_apple_device
    THEN 'T1 - Ecosystem Enthusiast'
    WHEN (
      CASE WHEN qtd_apple_purchases          >= 1    THEN 1 ELSE 0 END
      + CASE WHEN COALESCE(average_order_value, 0)  >= 2000 THEN 1 ELSE 0 END
      + CASE WHEN qtd_apple_categories_visited >= 2          THEN 1 ELSE 0 END
    ) >= 2
    THEN 'T2 - Aspirational Buyer'
    WHEN visited_apple_category OR uses_apple_device
    THEN 'T3 - Apple Interested'
  END AS apple_lover_tier,
  apple_lover_score,
  qtd_apple_purchases,
  qtd_apple_categories_bought,
  ROUND(total_apple_spend, 2)      AS total_apple_spend,
  last_apple_purchase_date,
  visited_apple_category,
  qtd_apple_categories_visited,
  uses_apple_device,
  ROUND(COALESCE(average_order_value, 0), 2)   AS average_order_value,
  ROUND(COALESCE(average_future_spend, 0), 2)  AS average_future_spend,
  COALESCE(buyer_status, '') AS buyer_status
FROM scored
WHERE (
    (qtd_apple_categories_bought >= 2 AND qtd_apple_purchases >= 2 AND uses_apple_device)
    OR (
      CASE WHEN qtd_apple_purchases >= 1 THEN 1 ELSE 0 END
      + CASE WHEN COALESCE(average_order_value, 0) >= 2000 THEN 1 ELSE 0 END
      + CASE WHEN qtd_apple_categories_visited >= 2 THEN 1 ELSE 0 END
    ) >= 2
    OR visited_apple_category
    OR uses_apple_device
)
ORDER BY apple_lover_score DESC, total_apple_spend DESC
""".strip()


@router.get("/apple-lover/tiers")
def apple_lover_tiers(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end:   str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    today = date.today()
    start_date = _validate_optional_iso_date(start) or str(today.replace(day=1))
    end_date   = _validate_optional_iso_date(end)   or str(today)
    try:
        sql = _build_apple_lover_tiers_sql(start_date, end_date)
        records = run_bigquery_records(
            sql, EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None, timeout=300,
        )

        contacts = []
        t1 = t2 = t3 = 0
        for r in records:
            tier = str(r.get("apple_lover_tier") or "")
            if tier == "T1 - Ecosystem Enthusiast":   t1 += 1
            elif tier == "T2 - Aspirational Buyer":   t2 += 1
            elif tier == "T3 - Apple Interested":     t3 += 1
            contacts.append({
                "contact_id":                 str(r.get("contact_id") or ""),
                "external_id":                str(r.get("external_id") or ""),
                "apple_lover_tier":           tier,
                "apple_lover_score":          int(r.get("apple_lover_score") or 0),
                "qtd_apple_purchases":        int(r.get("qtd_apple_purchases") or 0),
                "qtd_apple_categories_bought":int(r.get("qtd_apple_categories_bought") or 0),
                "total_apple_spend":          float(r.get("total_apple_spend") or 0),
                "last_apple_purchase_date":   str(r.get("last_apple_purchase_date") or ""),
                "visited_apple_category":     bool(r.get("visited_apple_category") or False),
                "qtd_apple_categories_visited":int(r.get("qtd_apple_categories_visited") or 0),
                "uses_apple_device":          bool(r.get("uses_apple_device") or False),
                "average_order_value":        float(r.get("average_order_value") or 0),
                "average_future_spend":       float(r.get("average_future_spend") or 0),
                "buyer_status":               str(r.get("buyer_status") or ""),
            })

        return {
            "start_date": start_date,
            "end_date":   end_date,
            "summary":    {"t1": t1, "t2": t2, "t3": t3, "total": t1 + t2 + t3},
            "contacts":   contacts,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao calcular Apple Lover tiers: {exc}") from exc


# ---------------------------------------------------------------------------
# Auditoria de Receita CRM — cruzamento revenue_attribution × si_purchases
# ---------------------------------------------------------------------------

@router.get("/emarsys/auditoria-receita-crm")
def auditoria_receita_crm(
    start: str = Query(default="2026-03-01"),
    end: str = Query(default="2026-04-30"),
) -> dict[str, Any]:
    try:
        start_date = date.fromisoformat(start).isoformat()
        end_date = date.fromisoformat(end).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Datas inválidas: {exc}") from exc

    project = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    contacts_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE)
    purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)

    sql = f"""
WITH deduped AS (
  SELECT order_id, contact_id, treatments
  FROM `{project}.{dataset}.{revenue_table}`
  WHERE ARRAY_LENGTH(COALESCE(treatments, [])) > 0
    AND order_id IS NOT NULL
    AND DATE(event_time) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id, contact_id ORDER BY partitiontime DESC, event_time DESC) = 1
),
treatment_agg AS (
  SELECT
    d.order_id,
    d.contact_id,
    ROUND(SUM(COALESCE(t.attributed_amount, 0)), 2)         AS valor_atribuido,
    COUNT(*)                                                  AS qtd_treatments,
    NULLIF(STRING_AGG(
      DISTINCT NULLIF(UPPER(COALESCE(CAST(t.channel AS STRING), '')), ''),
      ', ' ORDER BY NULLIF(UPPER(COALESCE(CAST(t.channel AS STRING), '')), '')
    ), '')                                                    AS canais,
    NULLIF(STRING_AGG(
      DISTINCT NULLIF(CAST(t.campaign_id AS STRING), 'NULL'),
      ', ' ORDER BY NULLIF(CAST(t.campaign_id AS STRING), 'NULL')
    ), '')                                                    AS campaign_ids
  FROM deduped d
  CROSS JOIN UNNEST(d.treatments) AS t
  WHERE COALESCE(t.attributed_amount, 0) > 0
  GROUP BY d.order_id, d.contact_id
),
contacts_bridge AS (
  SELECT DISTINCT contact_id, si_contact_id
  FROM `{project}.{dataset}.{contacts_table}`
  WHERE contact_id IS NOT NULL
),
real_purchases AS (
  SELECT
    p.order_id,
    cb.contact_id,
    ROUND(SUM(COALESCE(p.sales_amount, 0)), 2) AS valor_real,
    DATE(MIN(p.purchase_date))                 AS purchase_date
  FROM `{project}.{dataset}.{purchases_table}` p
  LEFT JOIN contacts_bridge cb ON cb.si_contact_id = p.si_contact_id
  WHERE DATE(p.purchase_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND p.order_id IS NOT NULL
  GROUP BY p.order_id, cb.contact_id
),
combined AS (
  SELECT
    ta.order_id,
    ta.contact_id,
    ta.valor_atribuido,
    ta.qtd_treatments,
    ta.canais,
    ta.campaign_ids,
    (cb.contact_id IS NULL)                                   AS sem_vinculo,
    rp.valor_real,
    rp.purchase_date,
    ROUND(COALESCE(rp.valor_real, 0) - ta.valor_atribuido, 2) AS delta_valor,
    CASE
      WHEN rp.valor_real IS NULL OR rp.valor_real = 0 THEN NULL
      ELSE ROUND((rp.valor_real - ta.valor_atribuido) / rp.valor_real * 100, 2)
    END AS delta_pct,
    CASE
      WHEN cb.contact_id IS NULL                                   THEN 'sem_vinculo'
      WHEN rp.valor_real IS NULL                                   THEN 'sem_purchase'
      WHEN ta.valor_atribuido > COALESCE(rp.valor_real, 0)        THEN 'sobreatribuido'
      WHEN rp.valor_real > 0
       AND ABS(rp.valor_real - ta.valor_atribuido) / rp.valor_real <= 0.01 THEN 'atribuicao_total'
      ELSE 'atribuicao_parcial'
    END AS status
  FROM treatment_agg ta
  LEFT JOIN contacts_bridge cb ON cb.contact_id = ta.contact_id
  LEFT JOIN real_purchases rp  ON rp.order_id  = ta.order_id
                               AND rp.contact_id = ta.contact_id
)
SELECT * FROM combined
ORDER BY COALESCE(purchase_date, DATE('2099-01-01')) DESC, delta_valor DESC
""".strip()

    try:
        records = run_bigquery_records(
            sql,
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
            timeout=120,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao executar auditoria receita CRM: {exc}") from exc

    items = _records_to_response_items(records)

    # ---- Aggregates em Python ----

    # totals
    total_orders = len(items)
    soma_valor_real = round(sum(float(it.get("valor_real") or 0) for it in items), 2)
    soma_valor_atribuido = round(sum(float(it.get("valor_atribuido") or 0) for it in items), 2)
    delta_total = round(soma_valor_real - soma_valor_atribuido, 2)
    delta_pcts = [float(it["delta_pct"]) for it in items if it.get("delta_pct") is not None]
    delta_medio_pct = round(sum(delta_pcts) / len(delta_pcts), 2) if delta_pcts else None
    count_sobreatribuidos = sum(1 for it in items if it.get("status") == "sobreatribuido")
    count_sem_vinculo = sum(1 for it in items if it.get("status") == "sem_vinculo")
    count_sem_purchase = sum(1 for it in items if it.get("status") == "sem_purchase")

    totals = {
        "total_orders": total_orders,
        "soma_valor_real": soma_valor_real,
        "soma_valor_atribuido": soma_valor_atribuido,
        "delta_total": delta_total,
        "delta_medio_pct": delta_medio_pct,
        "count_sobreatribuidos": count_sobreatribuidos,
        "count_sem_vinculo": count_sem_vinculo,
        "count_sem_purchase": count_sem_purchase,
    }

    # by_status
    status_acc: dict[str, dict[str, Any]] = {}
    for it in items:
        s = it.get("status") or "desconhecido"
        acc = status_acc.setdefault(s, {"status": s, "count": 0, "valor_real": 0.0, "valor_atribuido": 0.0})
        acc["count"] += 1
        acc["valor_real"] = round(acc["valor_real"] + float(it.get("valor_real") or 0), 2)
        acc["valor_atribuido"] = round(acc["valor_atribuido"] + float(it.get("valor_atribuido") or 0), 2)
    by_status = list(status_acc.values())

    # by_canal
    canal_acc: dict[str, dict[str, Any]] = {}
    for it in items:
        canais_str = it.get("canais") or ""
        if not canais_str:
            canais_list = ["(sem canal)"]
        else:
            canais_list = [c.strip() for c in canais_str.split(",") if c.strip()]
        for canal in canais_list:
            acc = canal_acc.setdefault(canal, {"canal": canal, "count": 0, "valor_atribuido": 0.0})
            acc["count"] += 1
            acc["valor_atribuido"] = round(acc["valor_atribuido"] + float(it.get("valor_atribuido") or 0), 2)
    by_canal = list(canal_acc.values())

    # by_day
    day_acc: dict[str, dict[str, Any]] = {}
    for it in items:
        pd_val = it.get("purchase_date")
        if pd_val is None:
            continue
        key = str(pd_val)
        acc = day_acc.setdefault(key, {"purchase_date": key, "valor_real": 0.0, "valor_atribuido": 0.0})
        acc["valor_real"] = round(acc["valor_real"] + float(it.get("valor_real") or 0), 2)
        acc["valor_atribuido"] = round(acc["valor_atribuido"] + float(it.get("valor_atribuido") or 0), 2)
    by_day = sorted(day_acc.values(), key=lambda x: x["purchase_date"])

    return {
        "items": items,
        "totals": totals,
        "by_status": by_status,
        "by_canal": by_canal,
        "by_day": by_day,
        "start_date": start_date,
        "end_date": end_date,
        "source": "bigquery_emarsys_open_data",
    }


@router.get("/emarsys/auditoria-nao-atribuidos")
def auditoria_nao_atribuidos(
    start: str = Query(default="2026-03-01"),
    end: str = Query(default="2026-04-30"),
) -> dict[str, Any]:
    try:
        start_date = date.fromisoformat(start).isoformat()
        end_date = date.fromisoformat(end).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Datas inválidas: {exc}") from exc

    project = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    contacts_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE)
    sms_sends_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_SENDS_TABLE)
    sms_reports_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_SEND_REPORTS_TABLE)
    email_opens_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)

    sql = f"""
WITH
purchases AS (
  SELECT
    order_id,
    si_contact_id,
    DATE(MIN(purchase_date))                          AS purchase_date,
    ROUND(SUM(COALESCE(sales_amount, 0)), 2)          AS valor_real
  FROM `{project}.{dataset}.{purchases_table}`
  WHERE DATE(purchase_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND order_id IS NOT NULL
  GROUP BY order_id, si_contact_id
),
contact_bridge AS (
  SELECT DISTINCT si_contact_id, contact_id
  FROM `{project}.{dataset}.{contacts_table}`
  WHERE si_contact_id IS NOT NULL
),
purchases_with_contact AS (
  SELECT
    p.order_id,
    p.purchase_date,
    p.si_contact_id,
    cb.contact_id,
    p.valor_real
  FROM purchases p
  LEFT JOIN contact_bridge cb ON cb.si_contact_id = p.si_contact_id
),
sms_accepted AS (
  SELECT DISTINCT contact_id, campaign_id
  FROM `{project}.{dataset}.{sms_reports_table}`
  WHERE UPPER(TRIM(COALESCE(CAST(status AS STRING), ''))) = 'ACCEPTED'
),
sms_window AS (
  SELECT DISTINCT ss.contact_id, ss.event_time, CAST(ss.campaign_id AS STRING) AS campaign_id
  FROM `{project}.{dataset}.{sms_sends_table}` ss
  INNER JOIN sms_accepted sa
    ON sa.contact_id  = ss.contact_id
   AND sa.campaign_id = ss.campaign_id
  WHERE DATE(ss.event_time)
    BETWEEN DATE_SUB(DATE('{start_date}'), INTERVAL 7 DAY) AND DATE('{end_date}')
),
email_window AS (
  SELECT DISTINCT eo.contact_id, eo.event_time, CAST(eo.campaign_id AS STRING) AS campaign_id
  FROM `{project}.{dataset}.{email_opens_table}` eo
  WHERE DATE(eo.event_time)
    BETWEEN DATE_SUB(DATE('{start_date}'), INTERVAL 7 DAY) AND DATE('{end_date}')
),
last_sms_per_order AS (
  SELECT
    p.order_id,
    MAX(sw.event_time)                                                        AS last_sms_time,
    ARRAY_AGG(sw.campaign_id ORDER BY sw.event_time DESC LIMIT 1)[OFFSET(0)] AS sms_campaign_id
  FROM purchases_with_contact p
  JOIN sms_window sw
    ON  sw.contact_id         = p.contact_id
    AND DATE(sw.event_time)  >= DATE_SUB(p.purchase_date, INTERVAL 7 DAY)
    AND DATE(sw.event_time)  <  p.purchase_date
  WHERE p.contact_id IS NOT NULL
  GROUP BY p.order_id
),
last_email_per_order AS (
  SELECT
    p.order_id,
    MAX(ew.event_time)                                                        AS last_email_time,
    ARRAY_AGG(ew.campaign_id ORDER BY ew.event_time DESC LIMIT 1)[OFFSET(0)] AS email_campaign_id
  FROM purchases_with_contact p
  JOIN email_window ew
    ON  ew.contact_id         = p.contact_id
    AND DATE(ew.event_time)  >= DATE_SUB(p.purchase_date, INTERVAL 7 DAY)
    AND DATE(ew.event_time)  <  p.purchase_date
  WHERE p.contact_id IS NOT NULL
  GROUP BY p.order_id
),
ra_deduped AS (
  SELECT
    order_id,
    contact_id,
    ARRAY_LENGTH(COALESCE(treatments, [])) > 0 AS has_treatment
  FROM `{project}.{dataset}.{revenue_table}`
  WHERE order_id IS NOT NULL AND contact_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id, contact_id ORDER BY partitiontime DESC, event_time DESC) = 1
),
email_names AS (
  SELECT
    CAST(id AS STRING)                                                                    AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)]        AS nome_campanha
  FROM `{project}.{dataset}.{email_campaigns_table}`
  WHERE id IS NOT NULL
  GROUP BY 1
),
sms_names AS (
  SELECT
    CAST(campaign_id AS STRING)                                                           AS campaign_id,
    ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)]        AS nome_campanha
  FROM `{project}.{dataset}.{sms_campaigns_table}`
  WHERE campaign_id IS NOT NULL
  GROUP BY 1
),
combined AS (
  SELECT
    pwc.order_id,
    pwc.purchase_date,
    pwc.contact_id,
    pwc.valor_real,
    (ls.last_sms_time IS NOT NULL AND le.last_email_time IS NOT NULL)   AS multi_gatilho,
    CASE
      WHEN ls.last_sms_time IS NULL AND le.last_email_time IS NULL THEN NULL
      WHEN ls.last_sms_time  IS NULL                              THEN 'EMAIL'
      WHEN le.last_email_time IS NULL                             THEN 'SMS'
      WHEN ls.last_sms_time  >= le.last_email_time                THEN 'SMS'
      ELSE 'EMAIL'
    END AS canal_last_touch,
    CASE
      WHEN ls.last_sms_time IS NULL AND le.last_email_time IS NULL THEN NULL
      WHEN ls.last_sms_time  IS NULL                              THEN le.last_email_time
      WHEN le.last_email_time IS NULL                             THEN ls.last_sms_time
      WHEN ls.last_sms_time  >= le.last_email_time                THEN ls.last_sms_time
      ELSE le.last_email_time
    END AS data_gatilho,
    CASE
      WHEN ls.last_sms_time IS NULL AND le.last_email_time IS NULL THEN NULL
      WHEN ls.last_sms_time  IS NULL                              THEN le.email_campaign_id
      WHEN le.last_email_time IS NULL                             THEN ls.sms_campaign_id
      WHEN ls.last_sms_time  >= le.last_email_time                THEN ls.sms_campaign_id
      ELSE le.email_campaign_id
    END AS campaign_id_gatilho,
    (ra.order_id IS NOT NULL)         AS em_revenue_attribution,
    COALESCE(ra.has_treatment, FALSE) AS foi_atribuido
  FROM purchases_with_contact pwc
  LEFT JOIN last_sms_per_order   ls ON ls.order_id = pwc.order_id
  LEFT JOIN last_email_per_order le ON le.order_id = pwc.order_id
  LEFT JOIN ra_deduped           ra ON ra.order_id  = pwc.order_id
                                   AND ra.contact_id = pwc.contact_id
),
with_names AS (
  SELECT
    c.*,
    COALESCE(en.nome_campanha, sn.nome_campanha) AS nome_campanha_gatilho
  FROM combined c
  LEFT JOIN email_names en ON en.campaign_id = c.campaign_id_gatilho
  LEFT JOIN sms_names   sn ON sn.campaign_id = c.campaign_id_gatilho
)
SELECT
  order_id,
  purchase_date,
  contact_id,
  valor_real,
  canal_last_touch,
  data_gatilho,
  IF(data_gatilho IS NOT NULL,
     DATE_DIFF(purchase_date, DATE(data_gatilho), DAY),
     NULL)                            AS dias_gatilho_compra,
  campaign_id_gatilho,
  nome_campanha_gatilho,
  multi_gatilho,
  em_revenue_attribution,
  foi_atribuido,
  CASE
    WHEN contact_id IS NULL         THEN 'sem_vinculo'
    WHEN NOT em_revenue_attribution THEN 'ausente_revenue'
    WHEN canal_last_touch = 'SMS'   THEN 'nao_atribuido_sms'
    ELSE                                 'nao_atribuido_email'
  END AS status
FROM with_names
WHERE
  contact_id IS NULL
  OR (
    canal_last_touch IS NOT NULL
    AND DATE_DIFF(purchase_date, DATE(data_gatilho), DAY) BETWEEN 1 AND 7
  )
ORDER BY valor_real DESC
""".strip()

    try:
        all_records = run_bigquery_records(
            sql,
            EMARSYS_OPEN_DATA_PROJECT_ID,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
            timeout=180,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao executar auditoria não atribuídos: {exc}") from exc

    all_items = _records_to_response_items(all_records)

    items = [it for it in all_items if not it.get("foi_atribuido")]

    total_eligible = len(all_items)
    total_nao_atribuidos = len(items)
    pct_nao_atribuicao = round(total_nao_atribuidos / total_eligible * 100, 2) if total_eligible else 0.0
    receita_nao_atribuida = round(sum(float(it.get("valor_real") or 0) for it in items), 2)
    count_sms = sum(1 for it in items if (it.get("canal_last_touch") or "").upper() == "SMS")
    count_email = sum(1 for it in items if (it.get("canal_last_touch") or "").upper() == "EMAIL")
    count_ausentes = sum(1 for it in items if it.get("status") == "ausente_revenue")
    count_sem_vinculo = sum(1 for it in items if it.get("status") == "sem_vinculo")

    totals = {
        "total_eligible": total_eligible,
        "total_nao_atribuidos": total_nao_atribuidos,
        "pct_nao_atribuicao": pct_nao_atribuicao,
        "receita_nao_atribuida": receita_nao_atribuida,
        "count_sms": count_sms,
        "count_email": count_email,
        "count_ausentes_revenue": count_ausentes,
        "count_sem_vinculo": count_sem_vinculo,
    }

    # by_status
    status_acc: dict[str, dict[str, Any]] = {}
    for it in items:
        s = it.get("status") or "desconhecido"
        acc = status_acc.setdefault(s, {"status": s, "count": 0, "valor_real": 0.0})
        acc["count"] += 1
        acc["valor_real"] = round(acc["valor_real"] + float(it.get("valor_real") or 0), 2)
    by_status = list(status_acc.values())

    # by_canal (non-attributed only)
    canal_acc: dict[str, dict[str, Any]] = {}
    for it in items:
        canal = (it.get("canal_last_touch") or "(sem canal)").upper()
        acc = canal_acc.setdefault(canal, {"canal": canal, "count": 0, "valor_real": 0.0})
        acc["count"] += 1
        acc["valor_real"] = round(acc["valor_real"] + float(it.get("valor_real") or 0), 2)
    by_canal = list(canal_acc.values())

    # by_day (eligible vs nao_atribuidos)
    day_acc: dict[str, dict[str, Any]] = {}
    for it in all_items:
        pd_val = it.get("purchase_date")
        if pd_val is None:
            continue
        key = str(pd_val)
        acc = day_acc.setdefault(key, {"purchase_date": key, "elegiveis": 0, "nao_atribuidos": 0})
        acc["elegiveis"] += 1
        if not it.get("foi_atribuido"):
            acc["nao_atribuidos"] += 1
    by_day = sorted(day_acc.values(), key=lambda x: x["purchase_date"])

    # by_campaign — top 10 by non-attributed revenue
    campaign_acc: dict[str, dict[str, Any]] = {}
    for it in items:
        cid = str(it.get("campaign_id_gatilho") or "(sem campanha)")
        nome = str(it.get("nome_campanha_gatilho") or cid)
        acc = campaign_acc.setdefault(cid, {"campaign_id": cid, "nome_campanha": nome, "count": 0, "valor_real": 0.0})
        acc["count"] += 1
        acc["valor_real"] = round(acc["valor_real"] + float(it.get("valor_real") or 0), 2)
    by_campaign = sorted(campaign_acc.values(), key=lambda x: x["valor_real"], reverse=True)[:10]

    return {
        "items": items,
        "totals": totals,
        "by_status": by_status,
        "by_canal": by_canal,
        "by_day": by_day,
        "by_campaign": by_campaign,
        "start_date": start_date,
        "end_date": end_date,
        "source": "bigquery_emarsys_open_data",
    }


# ── Classificação de produtos por SKU (Cod_Produto) ────────────────────────────
# Formato: {Cod_Produto: (tipo, categoria, marca_ou_None)}
# tipos: 'device' | 'acc_apple' | 'acc_parceiro'
# SKUs com prefixo 000000010000 (serviços/reparos) são filtrados na query, não aqui.
_ACESSORIOS_SKU_MAP: dict[str, tuple[str, str, str | None]] = {
    '000000000100019979': ('acessorio', 'Carregador', 'Originais iPlace'),  # CARREG IPLACE 2PORT 30W BCO OP1ANG3D1AC
    '000000000100067576': ('acessorio', 'EarPods', 'Apple'),  # FONE APPLE EARPODS USB-C MYQY3BZ/A
    '000000000100024363': ('acessorio', 'Carregador Apple', 'Apple'),  # CARREG APPLE 20W USB-C BCO MUVU3BZ/A
    '000000000100067022': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PM ESSENT A.U OIV0791
    '000000000100068068': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C LIGHT BCO 1,2 LCBR12NY
    '000000000100068102': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C USB-C BCO 1,2 CCBR12NY
    '000000000100024708': ('acessorio', 'Carregador Apple', 'Apple'),  # CARREG APPLE 30W USB-C BCO MW2G3BZ/A
    '000000000100046292': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-C LIGTH 1M BCO MUQ93AM/A
    '000000000100060548': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE 60W USB-C 1M BCO MW493AM/A
    '000000000100072410': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS PRO 3 MFHP4BZ/A
    '000000000100061067': ('acessorio', 'Carregador', 'Originais iPlace'),  # KIT VIAGEM IPLACE 30W LIGHT CNZ OP1VLCC
    '000000000100066992': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX AIRCUS OIV0820
    '000000000100072473': ('device', 'iPhone', None),  # IPHONE 17 PRO MAX SILVER 256GB MFYM4BE/A
    '000000000100080116': ('device', 'iPhone', None),  # IPHONE 17 BLACK 256GB MG6J4BR/A
    '000000000100014834': ('acessorio', 'Carregador', 'Originais iPlace'),  # CARREG IPLACE PORTATIL PTO OP1HFCAD
    '000000000100057293': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE LIGH USB-A 1,2M BCO OP1DLAB1
    '000000000100068067': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-A USB-C BCO 1,2 CABR12NY
    '000000000100072474': ('device', 'iPhone', None),  # IPHONE 17 PRO MAX C ORG 256GB MFYN4BE/A
    '000000000100066971': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH17PMAX PROSAF A.U OIV0795
    '000000000100067013': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17 ESSENT A.U OIV0788
    '000000000100068611': ('acessorio', 'Outros', 'Originais iPlace'),  # KIT LIMPA TELAS IPLACE OIV0780
    '000000000100080117': ('device', 'iPhone', None),  # IPHONE 17 WHITE 256GB MG6K4BR/A
    '000000000100032026': ('device', 'iPhone', None),  # IPHONE 15 BLUE 128GB MTP43BR/A
    '000000000100033486': ('acessorio', 'EarPods', 'Apple'),  # FONE APPLE EARPODS LIGHTN MWTY3BZ/A
    '000000000100031967': ('device', 'iPhone', None),  # IPHONE 15 BLACK 128GB MTP03BR/A
    '000000000100056775': ('acessorio', 'Fone', 'JBL'),  # FONE JBL IN WAVE BUDS 2 BCO 28913824
    '000000000100064789': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS 4GER CAN MXP93BZ/A
    '000000000100014433': ('acessorio', 'Caneta', 'Apple'),  # APPLE PENCIL USB-C BCO MUWA3AM/A
    '000000000100068752': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C USB-C BCO 3 CCBR3NY
    '000000000100068069': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C USB-C BCO 1,2 CCBR12SI
    '000000000100080719': ('acessorio', 'Carregador', 'Originais iPlace'),  # KIT VIAGEM IPLACE 30WUSBC BRASIL KVB3CRI
    '000000000100060277': ('device', 'iPhone', None),  # IPHONE 16E BLK 128GB MD1Q4BR/A
    '000000000100068081': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C LIGHT PTO 1,2 LCPT12NY
    '000000000100020081': ('acessorio', 'Carregador', 'Originais iPlace'),  # KIT VIAGEM IPLACE 30WUSBC BCO OP1V3DACFW
    '000000000100066983': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PRO ESSENT A.U OIV0790
    '000000000100064788': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS 4GER USB-C MXP63BZ/A
    '000000000100072475': ('device', 'iPhone', None),  # IPHONE 17 PRO MAX DP BL 256GB MFYP4BE/A
    '000000000100041976': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15ANTIBAC A.U OIV0542
    '000000000100066974': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17 PROSAF A.U OIV0792
    '000000000100066993': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 AIRCUS OIV0818
    '000000000100060629': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16/17E ANTIBAC OIV0660
    '000000000100053737': ('device', 'iPhone', None),  # IPHONE 16 BLACK 128GB MYE73BR/A
    '000000000100046277': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE LIGHT USB 1M BCO MUQW3AM/A
    '000000000100080721': ('acessorio', 'Outros', 'Originais iPlace'),  # GARRAFA IPLACE SUPORTE MAG BRAS OIV0940
    '000000000100068084': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C USB-C PTO 1,2 CCPT12NY
    '000000000100072534': ('device', 'Apple Watch', None),  # WATCH SE 3 40 S AL S SB SM G MEH34AM/A
    '000000000100042273': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16ANTIBAC A.U OIV0546
    '000000000100066986': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PRO PROSAF A.U OIV0794
    '000000000100060982': ('device', 'iPad', None),  # IPAD 11TH WIFI 128GB SILVER MD3Y4BZ/A
    '000000000100079131': ('acessorio', 'AirTag', 'Apple'),  # AIRTAG APPLE PAC 1 UN 2TH BCO MFE94BE/A
    '000000000100017002': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE TEC UNIV 9A11 AZL IPSTA1010
    '000000000100044223': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPAD 10 ANTIBAC OIV0109
    '000000000100060278': ('device', 'iPhone', None),  # IPHONE 16E WHT 128GB MD1R4BR/A
    '000000000100046902': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16E/17E ESENT PT OIV0367
    '000000000100080118': ('device', 'iPhone', None),  # IPHONE 17 MIST BLUE 256GB MG6L4BR/A
    '000000000100053739': ('device', 'iPhone', None),  # IPHONE 16 PINK 128GB MYEA3BR/A
    '000000000100053738': ('device', 'iPhone', None),  # IPHONE 16 WHITE 128GB MYE93BR/A
    '000000000100055842': ('acessorio', 'Adaptador', 'Originais iPlace'),  # ADAPT IPLACE 7EM1 USBC CNZ OP1GHCHRU3
    '000000000100066979': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PM PREMIUM A.U OIV0802
    '000000000100032836': ('acessorio', 'Fone', 'Originais iPlace'),  # FONE IPLACE IN N270 BCO AUHEL5353
    '000000000100015866': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 AIRCUS OIV0445
    '000000000100075073': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 17PM PC SHINE TR OIV0913
    '000000000100020299': ('acessorio', 'Carregador', 'Originais iPlace'),  # CARREG IPLACE 2USB-C 65W BCO OP1AGN6C2UC
    '000000000100066960': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17PRO AIRCUS OIV0819
    '000000000100072467': ('device', 'iPhone', None),  # IPHONE 17 PRO DEEP BLUE 256GB MG8J4BE/A
    '000000000100056108': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH16 ANT/PRIV A.U. OIV0618
    '000000000100068086': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C USB-C AZL 1,2 CCAZ12NY
    '000000000100068085': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-A LIGHT BCO 1,2 LABR12NY
    '000000000100067030': ('acessorio', 'Outros', 'Originais iPlace'),  # VENTOSA IPLACE AVELA OIV0866
    '000000000100067014': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH17PMAX PROMAT A.U OIV0799
    '000000000100052636': ('acessorio', 'Adaptador', 'Originais iPlace'),  # ADAPT IPLACE 3EM1 USB-C CNZ ADTRA0449
    '000000000100066951': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 SILICONE PTO OIV0829
    '000000000100060983': ('device', 'iPad', None),  # IPAD 11TH WIFI 128GB BLUE MD4A4BZ/A
    '000000000100031719': ('acessorio', 'Fone', 'Originais iPlace'),  # FONE IPLACE WE.DUO N235 BRANCO AUHEL5454
    '000000000100042020': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15PRIVACID A.U OIV0543
    '000000000100020088': ('acessorio', 'Carregador', 'Mister'),  # CARREG MISTER VEICULAR 28W PTO MT1BACS
    '000000000100046905': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16E/17E SLIM OIV0366
    '000000000100072541': ('device', 'Apple Watch', None),  # WATCH SE 3 44 M AL M SB ML G MEHQ4AM/A
    '000000000100066954': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 SHINE OIV0822
    '000000000100068065': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C LIGHT AZL 1,2 LCAZ12NY
    '000000000100072465': ('device', 'iPhone', None),  # IPHONE 17 PRO SILVER 256GB MG8G4BE/A
    '000000000100055383': ('acessorio', 'Mouse', 'Apple'),  # MOUSE MAGIC APPLE TOUCH ID BCO MXK53BE/A
    '000000000100068751': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C LIGHT BCO 3M LCBR3NY
    '000000000100014439': ('acessorio', 'Caneta', 'Apple'),  # APPLE PENCIL PRO BCO MX2D3AM/A
    '000000000100040794': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI PEBBLE 2 M350S BCO 910-007047
    '000000000100075443': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 17PM SHELL AZUL OIV0921
    '000000000100060985': ('device', 'iPad', None),  # IPAD 11TH WIFI 128GB PINK MD4E4BZ/A
    '000000000100071399': ('acessorio', 'Carregador', 'Originais iPlace'),  # KIT VIAGEM IPLACE 30WUSBC ONCA KVO3CRI
    '000000000100042663': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PM ANTIBACT A.U OIV0558
    '000000000100056106': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH16PM ANT/PRIV A.U. OIV0621
    '000000000100032029': ('device', 'iPhone', None),  # IPHONE 15 BLUE 256GB MTP93BR/A
    '000000000100067001': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM IPH 17P/PMAX AZL OIV0875
    '000000000100046941': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 POLI PTO OIV0419
    '000000000100053736': ('device', 'iPhone', None),  # IPHONE 16 ULTRAMARINE 128GB MYEC3BR/A
    '000000000100032020': ('device', 'iPhone', None),  # IPHONE 15 BLACK 256GB MTP63BR/A
    '000000000100068336': ('acessorio', 'Mouse', 'Originais iPlace'),  # MOUSE SEM FIO IPLACE BT BCO ACSARWMODM
    '000000000100024701': ('acessorio', 'Carregador Apple', 'Apple'),  # CARREG APPLE 35W DUAL USBC BCO MW2K3BZ/A
    '000000000100075046': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 17PM PC STAND PT OIV0919
    '000000000100080119': ('device', 'iPhone', None),  # IPHONE 17 LAVENDER 256GB MG6M4BR/A
    '000000000100071501': ('acessorio', 'Carregador', 'Originais iPlace'),  # CARREG IPLACE 2USB-C 45W BCO OP1ANG4C2UC
    '000000000100081113': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE 240W USBC 2M BCO MYQT3AM/A
    '000000000100067003': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX PEEL LRJ OIV0840
    '000000000100067031': ('acessorio', 'Outros', 'Originais iPlace'),  # RING SHINE IPLACE MAG OIV0868
    '000000000100019856': ('acessorio', 'Carregador', 'Mister'),  # CARREG MISTER 2PORT 30W BCO MT1A30W2B
    '000000000100063908': ('acessorio', 'Outros', 'Originais iPlace'),  # SMART TAG IPLACE CNZ ACTUYSTFMP
    '000000000100072476': ('device', 'iPhone', None),  # IPHONE 17 PRO MAX SILVER 512GB MFYQ4BE/A
    '000000000100072478': ('device', 'iPhone', None),  # IPHONE 17 PRO MAX DP BL 512GB MFYU4BE/A
    '000000000100080880': ('device', 'iPhone', None),  # IPHONE 17E SOFT PINK 256GB MHRX4BR/A
    '000000000100080878': ('device', 'iPhone', None),  # IPHONE 17E BLACK 256GB MHRV4BR/A
    '000000000100046714': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 AIRCUS OIV0303
    '000000000100075047': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 17PM PC ESSEN PT OIV0917
    '000000000100020316': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USBC WATCH 1,2M BCO OP1EWTBC
    '000000000100080720': ('acessorio', 'Outros', 'Originais iPlace'),  # KIT PUL IPLACE BRASIL 38-41MM OIV0944
    '000000000100047372': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 SHINE OIV0449
    '000000000100066961': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX KVELAR VRD OIV0848
    '000000000100066840': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX BLEND CNZ OIV0849
    '000000000100080130': ('device', 'iPhone', None),  # IPHONE 17 SAGE 256GB MG6N4BR/A
    '000000000100068082': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C USB-C AVL 1,2 CCAV12SI
    '000000000100067021': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM IPH 17P/PMAX SIL OIV0873
    '000000000100053761': ('device', 'iPhone', None),  # IPHONE 16 BLACK 256GB MYEE3BR/A
    '000000000100079315': ('acessorio', 'Fone', 'JBL'),  # FONE JBL TUNE T530BT PRETO 28914075
    '000000000100026335': ('acessorio', 'Pulseira', 'Originais iPlace'),  # KIT P IPLACE WATCH 38-41 LIL/BEG OIV0531
    '000000000100068066': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C LIGHT AVL 1,2 LCAV12SI
    '000000000100067006': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 STAND PTO OIV0833
    '000000000100053034': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH SIL IMA 42-45 PTO OIV0588
    '000000000100046298': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-C LIGHT 2M BCO MW2R3AM/A
    '000000000100075277': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 17PM STAND LARA  OIV0922
    '000000000100072554': ('device', 'Apple Watch', None),  # WATCH 11 42 RG AL LB SB SM G MEU04AM/A
    '000000000100067015': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM IPH 17P/PMAX LRJ OIV0874
    '000000000100019344': ('acessorio', 'MagSafe', 'Originais iPlace'),  # CARREG IPLACE 3EM1 MAGSAFE BCO OP1FLWS
    '000000000100068318': ('acessorio', 'Outros', 'Originais iPlace'),  # SMART KEY IPLACE LOTRASKBFM
    '000000000100067000': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX SHINE OIV0824
    '000000000100075442': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 17PM SHELL LARA OIV0920
    '000000000100016443': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPAD 2EM1 10TH PTO OIV0393
    '000000000100053762': ('device', 'iPhone', None),  # IPHONE 16 WHITE 256GB MYEF3BR/A
    '000000000100066958': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX PEEL CNZ OIV0841
    '000000000100072477': ('device', 'iPhone', None),  # IPHONE 17 PRO MAX C ORG 512GB MFYT4BE/A
    '000000000100071397': ('acessorio', 'Caneta', 'Originais iPlace'),  # CANETA IPLACE IPAD INDU/USBC BCO CNBWCWI
    '000000000100047568': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 SHINE OIV0566
    '000000000100043610': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE WATCH 40MM C/B OIV0082
    '000000000100053763': ('device', 'iPhone', None),  # IPHONE 16 PINK 256GB MYEG3BR/A
    '000000000100066796': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE WATCH BUMPER 42MM OIV0876
    '000000000100056768': ('acessorio', 'Fone', 'JBL'),  # FONE JBL IN WAVE BEAM 2 PTO 28913846
    '000000000100026008': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE WATCH BUMPER 45MM OIV0385
    '000000000100026001': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE WATCH BUMPER 41MM OIV0384
    '000000000100069935': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL BOOMBOX 4 PTO 28913917
    '000000000100051649': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 ESSENT PTO OIV0591
    '000000000100045625': ('acessorio', 'Outros', 'Originais iPlace'),  # ALCA OMBRO IPLACE CORD 160 PTO OIV0401
    '000000000100046794': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE PAMPAS 13 PTO OIV0578
    '000000000100016211': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX AIRCUS OIV0448
    '000000000100072536': ('device', 'Apple Watch', None),  # WATCH SE 3 40 M AL M SB SM G MEH94AM/A
    '000000000100066795': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE WATCH BUMPER 46MM OIV0877
    '000000000100055025': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS 4 SIL PTO OIV0603
    '000000000100047064': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 ESSENT PTO OIV0441
    '000000000100068083': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C LIGHT LIL 1,2 LCLI12NY
    '000000000100072466': ('device', 'iPhone', None),  # IPHONE 17 PRO COS ORANGE 256GB MG8H4BE/A
    '000000000100080323': ('device', 'Mac', None),  # MACBOOK NEO 13 A18P BLS 256GB MHFH4BZ/A
    '000000000100065952': ('acessorio', 'Outros', 'Originais iPlace'),  # SMART TAG IPLACE COMBO 2 CNZ LOTUYSTCBF
    '000000000100075279': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM 3 EM 1 IP 17PM AZ OIV0926
    '000000000100068080': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C USB-C LIL 1,2 CCLI12NY
    '000000000100075290': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM 3 EM 1 IP 17PM LR OIV0925
    '000000000100031667': ('acessorio', 'Fone', 'Originais iPlace'),  # FONE IPLACE IN N60 USBC BCO AUBOT5151
    '000000000100056767': ('acessorio', 'Fone', 'JBL'),  # FONE JBL IN WAVE BUDS 2 PTO 28913823
    '000000000100067033': ('acessorio', 'Outros', 'Originais iPlace'),  # SUPORTE DE GLOSS OFF WHITE OIV0867
    '000000000100066972': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PRO PROMAT A.U OIV0798
    '000000000100067016': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17 PROMAT A.U OIV0796
    '000000000100016460': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPAD 2EM1 10TH RSA OIV0394
    '000000000100080318': ('device', 'Mac', None),  # MACBOOK NEO 13 A18P SIL 512GB MHFC4BZ/A
    '000000000100066793': ('acessorio', 'Outros', 'Originais iPlace'),  # MALA IPLACE DE BORDO W/TAG PTO OIV0890
    '000000000100072794': ('acessorio', 'MagSafe', 'Apple'),  # CARREGADOR APPLE MAGSAFE 1M MGD74BE/A
    '000000000100068090': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17PMAX EDGE AZUL OIV0908
    '000000000100016467': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE TEC 10TH RSA IPSTA1212B
    '000000000100080321': ('device', 'Mac', None),  # MACBOOK NEO 13 A18P IND 256GB MHFF4BZ/A
    '000000000100063973': ('acessorio', 'Fone', 'Originais iPlace'),  # FONE IPLACE OVER N390 PTO AUHEL6467
    '000000000100051680': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE 240W USBC 2M BCO MYQT3AM/A
    '000000000100074059': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS PRO 3 PU MAR OIV0692
    '000000000100019337': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USBC MAGSAF 1,2M BCO OP1EMSB
    '000000000100053550': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE WATCH 46MM C/B OIV0600
    '000000000100034608': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL GO 4 PTO 28913760
    '000000000100080879': ('device', 'iPhone', None),  # IPHONE 17E WHITE 256GB MHRW4BR/A
    '000000000100027290': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE OLIVIA MRM OIV0367
    '000000000100043772': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE WATCH 49MM C/B OIV0087
    '000000000100056766': ('acessorio', 'Fone', 'JBL'),  # FONE JBL IN WAVE BEAM 2 BCO 28913847
    '000000000100064550': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH TITANIU 42-49 SIL OIV0674
    '000000000100045609': ('acessorio', 'Outros', 'Originais iPlace'),  # ALCA OMBRO IPLACE CORD 160 BEGE OIV0400
    '000000000100043705': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE WATCH 44MM C/B OIV0085
    '000000000100072559': ('device', 'Apple Watch', None),  # WATCH 11 46 JB AL BK SB ML G MEUX4AM/A
    '000000000100041368': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 14 ANTIBACT A.U OIV0540
    '000000000100075048': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 17PRO PC STAND PT OIV0918
    '000000000100075072': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 17PRO PC ESSEN PT OIV0916
    '000000000100078947': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL BOOMBOX 4 LARA 28913923
    '000000000100080250': ('device', 'Mac', None),  # MACB AIR 13 M5 16GB SIL 512GB MDH74BZ/A
    '000000000100066970': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM IPH 17 SILVER OIV0871
    '000000000100047297': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX ESSENT PTO OIV0444
    '000000000100027202': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH TECID 38-41 RSA OIV0412
    '000000000100071398': ('acessorio', 'Carregador', 'Originais iPlace'),  # KIT VIAGEM IPLACE 30WUSBC COW KVV3CRI
    '000000000100080147': ('device', 'iPhone', None),  # IPHONE 17E BLACK 256GB MHRV4BE/A
    '000000000100079330': ('acessorio', 'Fone', 'JBL'),  # FONE JBL TUNE 730BT PRETO 28914080
    '000000000100066962': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 KVELAR VERDE OIV0846
    '000000000100079132': ('acessorio', 'AirTag', 'Apple'),  # AIRTAG APPLE PAC 4 UN 2TH BCO MFEA4BE/A
    '000000000100051977': ('acessorio', 'Capa/Case', 'Logitech'),  # CAPA LOGI TEC UNIVER PTO 920-008334
    '000000000100067027': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 LOOP AVELA OIV0852
    '000000000100067034': ('acessorio', 'Outros', 'Originais iPlace'),  # WALLET IPLACE PU CNZ OIV0869
    '000000000100053760': ('device', 'iPhone', None),  # IPHONE 16 TEAL 128GB MYED3BR/A
    '000000000100079398': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE MAC 13 COURO AZUL OIV0938
    '000000000100072542': ('device', 'Apple Watch', None),  # WATCH SE 3 40 S AL S SB SM C MEP64AM/A
    '000000000100071500': ('acessorio', 'Adaptador', 'Originais iPlace'),  # ADAPT IPLACE VEICUL CARPLAY CNZ AVCCATJ
    '000000000100034651': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL GO 4 AZL 28913761
    '000000000100080131': ('device', 'iPhone', None),  # IPHONE 17 BLACK 512GB MG6P4BR/A
    '000000000100067029': ('acessorio', 'Outros', 'Originais iPlace'),  # RING LIGHT IPLACE SELFIE ACTELSRLMF
    '000000000100075071': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 17PRO PC SHINE TR OIV0912
    '000000000100066794': ('acessorio', 'Outros', 'Originais iPlace'),  # MALA IPLACE DE BORDO W/TAG BCO OIV0891
    '000000000100072445': ('device', 'iPhone', None),  # IPHONE 17 MIST BLUE 256GB MG6L4BE/A
    '000000000100055384': ('acessorio', 'Mouse', 'Apple'),  # MOUSE MAGIC APPLE TOUCH PTO MXK63BE/A
    '000000000100031527': ('acessorio', 'Fone', 'Originais iPlace'),  # FONE IPLACE IN N20 LIGH BCO AUBOT2929
    '000000000100060362': ('acessorio', 'MagSafe', 'Originais iPlace'),  # CARREG IPLACE 2EM1 MAGSAFE BCO OIFMSAP
    '000000000100072470': ('device', 'iPhone', None),  # IPHONE 17 PRO DEEP BLUE 512GB MG8N4BE/A
    '000000000100072456': ('device', 'iPhone', None),  # IPHONE AIR SKY BLUE 256GB MG2P4BE/A
    '000000000100017760': ('acessorio', 'Outros', 'Originais iPlace'),  # DIFUSOR IPLACE SMART C/ HOMEKIT OP5CADI
    '000000000100066948': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX STEAL OIV0853
    '000000000100040727': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 13ANTIBACT A.U OIV0539
    '000000000100038603': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM IPH16P/16PMAX SIL OIV0506
    '000000000100052637': ('acessorio', 'Adaptador', 'Originais iPlace'),  # ADAPT IPLACE HDMI USB-C CNZ ADTRA0348
    '000000000100017372': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE LIGH USB-C 1,2M BCO OP1DLCB1
    '000000000100046361': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA ENVELOPE IPLACE MAC13,3 MAR OIV0440
    '000000000100038596': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM IPH16P/16PMAX PTO OIV0505
    '000000000100080319': ('device', 'Mac', None),  # MACBOOK NEO 13 A18P CITR 256GB MHFD4BZ/A
    '000000000100017766': ('acessorio', 'Outros', 'Originais iPlace'),  # LAMPADA IPLACE COLOR C/ HOMEKIT OP5CLC
    '000000000100072481': ('device', 'iPhone', None),  # IPHONE 17 PRO MAX DP BL 1TB MFYX4BE/A
    '000000000100080133': ('device', 'iPhone', None),  # IPHONE 17 MIST BLUE 512GB MG6T4BR/A
    '000000000100080148': ('device', 'iPhone', None),  # IPHONE 17E WHITE 256GB MHRW4BE/A
    '000000000100080132': ('device', 'iPhone', None),  # IPHONE 17 WHITE 512GB MG6Q4BR/A
    '000000000100072612': ('device', 'Apple Watch', None),  # WATCH ULTRA3 49 BLACK TI BK  MF0J4BE/A
    '000000000100053539': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE WATCH 42MM C/B OIV0599
    '000000000100055034': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS 4 TRANSP OIV0607
    '000000000100027101': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE RAFA PTO OIV0368
    '000000000100066430': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE BASIC 14 CNZ OIV0773
    '000000000100046973': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 POLI PTO OIV0496
    '000000000100053764': ('device', 'iPhone', None),  # IPHONE 16 ULTRAMARINE 256GB MYEH3BR/A
    '000000000100017406': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE LIGH USB-C 1,2M PTO OP1DLCP1
    '000000000100080256': ('device', 'Mac', None),  # MACB AIR 13 M5 16GB MDN 512GB MDHE4BZ/A
    '000000000100060986': ('device', 'iPad', None),  # IPAD 11TH WIFI 256GB SILVER MD4G4BZ/A
    '000000000100079334': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE MAC 13 COURO LILAS OIV0939
    '000000000100066996': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX SILIC PTO OIV0831
    '000000000100068091': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 EDGE OFF OIV0911
    '000000000100074070': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS PRO 3 TRANSP OIV0690
    '000000000100043413': ('acessorio', 'Fone', 'Logitech'),  # FONE LOGI OV ZONEVIBE 100 BCO 981-001218
    '000000000100024756': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CASE VIAGEM IPLACE DE COURO PRETO
    '000000000100066943': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE MAG MAC AIR 13.6 OIV0781
    '000000000100041209': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI PEBBLE K380 BCO 920-011790
    '000000000100016204': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX SHINE OIV0452
    '000000000100065121': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL CHARGE 6 PTO 28913863
    '000000000100047030': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE PAMPAS 16 PTO OIV0320
    '000000000100063972': ('acessorio', 'Fone', 'Originais iPlace'),  # FONE IPLACE OVER N390 BCO AUHEL8287
    '000000000100067002': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17PRO KVELAR VRD OIV0847
    '000000000100067032': ('acessorio', 'Outros', 'Originais iPlace'),  # WALLET IPLACE PU PTO OIV0870
    '000000000100039039': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPAD AIR 11 OIV0407
    '000000000100030426': ('device', 'iPhone', None),  # IPHONE 14 MIDNIGHT 128GB MPUF3BR/A
    '000000000100074072': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS 4 PU MARROM OIV0693
    '000000000100079150': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL SB180 PTO 58033019
    '000000000100053765': ('device', 'iPhone', None),  # IPHONE 16 TEAL 256GB MYEJ3BR/A
    '000000000100072516': ('device', 'iPhone', None),  # IPHONE 17 PRO DEEP BLUE 1TB MG8R4BE/A
    '000000000100066959': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17PRO SILIC PTO OIV0830
    '000000000100072482': ('device', 'iPhone', None),  # IPHONE 17 PRO MAX SILVER 2TB MFYY4BE/A
    '000000000100041405': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 14PRIVACID A.U OIV0541
    '000000000100041353': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 14ANTIBAC OIV0028
    '000000000100071983': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE MAC AIR 13,6 PU MAR OIV0685
    '000000000100080397': ('acessorio', 'Outros', 'JBL'),  # CAIXA SOM JBL ENCOR 2 2MIC PTO 58035039
    '000000000100016525': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE TEC PRO 11 CNZ IPSTA1414
    '000000000100058172': ('acessorio', 'Caneta', 'Apple'),  # APPLE PENCIL PONTAS (4) MX763AM/A
    '000000000100081087': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE WATCH USB-C 1M MT0H3BE/A
    '000000000100067005': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17PRO SHINE OIV0823
    '000000000100017815': ('acessorio', 'Outros', 'Originais iPlace'),  # TOMADA IPLACE INTELIGENTE BIVO 10A OP5CP
    '000000000100066836': ('acessorio', 'Outros', 'Originais iPlace'),  # ORGANIZADOR IPLACE TRIP PTO OIV0778
    '000000000100059036': ('device', 'Apple TV', None),  # APPLE TV 4K 64GB WI-FI PTO MN873BZ/A
    '000000000100026362': ('acessorio', 'Pulseira', 'Originais iPlace'),  # KIT P IPLACE WATCH 42-49 CNZ/AZL OIV0532
    '000000000100038621': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM IPH16/16PLUS PTO OIV0504
    '000000000100063912': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16/17E DROP NUDE OIV0671
    '000000000100060987': ('device', 'iPad', None),  # IPAD 11TH WIFI 256GB BLUE MD4H4BZ/A
    '000000000100043484': ('acessorio', 'Fone', 'Logitech'),  # FONE LOGI ON C/FIO H390 RSA 981-001280
    '000000000100060984': ('device', 'iPad', None),  # IPAD 11TH WIFI 128GB YELLOW MD4D4BZ/A
    '000000000100072539': ('device', 'Apple Watch', None),  # WATCH SE 3 44 S AL S SB ML G MEHJ4AM/A
    '000000000100072443': ('device', 'iPhone', None),  # IPHONE 17 BLACK 256GB MG6J4BE/A
    '000000000100061669': ('acessorio', 'AirTag', 'Apple'),  # AIRTAG APPLE PAC 1 UNIDADE BCO MX532BE/A
    '000000000100067018': ('acessorio', 'Outros', 'Originais iPlace'),  # GARRAFA IPLACE SUPORTE MAG COW OIV0893
    '000000000100066428': ('acessorio', 'Outros', 'Originais iPlace'),  # SSD EXTERNO IPLACE 1TB CNZ ACSSKSSDUT
    '000000000100065953': ('acessorio', 'Adaptador', 'Originais iPlace'),  # ADAPT IPLACE 14EM1 USBC CNZ ADSSKMVHRA
    '000000000100019873': ('acessorio', 'Carregador', 'Mister'),  # CARREG MISTER 2PORT 30W PTO MT1A30W2P
    '000000000100065115': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL FLIP 7 PTO 28913860
    '000000000100073530': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-A USB-C BEA CZ MDGJ4LL/A
    '000000000100056184': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS 4 STEAL OIV0606
    '000000000100072537': ('device', 'Apple Watch', None),  # WATCH SE 3 40 M AL M SB ML G MEHC4AM/A
    '000000000100041402': ('acessorio', 'Outros', 'Logitech'),  # WEBCAM LOGI F HD BRIO 500 GRF 960-001412
    '000000000100066957': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH AIR AIRCUS OIV0821
    '000000000100066842': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX LOOP AVELA OIV0851
    '000000000100067024': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH AIR PROSAF A.U OIV0793
    '000000000100046399': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE ESSENC 15,6 PTO OIV0527
    '000000000100017769': ('acessorio', 'Outros', 'Originais iPlace'),  # LUMINARIA IPLACE COLOR C/HOMEKIT OP5CLSC
    '000000000100072468': ('device', 'iPhone', None),  # IPHONE 17 PRO SILVER 512GB MG8K4BE/A
    '000000000100065951': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPAD 2/1 TELA 13 PTO OIV0676
    '000000000100017422': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE LIGH USB-C 3M BCO OP1DLCB3
    '000000000100046334': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15PRO AIRCUS OIV0259
    '000000000100027247': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE TRANSV MRM OIV0355
    '000000000100073538': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-C BEATS CZA CAR MDGD4LL/A
    '000000000100027236': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH TEC MAG 42-49 VRD OIV0414
    '000000000100041410': ('acessorio', 'Outros', 'Logitech'),  # DESKPAD LOGI GRAFIT 956-000047
    '000000000100024742': ('acessorio', 'Mouse', 'Originais iPlace'),  # MOUSE IPLACE SEM FIO CNZ OP4MSFO
    '000000000100052235': ('acessorio', 'Carregador Apple', 'Apple'),  # CARREG APPLE 70W USB-C BCO MXN53BZ/A
    '000000000100047926': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE DIGITAL 16 PTO OIV0386
    '000000000100072561': ('device', 'Apple Watch', None),  # WATCH 11 46 SG AL BK SB ML G MEV44AM/A
    '000000000100068335': ('acessorio', 'Outros', 'Originais iPlace'),  # TRIPÉ SELFIE IPLACE ACWIWSSBRC
    '000000000100034654': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL GO 4 BCO 28913762
    '000000000100057276': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 13PRIVACID A.U OIV0653
    '000000100048732001': ('device', 'iPhone', None),  # IPHONE 13  STARLIGHT 128GB BB I, E
    '000000100048716001': ('device', 'iPhone', None),  # IPHONE 13 MIDNIGHT 128GB BB I, E
    '000000000100050620': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI MX KEYS CINZ 920-011564
    '000000000100043459': ('acessorio', 'Fone', 'Logitech'),  # FONE LOGI OV ZONEVIBE 100 RSA 981-001223
    '000000000100027293': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE OLIVIA PTO OIV0366
    '000000000100072453': ('device', 'iPhone', None),  # IPHONE AIR SPACE BLACK 256GB MG2L4BE/A
    '000000000100066945': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS 4 ONCA OIV0865
    '000000000100066304': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE TRANSV ESSENC PTO OIV0776
    '000000000100079311': ('acessorio', 'Fone', 'JBL'),  # FONE JBL TUNE 780NC PRETO 28914103
    '000000000100072535': ('device', 'Apple Watch', None),  # WATCH SE 3 40 S AL S SB ML G MEH54AM/A
    '000000000100063911': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16/17E STAND PTO OIV0670
    '000000000100066665': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE TRIP 15,6 PTO OIV0777
    '000000000100041227': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI PEBBLE K380 GRF 920-011789
    '000000000100024796': ('acessorio', 'Outros', 'Originais iPlace'),  # ORGANIZADOR IPLACE COURO PTO OIV0201
    '000000000100067208': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX BMW PTO OIV0899
    '000000000100046678': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 14 AIRCUS OIV0307
    '000000000100075278': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM 3 EM 1 IP 17PM SL OIV0924
    '000000000100066955': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 BLEND CNZ OIV0850
    '000000000100052659': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH SIL 38/41 PTO OIV0595
    '000000000100066305': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPAD UNIVER 9 A 11 OIV0668
    '000000000100072550': ('device', 'Apple Watch', None),  # WATCH 11 42 JB AL BK SB SM G MEQT4AM/A
    '000000000100069936': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL BOOMBOX 4 BCO 28913921
    '000000000100050715': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI LIFT BCO 910-006469
    '000000000100066429': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE BASIC 15,6 CNZ OIV0772
    '000000000100060280': ('device', 'iPhone', None),  # IPHONE 16E WHT 256GB MD1W4BR/A
    '000000000100068326': ('acessorio', 'Outros', 'Originais iPlace'),  # SMART CARD IPLACE LOREFSCBWC
    '000000000100072471': ('device', 'iPhone', None),  # IPHONE 17 PRO SILVER 1TB MG8P4BE/A
    '000000000100072549': ('device', 'Apple Watch', None),  # WATCH SE 3 44 M AL M SB ML C MEPJ4AM/A
    '000000000100066843': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 STEAL OIV0856
    '000000000100027244': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE TRANSV PTO OIV0568
    '000000000100066950': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX SHINE PTO OIV0828
    '000000000100017398': ('acessorio', 'Teclado', 'Originais iPlace'),  # TECLADO IPLACE NUM PTO OP4TSFAN
    '000000100048694001': ('device', 'iPhone', None),  # IPHONE 13  PINK 128GB BB I, E
    '000000000100035735': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL XTREME 4 PTO 28913740
    '000000000100078946': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL ENCORE 2MI BCO 28914163
    '000000000100072483': ('device', 'iPhone', None),  # IPHONE 17 PRO MAX C ORG 2TB MG004BE/A
    '000000000100047961': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE SUPOR DESKP 16 PTO OIV0396
    '000000000100072484': ('device', 'iPhone', None),  # IPHONE 17 PRO MAX DP BL 2TB MG014BE/A
    '000000000100066664': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPAD MAG 10TH OIV0783
    '000000000100063910': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE POCKET 14 PTO OIV0667
    '000000000100072544': ('device', 'Apple Watch', None),  # WATCH SE 3 40 M AL M SB SM C MEP94AM/A
    '000000000100052119': ('acessorio', 'Carregador Apple', 'Apple'),  # CARREG APPLE USB-C MAG 2M BCO MX6Y3BE/A
    '000000000100068327': ('acessorio', 'Outros', 'Originais iPlace'),  # SMART PASS IPLACE LOREFSPTWC
    '000000000100060628': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16/17E ANTIB/PRIV OIV0661
    '000000000100067004': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH AIR SHINE OIV0825
    '000000000100046367': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE PAMPAS 16 BEG OIV0437
    '000000000100067020': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH AIR PROMAT A.U OIV0797
    '000000000100052080': ('acessorio', 'Outros', 'Apple'),  # CARTEIRA APPLE TECIDO PTO MA6W4ZM/A
    '000000000100068324': ('acessorio', 'Outros', 'Originais iPlace'),  # SMART DETECTOR IPLACE LOTRASDIRL
    '000000000100066989': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 SHINE PTO OIV0826
    '000000000100067019': ('acessorio', 'Outros', 'Originais iPlace'),  # GARRAFA IPLACE SUPORTE MAG ONCA OIV0894
    '000000000100080322': ('device', 'Mac', None),  # MACBOOK NEO 13 A18P IND 512GB MHFG4BZ/A
    '000000000100080134': ('device', 'iPhone', None),  # IPHONE 17 LAVENDER 512GB MG6U4BR/A
    '000000000100055313': ('acessorio', 'Teclado', 'Apple'),  # TECLADO APPLE NUM EUA PTO MXK83BZ/A
    '000000000100072480': ('device', 'iPhone', None),  # IPHONE 17 PRO MAX C ORG 1TB MFYW4BE/A
    '000000000100059159': ('acessorio', 'Fone', 'Originais iPlace'),  # MICROFONE IPLACE LAPELA PTO AUTRA4966
    '000000000100066792': ('acessorio', 'Outros', 'Originais iPlace'),  # MALA IPLACE DE BORDO W/TAG RSA OIV0892
    '000000000100027021': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 42/44/49 COURO MARINHO OIV0208
    '000000000100016532': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPAD 2EM1 PRO 13 PTO OIV0391
    '000000000100042534': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PRO ANTIBAC A.U OIV0554
    '000000000100072469': ('device', 'iPhone', None),  # IPHONE 17 PRO COS ORANGE 512GB MG8M4BE/A
    '000000000100024894': ('acessorio', 'Outros', 'Originais iPlace'),  # DESKPAD IPLACE CARAMELO OIV0194
    '000000000100024823': ('acessorio', 'Outros', 'Originais iPlace'),  # ORGANIZADOR IPLACE DIGITAL PTO OIV0387
    '000000000100054574': ('device', 'iPad', None),  # IPAD MINI 7TH WF 128GB SPG MXN63BZ/A
    '000000000100066976': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PMAX PROSAFE OIV0810
    '000000000100072479': ('device', 'iPhone', None),  # IPHONE 17 PRO MAX SILVER 1TB MFYV4BE/A
    '000000000100032894': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYBOARD APPLE 10TH BCO MQDP3BZ/A
    '000000000100080115': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE WATCH USB-A 1M MW6A3BE/A
    '000000000100015353': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS PRO2 SIL PTO OIV0096
    '000000000100052642': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH SIL IMA 38-41 RSA OIV0594
    '000000000100032942': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYBOARD APPLE PRO13 PTO MWR53BZ/A
    '000000000100066835': ('acessorio', 'Outros', 'Originais iPlace'),  # ORGANIZADOR IPLACE BASIC CNZ OIV0774
    '000000000100030874': ('acessorio', 'Fone', 'JBL'),  # FONE JBL C50HI PRETO 28913221
    '000000000100057294': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE NEOPRENE 14 PTO OIV0651
    '000000000100066946': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17PRO STAND PTO OIV0834
    '000000000100060493': ('acessorio', 'Caneta', 'Apple'),  # APPLE PENCIL 2ª GER BCO MXN43BZ/A
    '000000000100067217': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX GUESS MRM OIV0895
    '000000000100051763': ('device', 'iPhone', None),  # IPHONE 16 PRO MAX BLACK 1TB MYX43BE/A
    '000000000100047291': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PRO AIRCUS OIV0447
    '000000000100072571': ('device', 'Apple Watch', None),  # WATCH 11 42 RG AL LB SB ML C MF8F4AM/A
    '000000000100073531': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-A USB-C BEA PTO MDGG4LL/A
    '000000000100052962': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH SIL IMA 42-45 MRM OIV0593
    '000000000100046324': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE WATCH UBS-C 1M MT0H3BE/A
    '000000000100046799': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE PAMPAS 13 MRM OIV0647
    '000000000100080320': ('device', 'Mac', None),  # MACBOOK NEO 13 A18P CITR 512GB MHFE4BZ/A
    '000000000100066980': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH AIR ESSENT A.U OIV0789
    '000000000100017812': ('acessorio', 'Outros', 'Originais iPlace'),  # LUMINARIA IPLACE RELAX C/HOMEKIT OP5CLSR
    '000000000100080225': ('device', 'iPad', None),  # IPAD AIR M4 11 WF SPG 128GB MH304BZ/A
    '000000000100080317': ('device', 'Mac', None),  # MACBOOK NEO 13 A18P SIL 256GB MHFA4BZ/A
    '000000000100047252': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PLUS AIRCUS OIV0446
    '000000000100051725': ('device', 'iPhone', None),  # IPHONE 16 PLUS BLACK 128GB MXVU3BE/A
    '000000000100060989': ('device', 'iPad', None),  # IPAD 11TH WIFI 256GB PINK MD4P4BZ/A
    '000000000100060994': ('device', 'iPad', None),  # IPAD 11TH CELL 128GB SILVER MD7F4BZ/A
    '000000000100058987': ('device', 'Apple TV', None),  # APPLE TV 4K 128GB WF/ETRN PTO MN893BZ/A
    '000000000100038770': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPAD PRO 13 OIV0409
    '000000000100080752': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS MAX 2 PTO MHWK4BE/A
    '000000000100027185': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH TECID 38-41 NUDE OIV0411
    '000000000100020095': ('acessorio', 'Carregador', 'Originais iPlace'),  # CARREG IPLACE VEICULAR 30W OP1BACS
    '000000000100038491': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM IPH15/15PLUS PTO OIV0299
    '000000000100066994': ('acessorio', 'Pulseira', 'Originais iPlace'),  # PULSEIRA IPLACE ONCA 38-41MM OIV0864
    '000000000100066662': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE MAG MAC PRO 14 OIV0782
    '000000000100080135': ('device', 'iPhone', None),  # IPHONE 17 SAGE 512GB MG6V4BR/A
    '000000000100018442': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USBC USBC 1,2M CNZ OP1DCMC1
    '000000000100067026': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 PEEL CNZ OIV0842
    '000000000100068089': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17PRO EDGE AZUL OIV0909
    '000000000100053015': ('acessorio', 'Outros', 'Originais iPlace'),  # ESTABILIZADOR IPLACE CAMERA PTO OICSFT1
    '000000000100067017': ('acessorio', 'Outros', 'Originais iPlace'),  # GARRAFA IPLACE SUPORTE MAG PTO OIV0775
    '000000000100068320': ('acessorio', 'Outros', 'Originais iPlace'),  # SMART TAG IPLACE PRETO LOREFSTPTO
    '000000000100047924': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE CORTES 16 MRM OIV0324
    '000000000100055839': ('acessorio', 'Outros', 'Originais iPlace'),  # SACOLA COLEÇÃO SPRING OIV0613
    '000000000100057011': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH COURO 42-49 MRM OIV0648
    '000000000100066953': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX STAND PTO OIV0835
    '000000000100066944': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS 4 COW OIV0861
    '000000000100072538': ('device', 'Apple Watch', None),  # WATCH SE 3 44 S AL S SB SM G MEHG4AM/A
    '000000000100047788': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE PAMPAS 15 PTO OIV0572
    '000000000100067575': ('acessorio', 'Outros', 'Originais iPlace'),  # SUPORTE VEIC IPLACE QI2 15W CNZ OIVMGP
    '000000000100047326': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PRO ESSENT PTO OIV0443
    '000000000100016498': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPAD 2EM1 PRO 11 PTO OIV0392
    '000000000100072472': ('device', 'iPhone', None),  # IPHONE 17 PRO COS ORANGE 1TB MG8Q4BE/A
    '000000000100016484': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE TEC 10TH CNZ IPSTA1313
    '000000000100040725': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI SIGNAT M650 GRF 910-006231
    '000000000100061670': ('acessorio', 'AirTag', 'Apple'),  # AIRTAG APPLE PAC 4 UNIDADE BCO MX542BE/A
    '000000000100068337': ('acessorio', 'Teclado', 'Originais iPlace'),  # TECLADO SEM FIO IPLACE BT CNZ ACSARWKSNP
    '000000000100052301': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 42 ESP PTO MXLJ3AM/A
    '000000000100050625': ('acessorio', 'Fone', 'JBL'),  # FONE JBL IN LIVE BUDS 3 PTO 28913780
    '000000000100073539': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-C BEATS PRETO MDGA4LL/A
    '000000000100035180': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPHONE 13 TRANSP MM2X3ZE/A
    '000000000100055037': ('acessorio', 'AirTag', 'Originais iPlace'),  # PUL IPLACE AIRTAG KIDS AZL OIV0602
    '000000000100055310': ('acessorio', 'Teclado', 'Apple'),  # TECLADO APPLE TOUCH ID EUA SIL MXCK3BZ/A
    '000000000100045732': ('acessorio', 'Outros', 'Originais iPlace'),  # SUPORTE IPLACE MULT MAC CNZ OP1GSLHU3B
    '000000000100032784': ('acessorio', 'Fone', 'JBL'),  # FONE JBL ON TUNE 520 BCO 28913697
    '000000000100027574': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH COURO 42-49 PTO OIV0565
    '000000000100017379': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE LIGH USB-C 1,2M CNZ OP1DLCC1
    '000000000100079314': ('acessorio', 'Fone', 'JBL'),  # FONE JBL SOUNDGEAR CLIP COBRE 28914043
    '000000000100042490': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PRO A.U OIV0555
    '000000000100047922': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE CORTES 16 PTO OIV0323
    '000000000100047929': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE SUPOR DESKP 16 MRM OIV0397
    '000000000100066991': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH AIR SILIC PTO OIV0832
    '000000000100081088': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE WATCH USB-A 1M MW6A3BE/A
    '000000000100032918': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYBOARD APPLE PRO11 PTO MWR23BZ/A
    '000000000100072454': ('device', 'iPhone', None),  # IPHONE AIR CLOUD WHITE 256GB MG2M4BE/A
    '000000000100066982': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PMAX PREMIUM OIV0817
    '000000000100047142': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 DROP NUDE OIV0454
    '000000000100063310': ('acessorio', 'Mouse', 'Originais iPlace'),  # MOUSE IPLACE GAMER IPSAR2525
    '000000000100046848': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE PAMPAS 13 BEG OIV0577
    '000000000100024935': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE MAC AIR 13,6 TRANSP OIV0296
    '000000000100068325': ('acessorio', 'Outros', 'Originais iPlace'),  # SMART LOCK IPLACE TSA LOREFSLTSA
    '000000000100072455': ('device', 'iPhone', None),  # IPHONE AIR LIGHT GOLD 256GB MG2N4BE/A
    '000000000100072447': ('device', 'iPhone', None),  # IPHONE 17 SAGE 256GB MG6N4BE/A
    '000000000100065132': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL CHARGE 6 AZL 28913864
    '000000000100055035': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS PRO 2 AZL OIV0604
    '000000000100032742': ('acessorio', 'Fone', 'Originais iPlace'),  # FONE IPLACE OVER N350 PTO AUHEL3030
    '000000000100055311': ('acessorio', 'Teclado', 'Apple'),  # TECLADO APPLE EUA BCO MXCL3BZ/A
    '000000000100072444': ('device', 'iPhone', None),  # IPHONE 17 WHITE 256GB MG6K4BE/A
    '000000000100042465': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16 PR ANTIBLU A.U OIV0556
    '000000000100066985': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17 PREMIUM A.U OIV0800
    '000000000100066973': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PRO PREMIUM A.U OIV0801
    '000000000100054643': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI MX ERGO TRACKB PTO 910-007261
    '000000000100046393': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE PAMPAS 16 MRM OIV0438
    '000000000100067150': ('acessorio', 'Teclado', 'Originais iPlace'),  # TECLADO IPLACE MECANICO GAMER IPSAR2727
    '000000000100036250': ('acessorio', 'Fone', 'JBL'),  # MICROFONE JBL QUANT TALK PTO 28913738
    '000000000100051945': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE BEATS IPH 16PRO PTO MCFL4LL/A
    '000000000100017763': ('acessorio', 'Outros', 'Originais iPlace'),  # FITA IPLACE LED RGBW 5M C/HOMEKIT OP5CF5
    '000000000100046305': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 PLUS AIRCUSHI OIV0211
    '000000000100069612': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL ENCOR ESS2 PTO 28913925
    '000000000100078943': ('acessorio', 'Fone', 'JBL'),  # FONE JBL SENSELITE PRETO 28914169
    '000000000100072603': ('device', 'Apple Watch', None),  # WATCH ULTRA3 49 NT TI AB  MEWH4BE/A
    '000000000100067450': ('acessorio', 'Fone', 'Originais iPlace'),  # FONE IPLACE GAM X700P OVER BCO AUSAR3737
    '000000000100059160': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE LIA NUDE OIV0658
    '000000000100016811': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPAD 2EM1 AIR 11 PTO OIV0389
    '000000000100042639': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PMAX GAMER A.U OIV0561
    '000000000100043405': ('acessorio', 'Fone', 'Logitech'),  # FONE LOGI ON C/FIO H390 BCO 981-001285
    '000000000100061095': ('acessorio', 'Capa/Case', 'Apple'),  # SMART FOLIO APPLE A16 BCO MDEJ4ZM/A
    '000000000100064926': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPAD A16 DROPP NUDE OIV0771
    '000000000100029599': ('device', 'iPhone', None),  # IPHONE SE 3RD MIDNIGHT 64GB MMXF3BZ/A
    '000000000100026369': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH PARTY 38-41 BEG OIV0530
    '000000000100073536': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-C BEATS VERM EL MDGF4LL/A
    '000000000100072755': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 17 PMAX PRETO MGFR4ZM/A
    '000000000100053033': ('acessorio', 'Outros', 'Originais iPlace'),  # DESKPAD IPLACE PTO OIV0586
    '000000000100018597': ('acessorio', 'Adaptador', 'Apple'),  # ADAPT APPLE USBC LIGHT BCO MUQX3AM/A
    '000000100048321001': ('device', 'iPhone', None),  # IPHONE 15 PRO TITANIUM 128GB BB I, E
    '000000100048208001': ('device', 'iPhone', None),  # IPHONE 15 BLACK 128GB BB I, E
    '000000000100015702': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15 PRO CANDY VRD OIV0283
    '000000100048399001': ('device', 'iPhone', None),  # IPHONE 12 WHITE 64GB BB I, E
    '000000000100080149': ('device', 'iPhone', None),  # IPHONE 17E SOFT PINK 256GB MHRX4BE/A
    '000000000100055036': ('acessorio', 'AirTag', 'Originais iPlace'),  # PUL IPLACE AIRTAG KIDS RSA OIV0601
    '000000000100073534': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-C LIGHT BEAT CZ MDGL4LL/A
    '000000000100072556': ('device', 'Apple Watch', None),  # WATCH 11 42 SI AL PF SB SM G MEU64AM/A
    '000000000100051727': ('device', 'iPhone', None),  # IPHONE 16 PLUS PINK 128GB MXVW3BE/A
    '000000000100066995': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17 PREMIUM OIV0815
    '000000000100072669': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 17 PRO TRANSP MGFT4ZM/A
    '000000000100072666': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 17 PRETO MGF14ZM/A
    '000000000100072555': ('device', 'Apple Watch', None),  # WATCH 11 42 RG AL LB SB ML G MEU44AM/A
    '000000000100041244': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI PEBBLE K380 RSA 920-011791
    '000000000100041296': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI WAVE KEYS GRAF 920-012281
    '000000000100037048': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPHONE 15 PRETO MT0J3ZM/A
    '000000000100060410': ('acessorio', 'Caneta', 'Originais iPlace'),  # CANETA IPLACE IPAD USB-C CNZ ACRUISPCWG
    '000000000100065114': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL FLIP 7 AZL 28913861
    '000000000100072793': ('acessorio', 'MagSafe', 'Apple'),  # BATERIA APPLE MAGSAFE IPH AIR MGPG4BE/A
    '000000000100073537': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-C BEATS AZUL PO MDGE4LL/A
    '000000000100072543': ('device', 'Apple Watch', None),  # WATCH SE 3 40 S AL S SB ML C MEP74AM/A
    '000000000100042324': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PLU ANTIBAC OIV0422
    '000000000100071414': ('acessorio', 'Outros', 'Originais iPlace'),  # CORDA SMART IPLACE PTO OIV0787
    '000000000100051937': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 46 ESP NIKE AREN MYL83AM/A
    '000000000100074071': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS PRO 3 SIL PT OIV0691
    '000000000100052076': ('acessorio', 'AirTag', 'Apple'),  # CHAVEIRO APPLE AIRTAG TEC PTO MA7G4ZM/A
    '000000000100024921': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE MAC AIR 13,3 M1 TRAN OIV0295
    '000000000100047927': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE ATLAS 16 PTO OIV0383
    '000000000100042646': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PM PRIVACID A.U OIV0559
    '000000000100040230': ('acessorio', 'Caneta', 'Logitech'),  # CANETA LOGI DIG CRYON PRATA 914-000070
    '000000000100040682': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI MX MASTER 3S CNZ 910-006562
    '000000000100067023': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM IPH AIR SILVER OIV0872
    '000000000100066981': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PRO PROSAFE OIV0809
    '000000000100046863': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 15 PROMAX 4/1 OIV0360
    '000000000100063299': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 14ANTIBAC/PRIV OIV0664
    '000000000100027004': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH COURO 40-41 PTO OIV0205
    '000000000100047838': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE PAMPAS 15 CAFE OIV0567
    '000000000100063909': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH BUMPER 42-45 PTO OIV0665
    '000000000100045529': ('acessorio', 'Outros', 'Originais iPlace'),  # ALCA DE MAO BRINDE OIV0317
    '000000000100014993': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 PLUS AIRCUSHION 303736
    '000000000100071982': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE MAC PRO 14 TRANSP OIV0687
    '000000000100071453': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL GO ESSEN 2 PTO 28913988
    '000000000100027028': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 42/44/49 COURO MARROM OIV0206
    '000000000100080253': ('device', 'Mac', None),  # MACB AIR 13 M5 16GB STL 512GB MDHA4BZ/A
    '000000000100034325': ('acessorio', 'Caixa de Som', 'Originais iPlace'),  # CAIXA DE SOM IPLACE S100 PTO AUWEI2828
    '000000000100056093': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16 ANTIBAC/PRIV OIV0634
    '000000000100066984': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17 PROSAFE OIV0807
    '000000000100079329': ('acessorio', 'Fone', 'JBL'),  # FONE JBL TUNE 730BT BRANCO 28914081
    '000000000100042421': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PRO GAMER OIV0435
    '000000000100037274': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 15 PRO TRANSPARE MT223ZM/A
    '000000000100067011': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PMAX ESSENTIAL OIV0806
    '000000000100046383': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15PRO MAX AIRCSH OIV0213
    '000000000100041097': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI MX MINI RSA 920-010507
    '000000000100069411': ('acessorio', 'Cabo', 'Mister'),  # CABO MISTER USB-C LIGH 1,5M BCO LCB1NVE
    '000000000100052118': ('acessorio', 'Carregador Apple', 'Apple'),  # CARREG APPLE USB-C MAG 1M BCO MX6X3BE/A
    '000000000100066997': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17PRO SHINE PTO OIV0827
    '000000000100016917': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA SLIM IPAD IPLACE PAMPAS MARIOIV0571
    '000000000100043739': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE WATCH 45MM C/B OIV0086
    '000000000100015900': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 PARTY RSA OIV0523
    '000000100048228001': ('device', 'iPhone', None),  # IPHONE 15 PINK 256GB BB I, E
    '000000100048221001': ('device', 'iPhone', None),  # IPHONE 15 BLUE 128GB BB I, E
    '000000000100058169': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-C MGSAFE 2M BCO MW613AM/A
    '000000000100016259': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX STAND CNZ OIV0489
    '000000000100060279': ('device', 'iPhone', None),  # IPHONE 16E BLK 256GB MD1T4BR/A
    '000000100048227001': ('device', 'iPhone', None),  # IPHONE 15 PINK 128GB BB I, E
    '000000000100047375': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX RING RSA OIV0477
    '000000000100047171': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 16 RING ROSA OIV0474
    '000000000100051730': ('device', 'iPhone', None),  # IPHONE 16 PLUS BLACK 256GB MXWN3BE/A
    '000000000100051200': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI TO GO 2 GRF 920-012867
    '000000000100041915': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15ANTIBAC OIV0239
    '000000000100072546': ('device', 'Apple Watch', None),  # WATCH SE 3 44 S AL S SB SM C MEPE4AM/A
    '000000000100046831': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 13 4 EM 1 OIV0356
    '000000000100039056': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPAD AIR 13 OIV04081
    '000000000100072611': ('device', 'Apple Watch', None),  # WATCH ULTRA3 49 NT TI NT TML MF0E4BE/A
    '000000000100026386': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH PARTY 38-41 RSA OIV0529
    '000000000100026987': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH COURO 40-41 MRM OIV0207
    '000000000100038699': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPAD PRO 11 OIV0410
    '000000000100072570': ('device', 'Apple Watch', None),  # WATCH 11 42 RG AL LB SB SM C MF8E4AM/A
    '000000000100047710': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 13 AIRCUS OIV0327
    '000000000100069408': ('acessorio', 'Cabo', 'Mister'),  # CABO MISTER USB-C LIGH 1,5M PTO LCP1NVE
    '000000000100072547': ('device', 'Apple Watch', None),  # WATCH SE 3 44 S AL S SB ML C MEPF4AM/A
    '000000000100052304': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 42 ESP NIKE AREN MYJR3AM/A
    '000000000100052307': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 42 ESP BLUSH MXLN3AM/A
    '000000000100032573': ('acessorio', 'Capa/Case', 'Apple'),  # SMART FOLIO APPLE PRO 13 PTO MWK33ZM/A
    '000000000100079306': ('acessorio', 'Fone', 'JBL'),  # FONE JBL TUNE 780NC BRANCO 28914104
    '000000000100035917': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL WIND 3 PTO 28913718
    '000000000100036239': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 14 SIL ROSA GIZ MPRX3ZE/A
    '000000000100072552': ('device', 'Apple Watch', None),  # WATCH 11 42 SG AL BK SB SM G MEQW4AM/A
    '000000000100052115': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 46 ESP CNZ MXLY3AM/A
    '000000000100056116': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPHONE 16 ANTIBAC OIV0626
    '000000000100055245': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE LIA PTO OIV0644
    '000000000100055033': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS PRO 2 STEAL OIV0605
    '000000000100042368': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PLUS PRIVACID OIV0426
    '000000000100027045': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 42/44/49 COURO PRETO OIV0204
    '000000000100069407': ('acessorio', 'Cabo', 'Mister'),  # CABO MISTER USB-A LIGH 1,5M BCO LAB1NVE
    '000000000100071496': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 13 ESSENTIAL OIV0683
    '000000000100064551': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH TITANIU 42-49 PTO OIV0673
    '000000100048148001': ('device', 'iPhone', None),  # IPHONE 14 PRO MAX D PURPLE 128GB BB I, E
    '000000000100015667': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15PRO NORON BRA OIV0226
    '000000000100016187': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 PROMX LIL BRI OIV0456
    '000000000100080257': ('device', 'Mac', None),  # MACB AIR 13 M5 16GB MDN 1TB MDHF4BZ/A
    '000000000100031570': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE LIGH P2 1,5M BCO AUBOT1010
    '000000000100067216': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA/CABO LACOSTE IPH17PRO PTO OIV0906
    '000000000100051728': ('device', 'iPhone', None),  # IPHONE 16 PLUS ULTMARINE 128GB MXVX3BE/A
    '000000000100047850': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPHONE IPLACE SCREEN PTO 15 OIV0402
    '000000000100072568': ('device', 'Apple Watch', None),  # WATCH 11 42 SG AL BK SB SM C MF8A4AM/A
    '000000000100067010': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17 ESSENTIAL OIV0803
    '000000000100072540': ('device', 'Apple Watch', None),  # WATCH SE 3 44 M AL M SB SM G MEHN4AM/A
    '000000000100072519': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 17 PRO PRETO MGFK4ZM/A
    '000000000100080227': ('device', 'iPad', None),  # IPAD AIR M4 11 WF STL 128GB MH334BZ/A
    '000000000100061167': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYBOARD APPLE AIR11 BCO MDFV4BZ/A
    '000000000100060995': ('device', 'iPad', None),  # IPAD 11TH CELL 128GB BLUE MD7G4BZ/A
    '000000100048717001': ('device', 'iPhone', None),  # IPHONE 13 MIDNIGHT 128GB BB N, E
    '000000000100047411': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 FORCE PTO OIV0510
    '000000000100040812': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI PEBBLE 2 M350S RSA 910-007048
    '000000000100072610': ('device', 'Apple Watch', None),  # WATCH ULTRA3 49 NT TI NT TML MEWY4BE/A
    '000000000100034980': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL BOOMBOX 3 PTO 2891362
    '000000000100055319': ('device', 'Mac', None),  # IMAC 24 M4 SILVER 256GB 8GPU MWUC3BZ/A
    '000000000100056105': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH16PRO ANTIBAC/PRIV OIV0636
    '000000000100047096': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 16 CANDY ROSA OIV0457
    '000000000100054641': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI ERGO M575S PTO 910-007031
    '000000000100032911': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYBOARD APPLE PRO11 BCO MWR03BZ/A
    '000000000100035829': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP12MINI SILMAG WHT MHKV3ZE/A
    '000000000100072524': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH AIR TRANSP FOSC MGH34ZM/A
    '000000000100046750': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 PRO SIL PRETO OIV0349
    '000000000100041994': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15ANTI BLUE A.U OIV0544
    '000000000100026980': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 40/41 COURO MARINHO OIV0209
    '000000000100016910': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA SLIM IPAD IPLACE PAMPAS PRETO
    '000000000100032787': ('acessorio', 'Fone', 'JBL'),  # FONE JBL ON TUNE 520 PTO 28913696
    '000000100048340001': ('device', 'iPhone', None),  # IPHONE 15 PRO MAX BLK TITAN 256GB BB, E
    '000000000100043571': ('acessorio', 'Fone', 'Logitech'),  # FONE LOGI ON ZONE 300 BCO 981-001416
    '000000000100027296': ('acessorio', 'Outros', 'Originais iPlace'),  # SMART TAG IPLACE SAMPA CNZ OP5TB
    '000000000100027566': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA AIRTAG IPLACE SPRING ROSA OIV0538
    '000000000100036334': ('acessorio', 'Fone', 'Originais iPlace'),  # FONE IPLACE IN GAMER X220 BCO AUHEL5656
    '000000000100040301': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE/F2 IP 12PMAX VIDR TRANS C/BDA
    '000000000100037179': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 15 PLUS TRANSPAR MT213ZM/A
    '000000000100018449': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USBC USBC 1,2M PTO OP1DCMP1
    '000000000100037209': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 15 PRO ROSA CLAR MT1F3ZM/A
    '000000000100075276': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 17PM STAND AZUL OIV0923
    '000000000100035540': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL PARTBOX110 AMA 58035030
    '000000000100046221': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 12 TRANS SLIM OIV0131
    '000000000100055382': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC TRACKPAD APPLE PTO MXKA3BE/A
    '000000000100034657': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL GO ESSENT PTO 28913614
    '000000000100040648': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP 12/12 PRO PRIV OIV0026
    '000000000100072586': ('device', 'Apple Watch', None),  # WATCH 11 46 SG AL BK SB ML C MFCA4AM/A
    '000000000100046947': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PLUS POLI PTO OVI0497
    '000000000100072619': ('device', 'Apple Watch', None),  # WATCH ULTRA3 49 BK TI BK TML MF1Q4BE/A
    '000000000100036205': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 14 SIL AZUL TEM MPRV3ZE/A
    '000000000100041933': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15 ANTIBLUE OIV0243
    '000000000100067213': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 BMW PTO OIV0901
    '000000000100025293': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYBOARD APPLE 3 MK2A3BZ/A
    '000000000100072551': ('device', 'Apple Watch', None),  # WATCH 11 42 JB AL BK SB ML G MEQU4AM/A
    '000000000100046788': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP15 PRO MAX SIL PTO OIV0350
    '000000000100080754': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS MAX 2 ESTEL MHWL4BE/A
    '000000000100080881': ('device', 'iPhone', None),  # IPHONE 17E BLACK 512GB MHRY4BR/A
    '000000000100047025': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PRO STAND PTO OIV0485
    '000000000100032781': ('acessorio', 'Fone', 'JBL'),  # FONE JBL ON TUNE 520 AZL 28913698
    '000000000100053569': ('acessorio', 'Capa/Case', 'Logitech'),  # CAPA LOGI TEC 10TH GRF 920-011295
    '000000000100025852': ('device', 'Apple TV', None),  # APPLE TV 4K 64GB MP7P2BZ/A
    '000000000100060721': ('acessorio', 'Adaptador', 'Apple'),  # ADAPT APPLE USB-C TO USB BCO MW5L3AM/A
    '000000000100015228': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPHONE IPLACE SIL AZU 14 PR OIV0053
    '000000000100069412': ('acessorio', 'Outros', 'Originais iPlace'),  # APRESENTADOR IPLACE USB-A CNZ ACTRAPPCAB
    '000000000100017142': ('acessorio', 'Cabo', 'Mister'),  # CABO MISTER USB-C USBC 1,5 PTO MT1DCCP
    '000000000100058249': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE MAC AIR 13,6 SHINE OIV0656
    '000000000100016320': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA  SLIM IPAD IPLACE PAMPAS CAFE
    '000000100048346001': ('device', 'iPhone', None),  # IPHONE 15 PRO MAX TITANIUM 256GB BB I, E
    '000000000100015810': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15 PRO MAX BRILHO OIV0272
    '000000000100064790': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS MAX PTO MWW43BE/A
    '000000000100027113': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE SILIC 38/41MARR IMA OIV0379
    '000000000100045760': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 11 SIL ROS CHA 303861
    '000000000100065116': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL FLIP 7 BCO 28913862
    '000000000100080160': ('device', 'iPad', None),  # IPAD AIR M4 13 WF SP GR 128GB MH5N4BZ/A
    '000000000100046640': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 PRO ALCA PTO OIV0276
    '000000000100072459': ('device', 'iPhone', None),  # IPHONE AIR LIGHT GOLD 512GB MG2U4BE/A
    '000000000100044247': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPAD 9 ANTIBAC OIV0108,
    '000000000100072548': ('device', 'Apple Watch', None),  # WATCH SE 3 44 M AL M SB SM C MEPH4AM/A
    '000000000100080755': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS MAX 2 AZUL MHWM4BE/A
    '000000100048839001': ('device', 'iPhone', None),  # IPHONE 14 PURPLE 128GB BB I, E
    '000000000100032949': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 11 SIL BRANCO MWVX2ZM/A
    '000000000100034283': ('acessorio', 'Caixa de Som', 'Originais iPlace'),  # CAIXA DE SOM IPLACE CONNECT S50 PRETA/CI
    '000000000100046866': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 14 SIL PTO OIV0361
    '000000000100032104': ('device', 'iPhone', None),  # IPHONE 15 PINK 128GB MTP13BR/A
    '000000000100016040': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PRO SHINE OIV0451
    '000000000100073535': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-C LIGH BEAT VER MFEH4LL/A
    '000000100048343001': ('device', 'iPhone', None),  # IPHONE 15 PRO MAX BLU TITAN 256GB BB, E
    '000000000100034983': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL BOOMBOX 3WF PT 28913670
    '000000000100040776': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI PEBBLE 2 M350S GFT 910-007049
    '000000000100080251': ('device', 'Mac', None),  # MACB AIR 13 M5 16GB  SIL 1TB MDH84BZ/A
    '000000000100053036': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 13 POLI PTO OIV0589
    '000000000100073509': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-A USB-C BEA VER MFEJ4LL/A
    '000000000100027335': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA AIRTAG IPLACE TPU PET RSA PP0760
    '000000000100045880': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14 MS MARSALA O12191
    '000000000100055032': ('acessorio', 'Fone', 'Originais iPlace'),  # SUPORTE IPLACE HEADSET MUL 3X1 IPLUM2121
    '000000000100067209': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX MERC PTO OIV0902
    '000000000100075679': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MALA IPLACE MAO C SLEEVE COUR PT OIV0928
    '000000000100019050': ('acessorio', 'Adaptador', 'Apple'),  # ADAPT APPLE USB-C AV DIG BCO MW5M3AM/A
    '000000000100052117': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 46 ESP NIKE CHAM MYLC3AM/A
    '000000000100054161': ('acessorio', 'Capa/Case', 'Logitech'),  # CAPA LOGI TEC AIR 11 CNZ 920-012626
    '000000000100017478': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE LIGH USB-C 2M BCO OP1DLCB2
    '000000000100037226': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPHONE 15 PRO PRETO MT1A3ZM/A
    '000000000100046753': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHO 15 PRO MAX SLIM OIV0354
    '000000000100031853': ('acessorio', 'Fone', 'JBL'),  # FONE OUVIDO JBL ENDURRACE BLKBR 28913810
    '000000000100032870': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYB 5GER APPLE 12.9 BCO MJQL3BZ/A
    '000000000100019972': ('acessorio', 'Carregador', 'Mister'),  # KIT VIAGEM MISTER 30W USB-C PTO MT4VCCP
    '000000000100016245': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I16PROMAX CANDY ROSA OIV0460
    '000000000100016146': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX DROP NUDE OIV0466
    '000000000100015794': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15 PROMAX ALC PTO OIV0277
    '000000100048811001': ('device', 'iPhone', None),  # IPHONE 14 MIDNIGHT 128GB BB N, E
    '000000000100066663': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPAD MAG PRO 11 OIV0785
    '000000100048109001': ('device', 'iPhone', None),  # IPHONE 14 PRO D PURPLE 128GB BB I, E
    '000000000100051732': ('device', 'iPhone', None),  # IPHONE 16 PLUS PINK 256GB MXY13BE/A
    '000000000100066838': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17PRO STEAL OIV0854
    '000000000100015941': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PLUS DROP NUDE OIV0465
    '000000000100055386': ('device', 'Mac', None),  # IMAC 24 M4 SILVER 256GB 10GPU MWUU3BZ/A
    '000000000100080226': ('device', 'iPad', None),  # IPAD AIR M4 11 WF BL 128GB MH314BZ/A
    '000000100048695001': ('device', 'iPhone', None),  # IPHONE 13  PINK 128GB BB N, E
    '000000000100027144': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 38/40/41 METAL DOURADO OIV0255
    '000000000100031290': ('acessorio', 'Fone', 'JBL'),  # FONE DE OUVIDO JBL ENDUR RACE BLU 289135
    '000000000100031387': ('acessorio', 'Fone', 'JBL'),  # FONE DE OUVIDO JBL TUNE FLX PTO 28913646
    '000000000100020235': ('acessorio', 'Outros', 'Originais iPlace'),  # SUPORTE IPLACE VEICULAR PTO 15W OP1BWFS
    '000000000100027560': ('acessorio', 'Pulseira', 'Originais iPlace'),  # PULSEIRA IPLACE AIRTAG KIDS OIV0310
    '000000000100041418': ('acessorio', 'Outros', 'Logitech'),  # MOUSEPAD LOGI STUDIO GRF 956-000035
    '000000000100045641': ('acessorio', 'Outros', 'Originais iPlace'),  # POCHETE IPLACE PRT OIV0342
    '000000000100045883': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14 MS VERDE O1241
    '000000000100080163': ('device', 'iPad', None),  # IPAD AIR M4 13 WF SP GR 256GB MH5U4BZ/A
    '000000000100043467': ('acessorio', 'Fone', 'Logitech'),  # FONE LOGI ON C/FIO H390 PTO 981-000014
    '000000000100068321': ('acessorio', 'Outros', 'Originais iPlace'),  # SMART TAG IPLACE BRANCO LOREFSTBCO
    '000000000100046860': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 15 PRO 4 EM 1 OIV0359
    '000000000100041360': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 14PRIVACID OIV0007
    '000000000100064925': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPAD A16 DROPP PTO OIV0770
    '000000000100060361': ('acessorio', 'Carregador', 'Originais iPlace'),  # CARREG IPLACE 3EM1 PORTATIL CNZ OIMWADC
    '000000100048855001': ('device', 'iPhone', None),  # IPHONE 14 STARLIGHT 128GB BB I, E
    '000000000100015202': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 PRO SIL CINZA OIV0065
    '000000000100042552': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PLU ANTIBAC A.U OIV0550
    '000000000100041610': ('acessorio', 'Capa/Case', 'Logitech'),  # CAPA TEC LOGITECH IPAD UNIPTO 920-008334
    '000000000100019668': ('acessorio', 'Outros', 'Originais iPlace'),  # ADA IPLACE PAR USB 2 SAID SMART IC2.4 BC
    '000000000100074514': ('device', 'iPad', None),  # IPAD PRO 11 M5 WIFI 256GB SIL MDWL4BZ/A
    '000000000100074515': ('device', 'iPad', None),  # IPAD PRO 11 M5 WIFI 512GB SB MDWM4BZ/A
    '000000000100018415': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USBC USBC 1,2M BCO OP1DCMB1
    '000000000100018456': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C USB-C15CM BCO OP1DCCB0
    '000000000100052074': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16PMAX TRANSP MA7F4ZM/A
    '000000000100035973': ('acessorio', 'Outros', 'JBL'),  # CAIXA SOM JBL ENCORE ESS PTO 28913611
    '000000000100072620': ('device', 'Apple Watch', None),  # WATCH ULTRA3 49 BK TI BK TML MF1T4BE/A
    '000000000100072691': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 17 ROXO MGF04ZM/A
    '000000000100042063': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15PLU SANTIBAC OIV0240
    '000000000100042028': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15 PLUS ANTIBLUE OIV0244
    '000000000100031804': ('acessorio', 'Fone', 'JBL'),  # FONE DE OUVIDO JBL TUNE FLX PTO 28913803
    '000000000100042385': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PRO ANTIBAC OIV0423
    '000000000100037103': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 15 TRANSPARENTE MT203ZM/A
    '000000000100037065': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPHON 15 ROSA CLARO MT0U3ZM/A
    '000000000100042437': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PLU GAMER A.U OIV0553
    '000000000100046643': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 PRO BRIHO OIV0271
    '000000000100046834': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14 4 EM 1 OIV0357
    '000000000100041323': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI WAVE KEYS BCO 920-012282
    '000000000100080324': ('device', 'Mac', None),  # MACBOOK NEO 13 A18P BLS 512GB MHFJ4BZ/A
    '000000000100034429': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL CLIP 5 PTO 28913768
    '000000000100047416': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX BUBBLE PTO OIV0509
    '000000000100047418': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX FORCE PTO OIV0512
    '000000000100046979': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PRO POLI PTO OIV0498
    '000000000100046675': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP12 TRANS MAGNETICA OIV0309
    '000000000100047177': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 STAND PTO OIV0483
    '000000000100046976': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PRO POLI BCO OIV0502
    '000000000100074513': ('device', 'iPad', None),  # IPAD PRO 11 M5 WIFI 256GB SB MDWK4BZ/A
    '000000000100055243': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE AURORA PRETA OIV0642
    '000000000100072795': ('acessorio', 'MagSafe', 'Apple'),  # CARREGADOR APPLE MAGSAFE 2M MGDM4BE/A
    '000000000100074525': ('device', 'iPad', None),  # IPAD PRO 13 M5 WIFI 256GB SB MDYJ4BZ/A
    '000000000100075070': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 17PRO PC SHINE PT OIV0914
    '000000000100074880': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15 PROSAFE OIV0694
    '000000000100071497': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15 ESSENTIAL OIV0684
    '000000000100054577': ('device', 'iPad', None),  # IPAD MINI 7TH WF 128GB PURPLE MXN93BZ/A
    '000000000100071981': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE MAC PRO 14 PU MAR OIV0686
    '000000000100024962': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE MAC AIR 15,3 M2 TRAN OIV0297
    '000000000100067210': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH17PMAX GUESS PTO OIV0897
    '000000000100051734': ('device', 'iPhone', None),  # IPHONE 16 PLUS TEAL 256GB MXY53BE/A
    '000000000100067025': ('acessorio', 'Pulseira', 'Originais iPlace'),  # PULSEIRA IPLACE COW 38-41MM OIV0860
    '000000000100051946': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16PRO SIL FUC MYYN3ZM/A
    '000000000100054645': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE AURORA 14 NUDE OIV0609
    '000000000100046105': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE WATCH USB-A 1M BCO MX2E2BE/A
    '000000000100080264': ('device', 'Mac', None),  # MACB AIR 15 M5 24GB SIL 1TB MDVC4BZ/A
    '000000000100016078': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX POLI BCO OIV0503
    '000000000100014334': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I12/12PRO AIRCUSHION OIV0006
    '000000000100067218': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17PRO BMW PTO OIV0900
    '000000000100024469': ('acessorio', 'MagSafe', 'Apple'),  # CARREG APPLE MAGSAFE COM IMA MHXH3BE/A
    '000000000100047714': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 13 SLIM OIV0328
    '000000000100047712': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 13 SILICONE PTO OIV0326
    '000000000100080259': ('device', 'Mac', None),  # MACB AIR 13 M5 16GB S BL 512GB MDHH4BZ/A
    '000000000100080258': ('device', 'Mac', None),  # MACB AIR 13 M5 24GB MDN 1TB MDHG4BZ/A
    '000000000100016163': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX RING AZL OIV0482
    '000000000100051919': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16PL SIL PTO MYY93ZM/A
    '000000000100051930': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 49 LOOP T VRD MXTN3AM/A
    '000000000100052114': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 46 ESPORTIVA PTO MXM43AM/A
    '000000000100060115': ('acessorio', 'Outros', 'Originais iPlace'),  # CHAVEIRO IPLACE SMART TAG CNZ OIV0659
    '000000000100056929': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 15 ROSA CLARO MXPH3ZM/A
    '000000100048163001': ('device', 'iPhone', None),  # IPHONE 14 PRO MAX GOLD 256GB BB I, E
    '000000000100060998': ('device', 'iPad', None),  # IPAD 11TH CELL 256GB SILVER MD7K4BZ/A
    '000000000100051952': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16PRO TRANSP MA7E4ZM/A
    '000000000100052079': ('acessorio', 'AirTag', 'Apple'),  # CHAVEIRO APPLE AIRTAG TEC AMO MA7K4ZM/A
    '000000000100017323': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C TO LIGH 15CM BCO 1799
    '000000000100066791': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16E ANTIBAC A.U OIV0888
    '000000000100060283': ('device', 'iPhone', None),  # IPHONE 16E BLK 128GB DEMO 3N762BE/A
    '000000100048830001': ('device', 'iPhone', None),  # IPHONE 14 STARLIGHT 128GB BB N, E
    '000000100049328001': ('device', 'Apple Watch', None),  # WATCH SE 2ND GPS 40MM STARLIGHT BB, E
    '000000000100016491': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE TEC 10TH VERDE IPSTA1111
    '000000000100060354': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16E SIL PTO MD3N4ZM/A
    '000000100048127001': ('device', 'iPhone', None),  # IPHONE 14 PRO SILVER 128GB BB I, E
    '000000000100015687': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15 PRO CANDY ROSA OIV0286
    '000000000100015402': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I14PROMAX SIL VER LIM 303858
    '000000100048362001': ('device', 'iPhone', None),  # IPHONE 12 BLACK 128GB BB N, E
    '000000100053744001': ('device', 'iPhone', None),  # IPHONE 16 PRO MAX TITAN PRETO 256GB B, E
    '000000100049420001': ('device', 'Apple Watch', None),  # WATCH S9 ALUM GPS 41MM PINK BB, E
    '000000100048812001': ('device', 'iPhone', None),  # IPHONE 14 MIDNIGHT 256GB BB N, E
    '000000100039301001': ('device', 'iPad', None),  # IPAD 9TH WF S. GRAY 64GB BB, E
    '000000000100066661': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE MAG IPAD AIR 11 OIV0784
    '000000000100080267': ('device', 'Mac', None),  # MACB AIR 15 M5 24GB STL 1TB MDVF4BZ/A
    '000000100048167001': ('device', 'iPhone', None),  # IPHONE 14 PRO MAX SILVER 256GB BB I, E
    '000000000100060988': ('device', 'iPad', None),  # IPAD 11TH WIFI 256GB YELLOW MD4J4BZ/A
    '000000000100014951': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CASE AIRPODS IPLACE PAMPAS ARTESAN PRETO
    '000000000100020448': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPHONE 14 TRANSP SLIM OIV0364
    '000000000100051941': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE BEATS IPH 16PL ROX MCFK4LL/A
    '000000000100051915': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16 TRANSP MA6A4ZM/A
    '000000000100051918': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE BEATS IPH 16PL PTO MCFG4LL/A
    '000000000100052303': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 42 CAQUI MYJY3AM/A
    '000000000100051861': ('device', 'Apple Watch', None),  # WATCH S10 DM 46 RG AL LB SB SM G 3N499BZ
    '000000000100037130': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 15 AZUL TEMPESTA MT0N3ZM/A
    '000000000100037172': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPHON 15 PLUS PRETO MT103ZM/A
    '000000000100036468': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 14 PLUS TRANS MPU43ZE/A
    '000000000100080280': ('device', 'Mac', None),  # MACB PRO 16 M5P 24GB SIL 1TB MGE44BZ/A
    '000000000100061090': ('device', 'Mac', None),  # MAC STUDIO M4 MAX 512GB 36GB MU963BZ/A
    '000000000100016064': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 16 PRO BUBBLE PTO OIV0508
    '000000100048307001': ('device', 'iPhone', None),  # IPHONE 15 PRO BLUE TITAN 128GB BB I, E
    '000000000100046944': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PLUS POLI BCO OIV0501
    '000000000100047816': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 CANDY RSA OIV0285
    '000000000100047818': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15 CANDY VERDE OIV0282
    '000000000100024928': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE MAC AIR 13,3 M1 TRAN OIV0298
    '000000000100024887': ('acessorio', 'Outros', 'Originais iPlace'),  # SUPORTE IPLACE MAC METAL PRATA OIV0111
    '000000000100041826': ('acessorio', 'Capa/Case', 'Logitech'),  # CAPA LOGI TEC PRO 13 CNZ 920-010097
    '000000000100051205': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP 12MINI VID TRAN C/BDA 1568
    '000000000100047996': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP12MI TRANS CLASS IP-1242PT
    '000000000100072582': ('device', 'Apple Watch', None),  # WATCH 11 42 GOLD TI GD ML C MF8Y4AM/A
    '000000000100072562': ('device', 'Apple Watch', None),  # WATCH 11 46 RG AL LB SB SM G MEV64AM/A
    '000000000100072563': ('device', 'Apple Watch', None),  # WATCH 11 46 RG AL LB SB ML G MEV74AM/A
    '000000000100041809': ('acessorio', 'Capa/Case', 'Logitech'),  # CAPA TC LOGITECH IPADPRO11 3R 920-010095
    '000000000100051947': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16PRO SIL PTO MYYJ3ZM/A
    '000000000100039415': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPHONE 11 ANTIBAC OIV0032
    '000000000100051618': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS 4GER CAN MXP93BZ/A
    '000000000100045918': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14 AIRCUSHION OIV0001
    '000000000100045925': ('acessorio', 'Adaptador', 'Originais iPlace'),  # ADAPTADOR IPLACE USB-C 6X1 G3.1 2011
    '000000000100055381': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC TRACKPAD APPLE BCO MXK93BE/A
    '000000000100017330': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C TO LIGH 15CM PRA 1800
    '000000000100055026': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS PRO 2 TRANSP OIV0608
    '000000000100056104': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH16PMAX ANTBAC/PRIV OIV0637
    '000000000100056112': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH16 PRO MAX ANTIBAC OIV0629
    '000000000100055407': ('device', 'Mac', None),  # MACBOOK AIR 13 M2 MID 256GB MC7X4BZ/A
    '000000000100040697': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI SIGNAT M650 BCO 910-006233
    '000000000100072602': ('device', 'Apple Watch', None),  # WATCH 11 46 GD TI GD ML ML C MFD84AM/A
    '000000000100038577': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM 14/14 PLUS SILVER OIV0088
    '000000000100047508': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX PARTY BCO OIV0521
    '000000000100047560': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX PARTY RSA OIV0525
    '000000000100047174': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 STAND CNZ OIV0487
    '000000000100054642': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI MX VERT GRF 910-005449
    '000000000100032771': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYB 11POL IPAD PRO 3TH MXQT2BZ/A
    '000000000100052961': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH SIL IMA 38-41 MRM OIV0592
    '000000000100055244': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE LIA PRETA SNAKE OIV0645
    '000000000100055312': ('acessorio', 'Teclado', 'Apple'),  # TECLADO APPLE TOUCH NUM EUA  MXK73BZ/A
    '000000000100074508': ('device', 'Mac', None),  # MACB PRO 14 M5 SB 16GB 1TB MDE14BZ/A
    '000000000100040690': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI MX MASTER 3S GRF 910-006561
    '000000000100036263': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPHONE 14 SIL MID MPRU3ZE/A
    '000000000100035880': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP12MINI SILMAG PNK MHKP3ZE/A
    '000000000100079313': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL ENCOR ES 2 BCO 28914164
    '000000000100054163': ('acessorio', 'Capa/Case', 'Logitech'),  # CAPA LOGI TEC PRO 13 GRF 920-012658
    '000000000100066988': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PRO ESSENTIAL OIV0805
    '000000000100066975': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PMAX PROMATTE OIV0814
    '000000000100038534': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM IPH14/14PLUS SIL OIV0092
    '000000000100045454': ('acessorio', 'Outros', 'Originais iPlace'),  # SUPORTE IPLACE PRA GUIDAO PTO OIV0311
    '000000000100042081': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15PLU PRIVACID OIV0252
    '000000000100042472': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PRO GAMER A.U OIV0557
    '000000000100046869': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14AIR CUSHION OIV0362
    '000000000100046756': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 15 PLUS SLIM OIV0352
    '000000000100068338': ('acessorio', 'Teclado', 'Originais iPlace'),  # TECLADO NUM IPLACE BT CNZ ACSARWKTAN
    '000000000100068317': ('acessorio', 'Outros', 'Originais iPlace'),  # SMART TAG IPLACE AZUL LOREFSTAZL
    '000000000100080392': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL PBCLUB 120 PTO 58035038
    '000000000100072558': ('device', 'Apple Watch', None),  # WATCH 11 46 JB AL BK SB SM G MEUW4AM/A
    '000000000100072560': ('device', 'Apple Watch', None),  # WATCH 11 46 SG AL BK SB SM G MEV04AM/A
    '000000000100015148': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 PRO SIL CINZA U 303843
    '000000000100043597': ('acessorio', 'Fone', 'Logitech'),  # FONE LOGI ON ZONE 300 RSA 981-001411
    '000000000100043654': ('acessorio', 'Película', 'Originais iPlace'),  # PEL TRANS IPLACE WATCH 42MM IP-1019VT
    '000000000100043549': ('acessorio', 'Película', 'Originais iPlace'),  # PEL TRANS IPLACE WATCH 38MM IP-1018VT
    '000000000100015883': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 PRO RING ROSA OIV0476
    '000000000100015907': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 SPRING ROSA OIV0533
    '000000000100060414': ('acessorio', 'Teclado', 'Apple'),  # TECLADO APPLE NUM EUA BCO MXCJ3BZ/A
    '000000000100061262': ('device', 'iPad', None),  # IPAD AIR 7TH 11 WF 128GB BL DM 3N671BZ/A
    '000000000100046510': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHON 15 PRO SIL ORQ OIV0261
    '000000000100046467': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 PRO MAX ORQ OIV0262
    '000000000100069613': ('acessorio', 'Fone', 'JBL'),  # FONE JBL OV TUNE 520C PTO 28914008
    '000000000100045704': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 11 SIL CINZA U 303863
    '000000000100072458': ('device', 'iPhone', None),  # IPHONE AIR CLOUD WHITE 512GB MG2T4BE/A
    '000000000100072446': ('device', 'iPhone', None),  # IPHONE 17 LAVENDER 256GB MG6M4BE/A
    '000000000100030563': ('device', 'iPhone', None),  # IPHONE 14 STARLIGHT 128GB MPUR3BR/A
    '000000000100027209': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH TEC MAG 38-41 VRD OIV0413
    '000000000100031710': ('acessorio', 'Fone', 'JBL'),  # FONE JBL IN TUNE 310C PTO 28913773
    '000000000100031439': ('acessorio', 'Fone', 'JBL'),  # FONE DE OUVIDO JBL REF AERO WHT 28913628
    '000000000100031293': ('acessorio', 'Fone', 'JBL'),  # FONE DE OUVIDO JBL ENDUR RACE COR 289135
    '000000000100031299': ('acessorio', 'Fone', 'JBL'),  # FONE DE OUVIDO JBL LIVE PRO2 TWS SIL 289
    '000000000100045837': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14 MS LILAS O12201
    '000000000100015018': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14PLUS SIL CINZA U 303842
    '000000000100015542': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I14PROMAX AIRCUSHION OIV0004
    '000000000100015292': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I14PROMAX SIL AMA SIC 303854
    '000000100048309001': ('device', 'iPhone', None),  # IPHONE 15 PRO BLUE TITAN 256GB BB I, E
    '000000000100016180': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX STAND PTO OIV0486
    '000000000100016023': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 16 PRO DROP LILAS OIV0469
    '000000000100015924': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 16 PLUS DROP NUDE OIV0462
    '000000000100061108': ('device', 'Mac', None),  # MACBOOK AIR M4 13 BL 256 16 DM MC6T4BZ/A
    '000000000100015168': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 PRO SIL ROS CHA 303847
    '000000000100015223': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 PRO SIL LAVANDA OIV005
    '000000000100015053': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14PLUS SIL PRETO OIV0060
    '000000000100015071': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS SPRING ROSA OIV0537
    '000000000100015103': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 PRO AIR CUSHION 303737
    '000000000100033398': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS 3GER MME73BE/A
    '000000000100034280': ('acessorio', 'Caixa de Som', 'Originais iPlace'),  # CAIXA DE SOM IPLACE CONNECT S50 AZUL/AMA
    '000000000100057681': ('device', 'Apple TV', None),  # APPLE TV 4K 64GB WI-FI MN873BZ/A
    '000000000100056772': ('acessorio', 'Fone', 'JBL'),  # FONE JBL IN WAVE BUDS 2 AZL 28913826
    '000000000100060990': ('device', 'iPad', None),  # IPAD 11TH WIFI 512GB SILVER MD4Q4BZ/A
    '000000100048225001': ('device', 'iPhone', None),  # IPHONE 15 GREEN 256GB BB I, E
    '000000100048303001': ('device', 'iPhone', None),  # IPHONE 15 PRO BLK TITANIUM 128GB BB I, E
    '000000100048305001': ('device', 'iPhone', None),  # IPHONE 15 PRO BLK TITANIUM 256GB BB I, E
    '000000100048180001': ('device', 'iPhone', None),  # IPHONE 14 PRO MAX SPC BLK 128GB BB I, E
    '000000000100080268': ('device', 'Mac', None),  # MACB AIR 15 M5 16GB MDN 512GB MDVH4BZ/A
    '000000000100080277': ('device', 'Mac', None),  # MACB PRO 14 M5P 24GB SPB 1TB MGDR4BZ/A
    '000000000100080262': ('device', 'Mac', None),  # MACB AIR 15 M5 16GB SIL 512GB MDV94BZ/A
    '000000000100051856': ('device', 'Apple Watch', None),  # WATCH S10 DM 42 RG AL PLUM SL G 3N492BZ
    '000000000100051859': ('device', 'Apple Watch', None),  # WATCH S10 DM 46 JB AL BK SB SM G 3N496BZ
    '000000000100051879': ('device', 'Apple Watch', None),  # WATCH S10 46 RG AL LB SB ML G MWWU3AM/A
    '000000000100052309': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 42 ESP NIKE PLAT MYJM3AM/A
    '000000000100052302': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 42 LOOP E AZL MXKX3AM/A
    '000000000100052305': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 42 MILANES DOU MXMN3AM/A
    '000000000100052081': ('acessorio', 'Outros', 'Apple'),  # CARTEIRA APPLE TECIDO VRD MA6Y4ZM/A
    '000000000100051949': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE BEATS IPH 16PRO AZL MCFN4LL/A
    '000000000100051938': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 46 LOOP E ESTL MYJE3AM/A
    '000000000100051911': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16 SIL PTO MYY13ZM/A
    '000000000100051913': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE BEATS IPH 16 ROX MCFF4LL/A
    '000000000100020044': ('acessorio', 'Carregador', 'Originais iPlace'),  # CARREG IPLACE 2PORT 30W VRD OP1ANG3DBGG
    '000000000100037404': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 15 PRO MAX TRANS MT233ZM/A
    '000000000100037196': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 15 PRO AZUL TEMP MT1D3ZM/A
    '000000000100052077': ('acessorio', 'AirTag', 'Apple'),  # CHAVEIRO APPLE AIRTAG TEC AZL MA7H4ZM/A
    '000000000100066987': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PRO PREMIUM OIV0816
    '000000000100053768': ('device', 'iPhone', None),  # IPHONE 16 WHITE 512GB MYEP3BR/A
    '000000000100054553': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 15 SIL PTO MXPD3ZM/A
    '000000000100018128': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE LIGHTN 15CM SPACE CIPMFI NEW
    '000000000100017463': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE LIGH USB-C 1,2M VRD OP1DLCGS
    '000000000100017471': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE LIGH USB-C 1,2M RSA OP1DLCRS
    '000000000100036188': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 14 TRANS MPU13ZE/A
    '000000000100035904': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP12MINI SILMAG KUM MHKN3ZE/A
    '000000000100036012': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL ENCORE ESS PTO 58035033
    '000000000100035546': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL PBCLUB 120 PTO 28913763
    '000000000100032451': ('acessorio', 'Capa/Case', 'Apple'),  # SMART FOLIO APPLE AIR 11 CNZ MWK53ZM/A
    '000000000100073429': ('acessorio', 'Outros', 'Originais iPlace'),  # DESKPAD IPLACE GAMER INDUC PTO IPGUA2929
    '000000000100072614': ('device', 'Apple Watch', None),  # WATCH ULTRA3 49 BK TI BK ALP MF0V4BE/A
    '000000000100039423': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPHONE 11 PRIV OIV0025
    '000000000100051828': ('device', 'Apple Watch', None),  # WATCH SE 2 44 SI AL DN SB ML G MXER3BE/A
    '000000000100051645': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE WATCH SIL 42/45 PTO OIV0596
    '000000000100066999': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH AIR ESSENTIAL OIV0804
    '000000000100051944': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16PL TRANSP MA7D4ZM/A
    '000000000100072587': ('device', 'Apple Watch', None),  # WATCH 11 46 RG AL LB SB SM C MFCG4AM/A
    '000000000100072584': ('device', 'Apple Watch', None),  # WATCH 11 46 JB AL BK SB ML C MFC44AM/A
    '000000000100072566': ('device', 'Apple Watch', None),  # WATCH 11 42 JB AL BK SB SM C MF834AM/A
    '000000000100050716': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI LIFT CANHTO GRF 910-006467
    '000000000100051617': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS 4GER USB-C MXP63BZ/A
    '000000000100025061': ('acessorio', 'Magic Mouse', 'Apple'),  # MAGIC MOUSE 3 APPLE BLACK DEMO MMMQ3BE/A
    '000000000100025300': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYBOARD APPLE TOUCH NUM MK2C3BZ/A
    '000000000100032434': ('acessorio', 'Capa/Case', 'Apple'),  # SMART FOLIO APPLE AIR 11 DENIM MWK63ZM/A
    '000000000100047562': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PRO PARTY BCO OIV0520
    '000000000100047564': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PRO PARTY RSA OIV0524
    '000000000100067219': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17PRO MERC PTO OIV0903
    '000000000100067220': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 GUESS MRM OIV0896
    '000000000100040769': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI MX ANYW 3S GRF 910-006932
    '000000000100040684': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP 12/12 PRO PRIV OIV0026
    '000000000100072609': ('device', 'Apple Watch', None),  # WATCH ULTRA3 49 NT TI NT TML MEWW4BE/A
    '000000000100053010': ('acessorio', 'Outros', 'Logitech'),  # WEBCAM LOGI F HD BRIO 100 GRF 960-001586
    '000000000100055242': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE AURORA 13 PTO SNK OIV0643
    '000000000100047210': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16 PLUS RING AZUL OIV0480
    '000000000100047213': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16 PLUS STAND PTO OIV0484
    '000000000100047258': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PLUS ESSEN PTO OIV0442
    '000000000100047093': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 16 CANDY AZUL OIV0461
    '000000000100047099': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 16 DROP LILAS OIV0468
    '000000000100047145': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 16 DROP VRD OIV0471
    '000000000100047061': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 SILICONE PINK OIV0490
    '000000000100046908': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP14 NORONHA MAG PTO OIV0420
    '000000000100041072': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI MX MINI CNZ 920-010506
    '000000000100072545': ('device', 'Apple Watch', None),  # WATCH SE 3 40 M AL M SB ML C MEPC4AM/A
    '000000000100080756': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS MAX 2 LARA MHWN4BE/A
    '000000000100080757': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS MAX 2 ROXO MHWP4BE/A
    '000000000100080390': ('acessorio', 'Fone', 'JBL'),  # FONE JBL SENSEPRO PRETO 28914038
    '000000000100068323': ('acessorio', 'Outros', 'Originais iPlace'),  # SMART TAG IPLACE ROSA LOREFSTRSA
    '000000000100046759': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 15 PRO SLIM OIV0353
    '000000000100046779': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE FLORIPA MAC13 VERMELHA
    '000000000100042360': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PLU GAMER OIV0434
    '000000000100042393': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PRO ANTIBLU OIV0431
    '000000000100042055': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15PLU GAMER OIV0248
    '000000000100027058': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE RAFA BEGE OIV0369
    '000000000100045678': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14 AIR CUSHION 303735
    '000000000100046591': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 14 ALCA PTO OIV278
    '000000000100041262': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGITECH KEYSTOGO AZL 920-010040
    '000000000100080180': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 17E TRANSP MHWC4ZM/A
    '000000000100080153': ('device', 'iPad', None),  # IPAD AIR M4 13 CL SP GR 128GB MH9D4BZ/A
    '000000000100034989': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL BOOMBOX 3 SQD 58035032
    '000000000100035132': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 13 SIL ROSA GIZ MM283ZE/A
    '000000000100034843': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL BAR 180 PTO 28913746
    '000000000100046097': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 12 SIL ROSA OIV0119
    '000000000100046196': ('acessorio', 'MagSafe', 'Apple'),  # CABO APPLE USB-C/MAGSAFE 2M  MLYV3AM/A
    '000000000100045967': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14 SIL ROSA OIV0047
    '000000000100046048': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 12 SIL CINZA OIV0118
    '000000000100046091': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 12 SIL LAVAN OIV0121
    '000000000100045834': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14 MS LARANJA O1251
    '000000000100027332': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA AIRTAG IPLACE TPU PET PTO PP0760
    '000000000100027612': ('acessorio', 'AirTag', 'Apple'),  # AIRTAG APPLE (PACOTE COM 4)MX542BE/A
    '000000000100027260': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE SPRING 38-41MM ROSA OIV0536
    '000000000100027161': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 42/44/45 METAL PTO OIV0256
    '000000000100043579': ('acessorio', 'Fone', 'Logitech'),  # FONE LOGI ON ZONE 300 GRF 981-001406
    '000000000100042516': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PL PRIVACID A.U OIV0551
    '000000000100042631': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PM ANTIBLU A.U OIV0560
    '000000000100072486': ('device', 'iPhone', None),  # IPHONE 17 P MAX DP BL 256GB DM 3P129BE/A
    '000000000100080883': ('device', 'iPhone', None),  # IPHONE 17E SOFT PINK 512GB MHU34BR/A
    '000000000100045475': ('acessorio', 'Outros', 'Originais iPlace'),  # ALCA MAO IPLACE 30CM TRANS OIV0314
    '000000000100045603': ('acessorio', 'Outros', 'Originais iPlace'),  # ALCA MAO IPLACE 22CM TRANSP OIV0399
    '000000000100045003': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP12MINI AZU ROYAL IP-1263SA
    '000000000100044490': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP XR SILIC CORAL IP-1123SC
    '000000000100072449': ('device', 'iPhone', None),  # IPHONE 17 WHITE 512GB MG6Q4BE/A
    '000000000100016747': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE FOLIO IPAD 10 PTO OIV0068
    '000000000100016944': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE FOLIO IPAD 9 PTO OIV0067
    '000000100047599001': ('device', 'iPhone', None),  # IPHONE 13 PRO GRAPHITE 128GB BB, E
    '000000100041571001': ('device', 'iPad', None),  # IPAD PRO 11 2ND WF S. GRAY 128GB BB, E
    '000000100038395001': ('device', 'iPad', None),  # IPAD 10TH WF BLUE 64GB BB, E
    '000000100038462001': ('device', 'iPad', None),  # IPAD 10TH WF SVR 64GB BB, E
    '000000000100066790': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16E BAC/PRIV A.U OIV0889
    '000000000100060282': ('device', 'iPhone', None),  # IPHONE 16E WHT 512GB MD274BR/A
    '000000100049360001': ('device', 'Apple Watch', None),  # WATCH SE GPS 40MM SPC GRAY BB, E
    '000000100049408001': ('device', 'Apple Watch', None),  # WATCH ULTRA CEL 49MM BB, E
    '000000100048183001': ('device', 'iPhone', None),  # IPHONE 15 BLACK 128GB BB N, E
    '000000000100015522': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 PRO MS MARROM 304116
    '000000000100015422': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 PRO MS LARANJA O1253
    '000000000100015612': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I14PROMAX TRANS SLIM OIV0129
    '000000000100016286': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX SPRING ROS OIV0535
    '000000000100015582': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I14PROMAX SIL ROSA OIV0050
    '000000100048457001': ('device', 'iPhone', None),  # IPHONE 11 BLACK 64GB BB N, E
    '000000100048798001': ('device', 'iPhone', None),  # IPHONE 14 BLUE 128GB BB N, E
    '000000100048754001': ('device', 'iPhone', None),  # IPHONE 13 GREEN 128GB BB I, E
    '000000100048439001': ('device', 'iPhone', None),  # IPHONE 11 WHITE 128GB BB I, E
    '000000100048435001': ('device', 'iPhone', None),  # IPHONE 11 PURPLE 64GB BB I, E
    '000000100048750001': ('device', 'iPhone', None),  # IPHONE 13  RED 256GB BB I, E
    '000000100053829001': ('device', 'iPhone', None),  # IPHONE 16 ROSA 128GB BB N, E
    '000000000100045766': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14 SIL AZUL CI 303849
    '000000000100069614': ('acessorio', 'Fone', 'JBL'),  # FONE JBL OV TUNE 520C BCO 28914009
    '000000000100017437': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE LIGH USB-C 1,2M PTO OP1DLCCK
    '000000000100046130': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 13 AIRCUSHION OIV0005
    '000000000100046045': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 12 SIL AZUL OIV0117
    '000000000100017883': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB USB-C 1,2M BCO OP1DACB1
    '000000000100018276': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB/LIGHT 3.1G 3M BCO 1814
    '000000000100044132': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPSE2ND/8/7 CLA TR IP-1006PT
    '000000000100044037': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPSE2ND/8/7 SUP MAG CMAGIP7
    '000000000100047644': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA SAMPA IPLACE CINZA IP-1099TC
    '000000000100080287': ('device', 'Mac', None),  # MACB PRO 16 M5M 48GB SPB 2TB MGEE4BZ/A
    '000000000100080156': ('device', 'iPad', None),  # IPAD AIR M4 13 CL SP GR 256GB MH9H4BZ/A
    '000000000100072509': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 17 PMAX CINZA G MGJD4LL/A
    '000000000100072492': ('device', 'iPhone', None),  # IPHONE 17 PRO SILVER 256GB DM 3P170BE/A
    '000000000100033447': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS 3GER LIGHT MPNY3BE/A
    '000000000100080232': ('device', 'iPad', None),  # IPAD AIR M4 11 WF PUR 256GB MH394BZ/A
    '000000000100043451': ('acessorio', 'Fone', 'Logitech'),  # FONE LOGI OV ZONEVIBE 100 GRF 981-001214
    '000000000100080252': ('device', 'Mac', None),  # MACB AIR 13 M5 24GB SIL 1TB MDH94BZ/A
    '000000000100032737': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA TECL APPLE IPADPRO 11 PTO MU8G2LL/A
    '000000000100045701': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 11 SIL AZUL CI 303862
    '000000000100046461': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 PRO AZUL PETR OIV0264
    '000000000100080228': ('device', 'iPad', None),  # IPAD AIR M4 11 WF PUR 128GB MH344BZ/A
    '000000000100045886': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14 MS PRETA 304115
    '000000000100043532': ('device', 'Apple Watch', None),  # WATCH S9 GPS 45 MID SB S/M DM 3M589BZ/A
    '000000000100051855': ('device', 'Apple Watch', None),  # WATCH S10 DM 42 RG AL LB SB SM G 3N490BZ
    '000000000100032492': ('acessorio', 'Capa/Case', 'Apple'),  # SMART FOLIO APPLE AIR 13 CNZ MWK93ZM/A
    '000000100039956001': ('device', 'iPad', None),  # IPAD AIR 5TH WF S. GRAY 256GB BB, E
    '000000000100051790': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 41 NIKE CIN/AZUL MC1G4AM/A
    '000000100045261001': ('device', 'iPhone', None),  # IPHONE 11 PRO MAX MID GREEN 512GB BB, E
    '000000000100047920': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE RIO MAC16 PRETA OIV0124
    '000000100046606001': ('device', 'iPhone', None),  # IPHONE 12 PRO MAX GRPHT 256GB BB, E
    '000000100046708001': ('device', 'iPhone', None),  # IPHONE 12 PRO MAX PBLUE 256GB BB, E
    '000000000100047502': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP14 NORONHA AZUL OIV0526
    '000000000100050717': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI LIFT GRF 910-006466
    '000000100039321001': ('device', 'iPad', None),  # IPAD 9TH WF S. GRAY 256GB BB, E
    '000000000100032108': ('device', 'iPhone', None),  # IPHONE 15 PINK 256GB MTP73BR/A
    '000000000100047329': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP16 PROMAX DROP VRD OIV0473
    '000000000100067215': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA/CABO LACOSTE IPH17 PTO OIV0907
    '000000000100032475': ('acessorio', 'Capa/Case', 'Apple'),  # SMART FOLIO APPLE AIR 11 VERDE MWK73ZM/
    '000000000100067211': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 GUESS PTO OIV0898
    '000000000100032631': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYB 5GER APPLE 12.9 P PTO MJQK3BZ
    '000000000100047452': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP16 PRO FORCE PTO OIV0511
    '000000000100047294': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP16 PRO DROP VRD OIV0472
    '000000000100047219': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 LILAS BRIL OIV0453
    '000000000100047148': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 16 RING AZUL OIV0479
    '000000000100047022': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 PRO RING AZUL OIV0481
    '000000000100047832': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE PAMPAS COURO VERMELHA
    '000000000100046765': ('acessorio', 'Outros', 'Originais iPlace'),  # ECHIP CLARO IPLACE SCBOP QRCODE 8NP NE E
    '000000000100080278': ('device', 'Mac', None),  # MACB PRO 14 M5P 24GB SPB 2TB MGDT4BZ/A
    '000000000100031296': ('acessorio', 'Fone', 'JBL'),  # FONE DE OUVIDO JBL LIVE PRO2 TWS BLK 289
    '000000000100069410': ('acessorio', 'Cabo', 'Mister'),  # CABO MISTER USB-A LIGH 1,5M PTO LAP1NVE
    '000000000100068088': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17PMAX EDGE OFF OIV0910
    '000000000100046897': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE PAMPAS 13 COURO CAFE
    '000000000100080265': ('device', 'Mac', None),  # MACB AIR 15 M5 16GB STL 512GB MDVD4BZ/A
    '000000000100046717': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP15PRO TR MAGNETICA OIV0304
    '000000000100072683': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH AIR BEATS AZUL MGJW4LL/A
    '000000000100072660': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 17 TRANSP MGF24ZM/A
    '000000000100072617': ('device', 'Apple Watch', None),  # WATCH ULTRA3 49 BK TI BC TL  MF1H4BE/A
    '000000000100072583': ('device', 'Apple Watch', None),  # WATCH 11 46 JB AL BK SB SM C MFC24AM/A
    '000000000100072567': ('device', 'Apple Watch', None),  # WATCH 11 42 JB AL BK SB ML C MF854AM/A
    '000000000100072564': ('device', 'Apple Watch', None),  # WATCH 11 46 SI AL PF SB SM G MEV94AM/A
    '000000000100045459': ('acessorio', 'Outros', 'Originais iPlace'),  # ALCA IPL IP ACRILI120 OWHI OIV0313
    '000000000100072598': ('device', 'Apple Watch', None),  # WATCH 11 46 SL TI SL ML ML C MFD44AM/A
    '000000000100034840': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL BAR 800PRO PTO 28913592
    '000000000100072589': ('device', 'Apple Watch', None),  # WATCH 11 46 SI AL PF SB SM C MFCP4AM/A
    '000000000100072585': ('device', 'Apple Watch', None),  # WATCH 11 46 SG AL BK SB SM C MFC94AM/A
    '000000000100040640': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP 12/12 PRO ANTIBAC OIV0033
    '000000000100034986': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL BOOMBOX 3 PTO 58035031
    '000000000100040554': ('device', 'iPad', None),  # IPAD PRO 13 M4 WF 256GB SB DM 3M780BZ/A
    '000000000100074526': ('device', 'iPad', None),  # IPAD PRO 13 M5 WIFI 256GB SIL MDYK4BZ/A
    '000000000100074908': ('acessorio', 'Fone', 'JBL'),  # MICROFONE JBL PARTY BOX WL PTO 28913769
    '000000000100026847': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 42/44 SILI AZUL ROYAL IP-1280SA
    '000000000100026922': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 38/40 SILICONE VERMEL IP-1325SV
    '000000000100038716': ('acessorio', 'Película', 'Originais iPlace'),  # PEL TRANS IPLACE IPAD PRO 12.9 IP-1022VT
    '000000000100027013': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE MIA COURO PRETA BCI001PTO
    '000000000100024370': ('acessorio', 'MagSafe', 'Apple'),  # MAGSAFE APPLE 45W POWER ADAPT MC747BZ/A
    '000000000100024148': ('acessorio', 'Carregador Apple', 'Apple'),  # CARREGADOR APPLE USB-C 61W MRW22BZ/A
    '000000000100024840': ('acessorio', 'Película', 'Originais iPlace'),  # PELICULA IPLACE MACBOOK 13,6 OIV0415
    '000000000100024847': ('acessorio', 'Película', 'Originais iPlace'),  # PELICULA IPLACE MACBOOK 14,2 OIV0416
    '000000000100024874': ('acessorio', 'Película', 'Originais iPlace'),  # PELICULA IPLACE MACBOOK 15,3 OIV0417
    '000000000100072616': ('device', 'Apple Watch', None),  # WATCH ULTRA3 49 BK TI BC TL  MF1D4BE/A
    '000000000100040204': ('acessorio', 'Caneta', 'Logitech'),  # CANETA DIG LOGITECH CRYON BRA 914-000033
    '000000000100074509': ('device', 'Mac', None),  # MACB PRO 14 M5 SB 24GB 1TB MDE34BZ/A
    '000000000100036386': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 14 PLUS SIL AZUL MPT53ZE/A
    '000000000100039482': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP12/PRO SIMAG VERM MHL63ZE/A
    '000000000100041064': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI ERGO K860 PTO 920-009169
    '000000000100041036': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI 400 PLU CNZ 920-007125
    '000000000100072517': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH AIR BEATS CALCA MGJU4LL/A
    '000000000100072514': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 17 PMAX TRANSP MGFW4ZM/A
    '000000000100042498': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PLU ANTIBLU A.U OIV0552
    '000000000100079328': ('acessorio', 'Fone', 'JBL'),  # FONE JBL TUNE 730BT AZUL 28914082
    '000000000100034286': ('acessorio', 'Caixa de Som', 'Originais iPlace'),  # CAIXA DE SOM IPLACE ENERGIE L55 PTO/AZUL
    '000000000100034999': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP12/PRO SILMAG KUM MHKY3ZE/A
    '000000000100045253': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 12 MINI CLASSICA TR 1587
    '000000000100035886': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP12MINI SILMAG PLM MHKQ3ZE/A
    '000000000100035961': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP12MINI COUMAG VRM MHK73ZE/A
    '000000000100044756': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP11PRO NANSIL PTO IP-1167SP
    '000000000100032935': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYBOARD APPLE PRO13 BCO MWR43BZ/A
    '000000000100072461': ('device', 'iPhone', None),  # IPHONE AIR SPACE BLACK 1TB MG2W4BE/A
    '000000000100035875': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL AUTH 300 PTO 28913719
    '000000000100035126': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL CHARGE 5 AZUL 28913427
    '000000000100034322': ('acessorio', 'Caixa de Som', 'Originais iPlace'),  # CAIXA DE SOM IPLACE ENERGIE L55 AZUL/AMA
    '000000000100040796': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP 13 MINI ESPELHO 302032
    '000000000100040771': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP 13 MINI ANTIBACT 302029
    '000000000100040676': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP 12/12 PRO ANTIBAC OIV0033
    '000000000100040674': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGITECH MX ANY3 ROSA 910-005994
    '000000000100040646': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGITECH MX ANY3 CINZA 910-005993
    '000000000100021836': ('device', 'iPad', None),  # IPAD AIR 13 6TH M2 CL 128GB SG MV6Q3BZ/A
    '000000000100034347': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 11PROMAX SIL ROS MWYY2ZM/A
    '000000000100041079': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI MX MINI GRF 920-010505
    '000000000100042002': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15GAMER A.U OIV0545
    '000000000100042342': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PLU ANTIBLU OIV0430
    '000000000100042306': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16 PRIVACID A.U OIV0547
    '000000000100042212': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP16 ANTIBACTERIA OIV0421
    '000000000100042176': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP 15 PROMAX ANTBLUE OIV0246
    '000000000100036197': ('acessorio', 'Fone', 'JBL'),  # MICROFONE JBL QUANT STREAM PTO 28913617
    '000000000100042135': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15 PRO GAMER OIV0249
    '000000000100031521': ('acessorio', 'Fone', 'JBL'),  # FONE DE OUVIDO JBL WAV FLEX WHT 28913666
    '000000100047588001': ('device', 'iPhone', None),  # IPHONE 13 PRO GOLD 256GB BB I, E
    '000000000100027062': ('acessorio', 'Pulseira', 'Originais iPlace'),  # PULSEIRA WATCH IPLACE METAL PRAT OIV0341
    '000000000100052070': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE BEATS IPH16PMAX ROX MCFU4LL/A
    '000000000100031488': ('acessorio', 'Fone', 'JBL'),  # FONE DE OUVIDO JBL WAV FLEX BLK 28913665
    '000000000100054592': ('device', 'iPad', None),  # IPAD MINI 7TH CEL 256GB PURPLE MXPY3BZ/A
    '000000000100054594': ('device', 'iPad', None),  # IPAD MINI 7TH WF+CEL 512GB BLU MYHD3BZ/A
    '000000100048733001': ('device', 'iPhone', None),  # IPHONE 13  STARLIGHT 128GB BB N, E
    '000000100048438001': ('device', 'iPhone', None),  # IPHONE 11 RED 64GB BB I, E
    '000000000100031482': ('acessorio', 'Fone', 'JBL'),  # FONE DE OUVIDO JBL WAV BUDS BLK 28913661
    '000000000100031381': ('acessorio', 'Fone', 'JBL'),  # FONE DE OUVIDO JBL TUNE FLX AZU 28913648
    '000000000100015839': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 SCREEN PTO OIV0404
    '000000100048009001': ('device', 'iPhone', None),  # IPHONE 13 PRO MAX S. BLUE 128GB BB, E
    '000000000100056765': ('acessorio', 'Fone', 'JBL'),  # FONE JBL IN WAVE BEAM 2 AZL 28913848
    '000000100047969001': ('device', 'iPhone', None),  # IPHONE 13 PRO MAX GOLD 512GB BB, E
    '000000100047962001': ('device', 'iPhone', None),  # IPHONE 13 PRO MAX GOLD 128GB BB, E
    '000000000100031807': ('acessorio', 'Fone', 'JBL'),  # FONE JBL TOURPROWIRELESS2 PRETO 28913802
    '000000000100016344': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA ENVELOPE IPAD IPLACE  PAMPAS CAFE
    '000000100048168001': ('device', 'iPhone', None),  # IPHONE 14 PRO MAX SILVER 512GB BB I, E
    '000000000100054586': ('device', 'iPad', None),  # IPAD MINI 7TH WF+CEL 128GB BLU MXPP3BZ/A
    '000000100048474001': ('device', 'iPhone', None),  # IPHONE 11 RED 128GB BB N, E
    '000000100048161001': ('device', 'iPhone', None),  # IPHONE 14 PRO MAX GOLD 1TB BB I, E
    '000000100048149001': ('device', 'iPhone', None),  # IPHONE 14 PRO MAX D PURPLE 256GB BB I, E
    '000000000100015048': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14PLUS SIL ROS CHA 303846
    '000000000100060997': ('device', 'iPad', None),  # IPAD 11TH CELL 128GB PINK MD7J4BZ/A
    '000000000100060999': ('device', 'iPad', None),  # IPAD 11TH CELL 256GB BLUE MD7L4BZ/A
    '000000000100061001': ('device', 'iPad', None),  # IPAD 11TH CELL 256GB PINK MD7N4BZ/A
    '000000100048122001': ('device', 'iPhone', None),  # IPHONE 14 PRO GOLD 1TB BB I, E
    '000000000100061253': ('device', 'iPad', None),  # IPAD AIR 7TH 13 WF 128GB SG DM 3N727BZ/A
    '000000000100061264': ('device', 'iPad', None),  # IPAD AIR 7TH 11 WF 128GB PU DM 3N673BZ/A
    '000000000100061326': ('acessorio', 'Outros', 'Apple'),  # MAGIC APPLE IPAD AIR13 M3 DEMO MDFW4BZ/A
    '000000000100015032': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CASE AIRPODS IPLACE PAMPAS MARROM
    '000000000100015297': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I14PROMAX SIL AZUL CI 303852
    '000000000100015263': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 PRO TRANS SLIM OIV0128
    '000000100048735001': ('device', 'iPhone', None),  # IPHONE 13  STARLIGHT 256GB BB N, E
    '000000100048222001': ('device', 'iPhone', None),  # IPHONE 15 BLUE 256GB BB I, E
    '000000000100061091': ('device', 'Mac', None),  # MAC STUDIO M3 ULTRA 1TB 96GB MU973BZ/A
    '000000000100057274': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15PMAX ANTB A.U OIV0655
    '000000100048325001': ('device', 'iPhone', None),  # IPHONE 15 PRO WHT TITANIUM 128GB BB I, E
    '000000000100064792': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS MAX AZL MWW63BE/A
    '000000000100066977': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH AIR PROSAFE OIV0808
    '000000000100015948': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 16 PLUS RING ROSA OIV0475
    '000000000100015377': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I14PROMAX SIL VER CER 303857
    '000000000100015392': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS 3 SIL PRETA OIV0074
    '000000000100015547': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I14PROMAX SIL AZUL OIV0054
    '000000000100018917': ('acessorio', 'Adaptador', 'Apple'),  # ADAP APPLE USB-C/AV DIGITAL MUF82AM/A
    '000000000100015979': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 16 PRO CANDY AZUL OIV0463
    '000000000100015207': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 PRO SIL PRETO OIV0061
    '000000000100051881': ('device', 'Apple Watch', None),  # WATCH S10 46 RG AL PLUM SL C MWY83AM/A
    '000000000100018835': ('acessorio', 'Adaptador', 'Apple'),  # ADAPTADOR APPLE USB-C TO VGA MJ1L2AM/A
    '000000000100051933': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 49 LOOP A AZL MYPW3AM/A
    '000000000100051733': ('device', 'iPhone', None),  # IPHONE 16 PLUS ULTMARINE 256GB MXY23BE/A
    '000000000100015567': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I14PROMAX SIL PRETO OIV0062
    '000000000100018753': ('acessorio', 'Adaptador', 'Apple'),  # ADAP APPLE THUNDER/ETHERNET MD463BE/A
    '000000000100015035': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CASE AIRPODS IPLACE PAMPAS PRETO
    '000000000100015143': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 PRO SIL AZUL CI 303851
    '000000000100030566': ('device', 'iPhone', None),  # IPHONE 14 STARLIGHT 256GB MPW43BR/A
    '000000000100015108': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 PRO ANTIBAC BLK 303784
    '000000000100014139': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP12PMAX TR AIRCUS IP-1247PT
    '000000000100052306': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 42 NIKE CIN/AZUL MXTX3AM/A
    '000000100048710001': ('device', 'iPhone', None),  # IPHONE 13  BLUE 128GB BB I, E
    '000000000100052308': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 42 NIKE BRAS MAG MYL23AM/A
    '000000000100052310': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 42 LOOP NIKE EST MYJC3AM/A
    '000000000100051936': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 46 LOOP E AZL MXL53AM/A
    '000000000100016047': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 PRO LILAS BRI OIV0455
    '000000100048064001': ('device', 'iPhone', None),  # IPHONE 14 PLUS MIDNIGHT 256GB BB N, E
    '000000000100031222': ('device', 'iPhone', None),  # IPHONE 15 PLUS PINK 128GB MU103BE/A
    '000000000100055451': ('device', 'Mac', None),  # MACBOOK PRO 14 M4 DM SB 512GB MW2U3BZ/A
    '000000000100055454': ('device', 'Mac', None),  # IMAC 24 M4 BLUE 256GB DEMO MWV13BZ/A
    '000000100053728001': ('device', 'iPhone', None),  # IPHONE 16 PRO MAX TIT DESERTO 256GB B, E
    '000000100048047001': ('device', 'iPhone', None),  # IPHONE 13 PRO MAX ALP GREEN 1TB BB, E
    '000000000100055321': ('device', 'Mac', None),  # IMAC 24 M4 BLUE 256GB 8GPU MWUF3BZ/A
    '000000000100051760': ('device', 'iPhone', None),  # IPHONE 16 PRO MAX WHITE 512GB MYX13BE/A
    '000000100053667001': ('device', 'iPhone', None),  # IPHONE 16 PRO MAX TIT BRANCO 256GB BB, E
    '000000100053796001': ('device', 'iPhone', None),  # IPHONE 16 ROSA 128GB BB I, E
    '000000000100055387': ('device', 'Mac', None),  # IMAC 24 M4 SILVER 512GB 10GPU MWUV3BZ/A
    '000000000100014954': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CASE AIRPODS IPLACE PAMPAS AMARELO
    '000000000100051707': ('device', 'iPhone', None),  # IPHONE 16 PRO MAX DESERT 256GB MYWX3BE/A
    '000000000100067012': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17PRO PROMATTE OIV0813
    '000000000100017125': ('acessorio', 'Cabo', 'Mister'),  # CABO MISTER USB-C USB 1,5 PTO MT1DCAP
    '000000000100016804': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA TC IPLACE IPAD PRO11 ROSA IPSTA1212
    '000000000100016958': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE FOLIO IPAD 9 VERDE OIV0072
    '000000000100016985': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPAD POLVO KIDS OIV0321
    '000000100053775001': ('device', 'iPhone', None),  # IPHONE 16 PRO TITAN PRETO 256GB BB, E
    '000000000100080889': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE MAG MAC NEO OIV0945
    '000000000100027667': ('acessorio', 'AirTag', 'Apple'),  # LACO APPLE PARA AIRTAG BCO MX4F2ZM/A
    '000000000100028118': ('device', 'iPhone', None),  # IPHONE 12 BLACK 128GB MGJA3BR/A
    '000000000100027661': ('acessorio', 'AirTag', 'Apple'),  # CHAV APPLE COURO P AIRTAG AZUL MHJ23ZM/A
    '000000000100029242': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE 42/44 ESP AZUL A MX0M2AM/A
    '000000000100029131': ('device', 'iPhone', None),  # IPHONE 13 BLUE 512GB MLQG3BZ/A
    '000000000100029017': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE 38/40 ESP VERDE MWUR2AM/A
    '000000000100030392': ('acessorio', 'Fone', 'JBL'),  # FONE JBL T110 BLK JBLT110BLK
    '000000000100029274': ('device', 'iPhone', None),  # IPHONE 13 MIDNIGHT 512GB MLQC3BZ/A
    '000000000100029593': ('device', 'iPhone', None),  # IPHONE 13 GREEN 256GB MNGL3BR/A
    '000000000100029522': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE 42/44 NIKE LOOP ROY/PT MWU32AM/A
    '000000000100029277': ('device', 'iPhone', None),  # IPHONE 13 STARLIGHT 512GB MLQD3BZ/A
    '000000000100030913': ('acessorio', 'Fone', 'JBL'),  # FONE JBL T215TWS BLACK 28913346
    '000000000100030916': ('acessorio', 'Fone', 'JBL'),  # FONE JBL T215TWS WHITE 28913347
    '000000000100031143': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 41 WHITE DEMO 3K926AM/A
    '000000000100031150': ('acessorio', 'Fone', 'JBL'),  # FONE JBL WAVE 200 TWS BCO 28913520
    '000000000100030815': ('acessorio', 'Fone', 'JBL'),  # FONE JBL T125TWS PRETO 28913334
    '000000000100030560': ('device', 'iPhone', None),  # IPHONE 14 RED 512GB MPXG3BR/A
    '000000000100031198': ('acessorio', 'Fone', 'JBL'),  # FONE DE OUVIDO JBL T130NC TWS BLACK 2891
    '000000000100025825': ('device', 'Apple TV', None),  # APPLE TV 4K 32GB MQD22BZ/A
    '000000000100025908': ('device', 'Apple TV', None),  # APPLE TV 4K 64GB WI-FI MN873BZ/A
    '000000000100027156': ('acessorio', 'Outros', 'Originais iPlace'),  # PASTA ENVEL MAC13 IPLACE PAMPAS OIV0573
    '000000000100027198': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE GISELE COURO PRETA BI001PTO
    '000000000100027241': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE GISELE COURO CREME BI002CRE
    '000000000100027387': ('acessorio', 'AirTag', 'Originais iPlace'),  # CHAV AIRTAG IPLACE TPU ORQUIDEA VTP0065
    '000000000100027569': ('acessorio', 'AirTag', 'Apple'),  # AIRTAG APPLE (PACOTE COM 1)MX532BE/A
    '000000000100026833': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 38/40 SILI AZUL ROYAL IP-1279SA
    '000000000100027055': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE RIO PRETA IP0006160323
    '000000000100026502': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 42/44 ESPORT AZUL IP-1146SA
    '000000000100026559': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 42/44 SILIC MARSALA IP-1133SM
    '000000000100027019': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE MIA VERDE LIMAO BCI003VDL
    '000000000100026584': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 38/40 NYLON ARCO-IRIS IP-1222NC
    '000000000100026706': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 42/44 NYLON ARCO-IRIS IP-1223NC
    '000000000100026723': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 42/44 NYLON VERDE MIL IP-1220NV
    '000000000100026765': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 42/44 SIL AZUL OCEANO IP-1214SA
    '000000000100026328': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE SIL ESP WATCH42/44ROS IP-1051SR
    '000000000100018582': ('acessorio', 'Adaptador', 'Apple'),  # ADAP APPLE LIGHT/USB CAMERA MD821BZ/A
    '000000000100018828': ('acessorio', 'Adaptador', 'Apple'),  # ADAPTADOR APPLE USB-C TO USB MJ1M2AM/A
    '000000100048101001': ('device', 'iPhone', None),  # IPHONE 14 PLUS YELLOW 128GB BB I, E
    '000000000100016777': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA TC IPLACE IPADPRO11 VERDE IPSTA1111
    '000000000100028233': ('device', 'Apple Watch', None),  # P AW 38 PSD SB RGP SM/ML TRYON 3C579BZ/A
    '000000000100017098': ('acessorio', 'Cabo', 'Mister'),  # CABO MISTER USB-C LIGH 1,5 BCO MT1DLCB
    '000000100048041001': ('device', 'iPhone', None),  # IPHONE 13 PRO MAX S. BLUE 256GB BB, E
    '000000100048049001': ('device', 'iPhone', None),  # IPHONE 13 PRO MAX ALP GREEN 128GB BB, E
    '000000100048060001': ('device', 'iPhone', None),  # IPHONE 13 PRO MAX ALP GREEN 256GB BB, E
    '000000100048063001': ('device', 'iPhone', None),  # IPHONE 14 PLUS MIDNIGHT 128GB BB N, E
    '000000100048066001': ('device', 'iPhone', None),  # IPHONE 14 PLUS BLUE 128GB BB I, E
    '000000100048082001': ('device', 'iPhone', None),  # IPHONE 14 PLUS PURPLE 128GB BB I, E
    '000000100047626001': ('device', 'iPhone', None),  # IPHONE 13 PRO GRAPHITE 1TB BB I, E
    '000000100047653001': ('device', 'iPhone', None),  # IPHONE 13 PRO S. BLUE 128GB BB I, E
    '000000100047685001': ('device', 'iPhone', None),  # IPHONE 13 PRO S. BLUE 256GB BB I, E
    '000000100047925001': ('device', 'iPhone', None),  # IPHONE 13 PRO MAX SILVER 1TB BB, E
    '000000000100017091': ('acessorio', 'Cabo', 'Mister'),  # CABO MISTER USB LIGHT 1,5M BCO MT1DLAB
    '000000100039966001': ('device', 'iPad', None),  # IPAD AIR 5TH WF PURPLE 64GB BB, E
    '000000100043250001': ('device', 'iPad', None),  # IPAD PRO 12.9 6TH CEL SVR 256GB BB, E
    '000000100045193001': ('device', 'iPhone', None),  # IPHONE 11 PRO MAX GOLD 256GB BB, E
    '000000100038773001': ('device', 'iPad', None),  # IPAD 7TH CEL GOLD 32GB BB, E
    '000000100038822001': ('device', 'iPad', None),  # IPAD 7TH CEL S. GRAY 32GB BB, E
    '000000100039116001': ('device', 'iPad', None),  # IPAD 8TH WF GOLD 32GB BB, E
    '000000100039155001': ('device', 'iPad', None),  # IPAD 8TH WF S. GRAY 32GB BB, E
    '000000100039565001': ('device', 'iPad', None),  # IPAD AIR 4TH CEL SKY BLUE 256GB BB, E
    '000000100039763001': ('device', 'iPad', None),  # IPAD AIR 4TH WF SILVER 64GB BB, E
    '000000100039947001': ('device', 'iPad', None),  # IPAD AIR 5TH WF S. GRAY 64GB BB, E
    '000000100040045001': ('device', 'iPad', None),  # IPAD AIR 5TH WF BLUE 64GB BB, E
    '000000000100016006': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 16 PRO CANDY ROSA OIV0459
    '000000000100016010': ('device', 'Mac', None),  # MACBOOK PRO 13 M18C SPGR 256GB MYD82BZ/A
    '000000000100014986': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CASE AIRPODS IPLACE PAMPAS TERRACOTA
    '000000100048711001': ('device', 'iPhone', None),  # IPHONE 13  BLUE 128GB BB N, E
    '000000100048719001': ('device', 'iPhone', None),  # IPHONE 13 MIDNIGHT 256GB BB N, E
    '000000100048731001': ('device', 'iPhone', None),  # IPHONE 13 MIDNIGHT 512GB BB N, E
    '000000100048738001': ('device', 'iPhone', None),  # IPHONE 13  RED 128GB BB I, E
    '000000000100014957': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CASE AIRPODS IPLACE PAMPAS BEGE
    '000000100048368001': ('device', 'iPhone', None),  # IPHONE 12 BLUE 128GB BB N, E
    '000000100048410001': ('device', 'iPhone', None),  # IPHONE 12 WHITE 64GB BB N, E
    '000000100048415001': ('device', 'iPhone', None),  # IPHONE 12 PURPLE 64GB BB I, E
    '000000100048001001': ('device', 'iPhone', None),  # IPHONE 13 PRO MAX GRAPHITE 128GB BB, E
    '000000100048451001': ('device', 'iPhone', None),  # IPHONE 11 WHITE 64GB BB I, E
    '000000100048697001': ('device', 'iPhone', None),  # IPHONE 13  PINK 256GB BB N, E
    '000000000100015682': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15PRO NORONHA PTO OIV0232
    '000000000100015772': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15PROMAX CDY ROSA OIV0287
    '000000000100015778': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15PROMAX CNDY VRD OIV0284
    '000000000100015816': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15PRMX CART MARI OIV0281
    '000000100048347001': ('device', 'iPhone', None),  # IPHONE 15 PRO MAX TITANIUM 512GB BB I, E
    '000000100048363001': ('device', 'iPhone', None),  # IPHONE 12 BLACK 256GB BB I, E
    '000000100048366001': ('device', 'iPhone', None),  # IPHONE 12 BLACK 64GB BB N, E
    '000000000100015347': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I14PROMAX SIL ROS CHA 303848
    '000000000100015359': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE AIRPODS PRO2 SIL RSA OIV0257
    '000000100048433001': ('device', 'iPhone', None),  # IPHONE 11 PURPLE 128GB BB I, E
    '000000100046777001': ('device', 'iPhone', None),  # IPHONE 12 PRO MAX SILVR 256GB BB, E
    '000000100046846001': ('device', 'iPhone', None),  # IPHONE 13 MINI PINK 128GB BB N, E
    '000000100046851001': ('device', 'iPhone', None),  # IPHONE 13 MINI PINK 256GB BB I, E
    '000000100046915001': ('device', 'iPhone', None),  # IPHONE 13 MINI BLUE 128GB BB I, E
    '000000100047012001': ('device', 'iPhone', None),  # IPHONE 13 MINI MIDNIGHT 128GB BB, E
    '000000100047033001': ('device', 'iPhone', None),  # IPHONE 13 MINI MIDNIGHT 256GB BB, E
    '000000100047181001': ('device', 'iPhone', None),  # IPHONE 13 MINI STARLIGHT 128GB BB, E
    '000000100048323001': ('device', 'iPhone', None),  # IPHONE 15 PRO TITANIUM 256GB BB I, E
    '000000100048342001': ('device', 'iPhone', None),  # IPHONE 15 PRO MAX BLU TITAN 1TB BB I, E
    '000000000100015233': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CASE AIRPODS PRO IPLACE PAMPAS ARTE PRET
    '000000000100015236': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CASE AIRPODS PRO IPLACE PAMPAS AMARELO
    '000000000100015965': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 PLUS TRA BRIL OIV0450
    '000000100048121001': ('device', 'iPhone', None),  # IPHONE 14 PRO D PURPLE 512GB BB I, E
    '000000100048142001': ('device', 'iPhone', None),  # IPHONE 14 PRO SPC BLK 256GB BB I, E
    '000000100048181001': ('device', 'iPhone', None),  # IPHONE 14 PRO MAX SPC BLK 256GB BB I, E
    '000000000100016071': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH16PMAX SCREEN PTO OIV0406
    '000000000100016112': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I16 PRO MAX SIL AZUL OIV0495
    '000000000100016218': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I16PROMAX CANDY AZUL OIV0464
    '000000000100016252': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I16PROMAX DROP LILAS OIV0470
    '000000000100016358': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA ENV IPAD IPLACE 11 PRETO OIV0570
    '000000100048108001': ('device', 'iPhone', None),  # IPHONE 14 PRO D PURPLE 1TB BB I, E
    '000000100048120001': ('device', 'iPhone', None),  # IPHONE 14 PRO D PURPLE 256GB BB I, E
    '000000000100014472': ('acessorio', 'Caneta', 'Apple'),  # APPLE PENCIL DEMO PRO MX2D3AM/A
    '000000000100019955': ('acessorio', 'Carregador', 'Mister'),  # KIT VIAGEM MISTER 30W LIGHT BCO MT4VLCB
    '000000000100020228': ('acessorio', 'Outros', 'Originais iPlace'),  # SUPORTE VEICULAR IPLACE PTO 15W OP1BWFS
    '000000000100020757': ('device', 'iPad', None),  # IPAD PRO 12.9 M2CL 1TB SILVR MP253BZ/A
    '000000000100021784': ('device', 'iPad', None),  # IPAD AIR 13 6TH M2 WF 256GB SG MV2D3BZ/A
    '000000000100019330': ('acessorio', 'Carregador', 'Originais iPlace'),  # CARREG IPLACE USB-C 20W BCO OP1ANG2D1UC
    '000000000100021976': ('device', 'iPad', None),  # IPAD PRO 11 M4 CELL 256GB SB MVW13BZ/A
    '000000000100026840': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 38/40 SILICONE ORQUID IP-1281SR
    '000000000100026888': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 38/40 SILICON AMARELO IP-1324SA
    '000000000100026956': ('acessorio', 'Pulseira', 'Originais iPlace'),  # P IPLACE 42/44 SIL VERMELHO IP-1326SV
    '000000000100027016': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # BOLSA IPLACE MIA COURO CREME BCI002CRE
    '000000000100024377': ('acessorio', 'MagSafe', 'Apple'),  # CARREGADOR APPLE MAGSAFE 1 85W MC556BZ/B
    '000000000100024749': ('acessorio', 'Outros', 'Originais iPlace'),  # ORGANIZADOR DE ACESSORI IPLACE IP-1152TC
    '000000000100024880': ('acessorio', 'Outros', 'Originais iPlace'),  # SUPORTE IPLACE MAC/IPAD BRANCO IP-1073PB
    '000000000100024175': ('acessorio', 'Carregador Apple', 'Apple'),  # CARREGADOR APPLE 96W USB-C MX0J2BZ/A
    '000000000100024969': ('acessorio', 'Adaptador', 'Originais iPlace'),  # SUPORTE ADAP IPLACE MULT 8EM1 OP1GSLHU3
    '000000000100022012': ('device', 'iPad', None),  # IPAD PRO 11 M4 CELL 512GB SB MVW33BZ/A
    '000000000100022018': ('device', 'iPad', None),  # IPAD PRO 13 M4 WIFI 256GB SB MVX23BZ/A
    '000000000100018408': ('acessorio', 'Cabo', 'Originais iPlace'),  # CABO IPLACE USB-C 3 GERAC 1,2M BCO 1555
    '000000000100025314': ('acessorio', 'Magic Mouse', 'Apple'),  # MAGIC MOUSE APPLE 3 BRANCO-BES MK2E3BE/A
    '000000000100051831': ('device', 'Apple Watch', None),  # WATCH SE 2 44 ST AL ST SB ML G MXEV3BE/A
    '000000000100051834': ('device', 'Apple Watch', None),  # WATCH SE 2 40 MI AL MI SB SM C MXGC3BE/A
    '000000000100051850': ('device', 'Apple Watch', None),  # WATCH SE 2 44 ST AL LG SL C MXGV3BE/A
    '000000000100046782': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 15 SIL PRETO OIV0348
    '000000000100046785': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 15 SLIM OIV0351
    '000000000100046843': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE PAMPAS 13 COURO AMARELA
    '000000000100046857': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE PAMPAS 13 COURO TERRACOTA
    '000000000100046308': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 PLUS SIL PRET OIV0219
    '000000000100046649': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 14 PTA CAR MARI OIV0280
    '000000000100046694': ('acessorio', 'Outros', 'Originais iPlace'),  # ECHIP CLARO IPLACE SCBOP QRCODE 2NP RJ E
    '000000000100015617': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15 PLUS NORON BRA OIV0225
    '000000000100046699': ('acessorio', 'Outros', 'Originais iPlace'),  # ECHIP CLARO IPLACE SCBOP QRCODE 5NP RS E
    '000000000100046774': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE FLORIPA MAC13 AZUL
    '000000000100047814': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15 NORONHA PTO OIV0230
    '000000000100046917': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE PAMPAS 13 MARINHO
    '000000000100046966': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE PAMPAS 15 MARINHO
    '000000000100047504': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 PARTY BCO OIV0522
    '000000000100047506': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16 PARTY BCO OIV0519
    '000000000100047566': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 16PRO SPRING ROS OIV0534
    '000000000100047768': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 NORONHA PTO OIV0234
    '000000000100047812': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15 NORONHA BCO OIV0224
    '000000000100072457': ('device', 'iPhone', None),  # IPHONE AIR SPACE BLACK 512GB MG2Q4BE/A
    '000000000100043897': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 12 NORONH PTO OIV0236
    '000000000100046697': ('acessorio', 'Outros', 'Originais iPlace'),  # ECHIP CLARO IPLACE SCBOP QRCODE 4NP PR E
    '000000000100052082': ('acessorio', 'Outros', 'Apple'),  # CARTEIRA APPLE TECIDO AMORA MA7A4ZM/A
    '000000000100052116': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 46 LOOP E VRD MXL83AM/A
    '000000000100052638': ('acessorio', 'Outros', 'Originais iPlace'),  # MALA IPLACE C/TEXTURA RSA OIV0598
    '000000000100051860': ('device', 'Apple Watch', None),  # WATCH S10 DM 46 JB AL INK SL G 3N498BZ/A
    '000000000100051199': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI TO GO 2 BCO 920-012919
    '000000000100067212': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 17 MERC PTO OIV0904
    '000000000100067214': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA/CABO LACOSTE IPH17PMAX PTO OIV0905
    '000000000100047320': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP16 PRO SIL AZUL OIV0494
    '000000000100047323': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP16 PRO SIL PINK OIV0491
    '000000000100047994': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP11PMAX VERDFLRST IP-1199SV
    '000000000100047995': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP12MI TRA AIRCUSH IP-1245PT
    '000000000100050474': ('device', 'iPad', None),  # IPAD AIR 11 6TH M2 CL 512GB BL MUXN3BZ/A
    '000000000100051805': ('device', 'Apple Watch', None),  # WATCH ULT2 49 BK TI DG ALP L MX4T3BE/A
    '000000000100050623': ('acessorio', 'Fone', 'JBL'),  # FONE JBL IN LIVE BEAM 3 PRATA 28913777
    '000000000100050624': ('acessorio', 'Fone', 'JBL'),  # FONE JBL IN LIVE BEAM 3 PTO 28913776
    '000000000100050718': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI LIFT ROS 910-006472
    '000000000100047876': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # MOCHILA IPLACE PAMPAS 15 MARINHO
    '000000000100047894': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP11PRONANSIL VERD IP-1172SV
    '000000000100047908': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE RIO MAC13 PRETA OIV0125
    '000000000100047941': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP11 PRO DUPLA PTO IP-1185PP
    '000000000100047943': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP11PRO AZU COBLTO IP-1196SA
    '000000000100047945': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 11PRO LAVANDA IP-1198SL
    '000000000100047949': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP11PMAX DUPLA PTO IP-1187PP
    '000000000100051794': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 41 NIKE ESTELAR MC1Q4AM/A
    '000000000100051799': ('device', 'Apple Watch', None),  # WATCH ULT2 49 N TI BLU TL SM MX4J3BE/A
    '000000000100050564': ('device', 'iPad', None),  # IPAD PRO 11 M4 CELL 2TB SB MVW73BZ/A
    '000000000100072488': ('device', 'iPhone', None),  # IPHONE AIR SP BLACK 256GB DM 3P149BE/A
    '000000000100072489': ('device', 'iPhone', None),  # IPHONE AIR CL WHITE 256GB DM 3P150BE/A
    '000000000100072490': ('device', 'iPhone', None),  # IPHONE AIR LIGHT GOLD 256GB DM 3P151BE/A
    '000000000100072493': ('device', 'iPhone', None),  # IPHONE 17 PRO DP BL 256GB DM 3P171BE/A
    '000000000100072496': ('device', 'iPhone', None),  # IPHONE 17 WHITE 256GB DM 3P195BE/A
    '000000000100072497': ('device', 'iPhone', None),  # IPHONE 17 MIST BLUE 256GB DM 3P196BE/A
    '000000000100045491': ('acessorio', 'Outros', 'Originais iPlace'),  # ALCA OMBRO IPLACE ACRILI120CM PR OIV0312
    '000000000100045497': ('acessorio', 'Outros', 'Originais iPlace'),  # ALCA OMBRO IPLACE 120CM BEGE OIV0315
    '000000000100072460': ('device', 'iPhone', None),  # IPHONE AIR SKY BLUE 512GB MG2V4BE/A
    '000000000100044206': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPAD 10 ANTIBAC OIV0109
    '000000000100044753': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP11PRONANSIL PPAI IP-1169SL
    '000000000100044834': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE 11PMAX NAN SIL PTO IP-1179SP
    '000000000100045048': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 12MINI VRD FLRS IP-1266SV
    '000000000100045259': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 12 PMAX CLAS TRANS 1589
    '000000000100041201': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGI MX S GRF 920-011563
    '000000000100041475': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPHONE 14 PLUS PRIV 303804
    '000000000100041554': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP 14 PRO ANTIBACTERIA 303793
    '000000000100041562': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPHONE 14 PRO ANTIBLUE 303797
    '000000000100041636': ('device', 'iPhone', None),  # IPHONE 12 MINI WHITE 64GB DEMO 3H481BZ/A
    '000000000100041647': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPHONE 14 PRO GAMER OIV0010
    '000000000100072487': ('device', 'iPhone', None),  # IPHONE 17 P MAX C ORG 256GB DM 3P130BE/A
    '000000000100044314': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPXS MAX CLAS TRAN IP-1070PT
    '000000000100044317': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPXS MAX CUSH TRAN IP-1071PT
    '000000000100044750': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP11PRONANSIL MRSL IP-1170SM
    '000000000100046127': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE LIGH 3,5MM 1,2M BCO MXK22BZ/A
    '000000000100046227': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14 TRANS SLIM OIV0126
    '000000000100072448': ('device', 'iPhone', None),  # IPHONE 17 BLACK 512GB MG6P4BE/A
    '000000000100072450': ('device', 'iPhone', None),  # IPHONE 17 MIST BLUE 512GB MG6T4BE/A
    '000000000100072452': ('device', 'iPhone', None),  # IPHONE 17 SAGE 512GB MG6V4BE/A
    '000000000100045716': ('acessorio', 'Adaptador', 'Originais iPlace'),  # ADAPT IPLACE MULTIPORTAS 8X1 OP1GHCHU3
    '000000000100045763': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14 SIL AMA SIC 303853
    '000000000100045792': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 14 SIL PTO ONX 303837
    '000000000100043586': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 11  AIR CUSHION IP-1143PT
    '000000000100046031': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE LIGHTNING TO USB 2M MD819BZ/A
    '000000000100046337': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 PRO SIL PRETO OIV0220
    '000000000100046425': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 12 NORONHA BRA OIV0229
    '000000000100046464': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 15 PRO MAX AZL OIV0265
    '000000000100046516': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPHONE 15 PLUS SLIM OIV0267
    '000000000100046594': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IPH 14 BRILHO OIV0273
    '000000000100045710': ('acessorio', 'Adaptador', 'Originais iPlace'),  # ADAP IPLACE USB-C MULTIPOR 6X1 G3 1880
    '000000000100042506': ('device', 'iPhone', None),  # IPHONE 15 PRO BLU T 128GB DEMO 3M441BE/A
    '000000000100042559': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PMAX ANTIBAC OIV0424
    '000000000100042585': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PMAX GAMER OIV0436
    '000000000100043333': ('acessorio', 'Película', 'Originais iPlace'),  # PEL VID IPLACE IP XS MAX TRAN IP-1067VT
    '000000000100043433': ('device', 'Apple Watch', None),  # WATCH S6 GPS 44 BLU AL DEMO 3H263BZ/A
    '000000000100045989': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE THUNDERBOLT 2M MD861BE/A
    '000000100053792001': ('device', 'iPhone', None),  # IPHONE 16 PLUS VERDE ACIZ 512GB BB I, E
    '000000100053808001': ('device', 'iPhone', None),  # IPHONE 16 BRANCO 128GB BB N, E
    '000000100053809001': ('device', 'iPhone', None),  # IPHONE 16 BRANCO 256GB BB N, E
    '000000100053740001': ('device', 'iPhone', None),  # IPHONE 16 PRO MAX TITAN NAT 1TB BB, E
    '000000100053742001': ('device', 'iPhone', None),  # IPHONE 16 PRO MAX TITAN NAT 512GB BB, E
    '000000100053743001': ('device', 'iPhone', None),  # IPHONE 16 PRO MAX TITAN PRETO 1TB BB, E
    '000000100053756001': ('device', 'iPhone', None),  # IPHONE 16 PRO TIT BRANCO 256GB BB, E
    '000000100053770001': ('device', 'iPhone', None),  # IPHONE 16 PRO TIT DESERTO 512GB BB, E
    '000000100053771001': ('device', 'iPhone', None),  # IPHONE 16 PRO TITAN NAT 1TB BB, E
    '000000000100052075': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16PMAX SIL FUC MYYX3ZM/A
    '000000000100065286': ('acessorio', 'Outros', 'JBL'),  # CAIXA SOM JBL ENCOR 2 2MIC PTO 28913879
    '000000000100065871': ('device', 'Mac', None),  # IMAC M4 CTO 32GB 1TB NUM SLV Z1K1
    '000000000100055393': ('device', 'Mac', None),  # IMAC 24 M4 PINK 512GB 10GPU MWV53BZ/A
    '000000000100055394': ('device', 'Mac', None),  # IMAC 24 M4 SILVER 512GB 10GPU MCR24BZ/A
    '000000000100055409': ('device', 'Mac', None),  # MACBOOK AIR 13 M3 SG 256GB MC8G4BZ/A
    '000000000100061054': ('device', 'iPad', None),  # IPAD AIR 7TH 13 WIFI 128GB SPG MCNH4BZ/A
    '000000000100061073': ('device', 'iPad', None),  # IPAD AIR 7TH 13 WIFI 512GB PUR MCNY4BZ/A
    '000000000100061081': ('device', 'Mac', None),  # MACBOOK AIR 15 M4 BLU 256GB 16 MC7A4BZ/A
    '000000000100056928': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 15 TRANSP MXRK3ZM/A
    '000000000100058000': ('acessorio', 'Outros', 'Originais iPlace'),  # SMART TAG IPLACE SAMPA CNZ OP5TB
    '000000000100058250': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE MAC AIR 13 M1 SHINE OIV0657
    '000000000100059473': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 40 STARLIGHT SP MYJ33AM/A
    '000000000100060281': ('device', 'iPhone', None),  # IPHONE 16E BLK 512GB MD1X4BR/A
    '000000000100015182': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 14 PRO MAGSAFE PTA 303492
    '000000000100015194': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE SIL AIRPODS 2 VERDE IP-1234S
    '000000100048853001': ('device', 'iPhone', None),  # IPHONE 14 RED 256GB BB I, E
    '000000100049220001': ('device', 'Apple Watch', None),  # WATCH S7 ALUM GPS 45MM GREEN BB, E
    '000000100049221001': ('device', 'Apple Watch', None),  # WATCH S7 ALUM GPS 45MM MIDNIGHT BB, E
    '000000100049287001': ('device', 'Apple Watch', None),  # WATCH S8 GPS 41MM STARLIGHT BB, E
    '000000100049423001': ('device', 'Apple Watch', None),  # WATCH S9 ALUM GPS 41MM STARLIGHT BB, E
    '000000100049429001': ('device', 'Apple Watch', None),  # WATCH ULTRA 2 49MM TITANIUM BB, E
    '000000100049445001': ('device', 'Apple Watch', None),  # WATCH S9 ALUM CELL 45MM MIDNIGHT BB, E
    '000000000100061223': ('device', 'Mac', None),  # MACBOOK AIR 13 M4 BLU 512GB 16 MC6U4BZ/A
    '000000000100015642': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 15PLUS NORONH PTO OIV0231
    '000000000100015323': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE I14PROMAX SIL CINZA U 303844
    '000000100053846001': ('device', 'iPhone', None),  # IPHONE 16 VERDE ACIZ 128GB BB N, E
    '000000000100014238': ('acessorio', 'Bolsa/Mochila', 'Apple'),  # SLEEVE APPLE IPADPRO 12.9 CAST MQ0Q2ZM/A
    '000000000100014249': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP12/12P TR CLAS IP-1243PT
    '000000000100014352': ('acessorio', 'Bolsa/Mochila', 'Originais iPlace'),  # SLEEVE IPLACE PAMPAS 16 CAFE OIV0439
    '000000000100014355': ('acessorio', 'Caneta', 'Apple'),  # APPLE PENCIL MK0C2BE/A
    '000000000100014407': ('acessorio', 'Caneta', 'Apple'),  # APPLE PENCIL 2GER MU8F2BZ/A
    '000000000100064609': ('acessorio', 'AirPods', 'Apple'),  # FONE APPLE AIRPODS MAX ROXO MWW83BE/A
    '000000000100061110': ('device', 'Mac', None),  # MACBOOK AIR M4 15 MN 256 16 DM MW1L3BZ/A
    '000000000100061112': ('device', 'Mac', None),  # MACBOOK AIR M4 15 BL 256 16 DM MC7A4BZ/A
    '000000000100061209': ('device', 'Mac', None),  # MACBOOK AIR 13 M4 SLV 512GB 24 MC654BZ/A
    '000000000100061222': ('device', 'Mac', None),  # MACBOOK AIR 13 M4 BLU 256GB 16 MC6T4BZ/A
    '000000100053791001': ('device', 'iPhone', None),  # IPHONE 16 PLUS VERDE ACIZ 256GB BB I, E
    '000000000100054585': ('device', 'iPad', None),  # IPAD MINI 7TH WF+CEL 128GB SPG MXPN3BZ/A
    '000000000100055429': ('device', 'Mac', None),  # MACBOOK PRO 14 M4 PRO SL 512GB MX2E3BZ/A
    '000000000100055442': ('device', 'Mac', None),  # MACBOOK PRO 16 M4 PRO SB 512GB MX2Y3BZ/A
    '000000000100055447': ('device', 'Mac', None),  # MACBOOK AIR 13 M3 DM MID 256GB MC8K4BZ/A
    '000000000100055448': ('device', 'Mac', None),  # MACBOOK AIR 15 M3 DM STA 256GB MC9F4BZ/A
    '000000000100055450': ('device', 'Mac', None),  # MACBOOK PRO 14 M4P DM SL 512GB MX2E3BZ/A
    '000000000100055452': ('device', 'Mac', None),  # MACBOOK PRO 16 M4 DM SB 512GB MX2X3BZ/A
    '000000000100051740': ('device', 'iPhone', None),  # IPHONE 16 PRO BLACK 128GB MYND3BE/A
    '000000000100051758': ('device', 'Apple Watch', None),  # WATCH SE 2 40 MI AL MI SB SM G MXE73BE/A
    '000000000100051759': ('device', 'Apple Watch', None),  # WATCH SE 2 40 MI AL MI SB ML G MXE93BE/A
    '000000000100051762': ('device', 'iPhone', None),  # IPHONE 16 PRO MAX NATURA 512GB MYX33BE/A
    '000000000100051775': ('device', 'iPhone', None),  # IPHONE 16 ULTRAMARINE 128GB DM 3N399BE/A
    '000000000100051787': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 41 CAQUI MC2G4AM/A
    '000000000100051940': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16PL SIL DENIN MYYA3ZM/A
    '000000000100051942': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE BEATS IPH 16 AZL MYY73ZM/A
    '000000000100051953': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE W DEM 49 AZUL MXTW3AM/A
    '000000000100051729': ('device', 'iPhone', None),  # IPHONE 16 PLUS TEAL 128GB MXVY3BE/A
    '000000000100051738': ('device', 'iPhone', None),  # IPHONE 16 PLUS ULTMARINE 512GB MY2D3BE/A
    '000000000100051865': ('device', 'Apple Watch', None),  # WATCH S10 42MM SI AL BC SL G MWWD3AM/A
    '000000000100051866': ('device', 'Apple Watch', None),  # WATCH S10 42 JB AL BK SB SM G MWWE3AM/A
    '000000000100051910': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE BEATS IPH 16 PTO MCFC4LL/A
    '000000000100051917': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16PL SIL FUC MYYE3ZM/A
    '000000000100051939': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE BEATS IPH 16 AZL MCFE4LL/A
    '000000000100051764': ('device', 'iPhone', None),  # IPHONE 16 PRO MAX WHITE 1TB MYX53BE/A
    '000000000100060358': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16E SIL VRD MD3X4ZM/A
    '000000000100060991': ('device', 'iPad', None),  # IPAD 11TH WIFI 512GB BLUE MD4Y4BZ/A
    '000000000100061012': ('device', 'iPad', None),  # IPAD AIR 7TH 11 WIFI 256GB STL MCA44BZ/A
    '000000000100061032': ('device', 'iPad', None),  # IPAD AIR 7TH 11 CELL 512GB STL MCG64BZ/A
    '000000000100061273': ('acessorio', 'Outros', 'Apple'),  # MAGIC APPLE IPAD AIR11 M3 DEMO MDFV4BZ/A
    '000000000100061508': ('device', 'Mac', None),  # MACBOOK AIR 13 M2 STA 256GB DM MC7W4BZ/A
    '000000000100063300': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 14ANTIBAC OIV0663
    '000000000100053733': ('device', 'Apple Watch', None),  # WATCH S10 46 RG AL LB SB ML CL MWY73AM/A
    '000000000100054575': ('device', 'iPad', None),  # IPAD MINI 7TH WF 128GB BLU MXN73BZ/A
    '000000000100066978': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 17 PROMATTE OIV0811
    '000000000100054581': ('device', 'iPad', None),  # IPAD MINI 7TH WF 256GB PURPLE MXNE3BZ/A
    '000000000100052069': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE BEATS IPH16PMAX AZL MCFT4LL/A
    '000000000100052071': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 16PMAX SIL PTO MYYT3ZM/A
    '000000000100054596': ('device', 'iPad', None),  # IPAD MINI 7TH CEL 512GB PURPLE MYHF3BZ/A
    '000000000100055291': ('device', 'iPhone', None),  # IPHONE 16 PRO WHITE 128GB MYNE3BE/A
    '000000000100055296': ('device', 'iPhone', None),  # IPHONE 16 PRO WHITE 256GB MYNJ3BE/A
    '000000000100052654': ('acessorio', 'Capa/Case', 'Logitech'),  # CAPA TC LOGI PRO 13 M4 GRAF 920-012658
    '000000000100053012': ('acessorio', 'Outros', 'Logitech'),  # WEBCAM LOGI U HD 4K MX GRF 960-001548
    '000000000100053013': ('acessorio', 'Outros', 'Logitech'),  # WEBCAM LOGI F HD BRIO 500 BCO 960-001426
    '000000000100056094': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH16PM ANT/BL/R A.U. OIV0625
    '000000000100054576': ('device', 'iPad', None),  # IPAD MINI 7TH WF 128GB STELLA MXN83BZ/A
    '000000000100054579': ('device', 'iPad', None),  # IPAD MINI 7TH WF 256GB BLU MXNC3BZ/A
    '000000000100054580': ('device', 'iPad', None),  # IPAD MINI 7TH WF 256GB STELLA MXND3BZ/A
    '000000000100052068': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE BEATS IPH16PMAX PTO MCFQ4LL/A
    '000000000100080285': ('device', 'Mac', None),  # MACB PRO 16 M5P 48GB SPB 1TB MGEC4BZ/A
    '000000000100080288': ('device', 'Mac', None),  # MACB PRO 14 M5P 24GB SIL 2TB MJLV4BZ/A
    '000000000100080309': ('device', 'Mac', None),  # MACB PRO 14 M5 32GB SPB 1TB MJ3D4BZ/A
    '000000000100080310': ('device', 'Mac', None),  # MACB PRO 14 M5 32GB SIL 1TB MJ3E4BZ/A
    '000000000100031316': ('device', 'iPhone', None),  # IPHONE 15 PLUS YLW 512GB MU1M3BE/A
    '000000000100080255': ('device', 'Mac', None),  # MACB AIR 13 M5 24GB STL 1TB MDHD4BZ/A
    '000000000100080260': ('device', 'Mac', None),  # MACB AIR 13 M5 16GB S BL 1TB MDHJ4BZ/A
    '000000000100080266': ('device', 'Mac', None),  # MACB AIR 15 M5 16GB STL 1TB MDVE4BZ/A
    '000000000100080269': ('device', 'Mac', None),  # MACB AIR 15 M5 16GB MDN 1TB MDVK4BZ/A
    '000000000100080279': ('device', 'Mac', None),  # MACB PRO 14 M5M 36GB SPB 2TB MGDU4BZ/A
    '000000000100080281': ('device', 'Mac', None),  # MACB PRO 16 M5P 48GB SIL 1TB MGE64BZ/A
    '000000000100041828': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP 14 PRO MAX ANTIBAC OIV0031
    '000000000100032507': ('acessorio', 'Fone', 'JBL'),  # FONE JBL GAMER QUANTUM 600 BLK 28913168
    '000000000100032550': ('acessorio', 'Fone', 'JBL'),  # FONE JBL GAMER QUANTUM 800 BLK 28913169
    '000000000100032566': ('acessorio', 'Capa/Case', 'Apple'),  # SMART FOLIO APPLE PRO 13 BCO MWK23ZM/A
    '000000000100032590': ('device', 'iPad', None),  # SMART KEYB IPAD PRO 12.9 DEMO MU8H2LL/A
    '000000000100080254': ('device', 'Mac', None),  # MACB AIR 13 M5 16GB STL 1TB MDHC4BZ/A
    '000000000100034027': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 11PRO SIL AZUL M MWYJ2ZM/A
    '000000000100034251': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP11PROMAX COU VERM MX0F2ZM/A
    '000000000100032383': ('acessorio', 'Capa/Case', 'Apple'),  # SMART FOLIO APPLE 10TH CEU MQDU3ZM/A
    '000000000100032458': ('acessorio', 'Capa/Case', 'Apple'),  # SMART FOLIO APPLE AIR 11 LIILAS MWK83ZM
    '000000000100032468': ('acessorio', 'Fone', 'JBL'),  # FONE JBL GAMER QUANTUM 200 BLK 28913167
    '000000000100032501': ('acessorio', 'Fone', 'JBL'),  # FONE JBL GAMER QUANTUM 300 BLK 28913177
    '000000000100035979': ('acessorio', 'Outros', 'JBL'),  # CAIXA SOM JBL ENCOR 2MIC PTO 58035034
    '000000000100032986': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 11 SIL PRETO MWVU2ZM/A
    '000000000100032993': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 11 TRANSP MWVG2ZM/A
    '000000000100033272': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE SIL IPSE2ND/8/7 RED MMWN2ZM/A
    '000000000100080240': ('device', 'iPad', None),  # IPAD AIR M4 11 WF PUR 1TB MH3K4BZ/A
    '000000000100032655': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYB APPLE DEMO PRO13BCO MWR43BZ/A
    '000000000100032662': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYB APPLE DEMO PRO13PTO MWR53BZ/A
    '000000000100032778': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYB 12POL IPAD PRO 4TH MXQU2BZ/A
    '000000000100032833': ('acessorio', 'Fone', 'JBL'),  # FONE JBL OV TUNE 770NC AZL 28913712
    '000000000100032839': ('acessorio', 'Fone', 'Originais iPlace'),  # FONE IPLACE OVER N370 PTO AUHEL4545
    '000000000100080284': ('device', 'Mac', None),  # MACB PRO 16 M5P 24GB SPB 1TB MGEA4BZ/A
    '000000000100080210': ('device', 'iPad', None),  # IPAD AIR M4 11 CL BL 128GB MH794BZ/A
    '000000000100080230': ('device', 'iPad', None),  # IPAD AIR M4 11 WF BL 256GB MH364BZ/A
    '000000000100080231': ('device', 'iPad', None),  # IPAD AIR M4 11 WF STL 256GB MH374BZ/A
    '000000000100080233': ('device', 'iPad', None),  # IPAD AIR M4 11 WF SPG 512GB MH3A4BZ/A
    '000000000100080234': ('device', 'iPad', None),  # IPAD AIR M4 11 WF BLU 512GB MH3C4BZ/A
    '000000000100035139': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP13 SI AZU ABISSAL MM293ZE/A
    '000000000100080152': ('device', 'iPhone', None),  # IPHONE 17E SOFT PINK 512GB MHU34BE/A
    '000000000100080166': ('device', 'iPad', None),  # IPAD AIR M4 13 WF PUR 256GB MH5X4BZ/A
    '000000000100080187': ('device', 'iPad', None),  # IPAD AIR M4 13 CL STL 128GB MH9F4BZ/A
    '000000000100080196': ('device', 'iPad', None),  # IPAD AIR M4 13 WF STL 128GB MH5Q4BZ/A
    '000000000100080198': ('device', 'iPad', None),  # IPAD AIR M4 13 WF BL 512GB MH604BZ/A
    '000000000100080199': ('device', 'iPad', None),  # IPAD AIR M4 13 WF STL 512GB MH614BZ/A
    '000000000100080200': ('device', 'iPad', None),  # IPAD AIR M4 13 WF PUR 512GB MH624BZ/A
    '000000000100029652': ('device', 'iPhone', None),  # IPHONE SE 3RD STARLIGHT 64GB MMXG3BZ/A
    '000000000100029941': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 49 TRAIL YEL S/M MQEG3AM/A
    '000000000100030187': ('acessorio', 'Pulseira', 'Apple'),  # P APPLE WATCH 49 BLUE ALPINE MT5M3AM/A
    '000000000100030384': ('device', 'iPhone', None),  # IPHONE 14 BLUE 512GB MPXN3BE/A
    '000000000100030387': ('device', 'iPhone', None),  # IPHONE 14 BLUE 128GB MPVN3BR/A
    '000000000100080882': ('device', 'iPhone', None),  # IPHONE 17E WHITE 512GB MHU04BR/A
    '000000000100031573': ('acessorio', 'Fone', 'JBL'),  # FONE JBL TOURPROWIRELESS2 PRETO 28913689
    '000000000100031596': ('device', 'iPhone', None),  # IPHONE 15 PRO MAX BLU TT 256GB MU7A3BE/A
    '000000000100031645': ('device', 'iPhone', None),  # IPHONE 15 PRO MAX WHT TT 256GB MU783BE/A
    '000000000100031721': ('device', 'iPad', None),  # IPAD MINI SMART COVER BLACK MX4R2ZM/A
    '000000000100031859': ('acessorio', 'Fone', 'JBL'),  # FONE OUVIDO JBL ENDURRACE CORBR 28913812
    '000000000100031922': ('device', 'iPhone', None),  # IPHONE 15 GREEN 128GB MTP53BE/A
    '000000000100031332': ('device', 'iPad', None),  # IPAD AIR 2 SMART COVER YELLOW MGXN2BZ/A
    '000000000100031485': ('acessorio', 'Fone', 'JBL'),  # FONE DE OUVIDO JBL WAV BUDS WHT 28913662
    '000000000100031496': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPADPRO12.9 COV PTO MPV62ZM/A
    '000000000100031524': ('acessorio', 'Fone', 'Originais iPlace'),  # FONE IN EAR TWS GAMER IPLACE AUHEL3131
    '000000000100031694': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPADPRO11SMARFOLAZU MX4X2ZM/A
    '000000000100072601': ('device', 'Apple Watch', None),  # WATCH 11 46 GD TI GD ML SM C MFD74AM/A
    '000000000100072565': ('device', 'Apple Watch', None),  # WATCH 11 46 SI AL PF SB ML G MEVA4AM/A
    '000000000100072569': ('device', 'Apple Watch', None),  # WATCH 11 42 SG AL BK SB ML C MF8C4AM/A
    '000000000100072576': ('device', 'Apple Watch', None),  # WATCH 11 42 NT TI NT ML C MF8P4AM/A
    '000000000100072577': ('device', 'Apple Watch', None),  # WATCH 11 42 SL TI BK SB SM C MF8R4AM/A
    '000000000100072580': ('device', 'Apple Watch', None),  # WATCH 11 42 GD TI LB SB SM C MF8W4AM/A
    '000000000100072664': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 17 SUP CALC MGTL4LL/A
    '000000000100072687': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 17 VD MUSGO MGEX4ZM/A
    '000000000100073532': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-A USB-C CURT PT MEQL4LL/A
    '000000000100073533': ('acessorio', 'Cabo Apple', 'Apple'),  # CABO APPLE USB-C LIGHT BEAT PT MDGK4LL/A
    '000000000100036379': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 14 PLUS SIL AURO MPTD3ZE/A
    '000000000100035815': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP12MINI SIL MAG PT MHKX3ZE/A
    '000000000100040159': ('acessorio', 'Película', 'Originais iPlace'),  # PELICULA IPLACE IP12MIN TR C/B IP-1248VT
    '000000000100040160': ('device', 'iPad', None),  # IPAD 9TH WIFI 64GB SPGR DEMO 3K2K3BZ/A
    '000000000100040166': ('device', 'iPad', None),  # IPAD AIR 11 6 M2 WF 128GB S DM 3M672BZ/A
    '000000000100040212': ('acessorio', 'Caneta', 'Logitech'),  # CANETA LOGITECH CRAYON USBC 914-000083
    '000000000100072615': ('device', 'Apple Watch', None),  # WATCH ULTRA3 49 BK TI BK ALP MF0X4BE/A
    '000000000100039104': ('device', 'Mac', None),  # MACBOOK PRO 14 M3 SIL 512 DEMO MR7J3BZ/A
    '000000000100039370': ('acessorio', 'Outros', 'Apple'),  # MAGIC APPLE KEYB 11 PRO 2 QDEMO
    '000000000100039379': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPHONE 11 ANTIBAC OIV0032
    '000000000100039413': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYBO IPAD PRO 11 3TH AIR 4TH DEMO
    '000000000100039456': ('acessorio', 'Magic Keyboard', 'Apple'),  # MAGIC KEYBOARD APPLEIPAD10 DEM MQDP3BZ/A
    '000000000100039561': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 12PMAX SI MAG WH MHLE3ZE/A
    '000000000100039648': ('device', 'Mac', None),  # MACBOOK PRO 16 M1PRO SG DEM512 MK183BZ/A
    '000000000100041959': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15PRIVACID OIV0251
    '000000000100072515': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 17 PRO AZUL MGF44ZM/A
    '000000000100041179': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 13 PRIV OIV0027
    '000000000100042164': ('device', 'iPhone', None),  # IPHONE 13 GREEN 128GB DEMO 3K584BZ/A
    '000000000100042299': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16GAMER A.U OIV0549
    '000000000100042415': ('device', 'iPhone', None),  # IPHONE 15 BLUE 128GB DEMO 3M425BE/A
    '000000000100042429': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 16PRO PRIV OIV0427
    '000000000100043636': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE WATCH 41MM C/B OIV0083
    '000000000100043735': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL XTREME 4 AZL 28913741
    '000000000100043768': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE 2GER IP11 AZU ROYL IP-1318SA
    '000000000100042097': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15 PRO ANTIBLUE OIV0245
    '000000000100042150': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15PRO ANTIBAC OIV0241
    '000000000100072600': ('device', 'Apple Watch', None),  # WATCH 11 46 GD TI LB SB ML C MFD64AM/A
    '000000000100040808': ('device', 'iPad', None),  # IPAD WI-FI 32GB SPGR DEMO 3C668BZ/A
    '000000000100040830': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI MX ANYW 3S RSA 910-006934
    '000000000100040883': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP 13 PMAX ANTIBACTE 302031
    '000000000100072604': ('device', 'Apple Watch', None),  # WATCH ULTRA3 49 NT TI LB ALP MEWK4BE/A
    '000000000100072606': ('device', 'Apple Watch', None),  # WATCH ULTRA3 49 NT TI LB ALP MEWP4BE/A
    '000000000100040528': ('device', 'iPad', None),  # IPAD PRO 11 M4 WF 256GB SB DM 3M772BZ/A
    '000000000100040543': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP 12/12 PRO ANTI BACT 301221
    '000000000100040577': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGITECH BLU PEBLE ROSE 910-005894
    '000000000100040613': ('acessorio', 'Mouse', 'Logitech'),  # MOUSE LOGI LIFT CANHTO GRAF 910-006467
    '000000000100072590': ('device', 'Apple Watch', None),  # WATCH 11 46 SI AL PF SB ML C MFCR4AM/A
    '000000000100072591': ('device', 'Apple Watch', None),  # WATCH 11 46 NT TI SG SB SM C MFCW4AM/A
    '000000000100072594': ('device', 'Apple Watch', None),  # WATCH 11 46 NT TI NT ML ML C MFD04AM/A
    '000000000100042158': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IPH 15PMAX PRIVACID OIV0254
    '000000000100036461': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 14 PLUS SIL SUCU MPTC3ZE/A
    '000000000100036519': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 14 PRO SIL AZUL MPTF3ZE/A
    '000000000100036526': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 14 PRO SIL LILAS MPTJ3ZE/A
    '000000000100036608': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 14 PRO SIL SUCU MPTL3ZE/A
    '000000000100036789': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 14PRO MX SI SUCU MPTY3ZE/A
    '000000000100037092': ('device', 'Mac', None),  # MACBOOK AIR 13 M3 ST DM 256GB MRXT3BZ/A
    '000000000100037260': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 15 PRO AZUL INVE MT1L3ZM/A
    '000000000100034700': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL GO ESSENT AZL 28913615
    '000000000100034885': ('acessorio', 'Outros', 'JBL'),  # OCULOS JBL SOUNDGEARS PEARL 28913766
    '000000000100034992': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP12/PRO SI MAG WHT MHL53ZE/A
    '000000000100035033': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP12/PRO SIMAG PLUM MHL23ZE/A
    '000000000100034299': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP11PRO MAX SIL AZU MWYW2ZM/A
    '000000000100040911': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE IP 13 PRO MAX ANTIBLUE 302028
    '000000000100034420': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL CLIP 4 PRETA 28913316
    '000000000100034566': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL GO 3 VERDE 28913281
    '000000000100034569': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL GO 3 VERMELHA 28913275
    '000000000100036182': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 14 SIL SUCULENTA MPT13ZE/A
    '000000000100036305': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IPH 14 COU LARAN MPP83ZE/A
    '000000000100078949': ('acessorio', 'Fone', 'JBL'),  # FONE JBL ENDURANCE PEAK 4 PTO 28914030
    '000000000100079308': ('acessorio', 'Fone', 'JBL'),  # FONE JBL TUNE T530BT BRANCO 28914076
    '000000000100079335': ('acessorio', 'Capa/Case', 'Originais iPlace'),  # CAPA IPLACE IP 17PM LACOSTE PT OIV0937
    '000000000100035543': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL PBSTAG 320 PTO 28913745
    '000000000100035798': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP12MINI MAGSAFE TR MHLL3ZE/A
    '000000000100035807': ('device', 'Apple Watch', None),  # WATCH S9 GPS 45 PINK SB M/L MR9H3BZ/A
    '000000000100034340': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP11 PROMAX SIL PTO MX002ZM/A
    '000000000100040962': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE ANTIBAC CB IP13PMAX IP-1392VA
    '000000000100041028': ('acessorio', 'Teclado', 'Logitech'),  # TECLADO LOGITECH BT K480 PRET 920-006348
    '000000000100038542': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM 14PRO14PROMAX GRY OIV0093
    '000000000100074549': ('device', 'iPad', None),  # IPAD PRO 13 M5 CELL 256GB SB ME7W4BZ/A
    '000000000100074557': ('device', 'iPad', None),  # IPAD PRO 13 M5 CELL 2TB SB ME8J4BZ/A
    '000000000100035146': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 13 SIL M NOITE MM2A3ZE/A
    '000000000100035165': ('acessorio', 'Outros', 'JBL'),  # CX DE SOM JBL CHARG ESSENT CINZ 28913283
    '000000000100035351': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL FLIP 6 BLK 28913556
    '000000000100035403': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL FLIP ESS 2 PTO 28913643
    '000000000100035497': ('acessorio', 'Caixa de Som', 'JBL'),  # CAIXA DE SOM JBL PARTYB 710 PTO 28913523
    '000000000100038527': ('acessorio', 'Película', 'Originais iPlace'),  # PEL IPLACE CAM IPH15 6.7/6.7 PRT OIV0302
    '000000000100074516': ('device', 'iPad', None),  # IPAD PRO 11 M5 WIFI 512GB SIL MDWN4BZ/A
    '000000000100074529': ('device', 'iPad', None),  # IPAD PRO 13 M5 WIFI 1TB SB MDYN4BZ/A
    '000000000100074537': ('device', 'iPad', None),  # IPAD PRO 11 M5 CELL 256GB SB ME2N4BZ/A
    '000000000100074538': ('device', 'iPad', None),  # IPAD PRO 11 M5 CELL 256GB SIL ME2P4BZ/A
    '000000000100074539': ('device', 'iPad', None),  # IPAD PRO 11 M5 CELL 512GB SB ME2Q4BZ/A
    '000000000100074540': ('device', 'iPad', None),  # IPAD PRO 11 M5 CELL 512GB SIL ME2T4BZ/A
    '000000000100037308': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 15PRO MAX AZL TP MT1P3ZM/A
    '000000000100037336': ('device', 'Apple Watch', None),  # AW S3 GPS 38MM GOLD ALU DEMO 3D211BZ/A
    '000000000100037363': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 15PRO MAX VRD CP MT1X3ZM/A
    '000000000100037390': ('acessorio', 'Capa/Case', 'Apple'),  # CAPA APPLE IP 15PRO MAX AZL IN MT1Y3ZM/A
    '000000000100037635': ('device', 'Apple Watch', None),  # WATCH SE 2ND GPS 44 STRL M/L MRE53BZ/A
    '000000000100038374': ('device', 'Mac', None),  # MACBOOK AIR 13 M28C SLVR 512GB MLY03BZ/A
    '000000000100074511': ('device', 'Mac', None),  # MACB PRO 14 M5 SIL 16GB 1TB MDE54BZ/A
}


def _acessorios_sku_lookup_cte() -> str:
    """Gera o CTE sku_lookup inline com todos os SKUs classificados."""
    rows = []
    for sku, (tipo, categoria, marca) in _ACESSORIOS_SKU_MAP.items():
        m = f"'{marca}'" if marca else 'NULL'
        rows.append(f"    STRUCT('{sku}', '{tipo}', '{categoria}', {m})")
    body = ",\n".join(rows)
    return (
        "sku_lookup AS (\n"
        "  SELECT * FROM UNNEST(ARRAY<STRUCT<sku STRING, tipo STRING, categoria STRING, marca STRING>>[\n"
        f"{body}\n"
        "  ])\n)"
    )


def _build_acessorios_vendas_sql(start_date: str, end_date: str, canal_filter: str = "") -> str:
    """Attach rate de acessórios por linha Apple — classificação 100% via SKU map (CSV)."""
    project = _quote_identifier(BASE_VENDAS_BQ_PROJECT)
    dataset = _quote_identifier(VENDAS_BQ_DATASET)
    table   = _quote_identifier(VENDAS_BQ_TABLE)
    canal_clause = f"AND UPPER(TRIM(Canal)) = '{canal_filter}'" if canal_filter else ""
    sku_cte = _acessorios_sku_lookup_cte()

    return f"""
WITH
{sku_cte},
all_items AS (
  SELECT
    CONCAT(CAST(Cod_Filial AS STRING), '-', CAST(Numero_Pedido AS STRING)) AS pedido_key,
    Cod_Produto
  FROM `{project}.{dataset}.{table}`
  WHERE Data_Completa BETWEEN '{start_date}' AND '{end_date}'
    AND UPPER(TRIM(Status_Pedidos)) = 'FATURADO'
    AND Cod_Produto NOT LIKE '000000010000%'
    {canal_clause}
),
classified AS (
  SELECT ai.pedido_key, lk.tipo, lk.categoria, lk.marca
  FROM all_items ai
  JOIN sku_lookup lk ON lk.sku = ai.Cod_Produto
),
pedidos_device AS (
  SELECT DISTINCT pedido_key, categoria AS linha_apple
  FROM classified
  WHERE tipo = 'device'
),
acc_apple AS (
  SELECT pedido_key, categoria
  FROM classified
  WHERE tipo = 'acessorio' AND marca = 'Apple'
),
acc_parceiro AS (
  SELECT pedido_key, categoria
  FROM classified
  WHERE tipo = 'acessorio' AND marca != 'Apple'
),
total_por_linha AS (
  SELECT linha_apple, COUNT(DISTINCT pedido_key) AS total_pedidos
  FROM pedidos_device GROUP BY 1
),
matrix_apple AS (
  SELECT pd.linha_apple, aa.categoria, 'apple' AS grupo,
    COUNT(DISTINCT pd.pedido_key) AS pedidos_com_acessorio
  FROM pedidos_device pd
  JOIN acc_apple aa ON aa.pedido_key = pd.pedido_key
  GROUP BY 1, 2, 3
),
matrix_parceiro AS (
  SELECT pd.linha_apple, ap.categoria, 'parceiro' AS grupo,
    COUNT(DISTINCT pd.pedido_key) AS pedidos_com_acessorio
  FROM pedidos_device pd
  JOIN acc_parceiro ap ON ap.pedido_key = pd.pedido_key
  GROUP BY 1, 2, 3
),
todos_acc AS (
  SELECT DISTINCT pedido_key FROM acc_apple
  UNION DISTINCT
  SELECT DISTINCT pedido_key FROM acc_parceiro
),
oportunidade AS (
  SELECT pd.linha_apple,
    COUNT(DISTINCT pd.pedido_key)  AS sem_acessorio,
    ANY_VALUE(tpl.total_pedidos)   AS total_pedidos,
    ROUND(COUNT(DISTINCT pd.pedido_key) * 100.0 / NULLIF(ANY_VALUE(tpl.total_pedidos), 0), 1) AS pct_sem_acessorio
  FROM pedidos_device pd
  JOIN total_por_linha tpl ON tpl.linha_apple = pd.linha_apple
  LEFT JOIN todos_acc ta ON ta.pedido_key = pd.pedido_key
  WHERE ta.pedido_key IS NULL
  GROUP BY 1
)
SELECT ma.linha_apple, ma.categoria, ma.grupo,
       ma.pedidos_com_acessorio,
       tpl.total_pedidos,
       ROUND(ma.pedidos_com_acessorio * 100.0 / NULLIF(tpl.total_pedidos, 0), 1) AS rate
FROM matrix_apple ma JOIN total_por_linha tpl ON tpl.linha_apple = ma.linha_apple
UNION ALL
SELECT mp.linha_apple, mp.categoria, mp.grupo,
       mp.pedidos_com_acessorio,
       tpl.total_pedidos,
       ROUND(mp.pedidos_com_acessorio * 100.0 / NULLIF(tpl.total_pedidos, 0), 1) AS rate
FROM matrix_parceiro mp JOIN total_por_linha tpl ON tpl.linha_apple = mp.linha_apple
UNION ALL
SELECT linha_apple, 'OPORTUNIDADE', 'oportunidade',
       sem_acessorio, total_pedidos, pct_sem_acessorio
FROM oportunidade
UNION ALL
SELECT linha_apple, 'TOTAL', 'total',
       total_pedidos, total_pedidos, 100.0
FROM total_por_linha
ORDER BY linha_apple, grupo, categoria
""".strip()


def _build_acessorios_marcas_vendas_sql(start_date: str, end_date: str, canal_filter: str = "") -> str:
    """Cards de marca (JBL/Logitech/Originais iPlace) — classificação 100% via SKU map (CSV)."""
    project = _quote_identifier(BASE_VENDAS_BQ_PROJECT)
    dataset = _quote_identifier(VENDAS_BQ_DATASET)
    table   = _quote_identifier(VENDAS_BQ_TABLE)
    canal_clause = f"AND UPPER(TRIM(Canal)) = '{canal_filter}'" if canal_filter else ""
    sku_cte = _acessorios_sku_lookup_cte()

    return f"""
WITH
{sku_cte},
brand_items AS (
  SELECT
    CONCAT(CAST(v.Cod_Filial AS STRING), '-', CAST(v.Numero_Pedido AS STRING)) AS pedido_key,
    COALESCE(NULLIF(TRIM(v.Desc_Produto), ''), 'Sem nome') AS desc_produto,
    lk.marca
  FROM `{project}.{dataset}.{table}` v
  JOIN sku_lookup lk ON lk.sku = v.Cod_Produto AND lk.tipo = 'acessorio' AND lk.marca != 'Apple'
  WHERE v.Data_Completa BETWEEN '{start_date}' AND '{end_date}'
    AND UPPER(TRIM(v.Status_Pedidos)) = 'FATURADO'
    AND v.Cod_Produto NOT LIKE '000000010000%'
    {canal_clause}
),
por_marca AS (
  SELECT marca, COUNT(DISTINCT pedido_key) AS pedidos, COUNT(*) AS itens
  FROM brand_items
  WHERE marca IN ('JBL', 'Logitech', 'Originais iPlace')
  GROUP BY 1
),
top_jbl_json AS (
  SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(nome, qtd) ORDER BY qtd DESC LIMIT 10)) AS v
  FROM (SELECT desc_produto AS nome, COUNT(*) AS qtd FROM brand_items WHERE marca = 'JBL' GROUP BY 1)
),
top_log_json AS (
  SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(nome, qtd) ORDER BY qtd DESC LIMIT 10)) AS v
  FROM (SELECT desc_produto AS nome, COUNT(*) AS qtd FROM brand_items WHERE marca = 'Logitech' GROUP BY 1)
),
top_ori_json AS (
  SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(nome, qtd) ORDER BY qtd DESC LIMIT 10)) AS v
  FROM (SELECT desc_produto AS nome, COUNT(*) AS qtd FROM brand_items WHERE marca = 'Originais iPlace' GROUP BY 1)
)
SELECT
  pm.marca, pm.pedidos, pm.itens,
  tj.v AS top_jbl_json,
  tl.v AS top_log_json,
  ori.v AS top_ori_json
FROM por_marca pm
CROSS JOIN top_jbl_json tj
CROSS JOIN top_log_json tl
CROSS JOIN top_ori_json ori
ORDER BY pm.pedidos DESC
""".strip()


@router.get("/acessorios")
def acessorios(
    start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    canal: str = Query(default=""),
) -> dict[str, Any]:
    import json as _json
    try:
        s = _validate_optional_iso_date(start) or start
        e = _validate_optional_iso_date(end) or end
        canal_filter = canal.upper().strip() if canal.strip() in ("VAREJO", "ECOMMERCE") else ""

        sql_matriz = _build_acessorios_vendas_sql(s, e, canal_filter)
        sql_marcas = _build_acessorios_marcas_vendas_sql(s, e, canal_filter)
        matriz_records = run_bigquery_records(sql_matriz, BASE_VENDAS_BQ_PROJECT, location=None)
        marcas_records = run_bigquery_records(sql_marcas, BASE_VENDAS_BQ_PROJECT, location=None)

        matrix_apple, matrix_parceiro, oportunidade, total_por_linha = [], [], [], []
        for row in matriz_records:
            grupo = str(row.get("grupo") or "")
            item = {
                "linha_apple":           str(row.get("linha_apple") or ""),
                "categoria":             str(row.get("categoria") or ""),
                "pedidos_com_acessorio": int(row.get("pedidos_com_acessorio") or 0),
                "total_pedidos":         int(row.get("total_pedidos") or 0),
                "rate":                  float(row.get("rate") or 0),
            }
            if grupo == "apple":
                matrix_apple.append(item)
            elif grupo == "parceiro":
                matrix_parceiro.append(item)
            elif grupo == "oportunidade":
                oportunidade.append({
                    "linha_apple":       item["linha_apple"],
                    "sem_acessorio":     item["pedidos_com_acessorio"],
                    "total_pedidos":     item["total_pedidos"],
                    "pct_sem_acessorio": item["rate"],
                })
            elif grupo == "total":
                total_por_linha.append({
                    "linha_apple":  item["linha_apple"],
                    "total_pedidos": item["total_pedidos"],
                })

        por_marca = []
        top_jbl, top_log, top_ori = [], [], []
        for row in marcas_records:
            por_marca.append({
                "marca":   str(row.get("marca") or ""),
                "pedidos": int(row.get("pedidos") or 0),
                "itens":   int(row.get("itens") or 0),
            })
        first = marcas_records[0] if marcas_records else {}
        top_jbl = _json.loads(first.get("top_jbl_json") or "[]")
        top_log = _json.loads(first.get("top_log_json") or "[]")
        top_ori = _json.loads(first.get("top_ori_json") or "[]")

        return {
            "matrix_apple":    matrix_apple,
            "matrix_parceiro": matrix_parceiro,
            "oportunidade":    oportunidade,
            "total_por_linha": total_por_linha,
            "por_marca":       por_marca,
            "top_produtos": {
                "JBL":              {"qtd": top_jbl},
                "Logitech":         {"qtd": top_log},
                "Originais iPlace": {"qtd": top_ori},
            },
            "start_date": s,
            "end_date":   e,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao consultar acessórios: {exc}") from exc


@router.get("/acessorios/oportunidade-export")
def acessorios_oportunidade_export(
    start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    linha: str = Query(default=""),
) -> dict[str, Any]:
    """Retorna pedidos com device Apple sem acessório no período (via vendas_iplace)."""
    project = _quote_identifier(BASE_VENDAS_BQ_PROJECT)
    dataset = _quote_identifier(VENDAS_BQ_DATASET)
    table   = _quote_identifier(VENDAS_BQ_TABLE)
    try:
        s = _validate_optional_iso_date(start) or start
        e = _validate_optional_iso_date(end) or end
        safe_linha = linha.strip().replace("'", "''")
        linha_filter = f"AND pd.linha_apple = '{safe_linha}'" if safe_linha else ""
        sql = f"""
WITH
all_items AS (
  SELECT
    CONCAT(CAST(Cod_Filial AS STRING), '-', CAST(Numero_Pedido AS STRING)) AS pedido_key,
    Cod_Filial,
    Numero_Pedido,
    Data_Completa,
    Canal,
    UPPER(COALESCE(Desc_Produto, '')) AS produto_upper
  FROM `{project}.{dataset}.{table}`
  WHERE Data_Completa BETWEEN '{s}' AND '{e}'
    AND UPPER(TRIM(Status_Pedidos)) = 'FATURADO'
    AND Cod_Produto NOT LIKE '000000010000%'
),
device_rows AS (
  SELECT DISTINCT pedido_key, Cod_Filial, Numero_Pedido, Data_Completa, Canal,
    CASE
      WHEN REGEXP_CONTAINS(produto_upper, r'^IPHONE')                                                    THEN 'iPhone'
      WHEN REGEXP_CONTAINS(produto_upper, r'^IPAD')                                                      THEN 'iPad'
      WHEN REGEXP_CONTAINS(produto_upper, r'^(?:MACB|IMAC|MAC\\s+(?:MINI|PRO|STUDIO|AIR))')             THEN 'Mac'
      WHEN REGEXP_CONTAINS(produto_upper, r'^(?:WATCH\\s|APPLE WATCH)')                                  THEN 'Apple Watch'
      WHEN REGEXP_CONTAINS(produto_upper, r'^APPLE TV')                                                  THEN 'Apple TV'
    END AS linha_apple
  FROM all_items
  WHERE REGEXP_CONTAINS(produto_upper, r'^(?:IPHONE|IPAD|MACB|IMAC|MAC\\s+(?:MINI|PRO|STUDIO|AIR)|WATCH\\s|APPLE\\s+(?:WATCH|TV))')
),
pedidos_device AS (
  SELECT DISTINCT pedido_key, Cod_Filial, Numero_Pedido, Data_Completa, Canal, linha_apple
  FROM device_rows WHERE linha_apple IS NOT NULL
),
todos_acc AS (
  SELECT DISTINCT pedido_key FROM all_items
  WHERE (
    (
      REGEXP_CONTAINS(produto_upper, r'AIR\\s*POD|AIRTAG|AIR TAG|EARPODS|MAGSAFE|CARTEIRA APPLE|MAGIC MOUSE|MOUSE MAGIC|MAGIC KEY(?:BOARD|B)|TECLADO APPLE|CABO APPLE|(?:CARREG|CARREGADOR) APPLE|APPLE PENCIL')
      OR REGEXP_CONTAINS(produto_upper, r'^P APPLE WATCH')
    )
    AND NOT REGEXP_CONTAINS(produto_upper, r'IPLACE|JBL|LOGI|MISTER')
  )
  OR (
    (produto_upper LIKE '%JBL%' OR produto_upper LIKE '%LOGI%' OR produto_upper LIKE '%IPLACE%' OR produto_upper LIKE '%MISTER%')
    AND NOT REGEXP_CONTAINS(produto_upper, r'^CHIP CLARO|^CLARO E-SIM|^ECHIP CLARO')
  )
)
SELECT
  pd.Cod_Filial     AS cod_filial,
  pd.Numero_Pedido  AS numero_pedido,
  pd.linha_apple,
  pd.Data_Completa  AS data_pedido,
  pd.Canal          AS canal
FROM pedidos_device pd
LEFT JOIN todos_acc ta ON ta.pedido_key = pd.pedido_key
WHERE ta.pedido_key IS NULL
  {linha_filter}
ORDER BY pd.linha_apple, pd.Data_Completa
LIMIT 50000
""".strip()
        records = run_bigquery_records(sql, BASE_VENDAS_BQ_PROJECT, location=None)
        items = [
            {
                "cod_filial":    str(r.get("cod_filial") or ""),
                "numero_pedido": str(r.get("numero_pedido") or ""),
                "linha_apple":   str(r.get("linha_apple") or ""),
                "data_pedido":   str(r.get("data_pedido") or ""),
                "canal":         str(r.get("canal") or ""),
            }
            for r in records
        ]
        return {"items": items, "total": len(items), "start_date": s, "end_date": e}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao exportar oportunidade: {exc}") from exc
