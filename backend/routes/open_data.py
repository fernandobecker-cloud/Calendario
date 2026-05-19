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
) -> dict[str, Any]:
    try:
        sql_total = _build_monthly_revenue_sql(start, end)
        sql_canal = _build_monthly_revenue_by_channel_sql(start, end)
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


def _build_audit_receita_por_campanha_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)
    event_time_filter, partition_filter = _build_attribution_date_filters(start_date, end_date, "r")
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS

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


def _build_audit_receita_resumo_sql(start_date: str | None = None, end_date: str | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)
    event_time_filter, partition_filter = _build_attribution_date_filters(start_date, end_date, "r")
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS

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
) -> dict[str, Any]:
    try:
        sql_detalhe = _build_audit_receita_por_campanha_sql(start, end)
        sql_resumo = _build_audit_receita_resumo_sql(start, end)
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
            location=BASE_VENDAS_BQ_LOCATION or None, timeout=55,
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


def _build_comparativo_crm_sql(start_date: str | None = None, end_date: str | None = None) -> str:
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
) -> dict[str, Any]:
    try:
        sql = _build_comparativo_crm_sql(start, end)
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


def _build_sms_apuracao_sql(nome: str, dispatch_date: str) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    sms_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_CAMPAIGNS_TABLE)
    sms_sends_table = _quote_identifier(EMARSYS_OPEN_DATA_SMS_SENDS_TABLE)
    si_purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS
    safe_nome = _sanitize_campanha_nome(nome)
    d = dispatch_date  # already validated ISO date

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
  WHERE DATE(ss.event_time) = DATE('{d}')
    AND DATE(ss.partitiontime) BETWEEN DATE_SUB(DATE('{d}'), INTERVAL 1 DAY)
                                   AND DATE_ADD(DATE('{d}'), INTERVAL 1 DAY)
),
sms_sends_agg AS (
  SELECT campaign_id, COUNT(DISTINCT contact_id) AS enviados
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
    AND DATE(r.event_time) BETWEEN DATE('{d}') AND DATE_ADD(DATE('{d}'), INTERVAL 7 DAY)
    AND DATE(r.partitiontime) BETWEEN DATE('{d}') AND DATE_ADD(DATE('{d}'), INTERVAL 8 DAY)
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
  WHERE DATE(r.partitiontime) BETWEEN DATE('{d}') AND DATE_ADD(DATE('{d}'), INTERVAL 8 DAY)
),
influencia_agg AS (
  SELECT
    pso.campaign_id,
    COUNT(DISTINCT pso.order_id) AS pedidos_influenciados,
    ROUND(COALESCE(SUM(p.sales_amount), 0), 2) AS receita_influenciada
  FROM post_send_orders pso
  LEFT JOIN `{project_id}.{dataset}.{si_purchases_table}` p ON p.order_id = pso.order_id
    AND DATE(p.purchase_date) BETWEEN DATE('{d}') AND DATE_ADD(DATE('{d}'), INTERVAL 7 DAY)
  GROUP BY 1
)
SELECT
  sc.nome_campanha,
  sc.campaign_id,
  COALESCE(ss.enviados, 0)             AS enviados,
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


