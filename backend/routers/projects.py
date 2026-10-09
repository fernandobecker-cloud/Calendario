"""Projects and tasks CRUD endpoints.

Persistencia escolhida por PROJECTS_STORAGE: "sheets" (default - planilha
"crm_database", abas "projects"/"tasks", backend/sheets_db.py) ou
"bigquery" (dataset portal_crm, backend/bq_db.py). Migracao: POST
/projects-storage/migrar-para-bigquery (admin), depois
PROJECTS_STORAGE=bigquery no Render; voltar pra "sheets" e o rollback.
"""

from __future__ import annotations

import os
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Request
from dateutil import parser as date_parser

from backend.schemas import (
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    TaskCreate,
    TaskOut,
    TaskProgressUpdate,
    TaskUpdate,
)
from backend import bq_db, sheets_db
from backend.sheets_db import SheetsDBTimeoutError

router = APIRouter(prefix="/api", tags=["projects"])

PROJECTS_STORAGE = os.getenv("PROJECTS_STORAGE", "sheets").strip().lower()
projects_db = bq_db if PROJECTS_STORAGE == "bigquery" else sheets_db
_DB_ERRORS = (sheets_db.SheetsDBError, bq_db.BQDBError)


def _handle_sheets_error(exc: Exception) -> None:
    if isinstance(exc, SheetsDBTimeoutError):
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    raise HTTPException(status_code=502, detail=str(exc)) from exc


def _validate_date_range(start_date: date | None, end_date: date | None) -> None:
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date nao pode ser menor que start_date")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        try:
            return date_parser.parse(value).date()
        except Exception:
            return None


def _normalize_task_status(value: str | None) -> str:
    allowed = {"planned", "doing", "blocked", "done"}
    normalized = (value or "").strip().lower()
    return normalized if normalized in allowed else "planned"


def _normalize_task_priority(value: str | None) -> str:
    allowed = {"low", "medium", "high"}
    normalized = (value or "").strip().lower()
    return normalized if normalized in allowed else "medium"


def _serialize_task(task: dict) -> dict:
    today = datetime.utcnow().date()
    end_date = _parse_date(task.get("end_date"))
    start_date = _parse_date(task.get("start_date"))
    status = _normalize_task_status(task.get("status"))
    priority = _normalize_task_priority(task.get("priority"))

    is_overdue = bool(end_date and status != "done" and today > end_date)

    if is_overdue:
        deadline_state = "overdue"
    elif not end_date:
        deadline_state = "normal"
    elif end_date == today:
        deadline_state = "due_today"
    elif 0 < (end_date - today).days <= 2:
        deadline_state = "due_soon"
    else:
        deadline_state = "normal"

    progress = task.get("progress", 0)
    try:
        progress_int = max(0, min(100, int(progress)))
    except Exception:
        progress_int = 0

    created_at_raw = task.get("created_at")
    try:
        created_at = datetime.fromisoformat(str(created_at_raw).replace("Z", "+00:00")).isoformat().replace("+00:00", "Z")
    except Exception:
        created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    title = (task.get("title") or "").strip() or "Tarefa sem titulo"

    return {
        "id": task["id"],
        "project_id": task["project_id"],
        "depends_on_task_id": task.get("depends_on_task_id"),
        "title": title,
        "description": task.get("description"),
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "progress": progress_int,
        "status": status,
        "priority": priority,
        "created_at": created_at,
        "is_overdue": is_overdue,
        "deadline_state": deadline_state,
    }


def _to_project_or_404(project_id: int) -> dict:
    try:
        project = projects_db.get_project(project_id)
    except _DB_ERRORS as exc:
        _handle_sheets_error(exc)

    if not project:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado")
    return project


def _to_task_or_404(task_id: int) -> dict:
    try:
        task = projects_db.get_task(task_id)
    except _DB_ERRORS as exc:
        _handle_sheets_error(exc)

    if not task:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return task


def _validate_dependency(project_id: int, task_id: int | None, depends_on_task_id: int | None) -> None:
    if depends_on_task_id is None:
        return

    if task_id is not None and depends_on_task_id == task_id:
        raise HTTPException(status_code=400, detail="Uma tarefa nao pode depender dela mesma")

    predecessor = _to_task_or_404(depends_on_task_id)
    if predecessor["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="A dependencia deve ser uma tarefa do mesmo projeto")


def _enforce_dependency_done_rule(task: dict, next_status: str | None) -> None:
    if next_status != "done":
        return

    predecessor_id = task.get("depends_on_task_id")
    if not predecessor_id:
        return

    predecessor = _to_task_or_404(int(predecessor_id))
    if predecessor.get("status") != "done":
        raise HTTPException(
            status_code=400,
            detail="Tarefa dependente nao pode ser concluida antes da tarefa predecessora.",
        )


@router.get("/projects", response_model=list[ProjectOut])
def list_projects() -> list[dict]:
    try:
        projects = projects_db.get_projects()
    except _DB_ERRORS as exc:
        _handle_sheets_error(exc)

    return sorted(projects, key=lambda item: item.get("created_at", ""), reverse=True)


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project_endpoint(payload: ProjectCreate) -> dict:
    _validate_date_range(payload.start_date, payload.end_date)

    try:
        return projects_db.create_project(payload.model_dump())
    except _DB_ERRORS as exc:
        _handle_sheets_error(exc)


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project_endpoint(project_id: int) -> dict:
    return _to_project_or_404(project_id)


@router.put("/projects/{project_id}", response_model=ProjectOut)
def update_project_endpoint(project_id: int, payload: ProjectUpdate) -> dict:
    current = _to_project_or_404(project_id)

    update_data = payload.model_dump(exclude_unset=True)
    start_date = update_data.get("start_date", current.get("start_date"))
    end_date = update_data.get("end_date", current.get("end_date"))
    _validate_date_range(start_date, end_date)

    try:
        updated = projects_db.update_project(project_id, update_data)
    except _DB_ERRORS as exc:
        _handle_sheets_error(exc)

    if not updated:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado")
    return updated


@router.delete("/projects/{project_id}")
def delete_project_endpoint(project_id: int) -> dict[str, str]:
    _to_project_or_404(project_id)

    try:
        deleted = projects_db.delete_project(project_id)
    except _DB_ERRORS as exc:
        _handle_sheets_error(exc)

    if not deleted:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado")
    return {"message": "Projeto deletado com sucesso"}


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
def list_project_tasks(project_id: int) -> list[dict]:
    _to_project_or_404(project_id)
    try:
        tasks = projects_db.get_tasks(project_id)
    except _DB_ERRORS as exc:
        _handle_sheets_error(exc)

    tasks_sorted = sorted(tasks, key=lambda item: item.get("created_at", ""))
    return [_serialize_task(item) for item in tasks_sorted]


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=201)
def create_task_endpoint(project_id: int, payload: TaskCreate) -> dict:
    _to_project_or_404(project_id)
    _validate_date_range(payload.start_date, payload.end_date)
    _validate_dependency(project_id=project_id, task_id=None, depends_on_task_id=payload.depends_on_task_id)

    task_data = payload.model_dump()
    if task_data.get("status") == "done":
        task_data["progress"] = 100

    _enforce_dependency_done_rule(task_data, task_data.get("status"))

    try:
        created = projects_db.create_task(project_id, task_data)
    except _DB_ERRORS as exc:
        _handle_sheets_error(exc)

    return _serialize_task(created)


