"""
schemas.py — Pydantic v2 request and response models.

Inbound schemas (WearablePayload, DeskPayload) validate the JSON that the
ESP32 and NodeMCU firmware POST to the ingest endpoints.  Any missing or
wrong-typed field causes a 422 Unprocessable Entity response with a clear
error message — no corrupt rows reach the database.

Outbound schemas document the structure of every API response so FastAPI
can auto-generate the OpenAPI spec (visible at /docs).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ─── Inbound (device → server) ────────────────────────────────────────────────


class WearablePayload(BaseModel):
    """
    Payload POSTed by the ESP32 wearable node approximately once per second.

    Field values are produced by the firmware after sensor fusion and alert
    logic — the backend stores them verbatim and does not recompute them.
    """

    device_id: str
    timestamp: datetime  # Pydantic parses ISO-8601 strings automatically.

    # φ = θ_upper − θ_lower  (see proposal §2.3 for the derivation)
    phi: float = Field(..., description="Differential spinal flexion angle (degrees)")
    phi_baseline: float = Field(
        ..., description="Per-user calibrated neutral angle captured at startup (degrees)"
    )

    # Firmware-level classifications.
    posture_state: Literal["GOOD", "SLOUCH"]
    activity_state: Literal["SEATED", "TRANSITION", "WALKING"]

    # True for the sample on which the haptic vibration alert fires.
    alert_fired: bool = False


class DeskPayload(BaseModel):
    """
    Payload POSTed by the NodeMCU desk-station node approximately every 30 s.

    All sensor fields are Optional — the desk station may omit sensors that
    are not physically wired; partial readings are still stored.
    """

    device_id: str
    timestamp: datetime
    screen_distance_cm: Optional[float] = None  # HC-SR04 ultrasonic
    lux: Optional[float] = None  # LDR-derived illuminance
    temperature_c: Optional[float] = None  # DHT22
    humidity_pct: Optional[float] = None  # DHT22


# ─── Outbound (server → dashboard) ───────────────────────────────────────────


class LiveSnapshot(BaseModel):
    """Current live state returned by GET /api/session/current."""

    phi: Optional[float]
    phi_baseline: Optional[float]
    posture_state: Optional[str]
    activity_state: Optional[str]
    alert_fired: Optional[bool]
    session_start: Optional[datetime]
    session_duration_min: Optional[float]
    last_updated: Optional[datetime]


class ChartPoint(BaseModel):
    """Single (timestamp, φ) sample for the live session chart."""

    timestamp: datetime
    phi: float


class SessionChartData(BaseModel):
    """Response from GET /api/session/current/chart."""

    phi_baseline: Optional[float]
    alert_threshold: Optional[float]  # phi_baseline + ALERT_THRESHOLD_DEGREES
    points: list[ChartPoint]


class DailySummary(BaseModel):
    """Analytics for one calendar day from GET /api/session/{date}."""

    date: str  # YYYY-MM-DD
    pct_good_posture: Optional[float]  # 0–100, None if no seated time
    slouch_events_per_hour: Optional[float]  # None if no seated time
    total_sitting_minutes: Optional[float]
    session_count: int


class HistoryPoint(BaseModel):
    """One day's summary — used to populate the 7-day bar chart."""

    date: str
    pct_good_posture: Optional[float]
    slouch_per_hour: Optional[float]
    sitting_min: Optional[float]


class HistoryResponse(BaseModel):
    """Response from GET /api/history."""

    history: list[HistoryPoint]


class DeskSnapshot(BaseModel):
    """Latest desk station reading from GET /api/desk/current."""

    timestamp: Optional[datetime]
    screen_distance_cm: Optional[float]
    lux: Optional[float]
    temperature_c: Optional[float]
    humidity_pct: Optional[float]
    # Ergonomic flags computed server-side so the JS stays thin.
    # too_close: distance < 50 cm (ophthalmology / display ergonomics guideline)
    # too_dark:  lux < 200        (ISO 9241-6 office-lighting minimum)
    flags: dict
