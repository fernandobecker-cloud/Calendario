"""Backend FastAPI para o CRM Campaign Planner."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import unicodedata
from base64 import b64decode
from pathlib import Path
from typing import Any, Literal

import gspread
import pandas as pd
from dateutil import parser
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.oauth2.service_account import Credentials
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
AUTH_DB_PATH = ROOT_DIR / "auth_users.db"

AUTH_USERNAME = os.getenv("AUTH_USERNAME", "").strip()
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "").strip()
AUTH_MODE = os.getenv("AUTH_MODE", "multi").strip().lower()

USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]+$")
PASSWORD_MIN_LENGTH = 6

app = FastAPI(title="CRM Campaign Planner API")


def is_single_auth_mode() -> bool:
    return AUTH_MODE in {"single", "simple"}


class UserCreatePayload(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=128)
    role: Literal["admin", "user"] = "user"


class UpdateRolePayload(BaseModel):
    role: Literal["admin", "user"]


class UpdatePasswordPayload(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=128)


class AuthUser(BaseModel):
    username: str
    role: Literal["admin", "user"]


def parse_allowed_origins() -> list[str]:
    """Lê CORS_ALLOWED_ORIGINS do ambiente (csv) com fallback local."""
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return ["http://127.0.0.1:8000", "http://localhost:8000"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not normalized:
        raise ValueError("Usuario vazio")
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("Use apenas letras, numeros, ponto, underline e hifen")
    return normalized


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    iterations = 150_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_hex, digest_hex = password_hash.split("$", maxsplit=3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    try:
        iterations = int(iterations_raw)
        salt = bytes.fromhex(salt_hex)
        expected_digest = bytes.fromhex(digest_hex)
    except ValueError:
        return False

    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(candidate, expected_digest)


def init_user_store() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def get_user(username: str) -> sqlite3.Row | None:
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT username, password_hash, role, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()


def user_count() -> int:
    with get_db_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()
    return int(row["total"]) if row else 0


def admin_count() -> int:
    with get_db_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM users WHERE role = 'admin'").fetchone()
    return int(row["total"]) if row else 0


def create_user_record(username: str, password: str, role: Literal["admin", "user"]) -> None:
    password_hash = hash_password(password)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role),
        )
        conn.commit()


def update_user_password(username: str, new_password: str) -> None:
    new_password_hash = hash_password(new_password)
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (new_password_hash, username),
        )
        conn.commit()


def update_user_role(username: str, role: Literal["admin", "user"]) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE users SET role = ? WHERE username = ?",
            (role, username),
        )
        conn.commit()


def ensure_bootstrap_admin() -> None:
    """Cria admin inicial pelo .env/Render quando ainda nao ha usuarios."""
    if is_single_auth_mode():
        return
    if user_count() > 0:
        return
    if not AUTH_USERNAME or not AUTH_PASSWORD:
        return

    try:
        username = normalize_username(AUTH_USERNAME)
    except ValueError:
        return

    if len(AUTH_PASSWORD) < PASSWORD_MIN_LENGTH:
        return

    create_user_record(username, AUTH_PASSWORD, "admin")


def is_auth_enabled() -> bool:
    """Em single usa credencial fixa; em multi usa usuarios cadastrados."""
    if is_single_auth_mode():
        return bool(AUTH_USERNAME and AUTH_PASSWORD)
    return user_count() > 0


def parse_basic_credentials(authorization_header: str | None) -> tuple[str, str] | None:
    if not authorization_header or not authorization_header.startswith("Basic "):
        return None

    encoded_credentials = authorization_header[6:].strip()
    if not encoded_credentials:
        return None

    try:
        decoded_bytes = b64decode(encoded_credentials, validate=True)
        decoded_credentials = decoded_bytes.decode("utf-8")
    except Exception:
        return None

    username, separator, password = decoded_credentials.partition(":")
    if not separator:
        return None

    return username, password


def authenticate_user(username_raw: str, password: str) -> AuthUser | None:
    if is_single_auth_mode():
        try:
            username = normalize_username(username_raw)
            expected_username = normalize_username(AUTH_USERNAME)
        except ValueError:
            return None

        if not secrets.compare_digest(username, expected_username):
            return None
        if not secrets.compare_digest(password, AUTH_PASSWORD):
            return None

        return AuthUser(username=expected_username, role="admin")

    try:
        username = normalize_username(username_raw)
    except ValueError:
        return None

    user = get_user(username)
    if not user:
        return None

    if not verify_password(password, user["password_hash"]):
        return None

    return AuthUser(username=user["username"], role=user["role"])


def unauthorized_response() -> Response:
    return Response(
        status_code=401,
        content="Unauthorized",
        headers={"WWW-Authenticate": 'Basic realm="CRM Campaign Planner"'},
    )


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next: Any) -> Response:
    """Protege app e API com Basic Auth, mantendo /health livre para monitoramento."""
    request.state.auth_user = None

    if request.url.path == "/health":
        return await call_next(request)

    if not is_auth_enabled():
        return await call_next(request)

    credentials = parse_basic_credentials(request.headers.get("Authorization"))
    if not credentials:
        return unauthorized_response()

    username, password = credentials
    auth_user = authenticate_user(username, password)
    if not auth_user:
        return unauthorized_response()

    request.state.auth_user = auth_user
    return await call_next(request)


def get_current_user(request: Request) -> AuthUser:
    user = getattr(request.state, "auth_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Nao autenticado")
    return user


def get_admin_user(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem executar esta acao")
    return current_user


def ensure_multi_user_mode() -> None:
    if is_single_auth_mode():
        raise HTTPException(
            status_code=404,
            detail="Gestao de usuarios desabilitada no modo de login unico",
        )


if not is_single_auth_mode():
    init_user_store()
    ensure_bootstrap_admin()

# Assets gerados pelo Vite (build React)
app.mount(
    "/assets",
    StaticFiles(directory=str(FRONTEND_DIST_DIR / "assets"), check_dir=False),
    name="assets",
)

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "").strip()
GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT", "").strip()


def normalize_text(text: str | None) -> str:
    """Normaliza texto para comparacao tolerante a acentos e caixa."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_only.strip().lower()