@router.put("/tasks/{task_id}", response_model=TaskOut)
def update_task_endpoint(task_id: int, payload: TaskUpdate) -> dict:
    current = _to_task_or_404(task_id)

    update_data = payload.model_dump(exclude_unset=True)
    start_date = update_data.get("start_date", _parse_date(current.get("start_date")))
    end_date = update_data.get("end_date", _parse_date(current.get("end_date")))
    _validate_date_range(start_date, end_date)

    if "depends_on_task_id" in update_data:
        _validate_dependency(
            project_id=current["project_id"],
            task_id=current["id"],
            depends_on_task_id=update_data.get("depends_on_task_id"),
        )

    next_status = update_data.get("status", current.get("status"))
    composed = {**current, **update_data}
    _enforce_dependency_done_rule(composed, next_status)

    if next_status == "done":
        update_data["progress"] = 100

    try:
        updated = projects_db.update_task(task_id, update_data)
    except _DB_ERRORS as exc:
        _handle_sheets_error(exc)

    if not updated:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return _serialize_task(updated)


@router.delete("/tasks/{task_id}")
def delete_task_endpoint(task_id: int) -> dict[str, str]:
    _to_task_or_404(task_id)

    try:
        deleted = projects_db.delete_task(task_id)
    except _DB_ERRORS as exc:
        _handle_sheets_error(exc)

    if not deleted:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return {"message": "Tarefa deletada com sucesso"}


@router.patch("/tasks/{task_id}/progress", response_model=TaskOut)
def update_task_progress(task_id: int, payload: TaskProgressUpdate) -> dict:
    current = _to_task_or_404(task_id)
    _enforce_dependency_done_rule(current, current.get("status"))

    next_progress = 100 if current.get("status") == "done" else payload.progress

    try:
        updated = projects_db.update_task(task_id, {"progress": next_progress})
    except _DB_ERRORS as exc:
        _handle_sheets_error(exc)

    if not updated:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return _serialize_task(updated)


@router.get("/projects-storage")
def projects_storage() -> dict[str, str]:
    return {"storage": PROJECTS_STORAGE}


@router.post("/projects-storage/migrar-para-bigquery")
def migrar_projects_para_bigquery(request: Request) -> dict:
    """Copia projects/tasks da planilha pro BigQuery (substitui o que ja
    estiver nas tabelas, preservando ids) e confere lendo de volta: mesma
    quantidade e mesmos campos em cada registro. Bloqueado depois da troca
    pra "bigquery", pra nao sobrescrever o que ja foi lancado la."""
    auth_user = getattr(request.state, "auth_user", None)
    if getattr(auth_user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem executar esta acao")
    if PROJECTS_STORAGE == "bigquery":
        raise HTTPException(
            status_code=409,
            detail="PROJECTS_STORAGE ja e 'bigquery' - migrar de novo sobrescreveria os dados atuais.",
        )
    try:
        projects = sheets_db.get_projects()
        tasks = sheets_db.get_all_tasks()
        gravados = bq_db.importar_projects(projects, tasks)
        projects_bq = bq_db.get_projects()
        tasks_bq = bq_db.get_all_tasks()
        chaves_sheets = {bq_db.chave_project(p) for p in projects} | {bq_db.chave_task(t) for t in tasks}
        chaves_bq = {bq_db.chave_project(p) for p in projects_bq} | {bq_db.chave_task(t) for t in tasks_bq}
    except _DB_ERRORS as exc:
        _handle_sheets_error(exc)

    divergentes = sorted({c[0] for c in chaves_sheets ^ chaves_bq})
    return {
        "gravados": gravados,
        "planilha": {"projects": len(projects), "tasks": len(tasks)},
        "bigquery": {"projects": len(projects_bq), "tasks": len(tasks_bq)},
        "ids_divergentes": divergentes,
        "confere": len(projects) == len(projects_bq) and len(tasks) == len(tasks_bq) and not divergentes,
    }
