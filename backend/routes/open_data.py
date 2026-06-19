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

def _attributed_orders_cte(start_date: str, end_date: str) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    revenue_table = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    tz = EMARSYS_TZ
    return f"""attributed AS (
  SELECT DISTINCT r.order_id
  FROM `{project_id}.{dataset}.{revenue_table}` r
  WHERE ARRAY_LENGTH(r.treatments) > 0
    AND DATE(r.event_time, '{tz}') BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND DATE(r.partitiontime) BETWEEN DATE_SUB(DATE('{start_date}'), INTERVAL 1 DAY)
                                   AND DATE_ADD(DATE('{end_date}'), INTERVAL 1 DAY)
    AND r.order_id IS NOT NULL
)"""


def _build_atribuida_top_produtos_sql(start_date: str, end_date: str) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    cte = _attributed_orders_cte(start_date, end_date)
    return f"""
WITH {cte}
SELECT
  COALESCE(NULLIF(TRIM(p.product_name), ''), 'Sem nome') AS produto,
  COUNT(DISTINCT p.order_id)                             AS pedidos,
  ROUND(SUM(p.sales_amount), 2)                         AS receita
FROM `{project_id}.{dataset}.{purchases_table}` p
INNER JOIN attributed a ON a.order_id = p.order_id
WHERE p.sales_amount > 0
GROUP BY 1
ORDER BY receita DESC
LIMIT 10
""".strip()


def _build_atribuida_top_categorias_sql(start_date: str, end_date: str) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    cte = _attributed_orders_cte(start_date, end_date)
    return f"""
WITH
{cte},
categorized AS (
  SELECT
    CASE
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(p.product_name,'')), r'IPHONE')                        THEN 'iPhone'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(p.product_name,'')), r'IPAD')                          THEN 'iPad'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(p.product_name,'')), r'MACBOOK|IMAC|MAC MINI|MAC PRO|MAC STUDIO') THEN 'Mac'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(p.product_name,'')), r'APPLE WATCH')                   THEN 'Apple Watch'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(p.product_name,'')), r'AIRPOD')                        THEN 'AirPods'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(p.product_name,'')), r'APPLE TV|APPLETV|HOMEPOD')      THEN 'Apple TV / HomePod'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(p.product_name,'')), r'SAMSUNG')                       THEN 'Samsung'
      WHEN REGEXP_CONTAINS(UPPER(COALESCE(p.product_name,'')), r'XIAOMI|MOTOROLA|LG |SONY|PHILIPS|BOSE|BEATS|JABRA|JBL') THEN 'Outras Marcas'
      ELSE 'Acessórios / Outros'
    END AS categoria,
    p.order_id,
    p.sales_amount
  FROM `{project_id}.{dataset}.{purchases_table}` p
  INNER JOIN attributed a ON a.order_id = p.order_id
  WHERE p.sales_amount > 0
)
SELECT
  categoria,
  COUNT(DISTINCT order_id) AS pedidos,
  ROUND(SUM(sales_amount), 2) AS receita
FROM categorized
GROUP BY 1
ORDER BY receita DESC
""".strip()


@router.get("/emarsys/atribuida-top-produtos")
def atribuida_top_produtos(
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> list[dict]:
    start_date = _validate_optional_iso_date(start) or str(date.today())
    end_date = _validate_optional_iso_date(end) or start_date
    try:
        sql = _build_atribuida_top_produtos_sql(start_date, end_date)
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
) -> list[dict]:
    start_date = _validate_optional_iso_date(start) or str(date.today())
    end_date = _validate_optional_iso_date(end) or start_date
    try:
        sql = _build_atribuida_top_categorias_sql(start_date, end_date)
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