def find_column(headers: list[str] | None, aliases: list[str]) -> str | None:
    """Encontra a primeira coluna compativel com algum alias."""
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


def load_google_sheet() -> pd.DataFrame:
    """Carrega a primeira aba da planilha via Service Account usando env vars."""
    if not GOOGLE_SERVICE_ACCOUNT:
        raise HTTPException(status_code=500, detail="Variavel GOOGLE_SERVICE_ACCOUNT nao configurada")
    if not SPREADSHEET_ID:
        raise HTTPException(status_code=500, detail="Variavel SPREADSHEET_ID nao configurada")

    try:
        service_account_info = json.loads(GOOGLE_SERVICE_ACCOUNT)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="GOOGLE_SERVICE_ACCOUNT contem JSON invalido") from exc

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
    dataframe = pd.DataFrame(rows, columns=headers).fillna("")
    return dataframe


def fetch_and_parse_csv() -> list[dict[str, Any]]:
    """Le a planilha privada e converte para eventos FullCalendar."""
    dataframe = load_google_sheet()
    if dataframe.empty:
        return []
    headers = dataframe.columns.tolist()

    col_data = find_column(headers, ["data"])
    col_campanha = find_column(headers, ["campanha", "assunto", "titulo", "title"])
    col_canal = find_column(headers, ["canal", "channel"])
    col_direcionamento = find_column(headers, ["direcionamento", "direcion", "target", "segmento"])
    col_status = find_column(headers, ["status", "situacao", "situação"])
    col_produto = find_column(headers, ["produto", "product"])
    col_observacao = find_column(headers, ["observacao", "obs", "observation"])

    missing_required: list[str] = []
    if not col_data:
        missing_required.append("DATA")

    if missing_required:
        missing_text = ", ".join(missing_required)
        raise HTTPException(
            status_code=500,
            detail=f"Colunas obrigatorias ausentes no CSV: {missing_text}",
        )

    events: list[dict[str, Any]] = []

    for row in dataframe.to_dict(orient="records"):
        date_str = (row.get(col_data) or "").strip()
        campaign = (row.get(col_campanha) or "").strip()
        channel = (row.get(col_canal) or "").strip() if col_canal else ""
        direcionamento = (row.get(col_direcionamento) or "").strip() if col_direcionamento else ""
        status = (row.get(col_status) or "").strip() if col_status else ""

        if not date_str:
            continue

        try:
            parsed_date = parser.parse(date_str, dayfirst=True)
        except Exception:
            continue

        product = (row.get(col_produto) or "").strip() if col_produto else ""
        observation = (row.get(col_observacao) or "").strip() if col_observacao else ""
        color = get_channel_color(channel)
        title_parts = [part for part in [channel, direcionamento] if part]
        display_title = " - ".join(title_parts) if title_parts else (campaign or "Campanha sem titulo")

        events.append(
            {
                "id": f"{parsed_date.strftime('%Y-%m-%d')}_{display_title}",
                "title": display_title,
                "start": parsed_date.strftime("%Y-%m-%d"),
                "allDay": True,
                "backgroundColor": color,
                "borderColor": color,
                "extendedProps": {
                    "canal": channel,
                    "direcionamento": direcionamento,
                    "status": status,
                    "titulo_original": campaign,
                    "produto": product,
                    "observacao": observation,
                    "data_original": date_str,
                },
            }
        )

    return events


