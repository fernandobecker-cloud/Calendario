"""Open data routes for BigQuery-backed sources."""

from __future__ import annotations

import os
from datetime import date, datetime
import re
from typing import Any

from fastapi import APIRouter, Query
from fastapi import HTTPException

from backend.event_sources import run_bigquery_records

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
    partitiontime_filter = ""
    if "partitiontime" in {column.lower() for column in column_names}:
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
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    sends_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_SENDS_TABLE)
    purchases_table = _quote_identifier(EMARSYS_OPEN_DATA_SI_PURCHASES_TABLE)

    safe_program_ids = [str(pid).strip() for pid in program_ids if str(pid).strip()]
    if not safe_program_ids:
        raise ValueError("Informe ao menos um program_id")

    program_id_values = ", ".join(f"'{pid}'" for pid in safe_program_ids)
    campaigns_filter = f"partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"
    activity_filter = _build_partitiontime_filter(start_date, end_date)

    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)
    if normalized_start and normalized_end:
        purchase_date_filter = f"DATE(p.purchase_date) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
    elif normalized_start:
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE('{normalized_start}')"
    elif normalized_end:
        purchase_date_filter = f"DATE(p.purchase_date) <= DATE('{normalized_end}')"
    else:
        purchase_date_filter = "p.purchase_date IS NOT NULL"

    return f"""
WITH campaign_programs AS (
  SELECT DISTINCT
    CAST(id AS STRING) AS campaign_id,
    CAST(COALESCE(program_id, 0) AS STRING) AS program_id
  FROM `{project_id}.{dataset}.{campaigns_table}`
  WHERE {campaigns_filter}
    AND program_id IS NOT NULL
    AND CAST(COALESCE(program_id, 0) AS STRING) IN ({program_id_values})
),
program_contacts AS (
  SELECT DISTINCT cp.program_id, CAST(s.contact_id AS STRING) AS contact_id
  FROM `{project_id}.{dataset}.{sends_table}` s
  JOIN campaign_programs cp ON CAST(s.campaign_id AS STRING) = cp.campaign_id
  WHERE {activity_filter}
    AND s.contact_id IS NOT NULL
),
program_revenue AS (
  SELECT
    pc.program_id,
    COALESCE(SUM(p.sales_amount), 0) AS receita
  FROM program_contacts pc
  LEFT JOIN `{project_id}.{dataset}.{purchases_table}` p
    ON CAST(p.si_contact_id AS STRING) = pc.contact_id
    AND {purchase_date_filter}
  GROUP BY 1
)
SELECT program_id, receita FROM program_revenue
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

    # event_time = data do pedido; partitiontime = data de carga (até ~7 dias de delay).
    # Filtramos por event_time para precisão e por partitiontime para eficiência de custo.
    if normalized_start and normalized_end:
        event_time_filter = f"DATE(event_time) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        partition_filter = f"DATE(partitiontime) BETWEEN DATE('{normalized_start}') AND DATE_ADD(DATE('{normalized_end}'), INTERVAL 7 DAY)"
    elif normalized_start:
        event_time_filter = f"DATE(event_time) >= DATE('{normalized_start}')"
        partition_filter = f"DATE(partitiontime) >= DATE('{normalized_start}')"
    elif normalized_end:
        event_time_filter = f"DATE(event_time) <= DATE('{normalized_end}')"
        partition_filter = f"DATE(partitiontime) <= DATE_ADD(DATE('{normalized_end}'), INTERVAL 7 DAY)"
    else:
        event_time_filter = f"DATE(event_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"
        partition_filter = f"partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS + 7} DAY)"

    return f"""
WITH attributed_orders AS (
  SELECT DISTINCT
    FORMAT_DATE('%Y-%m', DATE(event_time)) AS mes,
    order_id,
    contact_id,
    (SELECT COALESCE(SUM(i.price * i.quantity), 0) FROM UNNEST(items) AS i) AS valor_pedido
  FROM `{project_id}.{dataset}.{revenue_table}`
  WHERE ARRAY_LENGTH(treatments) > 0
    AND event_time IS NOT NULL
    AND {event_time_filter}
    AND {partition_filter}
)
SELECT
  mes,
  SUM(valor_pedido) AS receita_atribuida,
  COUNT(DISTINCT order_id) AS pedidos_atribuidos,
  COUNT(DISTINCT contact_id) AS compradores_unicos
