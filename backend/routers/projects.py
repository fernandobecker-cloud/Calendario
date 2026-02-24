"""Projects and tasks CRUD endpoints backed by Google Sheets."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from backend.schemas import (
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    TaskCreate,
    TaskOut,
    TaskProgressUpdate,
    TaskUpdate,
)
from backend.sheets_db import (
    SheetsDBError,
    SheetsDBTimeoutError,
    create_project,
    create_task,
    delete_project,
    delete_task,
    get_project,
    get_projects,
    get_task,
    get_tasks,
    update_project,
    update_task,
)

router = APIRouter(prefix="/api", tags=["projects"])


def _handle_sheets_error(exc: Exception) -> None:
    if isinstance(exc, SheetsDBTimeoutError):
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    raise HTTPException(status_code=502, detail=str(exc)) from exc


def _validate_date_range(start_date: date | None, end_date: date | None) -> None:
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date nao pode ser menor que start_date")


def _to_project_or_404(project_id: int) -> dict:
    try:
        project = get_project(project_id)
    except SheetsDBError as exc:
        _handle_sheets_error(exc)

    if not project:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado")
    return project


def _to_task_or_404(task_id: int) -> dict:
    try:
        task = get_task(task_id)
    except SheetsDBError as exc:
        _handle_sheets_error(exc)

    if not task:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return task


@router.get("/projects", response_model=list[ProjectOut])
def list_projects() -> list[dict]:
    try:
        projects = get_projects()
    except SheetsDBError as exc:
        _handle_sheets_error(exc)

    return sorted(projects, key=lambda item: item.get("created_at", ""), reverse=True)


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project_endpoint(payload: ProjectCreate) -> dict:
    _validate_date_range(payload.start_date, payload.end_date)

    try:
        return create_project(payload.model_dump())
    except SheetsDBError as exc:
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
        updated = update_project(project_id, update_data)
    except SheetsDBError as exc:
        _handle_sheets_error(exc)

    if not updated:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado")
    return updated


@router.delete("/projects/{project_id}")
def delete_project_endpoint(project_id: int) -> dict[str, str]:
    _to_project_or_404(project_id)

    try:
        deleted = delete_project(project_id)
    except SheetsDBError as exc:
        _handle_sheets_error(exc)

    if not deleted:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado")
    return {"message": "Projeto deletado com sucesso"}


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
def list_project_tasks(project_id: int) -> list[dict]:
    _to_project_or_404(project_id)
    try:
        tasks = get_tasks(project_id)
    except SheetsDBError as exc:
        _handle_sheets_error(exc)

    return sorted(tasks, key=lambda item: item.get("created_at", ""))


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=201)
def create_task_endpoint(project_id: int, payload: TaskCreate) -> dict:
    _to_project_or_404(project_id)
    _validate_date_range(payload.start_date, payload.end_date)

    try:
        return create_task(project_id, payload.model_dump())
    except SheetsDBError as exc:
        _handle_sheets_error(exc)


@router.put("/tasks/{task_id}", response_model=TaskOut)
def update_task_endpoint(task_id: int, payload: TaskUpdate) -> dict:
    current = _to_task_or_404(task_id)

    update_data = payload.model_dump(exclude_unset=True)
    start_date = update_data.get("start_date", current.get("start_date"))
    end_date = update_data.get("end_date", current.get("end_date"))
    _validate_date_range(start_date, end_date)

    try:
        updated = update_task(task_id, update_data)
    except SheetsDBError as exc:
        _handle_sheets_error(exc)

    if not updated:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return updated


@router.delete("/tasks/{task_id}")
def delete_task_endpoint(task_id: int) -> dict[str, str]:
    _to_task_or_404(task_id)

    try:
        deleted = delete_task(task_id)
    except SheetsDBError as exc:
        _handle_sheets_error(exc)

    if not deleted:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return {"message": "Tarefa deletada com sucesso"}


@router.patch("/tasks/{task_id}/progress", response_model=TaskOut)
def update_task_progress(task_id: int, payload: TaskProgressUpdate) -> dict:
    _to_task_or_404(task_id)

    try:
        updated = update_task(task_id, {"progress": payload.progress})
    except SheetsDBError as exc:
        _handle_sheets_error(exc)

    if not updated:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return updated
