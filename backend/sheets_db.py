"""Google Sheets persistence layer for projects and tasks."""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from typing import Any

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

PROJECT_HEADERS = [
    "id",
    "name",
    "owner",
    "description",
    "start_date",
    "end_date",
    "status",
    "created_at",
]

TASK_HEADERS = [
    "id",
    "project_id",
    "depends_on_task_id",
    "title",
    "description",
    "start_date",
    "end_date",
    "progress",
    "status",
    "priority",
    "created_at",
]

_SPREADSHEET_NAME = "crm_database"
_TIMEOUT_SECONDS = 8
_CACHE_TTL_SECONDS = 30

_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {
    "projects": (0.0, []),
    "tasks": (0.0, []),
}


class SheetsDBError(Exception):
    """Generic Google Sheets persistence error."""


class SheetsDBTimeoutError(SheetsDBError):
    """Google Sheets operation timed out."""


def _run_with_timeout(func, *args, timeout: int = _TIMEOUT_SECONDS, **kwargs):
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError as exc:
            raise SheetsDBTimeoutError("Operacao com Google Sheets excedeu o tempo limite") from exc


def _coerce_optional(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _coerce_int(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return default


def _iso_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _get_cached(key: str) -> list[dict[str, Any]] | None:
    now = time.time()
    with _cache_lock:
        ts, data = _cache[key]
        if now - ts < _CACHE_TTL_SECONDS:
            return [item.copy() for item in data]
    return None


def _set_cache(key: str, data: list[dict[str, Any]]) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), [item.copy() for item in data])


def _invalidate_cache(*keys: str) -> None:
    with _cache_lock:
        for key in keys:
            _cache[key] = (0.0, [])


def _build_client() -> gspread.Client:
    raw_service_account = os.getenv("GOOGLE_SERVICE_ACCOUNT", "").strip()
    if not raw_service_account:
        raise SheetsDBError("Variavel GOOGLE_SERVICE_ACCOUNT nao configurada")

    try:
        service_account_info = json.loads(raw_service_account)
    except json.JSONDecodeError as exc:
        raise SheetsDBError("GOOGLE_SERVICE_ACCOUNT contem JSON invalido") from exc

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    try:
        credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
        return gspread.authorize(credentials)
    except Exception as exc:  # pragma: no cover - network/auth integration
        raise SheetsDBError("Falha ao autenticar no Google Sheets") from exc


def _open_spreadsheet() -> gspread.Spreadsheet:
    client = _build_client()
    try:
        return _run_with_timeout(client.open, _SPREADSHEET_NAME)
    except SheetsDBTimeoutError:
        raise
    except Exception as exc:  # pragma: no cover - network integration
        raise SheetsDBError(f"Planilha '{_SPREADSHEET_NAME}' nao encontrada ou inacessivel") from exc


def _ensure_worksheet(spreadsheet: gspread.Spreadsheet, title: str, headers: list[str]) -> gspread.Worksheet:
    try:
        worksheet = _run_with_timeout(spreadsheet.worksheet, title)
    except SheetsDBTimeoutError:
        raise
    except Exception:
        worksheet = _run_with_timeout(spreadsheet.add_worksheet, title=title, rows=2000, cols=max(20, len(headers)))

    values = _run_with_timeout(worksheet.get_all_values)
    if not values:
        _run_with_timeout(worksheet.update, "A1", [headers])
    else:
        first_row = [cell.strip() for cell in values[0]]
        if first_row[: len(headers)] != headers:
            _run_with_timeout(worksheet.update, "A1", [headers])

    return worksheet


def _as_row(row: dict[str, Any], headers: list[str]) -> list[str]:
    result: list[str] = []
    for key in headers:
        value = row.get(key)
        result.append("" if value is None else str(value))
    return result


def _read_records(worksheet: gspread.Worksheet, headers: list[str]) -> list[dict[str, str]]:
    values = _run_with_timeout(worksheet.get_all_values)
    if not values:
        return []

    records: list[dict[str, str]] = []
    for row in values[1:]:
        normalized = row + [""] * max(0, len(headers) - len(row))
        records.append({headers[idx]: normalized[idx] for idx in range(len(headers))})
    return records


