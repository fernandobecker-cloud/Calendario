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


def _excerpt_error(exc: Exception, limit: int = 300) -> str:
    return str(exc).strip().replace("\n", " ").replace("\r", " ")[:limit] or exc.__class__.__name__


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


def build_bigquery_client(project_id: str) -> bigquery.Client:
    service_account_info = _load_service_account_info()
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]

    try:
        credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
        if not project_id:
            raise HTTPException(status_code=500, detail="Variavel BIGQUERY_PROJECT_ID nao configurada")
        return bigquery.Client(project=project_id, credentials=credentials)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Falha ao autenticar no BigQuery") from exc


def run_bigquery_query(sql: str, project_id: str, *, location: str | None = None) -> pd.DataFrame:
    """Executa uma consulta no BigQuery e devolve um DataFrame."""
    client = build_bigquery_client(project_id)
    try:
        job = client.query(sql, location=location)
        rows = job.result()
        dataframe = rows.to_dataframe(create_bqstorage_client=False)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao consultar BigQuery: {_excerpt_error(exc)}",
        ) from exc

    return dataframe.fillna("")
