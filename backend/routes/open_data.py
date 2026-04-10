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


def _build_email_campaigns_sql(limit: int) -> str:
    if EMARSYS_OPEN_DATA_QUERY:
        return EMARSYS_OPEN_DATA_QUERY

    project_id = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    table = _quote_identifier(EMARSYS_OPEN_DATA_EMAIL_CAMPAIGNS_TABLE)

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
  WHERE partitiontime >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {EMARSYS_OPEN_DATA_LOOKBACK_DAYS} DAY)
)
SELECT
  CAST(id AS STRING) AS campaign_id,
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


@router.get("/emarsys/email-campaigns")
def emarsys_email_campaigns(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    try:
        sql = _build_email_campaigns_sql(limit)
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
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao preparar resposta Open Data: {exc}") from exc


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