def serve_frontend_file(path: str) -> FileResponse:
    """Serve um arquivo do build React; fallback para index.html (SPA)."""
    index_file = FRONTEND_DIST_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                "Frontend nao encontrado (frontend/dist/index.html ausente). "
                "No deploy da Render, configure o build para executar "
                "'cd frontend && npm install && npm run build'."
            ),
        )

    target = (FRONTEND_DIST_DIR / path).resolve()

    # Bloqueia path traversal para fora da pasta dist
    if FRONTEND_DIST_DIR.resolve() not in target.parents and target != FRONTEND_DIST_DIR.resolve():
        return FileResponse(str(index_file))

    if target.is_file():
        return FileResponse(str(target))

    return FileResponse(str(index_file))


@app.get("/api/me")
def get_me(current_user: AuthUser = Depends(get_current_user)) -> dict[str, str]:
    return {"username": current_user.username, "role": current_user.role}


@app.get("/api/auth-config")
def get_auth_config(current_user: AuthUser = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "auth_mode": "single" if is_single_auth_mode() else "multi",
        "user_management_enabled": not is_single_auth_mode(),
        "current_user": {"username": current_user.username, "role": current_user.role},
    }


@app.patch("/api/me/password")
def update_my_password(
    payload: UpdatePasswordPayload, current_user: AuthUser = Depends(get_current_user)
) -> dict[str, str]:
    if is_single_auth_mode():
        raise HTTPException(
            status_code=400,
            detail="Troca de senha via app desabilitada no modo de login unico",
        )

    user = get_user(current_user.username)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")

    if not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")

    new_password = payload.new_password.strip()
    if len(new_password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(status_code=422, detail=f"Senha deve ter ao menos {PASSWORD_MIN_LENGTH} caracteres")

    if verify_password(new_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="A nova senha deve ser diferente da senha atual")

    update_user_password(current_user.username, new_password)
    return {"username": current_user.username}


@app.get("/api/users")
def list_users(_: AuthUser = Depends(get_admin_user)) -> dict[str, Any]:
    ensure_multi_user_mode()
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT username, role, created_at FROM users ORDER BY role DESC, username ASC"
        ).fetchall()

    users = [
        {"username": row["username"], "role": row["role"], "created_at": row["created_at"]} for row in rows
    ]
    return {"users": users, "total": len(users)}


@app.post("/api/users", status_code=201)
def create_user(payload: UserCreatePayload, _: AuthUser = Depends(get_admin_user)) -> dict[str, str]:
    ensure_multi_user_mode()
    try:
        username = normalize_username(payload.username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    password = payload.password.strip()
    if len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(status_code=422, detail=f"Senha deve ter ao menos {PASSWORD_MIN_LENGTH} caracteres")

    if get_user(username):
        raise HTTPException(status_code=409, detail="Usuario ja existe")

    try:
        create_user_record(username, password, payload.role)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Usuario ja existe") from exc

    return {"username": username, "role": payload.role}


@app.patch("/api/users/{username}/role")
def update_role(
    username: str, payload: UpdateRolePayload, current_admin: AuthUser = Depends(get_admin_user)
) -> dict[str, str]:
    ensure_multi_user_mode()
    try:
        target_username = normalize_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if target_username == current_admin.username:
        raise HTTPException(status_code=400, detail="Nao e permitido alterar o proprio perfil")

    user = get_user(target_username)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")

    new_role = payload.role
    current_role = user["role"]
    if current_role == new_role:
        return {"username": target_username, "role": new_role}

    if current_role == "admin" and new_role == "user" and admin_count() <= 1:
        raise HTTPException(status_code=400, detail="Nao e permitido rebaixar o ultimo administrador")

    update_user_role(target_username, new_role)
    return {"username": target_username, "role": new_role}


@app.delete("/api/users/{username}")
def delete_user(username: str, current_admin: AuthUser = Depends(get_admin_user)) -> dict[str, str]:
    ensure_multi_user_mode()
    try:
        target_username = normalize_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if target_username == current_admin.username:
        raise HTTPException(status_code=400, detail="Nao e permitido remover o proprio usuario")

    user = get_user(target_username)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")

    if user["role"] == "admin" and admin_count() <= 1:
        raise HTTPException(status_code=400, detail="Nao e permitido remover o ultimo administrador")

    with get_db_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (target_username,))
        conn.commit()

    return {"username": target_username}


@app.get("/api/events")
def get_events() -> dict[str, Any]:
    events = fetch_and_parse_csv()
    return {"events": events, "total": len(events)}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def home() -> FileResponse:
    return serve_frontend_file("index.html")


@app.get("/{full_path:path}")
def frontend_routes(full_path: str) -> FileResponse:
    if full_path.startswith("api/") or full_path == "api" or full_path == "health":
        raise HTTPException(status_code=404, detail="Not found")
    return serve_frontend_file(full_path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.server:app", host="127.0.0.1", port=8000, reload=True)
