"""
main.py — PostureGuard FastAPI application entry point.

This file:
  1. Creates the FastAPI app with metadata that populates /docs.
  2. Adds CORS middleware so the dashboard can call the API from any origin
     (useful during local development; in production both share the same domain).
  3. Registers the ingest and query routers under their respective /api/* paths.
  4. Adds a /health endpoint Render uses for health checks.
  5. Auto-creates database tables on startup (idempotent, no Alembic required).
  6. Serves the /dashboard static site from the same process so one Render
     service hosts both the API and the UI.

Local development:
    # Copy .env.example to .env and fill in credentials, then:
    uvicorn backend.main:app --reload --port 8000
    # Dashboard: http://localhost:8000/dashboard/
    # API docs:  http://localhost:8000/docs

Production (Render):
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import ingest, query


# ─── Startup / shutdown lifecycle ────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Create all database tables on first startup (idempotent — safe to run
    on every restart because SQLAlchemy checks table existence first).

    This avoids needing a separate Alembic migration step for a fresh
    Render deploy — just connect the DB, start the service, and the schema
    appears automatically.
    """
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown: nothing to clean up for a stateless web service.


# ─── FastAPI app ──────────────────────────────────────────────────────────────


app = FastAPI(
    title="PostureGuard API",
    description=(
        "Cloud backend for the PostureGuard wearable posture monitor "
        "(BITS Pilani Hyderabad, EEE F411 IoT Lab, 2026–27 Sem I). "
        "Receives sensor data from an ESP32 wearable node and a NodeMCU "
        "desk station, stores it in PostgreSQL, scores posture sessions, "
        "and serves analytics to the companion dashboard."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ─── CORS ─────────────────────────────────────────────────────────────────────

# allow_origins=["*"] lets the dashboard call the API even when you're
# developing it locally (file:// or http://localhost:*).
# In production both live on the same Render domain, so these requests are
# same-origin and CORS headers are not sent — this setting costs nothing.
# Note: allow_credentials must be False when allow_origins contains "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(ingest.router)
app.include_router(query.router)

# ─── Health check ─────────────────────────────────────────────────────────────


@app.get("/health", tags=["meta"])
def health():
    """
    Liveness endpoint.  Render pings this to confirm the service is healthy.

    Also useful to verify the app is awake after a free-tier spin-down:
        curl https://your-app.onrender.com/health
    Expected response: {"status": "ok", "service": "postureguard-api"}
    """
    return {"status": "ok", "service": "postureguard-api"}


# ─── Dashboard static files ───────────────────────────────────────────────────

# Resolve the dashboard directory relative to this source file so the path
# is correct regardless of the working directory Render uses when starting
# the process (which is always the repo root, but defensive code is good code).
_HERE = os.path.dirname(os.path.abspath(__file__))
_DASHBOARD_DIR = os.path.normpath(os.path.join(_HERE, "..", "dashboard"))

# StaticFiles with html=True serves index.html for bare directory requests.
# Explicit FastAPI routes (/health, /api/*) are matched before this mount,
# so there is no conflict.
app.mount("/dashboard", StaticFiles(directory=_DASHBOARD_DIR, html=True), name="dashboard")


@app.get("/", include_in_schema=False)
def root():
    """Redirect the bare root URL to the dashboard."""
    return RedirectResponse(url="/dashboard/")
