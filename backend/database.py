"""Database configuration for CRM project/task management."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT_DIR / "crm.db"
DB_PATH = Path(os.getenv("CRM_DB_PATH", str(DEFAULT_DB_PATH))).expanduser()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from backend import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_manual_migrations()


def _ensure_manual_migrations() -> None:
    """Simple compatibility migrations for existing SQLite databases."""
    with engine.begin() as conn:
        columns = conn.execute(text("PRAGMA table_info(tasks)")).fetchall()
        column_names = {row[1] for row in columns}
        if "depends_on_task_id" not in column_names:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN depends_on_task_id INTEGER"))