def _read_records_with_index(worksheet: gspread.Worksheet, headers: list[str]) -> list[tuple[int, dict[str, str]]]:
    values = _run_with_timeout(worksheet.get_all_values)
    if not values:
        return []

    records: list[tuple[int, dict[str, str]]] = []
    for sheet_row_idx, row in enumerate(values[1:], start=2):
        normalized = row + [""] * max(0, len(headers) - len(row))
        records.append((sheet_row_idx, {headers[idx]: normalized[idx] for idx in range(len(headers))}))
    return records


def _normalize_project(raw: dict[str, str]) -> dict[str, Any]:
    return {
        "id": _coerce_int(raw.get("id"), default=0),
        "name": (raw.get("name") or "").strip(),
        "owner": _coerce_optional(raw.get("owner")),
        "description": _coerce_optional(raw.get("description")),
        "start_date": _coerce_optional(raw.get("start_date")),
        "end_date": _coerce_optional(raw.get("end_date")),
        "status": (raw.get("status") or "planned").strip() or "planned",
        "created_at": (raw.get("created_at") or _iso_now()).strip(),
    }


def _normalize_task(raw: dict[str, str]) -> dict[str, Any]:
    return {
        "id": _coerce_int(raw.get("id"), default=0),
        "project_id": _coerce_int(raw.get("project_id"), default=0),
        "depends_on_task_id": _coerce_int(raw.get("depends_on_task_id"), default=0) or None,
        "title": (raw.get("title") or "").strip(),
        "description": _coerce_optional(raw.get("description")),
        "start_date": _coerce_optional(raw.get("start_date")),
        "end_date": _coerce_optional(raw.get("end_date")),
        "progress": max(0, min(100, _coerce_int(raw.get("progress"), default=0))),
        "status": (raw.get("status") or "planned").strip() or "planned",
        "priority": (raw.get("priority") or "medium").strip() or "medium",
        "created_at": (raw.get("created_at") or _iso_now()).strip(),
    }


def _next_id(records: list[dict[str, Any]]) -> int:
    if not records:
        return 1
    return max(int(item.get("id") or 0) for item in records) + 1


def _load_projects() -> list[dict[str, Any]]:
    cached = _get_cached("projects")
    if cached is not None:
        return cached

    spreadsheet = _open_spreadsheet()
    worksheet = _ensure_worksheet(spreadsheet, "projects", PROJECT_HEADERS)
    records = _read_records(worksheet, PROJECT_HEADERS)
    projects = [_normalize_project(item) for item in records if _coerce_int(item.get("id"), 0) > 0]
    projects.sort(key=lambda item: item["id"])
    _set_cache("projects", projects)
    return projects


def _load_tasks() -> list[dict[str, Any]]:
    cached = _get_cached("tasks")
    if cached is not None:
        return cached

    spreadsheet = _open_spreadsheet()
    worksheet = _ensure_worksheet(spreadsheet, "tasks", TASK_HEADERS)
    records = _read_records(worksheet, TASK_HEADERS)
    tasks = [_normalize_task(item) for item in records if _coerce_int(item.get("id"), 0) > 0]
    tasks.sort(key=lambda item: item["id"])
    _set_cache("tasks", tasks)
    return tasks


def get_projects() -> list[dict[str, Any]]:
    return _load_projects()


def get_project(project_id: int) -> dict[str, Any] | None:
    for project in _load_projects():
        if project["id"] == project_id:
            return project
    return None


def create_project(payload: dict[str, Any]) -> dict[str, Any]:
    projects = _load_projects()
    new_item = {
        "id": _next_id(projects),
        "name": payload["name"],
        "owner": payload.get("owner"),
        "description": payload.get("description"),
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "status": payload.get("status") or "planned",
        "created_at": _iso_now(),
    }

    spreadsheet = _open_spreadsheet()
    worksheet = _ensure_worksheet(spreadsheet, "projects", PROJECT_HEADERS)
    _run_with_timeout(worksheet.append_row, _as_row(new_item, PROJECT_HEADERS), value_input_option="USER_ENTERED")

    _invalidate_cache("projects")
    return new_item


