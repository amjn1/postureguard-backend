"""
database.py — SQLAlchemy engine and session factory.

DATABASE_URL is read from the environment variable of the same name.
On Render, this is automatically injected when you link a PostgreSQL
instance to your web service in the Render dashboard.

Connection-pool settings are tuned for Render's free-tier PostgreSQL,
which caps concurrent connections at ~20.  pool_pre_ping ensures stale
connections are refreshed before use (important when the free tier's
web service spins down between requests).
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Load .env in local development; no-op when env vars are already set (Render).
load_dotenv()

_raw_url: str = os.environ["DATABASE_URL"]

# Render's free PostgreSQL hands back the deprecated "postgres://" scheme;
# SQLAlchemy 2.x requires "postgresql://".
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    _raw_url,
    pool_pre_ping=True,  # detect and discard broken connections
    pool_size=5,         # keep 5 connections open in the pool
    max_overflow=2,      # allow 2 extra connections under burst load
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