def _build_acessorios_matriz_sql(start_date: str, end_date: str, canal_order_ids: list | None = None) -> str:
    """Retorna attach rate por linha Apple × categoria de acessório (apple e parceiro) + pool de oportunidade."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    pt = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)

    if canal_order_ids is not None:
        if canal_order_ids:
            ids_literal = ", ".join(f"'{str(oid).replace(chr(39), '')}'" for oid in canal_order_ids)
            order_id_filter = f"AND CAST(order_id AS STRING) IN UNNEST([{ids_literal}])"
        else:
            order_id_filter = "AND FALSE"
    else:
        order_id_filter = ""

    return f"""
WITH
-- Dispositivos Apple comprados no período (denominador)
apple_devices AS (
  SELECT
    CAST(si_contact_id AS STRING) AS si_contact_id,
    CAST(order_id AS STRING)      AS order_id,
    DATE(purchase_date)           AS purchase_date,
    CASE
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'IPHONE')                                   THEN 'iPhone'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'IPAD')                                     THEN 'iPad'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'MACBOOK|IMAC|MAC MINI|MAC PRO|MAC STUDIO') THEN 'Mac'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'APPLE WATCH')                              THEN 'Apple Watch'
    END AS linha_apple
  FROM `{project_id}.{dataset}.{pt}`
  WHERE DATE(purchase_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND sales_amount > 0
    {order_id_filter}
    AND REGEXP_CONTAINS(UPPER(COALESCE(product_name,'')),
          r'IPHONE|IPAD|MACBOOK|IMAC|MAC MINI|MAC PRO|MAC STUDIO|APPLE WATCH')
),
-- Um registro por (contato, linha Apple) — primeiro pedido como referência
apple_por_contato AS (
  SELECT
    si_contact_id,
    linha_apple,
    ARRAY_AGG(order_id ORDER BY purchase_date LIMIT 1)[SAFE_OFFSET(0)] AS first_order_id,
    MIN(purchase_date) AS first_purchase_date
  FROM apple_devices
  GROUP BY 1, 2
),
-- Denominadores
total_por_linha AS (
  SELECT linha_apple, COUNT(DISTINCT si_contact_id) AS total_clientes
  FROM apple_por_contato
  GROUP BY 1
),
-- Acessórios Apple (janela estendida: período + 30 dias)
apple_acc AS (
  SELECT
    CAST(si_contact_id AS STRING) AS si_contact_id,
    CAST(order_id AS STRING)      AS order_id,
    DATE(purchase_date)           AS purchase_date,
    CASE
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'AIRPOD')                                            THEN 'AirPods'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'AIRTAG|AIR TAG')                                    THEN 'AirTag'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'EARPODS')                                           THEN 'EarPods'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'MAGSAFE')                                           THEN 'MagSafe'
      WHEN UPPER(product_name) LIKE '%MAGIC MOUSE%'                                                   THEN 'Magic Mouse'
      WHEN UPPER(product_name) LIKE '%MAGIC KEYBOARD%'                                                THEN 'Magic Keyboard'
      WHEN UPPER(product_name) LIKE '%CABO%' AND UPPER(product_name) LIKE '%APPLE%'                  THEN 'Cabo Apple'
      WHEN UPPER(product_name) LIKE '%CARREGADOR%' AND UPPER(product_name) LIKE '%APPLE%'            THEN 'Carregador Apple'
    END AS categoria
  FROM `{project_id}.{dataset}.{pt}`
  WHERE DATE(purchase_date) BETWEEN DATE('{start_date}') AND DATE_ADD(DATE('{end_date}'), INTERVAL 30 DAY)
    AND sales_amount > 0
    AND (
      REGEXP_CONTAINS(UPPER(COALESCE(product_name,'')), r'AIRPOD|AIRTAG|AIR TAG|EARPODS|MAGSAFE|MAGIC MOUSE|MAGIC KEYBOARD')
      OR (UPPER(COALESCE(product_name,'')) LIKE '%CABO%'        AND UPPER(COALESCE(product_name,'')) LIKE '%APPLE%')
      OR (UPPER(COALESCE(product_name,'')) LIKE '%CARREGADOR%'  AND UPPER(COALESCE(product_name,'')) LIKE '%APPLE%')
    )
),
-- Acessórios parceiros: JBL, Logitech, Originais iPlace (janela estendida)
partner_acc AS (
  SELECT
    CAST(si_contact_id AS STRING) AS si_contact_id,
    CAST(order_id AS STRING)      AS order_id,
    DATE(purchase_date)           AS purchase_date,
    CASE
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'CARREGADOR')                          THEN 'Carregador'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'\\bCABO\\b')                           THEN 'Cabo'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'CAIXA DE SOM|SOUNDBAR')              THEN 'Caixa de Som'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'FONE DE OUVIDO|EARPODS|HEADPHONE|ON-EAR|OVER-EAR') THEN 'Fone'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'\\bMOUSE\\b')                         THEN 'Mouse'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'TECLADO|KEYBOARD')                   THEN 'Teclado'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'PELICULA|PELÍCULA')                  THEN 'Película'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'ADAPTADOR')                          THEN 'Adaptador'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'\\bCANETA\\b')                        THEN 'Caneta'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'\\bCAPA\\b|\\bCASE\\b')               THEN 'Capa/Case'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'\\bPULSEIRA\\b')                      THEN 'Pulseira'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'BOLSA|MOCHILA|\\bMALA\\b|\\bSLEEVE\\b') THEN 'Bolsa/Mochila'
      ELSE 'Outros'
    END AS categoria
  FROM `{project_id}.{dataset}.{pt}`
  WHERE DATE(purchase_date) BETWEEN DATE('{start_date}') AND DATE_ADD(DATE('{end_date}'), INTERVAL 30 DAY)
    AND sales_amount > 0
    AND (
      UPPER(COALESCE(product_name,'')) LIKE '%JBL%'
      OR UPPER(COALESCE(product_name,'')) LIKE '%LOGITECH%'
      OR UPPER(COALESCE(product_name,'')) LIKE '%ORIGINAIS IPLACE%'
    )
),
-- Matriz unificada: attach por linha × categoria × grupo
matrix_raw AS (
  SELECT
    apc.linha_apple,
    acc.categoria,
    acc.grupo,
    COUNT(DISTINCT CASE
      WHEN acc.order_id = apc.first_order_id THEN apc.si_contact_id
    END) AS clientes_mesmo_pedido,
    COUNT(DISTINCT CASE
      WHEN acc.order_id != apc.first_order_id
       AND acc.purchase_date > apc.first_purchase_date
       AND acc.purchase_date <= DATE_ADD(apc.first_purchase_date, INTERVAL 30 DAY)
      THEN apc.si_contact_id
    END) AS clientes_janela
  FROM apple_por_contato apc
  JOIN (
    SELECT si_contact_id, order_id, purchase_date, categoria, 'apple' AS grupo
    FROM apple_acc WHERE categoria IS NOT NULL
    UNION ALL
    SELECT si_contact_id, order_id, purchase_date, categoria, 'parceiro' AS grupo
    FROM partner_acc
  ) acc ON acc.si_contact_id = apc.si_contact_id
  GROUP BY 1, 2, 3
),
matrix AS (
  SELECT
    mr.linha_apple,
    mr.categoria,
    mr.grupo,
    mr.clientes_mesmo_pedido,
    mr.clientes_janela,
    tpl.total_clientes,
    ROUND(mr.clientes_mesmo_pedido * 100.0 / NULLIF(tpl.total_clientes, 0), 1) AS rate_mesmo_pedido,
    ROUND(mr.clientes_janela       * 100.0 / NULLIF(tpl.total_clientes, 0), 1) AS rate_janela
  FROM matrix_raw mr
  JOIN total_por_linha tpl ON tpl.linha_apple = mr.linha_apple
),
-- Pool de oportunidade: compradores Apple SEM nenhum acessório
todos_acc_contatos AS (
  SELECT DISTINCT si_contact_id FROM apple_acc WHERE categoria IS NOT NULL
  UNION DISTINCT
  SELECT DISTINCT si_contact_id FROM partner_acc
),
oportunidade AS (
  SELECT
    apc.linha_apple,
    COUNT(DISTINCT apc.si_contact_id)  AS sem_acessorio,
    ANY_VALUE(tpl.total_clientes)      AS total_clientes,
    ROUND(COUNT(DISTINCT apc.si_contact_id) * 100.0 / NULLIF(ANY_VALUE(tpl.total_clientes), 0), 1) AS pct_sem_acessorio
  FROM apple_por_contato apc
  JOIN total_por_linha tpl ON tpl.linha_apple = apc.linha_apple
  LEFT JOIN todos_acc_contatos tac ON tac.si_contact_id = apc.si_contact_id
  WHERE tac.si_contact_id IS NULL
  GROUP BY 1
),
-- Segmentos: flags por contato (janela 30 dias)
all_relevant_contacts AS (
  SELECT DISTINCT si_contact_id FROM apple_por_contato
  UNION DISTINCT
  SELECT si_contact_id FROM apple_acc WHERE categoria IS NOT NULL
  UNION DISTINCT
  SELECT si_contact_id FROM partner_acc
),
contact_flags AS (
  SELECT
    c.si_contact_id,
    CASE WHEN d.si_contact_id IS NOT NULL THEN 1 ELSE 0 END AS has_device,
    CASE WHEN a.si_contact_id IS NOT NULL THEN 1 ELSE 0 END AS has_apple_acc,
    CASE WHEN p.si_contact_id IS NOT NULL THEN 1 ELSE 0 END AS has_partner_acc
  FROM all_relevant_contacts c
  LEFT JOIN (SELECT DISTINCT si_contact_id FROM apple_por_contato) d ON d.si_contact_id = c.si_contact_id
  LEFT JOIN (SELECT DISTINCT si_contact_id FROM apple_acc WHERE categoria IS NOT NULL) a ON a.si_contact_id = c.si_contact_id
  LEFT JOIN (SELECT DISTINCT si_contact_id FROM partner_acc) p ON p.si_contact_id = c.si_contact_id
),
segmentos_agg AS (
  SELECT
    CASE
      WHEN has_device=1 AND has_apple_acc=0 AND has_partner_acc=0 THEN 'Device Apple + Sem acessório'
      WHEN has_device=0 AND has_apple_acc=1 AND has_partner_acc=0 THEN 'Somente acess. Apple (sem device)'
      WHEN has_device=0 AND has_apple_acc=0 AND has_partner_acc=1 THEN 'Somente acess. parceiros (sem device)'
      WHEN has_device=1 AND has_apple_acc=1 AND has_partner_acc=0 THEN 'Device Apple + Acess. Apple'
      WHEN has_device=1 AND has_apple_acc=0 AND has_partner_acc=1 THEN 'Device Apple + Acess. parceiros'
      WHEN has_device=1 AND has_apple_acc=1 AND has_partner_acc=1 THEN 'Device Apple + Acess. Apple + Parceiros'
      WHEN has_device=0 AND has_apple_acc=1 AND has_partner_acc=1 THEN 'Somente acess. Apple + Parceiros (sem device)'
    END AS segmento,
    COUNT(*) AS clientes
  FROM contact_flags
  GROUP BY 1
),
segmentos_total AS (
  SELECT SUM(clientes) AS total FROM segmentos_agg WHERE segmento IS NOT NULL
)
-- Resultado: linhas de matriz + linhas de oportunidade (grupo = 'oportunidade') + totais + segmentos
SELECT linha_apple, categoria, grupo,
       clientes_mesmo_pedido, clientes_janela, total_clientes,
       rate_mesmo_pedido, rate_janela
