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


_READ_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
_WRITE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _open_worksheet(scopes: list[str]) -> gspread.Worksheet:
    if not SPREADSHEET_ID:
        raise HTTPException(status_code=500, detail="Variavel SPREADSHEET_ID nao configurada")
    service_account_info = _load_service_account_info()
    try:
        credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
        client = gspread.authorize(credentials)
        worksheet = client.open_by_key(SPREADSHEET_ID).get_worksheet(0)
        if worksheet is None:
            raise HTTPException(status_code=500, detail="A planilha nao possui abas")
        return worksheet
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Falha ao conectar ao Google Sheets") from exc


def load_google_sheet() -> pd.DataFrame:
    """Carrega a primeira aba da planilha via Service Account."""
    try:
        worksheet = _open_worksheet(_READ_SCOPES)
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


def get_sheet_headers() -> list[str]:
    """Retorna a linha de cabeçalho da planilha do calendário."""
    worksheet = _open_worksheet(_WRITE_SCOPES)
    return worksheet.row_values(1)


def append_calendar_row(row_data: list[str]) -> int:
    """Adiciona uma linha ao final da planilha. Retorna o índice da linha (1-based)."""
    worksheet = _open_worksheet(_WRITE_SCOPES)
    try:
        result = worksheet.append_row(row_data, value_input_option="USER_ENTERED")
        updated_range = result.get("updates", {}).get("updatedRange", "")
        # "Sheet1!A5:G5" -> extract row number
        part = updated_range.split("!")[1] if "!" in updated_range else ""
        digits = "".join(c for c in part.split(":")[0] if c.isdigit())
        return int(digits) if digits else 0
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao inserir linha: {exc}") from exc


def update_calendar_row(row_index: int, row_data: list[str]) -> None:
    """Atualiza uma linha existente pelo índice (1-based)."""
    worksheet = _open_worksheet(_WRITE_SCOPES)
    try:
        n = len(row_data)
        end_col = chr(ord("A") + n - 1) if n <= 26 else "Z"
        worksheet.update(
            f"A{row_index}:{end_col}{row_index}",
            [row_data],
            value_input_option="USER_ENTERED",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao atualizar linha: {exc}") from exc


def delete_calendar_row(row_index: int) -> None:
    """Exclui uma linha da planilha pelo índice (1-based)."""
    worksheet = _open_worksheet(_WRITE_SCOPES)
    try:
        worksheet.delete_rows(row_index)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao excluir linha: {exc}") from exc


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


def run_bigquery_records(sql: str, project_id: str, *, location: str | None = None) -> list[dict[str, Any]]:
    """Executa uma consulta no BigQuery e devolve registros simples."""
    client = build_bigquery_client(project_id)
    try:
        job = client.query(sql, location=location)
        rows = job.result()
        return [dict(row.items()) for row in rows]
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao consultar BigQuery: {_excerpt_error(exc)}",
        ) from exc
