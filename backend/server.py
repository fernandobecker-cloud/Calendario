"""Backend FastAPI para o CRM Campaign Planner."""

from __future__ import annotations

import csv
import unicodedata
from io import StringIO
from pathlib import Path
from typing import Any

import requests
from dateutil import parser
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="CRM Campaign Planner API")

# Uso interno: aberto para facilitar execução local em qualquer host/porta.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQaQTSv32MuaQTlGRjr9m6s5pmyK9A9iZlRTNTePX8x0G5to5j6iLSkGx89fbiQLQ/"
    "pub?output=csv"
)


def normalize_text(text: str | None) -> str:
    """Normaliza texto para comparação tolerante a acentos e caixa."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_only.strip().lower()


def find_column(headers: list[str] | None, aliases: list[str]) -> str | None:
    """Encontra a primeira coluna compatível com algum alias."""
    if not headers:
        return None

    normalized_headers = {normalize_text(header): header for header in headers if header}
    for alias in aliases:
        alias_norm = normalize_text(alias)
        for normalized_header, original_header in normalized_headers.items():
            if alias_norm in normalized_header:
                return original_header
    return None


def get_channel_color(channel: str) -> str:
    channel_norm = normalize_text(channel)
    if "email" in channel_norm:
        return "#0071E3"
    if "whats" in channel_norm:
        return "#25D366"
    if "sms" in channel_norm:
        return "#FF9F0A"
    return "#8E8E93"


def fetch_and_parse_csv() -> list[dict[str, Any]]:
    """Lê o CSV público do Sheets e converte para eventos FullCalendar."""
    try:
        response = requests.get(CSV_URL, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Falha ao buscar Google Sheets") from exc

    csv_content = response.content.decode("utf-8-sig")
    reader = csv.DictReader(StringIO(csv_content))
    headers = reader.fieldnames or []

    col_data = find_column(headers, ["data"])
    col_campanha = find_column(headers, ["campanha", "assunto", "titulo", "title"])
    col_canal = find_column(headers, ["canal", "channel"])
    col_produto = find_column(headers, ["produto", "product"])
    col_observacao = find_column(headers, ["observacao", "obs", "observation"])

    missing_required: list[str] = []
    if not col_data:
        missing_required.append("DATA")
    if not col_campanha:
        missing_required.append("CAMPANHA/ASSUNTO")

    if missing_required:
        missing_text = ", ".join(missing_required)
        raise HTTPException(
            status_code=500,
            detail=f"Colunas obrigatórias ausentes no CSV: {missing_text}",
        )

    events: list[dict[str, Any]] = []

    for row in reader:
        date_str = (row.get(col_data) or "").strip()
        campaign = (row.get(col_campanha) or "").strip()

        if not date_str or not campaign:
            continue

        try:
            parsed_date = parser.parse(date_str, dayfirst=True)
        except Exception:
            continue

        channel = (row.get(col_canal) or "").strip()
        product = (row.get(col_produto) or "").strip() if col_produto else ""
        observation = (row.get(col_observacao) or "").strip() if col_observacao else ""
        color = get_channel_color(channel)

        events.append(
            {
                "id": f"{parsed_date.strftime('%Y-%m-%d')}_{campaign}",
                "title": campaign,
                "start": parsed_date.strftime("%Y-%m-%d"),
                "allDay": True,
                "backgroundColor": color,
                "borderColor": color,
                "extendedProps": {
                    "canal": channel,
                    "produto": product,
                    "observacao": observation,
                    "data_original": date_str,
                },
            }
        )

    return events


@app.get("/api/events")
def get_events() -> dict[str, Any]:
    events = fetch_and_parse_csv()
    return {"events": events, "total": len(events)}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def home() -> FileResponse:
    return FileResponse(str(FRONTEND_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.server:app", host="127.0.0.1", port=8000, reload=True)