FROM matrix
UNION ALL
SELECT linha_apple,
       'OPORTUNIDADE' AS categoria,
       'oportunidade' AS grupo,
       sem_acessorio  AS clientes_mesmo_pedido,
       0              AS clientes_janela,
       total_clientes,
       pct_sem_acessorio AS rate_mesmo_pedido,
       0              AS rate_janela
FROM oportunidade
UNION ALL
SELECT linha_apple,
       'TOTAL'        AS categoria,
       'total'        AS grupo,
       total_clientes AS clientes_mesmo_pedido,
       0, total_clientes, 100.0, 0
FROM total_por_linha
UNION ALL
SELECT
  s.segmento        AS linha_apple,
  'SEGMENTO'        AS categoria,
  'segmento'        AS grupo,
  s.clientes        AS clientes_mesmo_pedido,
  0                 AS clientes_janela,
  t.total           AS total_clientes,
  ROUND(s.clientes * 100.0 / NULLIF(t.total, 0), 1) AS rate_mesmo_pedido,
  0                 AS rate_janela
FROM segmentos_agg s
CROSS JOIN segmentos_total t
WHERE s.segmento IS NOT NULL
ORDER BY linha_apple, grupo, categoria
""".strip()


def _build_acessorios_marcas_sql(start_date: str, end_date: str, canal_order_ids: list | None = None) -> str:
    """Retorna cards de marca (JBL/Logitech/Originais iPlace) com CRM e top produtos."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    pt = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    rt = _quote_identifier(EMARSYS_OPEN_DATA_REVENUE_ATTRIBUTION_TABLE)
    lookback = EMARSYS_OPEN_DATA_LOOKBACK_DAYS

    if canal_order_ids is not None:
        if canal_order_ids:
            ids_literal = ", ".join(f"'{str(oid).replace(chr(39), '')}'" for oid in canal_order_ids)
            order_id_filter = f"AND CAST(order_id AS STRING) IN UNNEST([{ids_literal}])"
        else:
            order_id_filter = "AND FALSE"
    else:
        order_id_filter = ""

    return f"""
WITH
brand_items AS (
  SELECT
    CAST(order_id AS STRING)      AS order_id,
    CAST(si_contact_id AS STRING) AS si_contact_id,
    COALESCE(NULLIF(TRIM(product_name),''), 'Sem nome') AS product_name,
    sales_amount,
    CASE
      WHEN UPPER(product_name) LIKE '%JBL%'              THEN 'JBL'
      WHEN UPPER(product_name) LIKE '%LOGITECH%'          THEN 'Logitech'
      WHEN UPPER(product_name) LIKE '%ORIGINAIS IPLACE%' THEN 'Originais iPlace'
    END AS marca
  FROM `{project_id}.{dataset}.{pt}`
  WHERE DATE(purchase_date) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    {order_id_filter}
    AND sales_amount > 0
    AND (
      UPPER(COALESCE(product_name,'')) LIKE '%JBL%'
      OR UPPER(COALESCE(product_name,'')) LIKE '%LOGITECH%'
      OR UPPER(COALESCE(product_name,'')) LIKE '%ORIGINAIS IPLACE%'
    )
),
por_marca AS (
  SELECT marca, COUNT(DISTINCT order_id) AS pedidos, COUNT(*) AS itens, ROUND(SUM(sales_amount),2) AS receita
  FROM brand_items GROUP BY 1
),
attr_orders AS (
  SELECT DISTINCT CAST(r.order_id AS STRING) AS order_id
  FROM `{project_id}.{dataset}.{rt}` r
  CROSS JOIN UNNEST(r.treatments) AS t
  WHERE DATE(r.partitiontime) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback} DAY)
    AND t.attributed_amount > 0
    AND DATE(r.event_time, 'America/Sao_Paulo') BETWEEN DATE('{start_date}') AND DATE('{end_date}')
),
crm_por_marca AS (
  SELECT bi.marca, COUNT(DISTINCT bi.order_id) AS pedidos_crm, ROUND(SUM(bi.sales_amount),2) AS receita_crm
  FROM brand_items bi INNER JOIN attr_orders ao ON ao.order_id = bi.order_id
  GROUP BY 1
),
top_jbl AS (
  SELECT product_name AS nome, COUNT(*) AS qtd, ROUND(SUM(sales_amount),2) AS receita
  FROM brand_items WHERE marca = 'JBL' GROUP BY 1
),
top_log AS (
  SELECT product_name AS nome, COUNT(*) AS qtd, ROUND(SUM(sales_amount),2) AS receita
  FROM brand_items WHERE marca = 'Logitech' GROUP BY 1
),
top_ori AS (
  SELECT product_name AS nome, COUNT(*) AS qtd, ROUND(SUM(sales_amount),2) AS receita
  FROM brand_items WHERE marca = 'Originais iPlace' GROUP BY 1
)
SELECT
  pm.marca, pm.pedidos, pm.itens, pm.receita,
  COALESCE(cpm.pedidos_crm, 0) AS pedidos_crm,
  COALESCE(cpm.receita_crm, 0) AS receita_crm,
  (SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(nome,qtd,receita) ORDER BY qtd DESC LIMIT 10)) FROM top_jbl)  AS top_jbl_json,
  (SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(nome,qtd,receita) ORDER BY qtd DESC LIMIT 10)) FROM top_log)  AS top_log_json,
  (SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(nome,qtd,receita) ORDER BY receita DESC LIMIT 10)) FROM top_jbl)  AS top_jbl_receita_json,
  (SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(nome,qtd,receita) ORDER BY receita DESC LIMIT 10)) FROM top_log)  AS top_log_receita_json,
  (SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(nome,qtd,receita) ORDER BY qtd DESC LIMIT 10)) FROM top_ori)  AS top_ori_json,
  (SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(nome,qtd,receita) ORDER BY receita DESC LIMIT 10)) FROM top_ori)  AS top_ori_receita_json
FROM por_marca pm
LEFT JOIN crm_por_marca cpm ON cpm.marca = pm.marca
ORDER BY pm.receita DESC
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

        # Step 1: fetch order_ids from vendas project (different BQ location — cannot JOIN inline)
        canal_order_ids: list | None = None
        if canal_filter and BASE_VENDAS_BQ_PROJECT:
            safe_canal = canal_filter.replace("'", "''")
            sql_canal = f"""