def update_project(project_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    spreadsheet = _open_spreadsheet()
    worksheet = _ensure_worksheet(spreadsheet, "projects", PROJECT_HEADERS)
    indexed = _read_records_with_index(worksheet, PROJECT_HEADERS)

    target_row_idx: int | None = None
    target_item: dict[str, Any] | None = None

    for row_idx, raw in indexed:
        item = _normalize_project(raw)
        if item["id"] == project_id:
            target_row_idx = row_idx
            target_item = item
            break

    if target_row_idx is None or target_item is None:
        return None

    for key, value in update_data.items():
        target_item[key] = value

    target_item["id"] = project_id

    end_col = rowcol_to_a1(target_row_idx, len(PROJECT_HEADERS))
    _run_with_timeout(
        worksheet.update,
        f"A{target_row_idx}:{end_col}",
        [_as_row(target_item, PROJECT_HEADERS)],
        value_input_option="USER_ENTERED",
    )

    _invalidate_cache("projects")
    return target_item


def delete_project(project_id: int) -> bool:
    spreadsheet = _open_spreadsheet()
    projects_ws = _ensure_worksheet(spreadsheet, "projects", PROJECT_HEADERS)
    tasks_ws = _ensure_worksheet(spreadsheet, "tasks", TASK_HEADERS)

    projects_indexed = _read_records_with_index(projects_ws, PROJECT_HEADERS)
    project_row_idx: int | None = None
    for row_idx, raw in projects_indexed:
        if _normalize_project(raw)["id"] == project_id:
            project_row_idx = row_idx
            break

    if project_row_idx is None:
        return False

    _run_with_timeout(projects_ws.delete_rows, project_row_idx)

    tasks_indexed = _read_records_with_index(tasks_ws, TASK_HEADERS)
    rows_to_delete = [row_idx for row_idx, raw in tasks_indexed if _normalize_task(raw)["project_id"] == project_id]
    for row_idx in sorted(rows_to_delete, reverse=True):
        _run_with_timeout(tasks_ws.delete_rows, row_idx)

    _invalidate_cache("projects", "tasks")
    return True


def get_tasks(project_id: int) -> list[dict[str, Any]]:
    tasks = _load_tasks()
    return [task for task in tasks if task["project_id"] == project_id]


def get_task(task_id: int) -> dict[str, Any] | None:
    for task in _load_tasks():
        if task["id"] == task_id:
            return task
    return None


def create_task(project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    tasks = _load_tasks()
    new_item = {
        "id": _next_id(tasks),
        "project_id": project_id,
        "depends_on_task_id": payload.get("depends_on_task_id"),
        "title": payload["title"],
        "description": payload.get("description"),
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "progress": max(0, min(100, int(payload.get("progress", 0)))),
        "status": payload.get("status") or "planned",
        "priority": payload.get("priority") or "medium",
        "created_at": _iso_now(),
    }

    spreadsheet = _open_spreadsheet()
    worksheet = _ensure_worksheet(spreadsheet, "tasks", TASK_HEADERS)
    _run_with_timeout(worksheet.append_row, _as_row(new_item, TASK_HEADERS), value_input_option="USER_ENTERED")

    _invalidate_cache("tasks")
    return new_item


def update_task(task_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    spreadsheet = _open_spreadsheet()
    worksheet = _ensure_worksheet(spreadsheet, "tasks", TASK_HEADERS)
    indexed = _read_records_with_index(worksheet, TASK_HEADERS)

    target_row_idx: int | None = None
    target_item: dict[str, Any] | None = None

    for row_idx, raw in indexed:
        item = _normalize_task(raw)
        if item["id"] == task_id:
            target_row_idx = row_idx
            target_item = item
            break

    if target_row_idx is None or target_item is None:
        return None

    for key, value in update_data.items():
        if key == "project_id":
            continue
        target_item[key] = value

    target_item["id"] = task_id

    end_col = rowcol_to_a1(target_row_idx, len(TASK_HEADERS))
    _run_with_timeout(
        worksheet.update,
        f"A{target_row_idx}:{end_col}",
        [_as_row(target_item, TASK_HEADERS)],
        value_input_option="USER_ENTERED",
    )

    _invalidate_cache("tasks")
    return target_item


def delete_task(task_id: int) -> bool:
    spreadsheet = _open_spreadsheet()
    worksheet = _ensure_worksheet(spreadsheet, "tasks", TASK_HEADERS)
    indexed = _read_records_with_index(worksheet, TASK_HEADERS)

    target_row_idx: int | None = None
    for row_idx, raw in indexed:
        if _normalize_task(raw)["id"] == task_id:
            target_row_idx = row_idx
            break

    if target_row_idx is None:
        return False

    _run_with_timeout(worksheet.delete_rows, target_row_idx)
    _invalidate_cache("tasks")
    return True
