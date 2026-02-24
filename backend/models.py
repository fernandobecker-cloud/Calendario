"""SQLAlchemy models for projects and tasks."""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from backend.database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    owner = Column(String, nullable=True)
    description = Column(String, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    status = Column(String, nullable=False, default="planned")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    tasks = relationship(
        "Task",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    depends_on_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    progress = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="planned")
    priority = Column(String, nullable=False, default="medium")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    project = relationship("Project", back_populates="tasks")
    depends_on_task = relationship("Task", remote_side=[id], uselist=False)

    @property
    def is_overdue(self) -> bool:
        if not self.end_date:
            return False
        if self.status == "done":
            return False
        return datetime.utcnow().date() > self.end_date

    @property
    def deadline_state(self) -> str:
        if self.is_overdue:
            return "overdue"

        if not self.end_date:
            return "normal"

        today = datetime.utcnow().date()
        if self.end_date == today:
            return "due_today"

        delta_days = (self.end_date - today).days
        if 0 < delta_days <= 2:
            return "due_soon"

        return "normal"