FROM attributed_orders
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

    if normalized_start and normalized_end:
        event_time_filter = f"DATE(r.event_time) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        partition_filter = f"DATE(r.partitiontime) BETWEEN DATE('{normalized_start}') AND DATE_ADD(DATE('{normalized_end}'), INTERVAL 7 DAY)"
    elif normalized_start:
        event_time_filter = f"DATE(r.event_time) >= DATE('{normalized_start}')"
        partition_filter = f"DATE(r.partitiontime) >= DATE('{normalized_start}')"
    elif normalized_end:
        event_time_filter = f"DATE(r.event_time) <= DATE('{normalized_end}')"
        partition_filter = f"DATE(r.partitiontime) <= DATE_ADD(DATE('{normalized_end}'), INTERVAL 7 DAY)"
    else:
        event_time_filter = f"DATE(r.event_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"
        partition_filter = f"r.partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS + 7} DAY)"

    return f"""
SELECT
  FORMAT_DATE('%Y-%m', DATE(r.event_time)) AS mes,
  LOWER(t.channel) AS canal,
  ROUND(SUM(t.attributed_amount), 2) AS receita_atribuida,
  COUNT(DISTINCT r.order_id) AS pedidos_atribuidos,
  COUNT(DISTINCT r.contact_id) AS compradores_unicos
FROM `{project_id}.{dataset}.{revenue_table}` r
CROSS JOIN UNNEST(r.treatments) AS t
WHERE ARRAY_LENGTH(r.treatments) > 0
  AND r.event_time IS NOT NULL
  AND t.attributed_amount > 0
  AND {event_time_filter}
  AND {partition_filter}
GROUP BY mes, canal
ORDER BY mes, canal
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


def _build_attribution_date_filters(
    start_date: str | None,
    end_date: str | None,
    table_alias: str = "r",
) -> tuple[str, str]:
    """Returns (event_time_filter, partition_filter) for revenue_attribution queries."""
    normalized_start = _validate_optional_iso_date(start_date)
    normalized_end = _validate_optional_iso_date(end_date)
    p = f"{table_alias}.partitiontime" if table_alias else "partitiontime"
    e = f"DATE({table_alias}.event_time)" if table_alias else "DATE(event_time)"

    if normalized_start and normalized_end:
        event_time_filter = f"{e} BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        partition_filter = f"DATE({p}) BETWEEN DATE('{normalized_start}') AND DATE_ADD(DATE('{normalized_end}'), INTERVAL 7 DAY)"
    elif normalized_start:
        event_time_filter = f"{e} >= DATE('{normalized_start}')"
        partition_filter = f"DATE({p}) >= DATE('{normalized_start}')"
    elif normalized_end:
        event_time_filter = f"{e} <= DATE('{normalized_end}')"
        partition_filter = f"DATE({p}) <= DATE_ADD(DATE('{normalized_end}'), INTERVAL 7 DAY)"
    else:
        event_time_filter = f"{e} >= DATE_SUB(CURRENT_DATE(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"
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
        attr_event_time_filter = f"DATE(r.event_time) BETWEEN DATE('{normalized_start}') AND DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) BETWEEN DATE('{normalized_start}') AND DATE_ADD(DATE('{normalized_end}'), INTERVAL 7 DAY)"
        touch_partition_start = f"DATE_SUB(DATE('{normalized_start}'), INTERVAL 7 DAY)"
        touch_partition_end = f"DATE('{normalized_end}')"
    elif normalized_start:
        purchase_date_filter = f"DATE(p.purchase_date) >= DATE('{normalized_start}')"
        attr_event_time_filter = f"DATE(r.event_time) >= DATE('{normalized_start}')"
        attr_partition_filter = f"DATE(r.partitiontime) >= DATE('{normalized_start}')"
        touch_partition_start = f"DATE_SUB(DATE('{normalized_start}'), INTERVAL 7 DAY)"
        touch_partition_end = "CURRENT_DATE()"
    elif normalized_end:
        purchase_date_filter = f"DATE(p.purchase_date) <= DATE('{normalized_end}')"
        attr_event_time_filter = f"DATE(r.event_time) <= DATE('{normalized_end}')"
        attr_partition_filter = f"DATE(r.partitiontime) <= DATE_ADD(DATE('{normalized_end}'), INTERVAL 7 DAY)"
        touch_partition_start = f"DATE_SUB(CURRENT_DATE(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS + 7} DAY)"
        touch_partition_end = f"DATE('{normalized_end}')"
    else:
        purchase_date_filter = "p.purchase_date IS NOT NULL"
        attr_event_time_filter = f"DATE(r.event_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)"
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
                # Box 2 — attributed by Emarsys (attributed_amount from revenue_attribution)
                "atribuida_receita": round(_atribuida_val("atribuida"), 2),
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
