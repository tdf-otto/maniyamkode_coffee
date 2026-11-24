"""Database engine, session factory, and migration runner.

Migrations are numbered SQL files in app/db/migrations/. init_db() applies
any not yet recorded in schema_migrations, in order. The SQLAlchemy models in
app/db/models mirror the final schema and are used for all ORM access; the
SQL files are the source of truth for the physical schema (keeps types
portable to PostGIS later).
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .. import config
from . import models  # noqa: F401  (registers all tables on Base.metadata)
from .base import Base

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {},
)

# SQLite: allow the FastAPI threadpool to share one connection safely.
@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trivial
    if isinstance(dbapi_conn, sqlite3.Connection):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db() -> list[int]:
    """Apply pending migrations. Returns the list of newly applied versions.

    Migrations are applied with the sqlite3 driver's executescript (SQLite
    only runs one statement per execute call through SQLAlchemy). If
    DATABASE_URL ever points at PostGIS, swap this runner for Alembic — the
    numbered .sql files stay the source of truth.
    """
    config.ensure_dirs()
    if not config.DATABASE_URL.startswith("sqlite:///"):
        raise RuntimeError("init_db() currently supports SQLite only; see app/db/__init__.py")
    db_file = config.DATABASE_URL.removeprefix("sqlite:///")
    applied: list[int] = []
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            m = re.match(r"^(\d+)_(.+)\.sql$", path.name)
            if not m:
                continue
            version, name = int(m.group(1)), m.group(2)
            if version in done:
                continue
            conn.executescript(path.read_text())
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, utcnow()),
            )
            conn.commit()
            applied.append(version)
    finally:
        conn.close()
    return applied


def create_all() -> None:
    """Create ORM tables directly (used by tests on a throwaway DB)."""
    config.ensure_dirs()
    Base.metadata.create_all(engine)
