"""Open data routes for BigQuery-backed sources."""

from __future__ import annotations

import os
from datetime import date, datetime
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
EMARSYS_OPEN_DATA_LOCATION = os.getenv("EMARSYS_OPEN_DATA_LOCATION", "EU").strip()
EMARSYS_OPEN_DATA_QUERY = os.getenv("EMARSYS_OPEN_DATA_QUERY", "").strip()
EMARSYS_OPEN_DATA_LOOKBACK_DAYS = max(
    1,
    int(os.getenv("EMARSYS_OPEN_DATA_LOOKBACK_DAYS", "180").strip() or "180"),
)

router = APIRouter(prefix="/api/open-data", tags=["open-data"])


def _quote_identifier(value: str) -> str:
    safe = value.strip().replace("`", "")
    if not safe:
        raise ValueError("Identificador BigQuery vazio")
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


def _build_email_program_open_rates_sql(limit: int, start_date: str | None = None, end_date: str | None = None) -> str:
    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    campaigns_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)
    opens_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_OPENS_TABLE)
    sends_table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_SENDS_TABLE)
    partitiontime_filter = _build_partitiontime_filter(start_date, end_date)

    return f"""
WITH campaigns AS (
  SELECT
    CAST(COALESCE(program_id, 0) AS STRING) AS program_id,
    DATE(partitiontime) AS data,
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
  WHERE {partitiontime_filter}
    AND program_id IS NOT NULL
  GROUP BY 1, 2
),
sends AS (
  SELECT
    CAST(COALESCE(program_id, 0) AS STRING) AS program_id,
    DATE(partitiontime) AS data,
    COUNT(DISTINCT message_id) AS enviados
  FROM `{project_id}.{dataset}.{sends_table}`
  WHERE {partitiontime_filter}
    AND program_id IS NOT NULL
    AND message_id IS NOT NULL
  GROUP BY 1, 2
),
opens AS (
  SELECT
    CAST(COALESCE(program_id, 0) AS STRING) AS program_id,
    DATE(partitiontime) AS data,
    COUNT(DISTINCT message_id) AS aberturas_unicas
  FROM `{project_id}.{dataset}.{opens_table}`
  WHERE {partitiontime_filter}
    AND program_id IS NOT NULL
    AND message_id IS NOT NULL
  GROUP BY 1, 2
)
SELECT
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
LEFT JOIN sends s ON s.program_id = c.program_id AND s.data = c.data
LEFT JOIN opens o ON o.program_id = c.program_id AND o.data = c.data
WHERE c.campanha IS NOT NULL
  AND TRIM(c.campanha) != ''
ORDER BY c.data DESC, c.campanha
LIMIT {limit}
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
    limit: int = Query(default=50, ge=1, le=500),
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict[str, Any]:
    try:
        sql = _build_email_program_open_rates_sql(limit, start, end)
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
