"""Event source loaders for the CRM portal."""

from __future__ import annotations

import json
import os
from typing import Any

import gspread
import pandas as pd
from fastapi import HTTPException
from google.cloud import bigquery
from google.oauth2.service_account import Credentials

GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT", "").strip()
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "").strip()
EVENTS_DATA_SOURCE = os.getenv("EVENTS_DATA_SOURCE", "sheets").strip().lower()
BIGQUERY_PROJECT_ID = os.getenv("BIGQUERY_PROJECT_ID", "").strip()
BIGQUERY_DATASET = os.getenv("BIGQUERY_DATASET", "").strip()
BIGQUERY_TABLE = os.getenv("BIGQUERY_TABLE", "").strip()
BIGQUERY_QUERY = os.getenv("BIGQUERY_QUERY", "").strip()


def _load_service_account_info() -> dict[str, Any]:
    if not GOOGLE_SERVICE_ACCOUNT:
        raise HTTPException(status_code=500, detail="Variavel GOOGLE_SERVICE_ACCOUNT nao configurada")

    try:
        return json.loads(GOOGLE_SERVICE_ACCOUNT)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="GOOGLE_SERVICE_ACCOUNT contem JSON invalido") from exc


def load_google_sheet() -> pd.DataFrame:
    """Carrega a primeira aba da planilha via Service Account."""
    if not SPREADSHEET_ID:
        raise HTTPException(status_code=500, detail="Variavel SPREADSHEET_ID nao configurada")

    service_account_info = _load_service_account_info()
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    try:
        credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        worksheet = spreadsheet.get_worksheet(0)
        if worksheet is None:
            raise HTTPException(status_code=500, detail="A planilha nao possui abas")
        values = worksheet.get_all_values()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Falha ao autenticar ou ler Google Sheets com Service Account",
        ) from exc

    if not values:
        return pd.DataFrame()

    headers = values[0]
    rows = values[1:]
    return pd.DataFrame(rows, columns=headers).fillna("")


def _build_bigquery_client() -> bigquery.Client:
    service_account_info = _load_service_account_info()
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]

    try:
        credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
        project_id = BIGQUERY_PROJECT_ID or credentials.project_id
        if not project_id:
            raise HTTPException(status_code=500, detail="Variavel BIGQUERY_PROJECT_ID nao configurada")
        return bigquery.Client(project=project_id, credentials=credentials)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Falha ao autenticar no BigQuery") from exc


def _build_bigquery_sql() -> str:
    if BIGQUERY_QUERY:
        return BIGQUERY_QUERY

    if BIGQUERY_PROJECT_ID and BIGQUERY_DATASET and BIGQUERY_TABLE:
        return f"SELECT * FROM `{BIGQUERY_PROJECT_ID}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE}`"

    raise HTTPException(
        status_code=500,
        detail=(
            "Configure BIGQUERY_QUERY ou o conjunto BIGQUERY_PROJECT_ID, "
            "BIGQUERY_DATASET e BIGQUERY_TABLE"
        ),
    )


def load_bigquery_table() -> pd.DataFrame:
    """Executa a consulta configurada no BigQuery e devolve um DataFrame."""
    client = _build_bigquery_client()
    sql = _build_bigquery_sql()

    try:
        job = client.query(sql)
        rows = job.result()
        dataframe = rows.to_dataframe(create_bqstorage_client=False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Falha ao consultar BigQuery") from exc

    return dataframe.fillna("")


def load_events_dataframe() -> tuple[pd.DataFrame, str]:
    """Carrega eventos da fonte configurada e retorna tambem o nome da origem."""
    if EVENTS_DATA_SOURCE == "bigquery":
        return load_bigquery_table(), "bigquery"
    if EVENTS_DATA_SOURCE in {"sheets", "google_sheets", ""}:
        return load_google_sheet(), "google_sheets"

    raise HTTPException(
        status_code=500,
        detail="EVENTS_DATA_SOURCE invalida. Use 'sheets' ou 'bigquery'",
    )