def _build_email_apuracao_sql(nome: str, start_date: str, end_date: str) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    email_campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    email_sends_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_SENDS_TABLE)
    email_opens_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE)
    si_purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS
    safe_nome = _sanitize_campanha_nome(nome)
    s, e = start_date, end_date  # already validated ISO dates

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
  SELECT CAST(campaign_id AS STRING) AS campaign_id, COUNT(DISTINCT message_id) AS enviados
  FROM `{project_id}.{dataset}.{email_sends_table}`
  WHERE DATE(partitiontime) BETWEEN DATE('{s}') AND DATE('{e}')
    AND campaign_id IS NOT NULL AND message_id IS NOT NULL
  GROUP BY 1
),
email_opens_agg AS (
  SELECT CAST(campaign_id AS STRING) AS campaign_id, COUNT(DISTINCT message_id) AS aberturas
  FROM `{project_id}.{dataset}.{email_opens_table}`
  WHERE DATE(partitiontime) BETWEEN DATE('{s}') AND DATE('{e}')
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
    AND DATE(r.event_time) BETWEEN DATE('{s}') AND DATE_ADD(DATE('{e}'), INTERVAL 7 DAY)
    AND DATE(r.partitiontime) BETWEEN DATE('{s}') AND DATE_ADD(DATE('{e}'), INTERVAL 8 DAY)
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
  WHERE DATE(p.purchase_date) BETWEEN DATE('{s}') AND DATE_ADD(DATE('{e}'), INTERVAL 7 DAY)
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
opens_contacts AS (
  SELECT DISTINCT
    CAST(campaign_id AS STRING) AS campaign_id,
    contact_id,
    DATE(event_time) AS open_date
  FROM `{project_id}.{dataset}.{email_opens_table}`
  WHERE DATE(partitiontime) BETWEEN DATE('{s}') AND DATE('{e}')
    AND campaign_id IS NOT NULL AND contact_id IS NOT NULL
),
post_open_orders AS (
  SELECT DISTINCT oc.campaign_id, r.order_id
  FROM opens_contacts oc
  INNER JOIN `{project_id}.{dataset}.{revenue_table}` r ON r.contact_id = oc.contact_id
    AND DATE(r.event_time) BETWEEN oc.open_date AND DATE_ADD(oc.open_date, INTERVAL 7 DAY)
  WHERE DATE(r.partitiontime) BETWEEN DATE('{s}') AND DATE_ADD(DATE('{e}'), INTERVAL 8 DAY)
),
influencia_agg AS (
  SELECT
    poo.campaign_id,
    COUNT(DISTINCT poo.order_id) AS pedidos_influenciados,
    ROUND(COALESCE(SUM(p.sales_amount), 0), 2) AS receita_influenciada
  FROM post_open_orders poo
  LEFT JOIN `{project_id}.{dataset}.{si_purchases_table}` p ON p.order_id = poo.order_id
    AND DATE(p.purchase_date) BETWEEN DATE('{s}') AND DATE_ADD(DATE('{e}'), INTERVAL 7 DAY)
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
  COALESCE(itm.receita_nao_apple, 0)   AS receita_nao_apple
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
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        dispatch_date = _validate_optional_iso_date(date)
        if not dispatch_date:
            raise HTTPException(status_code=422, detail="Data de disparo invalida.")
        sql = _build_sms_apuracao_sql(nome, dispatch_date)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        items = [
            {
                "nome_campanha": str(row.get("nome_campanha") or ""),
                "campaign_id": str(row.get("campaign_id") or ""),
                "enviados": int(row.get("enviados") or 0),
                "pedidos_atribuidos": int(row.get("pedidos_atribuidos") or 0),
                "receita_atribuida": float(row.get("receita_atribuida") or 0),
                "receita_influenciada": float(row.get("receita_influenciada") or 0),
            }
            for row in records
        ]
        # Se Base Vendas BQ está configurado, pré-carrega CPFs em background para
        # que o endpoint regional responda mais rápido.
        if BASE_VENDAS_BQ_PROJECT and items:
            for item in items:
                cid_item = item.get("campaign_id")
                if cid_item:
                    ck = f"sms:{cid_item}:{dispatch_date}"
                    if _cpf_cache_get(ck) is None:
                        cpf_sql = _build_influenced_cpfs_sms_sql(cid_item, dispatch_date)
                        threading.Thread(
                            target=_prefetch_cpfs,
                            args=(ck, cpf_sql, EMARSYS_OPEN_DATA_PROJECT_ID, EMARSYS_OPEN_DATA_LOCATION or None),
                            daemon=True,
                        ).start()

        return {"items": items, "total": len(items), "nome": nome, "dispatch_date": dispatch_date}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao apurar SMS: {exc}") from exc


@router.get("/email-apuracao")
def email_apuracao(
    nome: str = Query(..., min_length=2, max_length=200),
    start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        start_date = _validate_optional_iso_date(start)
        end_date = _validate_optional_iso_date(end)
        if not start_date or not end_date:
            raise HTTPException(status_code=422, detail="Datas invalidas.")
        sql = _build_email_apuracao_sql(nome, start_date, end_date)
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        items = [
            {
                "nome_campanha": str(row.get("nome_campanha") or ""),
                "campaign_id": str(row.get("campaign_id") or ""),
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
        if BASE_VENDAS_BQ_PROJECT and items:
            for item in items:
                cid_item = item.get("campaign_id")
                if cid_item:
                    ck = f"email:{cid_item}:{start_date}:{end_date}"
                    if _cpf_cache_get(ck) is None:
                        cpf_sql = _build_influenced_cpfs_email_sql(cid_item, start_date, end_date)
                        threading.Thread(
                            target=_prefetch_cpfs,
                            args=(ck, cpf_sql, EMARSYS_OPEN_DATA_PROJECT_ID, EMARSYS_OPEN_DATA_LOCATION or None),
                            daemon=True,
                        ).start()

        return {"items": items, "total": len(items), "nome": nome, "start_date": start_date, "end_date": end_date}
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


@router.get("/emarsys/receita-atribuida-canal")
def receita_atribuida_canal(
    start: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    """Canal/filial breakdown da receita atribuída — cruzamento BigQuery CPFs × Base Vendas."""
    start_date = _validate_optional_iso_date(start)
    end_date = _validate_optional_iso_date(end)
    if not start_date or not end_date:
        raise HTTPException(status_code=400, detail="Informe data de inicio e fim.")

    try:
        # Step 1: get attributed CPFs (cache evita re-query no mesmo período)
        cache_key = f"canal_cpfs:{start_date}:{end_date}"
        attributed_cpfs = _cpf_cache_get(cache_key)
        if attributed_cpfs is None:
            sql = _build_attributed_cpfs_sql(start_date, end_date)
            cpf_records = run_bigquery_records(
                sql,
                EMARSYS_OPEN_DATA_PROJECT_ID,
                location=EMARSYS_OPEN_DATA_LOCATION or None,
                timeout=25,
            )
            attributed_cpfs = {
                str(r.get("cpf_normalized") or "")
                for r in cpf_records
                if r.get("cpf_normalized")
            }
            attributed_cpfs.discard("")
            _cpf_cache_set(cache_key, attributed_cpfs)

        if not attributed_cpfs:
            return {"canal": [], "filial": [], "total_clientes_crm": 0,
                    "matched_rows": 0, "start_date": start_date, "end_date": end_date}

        # Step 2: cross with Base Vendas via BigQuery
        if not BASE_VENDAS_BQ_PROJECT:
            raise HTTPException(status_code=500, detail="BASE_VENDAS_BQ_PROJECT nao configurado.")

        bv_sql = _build_bv_breakdown_sql(attributed_cpfs, start_date, end_date)
        bv_records = run_bigquery_records(
            bv_sql, BASE_VENDAS_BQ_PROJECT,
            location=BASE_VENDAS_BQ_LOCATION or None, timeout=25,
        )
        canal_groups: dict[str, dict[str, Any]] = {}
        filial_list = []
        matched_rows = 0
        for r in bv_records:
            canal = str(r.get("canal") or "(sem canal)").strip() or "(sem canal)"
            filial = str(r.get("codigo_filial") or "(sem filial)").strip() or "(sem filial)"
            linhas = int(r.get("linhas") or 0)
            receita = float(r.get("receita") or 0)
            matched_rows += linhas
            if canal not in canal_groups:
                canal_groups[canal] = {"canal": canal, "linhas": 0, "receita": 0.0}
            canal_groups[canal]["linhas"] += linhas
            canal_groups[canal]["receita"] += receita
            store_info = FILIAL_REGIONAL_MAP.get(filial)
            filial_list.append({
                "canal": canal,
                "codigo_filial": filial,
                "centro_sap": store_info["centro_sap"] if store_info else f"LJ{filial.zfill(3)}",
                "nome": store_info["nome"] if store_info else "",
                "regional": store_info["regional"] if store_info else "Outros",
                "linhas": linhas,
                "receita": receita,
            })
        canal_list = sorted(
            [{"canal": g["canal"], "linhas": g["linhas"], "receita": round(g["receita"], 2)}
             for g in canal_groups.values()],
            key=lambda x: -x["receita"] if x["receita"] else -x["linhas"],
        )
        filial_list.sort(key=lambda x: -x["receita"] if x["receita"] else -x["linhas"])
        revenue_column = "valor_faturamento_liquido"

        return {
            "canal": canal_list,
            "filial": filial_list,
            "total_clientes_crm": len(attributed_cpfs),
            "matched_rows": matched_rows,
            "revenue_column": revenue_column,
            "start_date": start_date,
            "end_date": end_date,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao calcular canal da receita atribuida: {exc}") from exc


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
        location=BASE_VENDAS_BQ_LOCATION or None, timeout=55,
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
    end_d = str(date.fromisoformat(d) + timedelta(days=7))
    cache_key = f"sms:{cid}:{d}"
    try:
        cpfs = _cpf_cache_get(cache_key)
        if cpfs is None:
            sql = _build_influenced_cpfs_sms_sql(cid, d)
            records = run_bigquery_records(
                sql, EMARSYS_OPEN_DATA_PROJECT_ID,
                location=EMARSYS_OPEN_DATA_LOCATION or None, timeout=25,
            )
            cpfs = {_normalize_match_key(str(r.get("cpf") or "")) for r in records if r.get("cpf")}
            cpfs.discard("")
            _cpf_cache_set(cache_key, cpfs)
        result = _cross_cpfs_regional(cpfs, d, end_d, total_influenciada=receita_influenciada)
        return {**result, "campaign_id": cid, "dispatch_date": d, "cpfs_from_cache": _cpf_cache_get(cache_key) is not None}
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
    end_extended = str(date.fromisoformat(e) + timedelta(days=7))
    cache_key = f"email:{cid}:{s}:{e}"
    try:
        cpfs = _cpf_cache_get(cache_key)
        if cpfs is None:
            sql = _build_influenced_cpfs_email_sql(cid, s, e)
            records = run_bigquery_records(
                sql, EMARSYS_OPEN_DATA_PROJECT_ID,
                location=EMARSYS_OPEN_DATA_LOCATION or None, timeout=25,
            )
            cpfs = {_normalize_match_key(str(r.get("cpf") or "")) for r in records if r.get("cpf")}
            cpfs.discard("")
            _cpf_cache_set(cache_key, cpfs)
        result = _cross_cpfs_regional(cpfs, s, end_extended, total_influenciada=receita_influenciada)
        return {**result, "campaign_id": cid, "start_date": s, "end_date": e, "cpfs_from_cache": _cpf_cache_get(cache_key) is not None}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao carregar regional e-mail: {exc}") from exc
