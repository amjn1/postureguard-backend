"""
database.py — SQLAlchemy engine and session factory.

Active deployment: SQLite (single file, no separate DB service needed).
The database file is created automatically on first startup in the project
root (postureguard.db).  It is excluded from git via .gitignore.

To switch to PostgreSQL later (e.g. Render), set DATABASE_URL to a
postgresql:// connection string — the engine configuration branch below
handles both drivers automatically.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()  # reads .env in development; no-op when env vars already set

# Default to a local SQLite file so `uvicorn backend.main:app` works
# out of the box with zero infrastructure.
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", "sqlite:///./postureguard.db"
)

# ── Engine configuration ───────────────────────────────────────────────────────

_is_sqlite = DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    # check_same_thread=False is required for SQLite when FastAPI's thread pool
    # hands the same connection to multiple request-handler threads.
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        # pool_size / max_overflow are not meaningful for SQLite's file-based
        # driver — omitting them avoids a SAWarning.
    )
else:
    # PostgreSQL (or any other server-side DB).
    # Render's free tier sometimes returns the deprecated "postgres://" scheme.
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,  # discard stale connections before use
        pool_size=5,
        max_overflow=2,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def get_db():
    """
    FastAPI dependency that yields a database session and guarantees cleanup.

    Usage in a route:
        db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
