"""Projects and tasks CRUD endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Project, Task
from backend.schemas import (
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    TaskCreate,
    TaskOut,
    TaskProgressUpdate,
    TaskUpdate,
)

router = APIRouter(prefix="/api", tags=["projects"])


def _validate_date_range(start_date: date | None, end_date: date | None) -> None:
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date nao pode ser menor que start_date")


def _task_done_blocked_by_dependency(db: Session, task: Task, next_status: str | None) -> bool:
    if next_status != "done":
        return False
    if not task.depends_on_task_id:
        return False

    predecessor = db.query(Task).filter(Task.id == task.depends_on_task_id).first()
    if not predecessor:
        return False
    return predecessor.status != "done"


def _enforce_dependency_done_rule(db: Session, task: Task, next_status: str | None) -> None:
    if _task_done_blocked_by_dependency(db, task, next_status):
        raise HTTPException(
            status_code=400,
            detail="Tarefa dependente nao pode ser concluida antes da tarefa predecessora.",
        )


def _validate_dependency(db: Session, project_id: int, task_id: int | None, depends_on_task_id: int | None) -> None:
    if depends_on_task_id is None:
        return

    if task_id is not None and depends_on_task_id == task_id:
        raise HTTPException(status_code=400, detail="Uma tarefa nao pode depender dela mesma")

    predecessor = db.query(Task).filter(Task.id == depends_on_task_id).first()
    if not predecessor:
        raise HTTPException(status_code=400, detail="Tarefa predecessora nao encontrada")

    if predecessor.project_id != project_id:
        raise HTTPException(status_code=400, detail="A dependencia deve ser uma tarefa do mesmo projeto")


def _get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto nao encontrado")
    return project


def _get_task_or_404(db: Session, task_id: int) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return task


def _serialize_task(task: Task) -> dict:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "start_date": task.start_date,
        "end_date": task.end_date,
        "progress": task.progress,
        "status": task.status,
        "priority": task.priority,
        "depends_on_task_id": task.depends_on_task_id,
        "created_at": task.created_at,
        "is_overdue": task.is_overdue,
        "deadline_state": task.deadline_state,
    }


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return db.query(Project).order_by(Project.created_at.desc()).all()


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    _validate_date_range(payload.start_date, payload.end_date)

    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)) -> Project:
    return _get_project_or_404(db, project_id)


@router.put("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)) -> Project:
    project = _get_project_or_404(db, project_id)

    update_data = payload.model_dump(exclude_unset=True)
    start_date = update_data.get("start_date", project.start_date)
    end_date = update_data.get("end_date", project.end_date)
    _validate_date_range(start_date, end_date)

    for field, value in update_data.items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return project


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    project = _get_project_or_404(db, project_id)

    db.delete(project)
    db.commit()
    return {"message": "Projeto deletado com sucesso"}


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
def list_project_tasks(project_id: int, db: Session = Depends(get_db)) -> list[dict]:
    _get_project_or_404(db, project_id)
    tasks = db.query(Task).filter(Task.project_id == project_id).order_by(Task.created_at.asc()).all()
    return [_serialize_task(task) for task in tasks]


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=201)
def create_task(project_id: int, payload: TaskCreate, db: Session = Depends(get_db)) -> dict:
    _get_project_or_404(db, project_id)
    _validate_date_range(payload.start_date, payload.end_date)
    _validate_dependency(db, project_id=project_id, task_id=None, depends_on_task_id=payload.depends_on_task_id)

    task_data = payload.model_dump()
    if task_data.get("status") == "done":
        task_data["progress"] = 100

    task = Task(project_id=project_id, **task_data)
    _enforce_dependency_done_rule(db, task, task.status)

    db.add(task)
    db.commit()
    db.refresh(task)
    return _serialize_task(task)


@router.put("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)) -> dict:
    task = _get_task_or_404(db, task_id)

    update_data = payload.model_dump(exclude_unset=True)
    start_date = update_data.get("start_date", task.start_date)
    end_date = update_data.get("end_date", task.end_date)
    _validate_date_range(start_date, end_date)

    if "depends_on_task_id" in update_data:
        _validate_dependency(
            db,
            project_id=task.project_id,
            task_id=task.id,
            depends_on_task_id=update_data.get("depends_on_task_id"),
        )

    next_status = update_data.get("status", task.status)
    _enforce_dependency_done_rule(db, task, next_status)

    if next_status == "done":
        update_data["progress"] = 100

    for field, value in update_data.items():
        setattr(task, field, value)

    db.commit()
    db.refresh(task)
    return _serialize_task(task)


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    task = _get_task_or_404(db, task_id)

    db.delete(task)
    db.commit()
    return {"message": "Tarefa deletada com sucesso"}


@router.patch("/tasks/{task_id}/progress", response_model=TaskOut)
def update_task_progress(task_id: int, payload: TaskProgressUpdate, db: Session = Depends(get_db)) -> dict:
    task = _get_task_or_404(db, task_id)

    _enforce_dependency_done_rule(db, task, task.status)

    task.progress = 100 if task.status == "done" else payload.progress

    db.commit()
    db.refresh(task)
    return _serialize_task(task)
