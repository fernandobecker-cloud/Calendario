"""
CRM Campaign Planner - Backend API
Servidor FastAPI que lê o Google Sheets publicado e entrega os eventos
para o calendário web.
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import requests
import csv
from io import StringIO
from typing import List, Dict
from dateutil import parser
from pathlib import Path


# ---------------- APP ---------------- #

app = FastAPI(title="CRM Campaign Planner API")

# libera acesso do navegador
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------- CAMINHOS CORRETOS ---------------- #

# pasta backend
BASE_DIR = Path(__file__).resolve().parent

# sobe para a raiz do projeto
ROOT_DIR = BASE_DIR.parent

# entra no frontend
FRONTEND_DIR = ROOT_DIR / "frontend"

print("Frontend localizado em:", FRONTEND_DIR)

# servir css e js
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ---------------- GOOGLE SHEETS ---------------- #

CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQaQTSv32MuaQTlGRjr9m6s5pmyK9A9iZlRTNTePX8x0G5to5j6iLSkGx89fbiQLQ/pub?output=csv"


# ---------------- UTILIDADES ---------------- #

def normalize(text):
    if not text:
        return ""

    return (
        text.lower()
        .replace("ç", "c")
        .replace("ã", "a")
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ê", "e")
        .replace("ô", "o")
        .strip()
    )


def find_column(headers, keyword):
    if not headers:
        return None
    for h in headers:
        if keyword in normalize(h):
            return h
    return None


# ---------------- LEITURA DO SHEETS ---------------- #

def fetch_and_parse_csv() -> List[Dict]:

    try:
        response = requests.get(CSV_URL, timeout=20)
        response.raise_for_status()

        # remove BOM e problemas de acento
        csv_content = response.content.decode("utf-8-sig")

        reader = csv.DictReader(StringIO(csv_content))
        headers = reader.fieldnames

        print("\nColunas encontradas:", headers)

        col_data = find_column(headers, "data")
        col_canal = find_column(headers, "canal")
        col_produto = find_column(headers, "produto")
        col_campanha = find_column(headers, "assunto")

        print("\nMapeamento:")
        print("Data:", col_data)
        print("Canal:", col_canal)
        print("Produto:", col_produto)
        print("Campanha:", col_campanha)

        events = []

        for row in reader:

            date_str = row.get(col_data)
            campanha = row.get(col_campanha)

            if not date_str or not campanha:
                continue

            try:
                parsed_date = parser.parse(date_str, dayfirst=True)
            except Exception:
                print("Não consegui ler a data:", date_str)
                continue

            canal = (row.get(col_canal) or "").lower()

            if "email" in canal:
                color = "#0071E3"
            elif "whats" in canal:
                color = "#25D366"
            elif "sms" in canal:
                color = "#FF9F0A"
            else:
                color = "#8E8E93"

            event = {
                "id": f"{date_str}_{campanha}",
                "title": campanha,
                "start": parsed_date.strftime("%Y-%m-%d"),
                "backgroundColor": color,
                "borderColor": color,
                "extendedProps": {
                    "canal": canal,
                    "produto": row.get(col_produto, ""),
                    "data_original": date_str
                }
            }

            events.append(event)

        print("\nEventos carregados:", len(events))
        return events

    except Exception as e:
        print("ERRO AO BUSCAR CSV:", e)
        raise HTTPException(status_code=500, detail="Erro ao buscar dados")


# ---------------- API ---------------- #

@app.get("/api/events")
def get_events():
    return fetch_and_parse_csv()


# ---------------- SITE ---------------- #

@app.get("/")
def home():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ---------------- RUN ---------------- #

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