SELECT DISTINCT CAST(Numero_Pedido AS STRING) AS order_id
FROM `{BASE_VENDAS_BQ_PROJECT}.{VENDAS_BQ_DATASET}.{VENDAS_BQ_TABLE}`
WHERE UPPER(TRIM(Canal)) = '{safe_canal}'
  AND Data_Completa BETWEEN '{s}' AND '{e}'
"""
            canal_records = run_bigquery_records(sql_canal, BASE_VENDAS_BQ_PROJECT, location=None)
            canal_order_ids = [str(r["order_id"]) for r in canal_records if r.get("order_id")]

        # Step 2: run Emarsys queries filtered by pre-fetched order_ids
        sql_matriz = _build_acessorios_matriz_sql(s, e, canal_order_ids)
        sql_marcas = _build_acessorios_marcas_sql(s, e, canal_order_ids)
        matriz_records = run_bigquery_records(sql_matriz, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        marcas_records = run_bigquery_records(sql_marcas, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)

        # Parse matrix rows by grupo
        matrix_apple, matrix_parceiro, oportunidade, total_por_linha, segmentos = [], [], [], [], []
        for row in matriz_records:
            grupo = str(row.get("grupo") or "")
            item = {
                "linha_apple":           str(row.get("linha_apple") or ""),
                "categoria":             str(row.get("categoria") or ""),
                "clientes_mesmo_pedido": int(row.get("clientes_mesmo_pedido") or 0),
                "clientes_janela":       int(row.get("clientes_janela") or 0),
                "total_clientes":        int(row.get("total_clientes") or 0),
                "rate_mesmo_pedido":     float(row.get("rate_mesmo_pedido") or 0),
                "rate_janela":           float(row.get("rate_janela") or 0),
            }
            if grupo == "apple":
                matrix_apple.append(item)
            elif grupo == "parceiro":
                matrix_parceiro.append(item)
            elif grupo == "oportunidade":
                oportunidade.append({
                    "linha_apple":     item["linha_apple"],
                    "sem_acessorio":   item["clientes_mesmo_pedido"],
                    "total_clientes":  item["total_clientes"],
                    "pct_sem_acessorio": item["rate_mesmo_pedido"],
                })
            elif grupo == "total":
                total_por_linha.append({
                    "linha_apple":   item["linha_apple"],
                    "total_clientes": item["total_clientes"],
                })
            elif grupo == "segmento":
                segmentos.append({
                    "segmento":   item["linha_apple"],
                    "clientes":   item["clientes_mesmo_pedido"],
                    "total":      item["total_clientes"],
                    "pct":        item["rate_mesmo_pedido"],
                })

        # Parse brand cards
        por_marca = []
        top_jbl_qtd, top_jbl_rec, top_log_qtd, top_log_rec, top_ori_qtd, top_ori_rec = [], [], [], [], [], []
        for row in marcas_records:
            por_marca.append({
                "marca":      str(row.get("marca") or ""),
                "pedidos":    int(row.get("pedidos") or 0),
                "itens":      int(row.get("itens") or 0),
                "receita":    float(row.get("receita") or 0),
                "pedidos_crm": int(row.get("pedidos_crm") or 0),
                "receita_crm": float(row.get("receita_crm") or 0),
            })
        first = marcas_records[0] if marcas_records else {}
        top_jbl_qtd  = _json.loads(first.get("top_jbl_json") or "[]")
        top_jbl_rec  = _json.loads(first.get("top_jbl_receita_json") or "[]")
        top_log_qtd  = _json.loads(first.get("top_log_json") or "[]")
        top_log_rec  = _json.loads(first.get("top_log_receita_json") or "[]")
        top_ori_qtd  = _json.loads(first.get("top_ori_json") or "[]")
        top_ori_rec  = _json.loads(first.get("top_ori_receita_json") or "[]")

        # Ordem de exibição dos segmentos
        SEG_ORDER = [
            'Device Apple + Sem acessório',
            'Device Apple + Acess. Apple',
            'Device Apple + Acess. parceiros',
            'Device Apple + Acess. Apple + Parceiros',
            'Somente acess. Apple (sem device)',
            'Somente acess. parceiros (sem device)',
            'Somente acess. Apple + Parceiros (sem device)',
        ]
        segmentos.sort(key=lambda x: SEG_ORDER.index(x['segmento']) if x['segmento'] in SEG_ORDER else 99)

        return {
            "matrix_apple":    matrix_apple,
            "matrix_parceiro": matrix_parceiro,
            "oportunidade":    oportunidade,
            "total_por_linha": total_por_linha,
            "segmentos":       segmentos,
            "por_marca":       por_marca,
            "top_produtos": {
                "JBL":               {"qtd": top_jbl_qtd, "receita": top_jbl_rec},
                "Logitech":          {"qtd": top_log_qtd, "receita": top_log_rec},
                "Originais iPlace":  {"qtd": top_ori_qtd, "receita": top_ori_rec},
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
    """Retorna lista de contatos Apple sem acessório (com CPF) para disparo CRM."""
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    pt  = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)
    ct  = _quote_identifier(EMARSYS_OPEN_DATA_SI_CONTACTS_TABLE)
    try:
        s = _validate_optional_iso_date(start) or start
        e = _validate_optional_iso_date(end) or end
        linha_filter = f"AND linha_apple = '{linha}'" if linha.strip() else ""
        sql = f"""
