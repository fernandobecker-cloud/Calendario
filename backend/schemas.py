"""Pydantic schemas for project and task APIs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProjectStatus = Literal["planned", "active", "done", "cancelled"]
TaskStatus = Literal["planned", "doing", "blocked", "done"]
TaskPriority = Literal["low", "medium", "high"]
DeadlineState = Literal["normal", "due_today", "due_soon", "overdue"]


class ProjectBase(BaseModel):
    name: str = Field(min_length=1)
    owner: str | None = None
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: ProjectStatus = "planned"


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    owner: str | None = None
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: ProjectStatus | None = None


class ProjectOut(ProjectBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskBase(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    progress: int = Field(default=0, ge=0, le=100)
    status: TaskStatus = "planned"
    priority: TaskPriority = "medium"
    depends_on_task_id: int | None = None


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    depends_on_task_id: int | None = None


class TaskProgressUpdate(BaseModel):
    progress: int = Field(ge=0, le=100)


class TaskOut(TaskBase):
    id: int
    project_id: int
    created_at: datetime
    is_overdue: bool
    deadline_state: DeadlineState

    model_config = ConfigDict(from_attributes=True)