WITH
apple_devices AS (
  SELECT
    CAST(si_contact_id AS STRING) AS si_contact_id,
    CAST(order_id AS STRING)      AS order_id,
    DATE(purchase_date)           AS purchase_date,
    CASE
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'IPHONE')                                   THEN 'iPhone'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'IPAD')                                     THEN 'iPad'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'MACBOOK|IMAC|MAC MINI|MAC PRO|MAC STUDIO') THEN 'Mac'
      WHEN REGEXP_CONTAINS(UPPER(product_name), r'APPLE WATCH')                              THEN 'Apple Watch'
    END AS linha_apple
  FROM `{project_id}.{dataset}.{pt}`
  WHERE DATE(purchase_date) BETWEEN DATE('{s}') AND DATE('{e}')
    AND sales_amount > 0
    AND REGEXP_CONTAINS(UPPER(COALESCE(product_name,'')),
          r'IPHONE|IPAD|MACBOOK|IMAC|MAC MINI|MAC PRO|MAC STUDIO|APPLE WATCH')
),
apple_por_contato AS (
  SELECT si_contact_id, linha_apple, MIN(purchase_date) AS purchase_date
  FROM apple_devices GROUP BY 1, 2
),
todos_acc AS (
  SELECT DISTINCT CAST(si_contact_id AS STRING) AS si_contact_id
  FROM `{project_id}.{dataset}.{pt}`
  WHERE DATE(purchase_date) BETWEEN DATE('{s}') AND DATE_ADD(DATE('{e}'), INTERVAL 30 DAY)
    AND sales_amount > 0
    AND (
      REGEXP_CONTAINS(UPPER(COALESCE(product_name,'')), r'AIRPOD|AIRTAG|EARPODS|MAGSAFE|MAGIC MOUSE|MAGIC KEYBOARD')
      OR (UPPER(COALESCE(product_name,'')) LIKE '%CABO%'       AND UPPER(COALESCE(product_name,'')) LIKE '%APPLE%')
      OR (UPPER(COALESCE(product_name,'')) LIKE '%CARREGADOR%' AND UPPER(COALESCE(product_name,'')) LIKE '%APPLE%')
      OR UPPER(COALESCE(product_name,'')) LIKE '%JBL%'
      OR UPPER(COALESCE(product_name,'')) LIKE '%LOGITECH%'
      OR UPPER(COALESCE(product_name,'')) LIKE '%ORIGINAIS IPLACE%'
    )
)
SELECT
  apc.si_contact_id,
  CAST(c.external_id AS STRING) AS cpf,
  apc.linha_apple,
  CAST(apc.purchase_date AS STRING) AS purchase_date
FROM apple_por_contato apc
LEFT JOIN todos_acc ta ON ta.si_contact_id = apc.si_contact_id
LEFT JOIN `{project_id}.{dataset}.{ct}` c ON CAST(c.si_contact_id AS STRING) = apc.si_contact_id
WHERE ta.si_contact_id IS NULL
  {linha_filter}
ORDER BY apc.linha_apple, apc.purchase_date
LIMIT 50000
""".strip()
        records = run_bigquery_records(sql, EMARSYS_OPEN_DATA_PROJECT_ID, location=EMARSYS_OPEN_DATA_LOCATION or None)
        items = [
            {
                "si_contact_id": str(r.get("si_contact_id") or ""),
                "cpf":           str(r.get("cpf") or ""),
                "linha_apple":   str(r.get("linha_apple") or ""),
                "purchase_date": str(r.get("purchase_date") or ""),
            }
            for r in records
        ]
        return {"items": items, "total": len(items), "start_date": s, "end_date": e}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao exportar oportunidade: {exc}") from exc
