"""
routers/query.py — Dashboard data-query endpoints.

All routes require X-API-Key (applied at the router level).

GET /api/session/current          Live snapshot (φ, state, session clock)
GET /api/session/current/chart    φ time-series for the session line chart
GET /api/session/{date}           Daily posture analytics (YYYY-MM-DD)
GET /api/history                  Per-day summaries for the bar chart (?range=7d)
GET /api/desk/current             Latest desk station reading + ergonomic flags
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import require_api_key
from ..database import get_db
from ..models import DeskReading, WearableReading
from ..schemas import (
    ChartPoint,
    DailySummary,
    DeskSnapshot,
    HistoryPoint,
    HistoryResponse,
    LiveSnapshot,
    SessionChartData,
)
from ..scoring import (
    ALERT_THRESHOLD_DEGREES,
    SESSION_GAP_SECONDS,
    ReadingSlice,
    compute_daily_summary,
    split_into_sessions,
)

# All routes in this router require a valid API key.
router = APIRouter(tags=["query"], dependencies=[Depends(require_api_key)])


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _orm_to_slice(r: WearableReading) -> ReadingSlice:
    """Convert a WearableReading ORM row to the lightweight ReadingSlice."""
    return ReadingSlice(
        timestamp=r.timestamp,
        phi=r.phi,
        phi_baseline=r.phi_baseline,
        posture_state=r.posture_state,
        activity_state=r.activity_state,
        alert_fired=r.alert_fired,
    )


def _readings_for_date(db: Session, target: date) -> list[WearableReading]:
    """
    Fetch all wearable readings for one UTC calendar day, sorted ascending.
    The half-open interval [00:00:00, 00:00:00 next day) is used so that
    exactly one day's worth of UTC rows is returned.
    """
    start = datetime(target.year, target.month, target.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return (
        db.query(WearableReading)
        .filter(WearableReading.timestamp >= start, WearableReading.timestamp < end)
        .order_by(WearableReading.timestamp.asc())
        .all()
    )


def _find_session_start(readings: list[WearableReading]) -> Optional[datetime]:
    """
    Identify the start of the most-recent session in the reading list.

    Scans backwards looking for the first gap > SESSION_GAP_SECONDS —
    everything after that gap is the current session.  If no such gap
    exists the entire list is one session and readings[0].timestamp is
    returned.
    """
    if not readings:
        return None
    for i in range(len(readings) - 1, 0, -1):
        gap = (readings[i].timestamp - readings[i - 1].timestamp).total_seconds()
        if gap > SESSION_GAP_SECONDS:
            return readings[i].timestamp
    return readings[0].timestamp


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get(
    "/api/session/current",
    response_model=LiveSnapshot,
    summary="Live posture snapshot",
)
def get_current_session(db: Session = Depends(get_db)):
    """
    Return the most-recent reading and the current session clock.

    Queries only the last 10 minutes of data — cheap enough to poll every
    3 seconds from the dashboard's live tile without straining the free-tier DB.

    Returns all-None fields if no readings have arrived in the last 10 minutes
    (device offline / not worn).
    """
    since = datetime.now(tz=timezone.utc) - timedelta(minutes=10)
    recent: list[WearableReading] = (
        db.query(WearableReading)
        .filter(WearableReading.timestamp >= since)
        .order_by(WearableReading.timestamp.asc())
        .all()
    )

    if not recent:
        return LiveSnapshot(
            phi=None,
            phi_baseline=None,
            posture_state=None,
            activity_state=None,
            alert_fired=None,
            session_start=None,
            session_duration_min=None,
            last_updated=None,
        )

    latest = recent[-1]
    session_start = _find_session_start(recent)
    duration_min = (
        (latest.timestamp - session_start).total_seconds() / 60.0
        if session_start
        else 0.0
    )

    return LiveSnapshot(
        phi=round(latest.phi, 2),
        phi_baseline=round(latest.phi_baseline, 2),
        posture_state=latest.posture_state,
        activity_state=latest.activity_state,
        alert_fired=latest.alert_fired,
        session_start=session_start,
        session_duration_min=round(duration_min, 1),
        last_updated=latest.timestamp,
    )


@router.get(
    "/api/session/current/chart",
    response_model=SessionChartData,
    summary="φ time-series for the live session chart",
)
def get_session_chart(db: Session = Depends(get_db)):
    """
    Return the φ time-series for today's most-recent session.

    Downsampled to ≤ 300 points so large responses do not degrade the
    browser.  Polled every 60 s from the dashboard (less frequent than
    the live tile).

    Also returns phi_baseline and alert_threshold so the dashboard can
    render the baseline and threshold reference lines without hard-coding
    those values in JavaScript.
    """
    today = date.today()
    rows = _readings_for_date(db, today)

    if not rows:
        return SessionChartData(phi_baseline=None, alert_threshold=None, points=[])

    slices = [_orm_to_slice(r) for r in rows]
    sessions = split_into_sessions(slices)
    current = sessions[-1] if sessions else []

    # Downsample: keep at most 300 evenly-spaced points.
    if len(current) > 300:
        step = len(current) // 300
        current = current[::step]

    baseline = current[-1].phi_baseline if current else None
    threshold = (baseline + ALERT_THRESHOLD_DEGREES) if baseline is not None else None

    return SessionChartData(
        phi_baseline=round(baseline, 2) if baseline is not None else None,
        alert_threshold=round(threshold, 2) if threshold is not None else None,
        points=[ChartPoint(timestamp=s.timestamp, phi=round(s.phi, 2)) for s in current],
    )


@router.get(
    "/api/session/{target_date}",
    response_model=DailySummary,
    summary="Daily posture analytics",
)
def get_daily_summary(target_date: str, db: Session = Depends(get_db)):
    """
    Compute and return posture analytics for the requested calendar day.

    The date must be supplied as YYYY-MM-DD (UTC).  All scoring is
    delegated to scoring.py — see that module for formula documentation.
    """
    try:
        d = date.fromisoformat(target_date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Date must be YYYY-MM-DD format."
        )

    rows = _readings_for_date(db, d)
    slices = [_orm_to_slice(r) for r in rows]
    result = compute_daily_summary(slices)

    return DailySummary(
        date=str(d),
        pct_good_posture=result.pct_good_posture,
        slouch_events_per_hour=result.slouch_events_per_hour,
        total_sitting_minutes=result.total_sitting_minutes,
        session_count=result.session_count,
    )


@router.get(
    "/api/history",
    response_model=HistoryResponse,
    summary="Multi-day history for the bar chart",
)
def get_history(
    range: str = Query(default="7d", pattern=r"^\d+d$"),
    db: Session = Depends(get_db),
):
    """
    Return per-day posture summaries for the last N days.

    The `range` query parameter accepts values like "7d", "14d", "30d".
    Days with no data are included with None metric values so the bar
    chart can display empty bars rather than skipping dates.
    """
    days = int(range.rstrip("d"))
    today = date.today()
    history: list[HistoryPoint] = []

    for i in range(days - 1, -1, -1):  # oldest first so chart renders left→right
        target = today - timedelta(days=i)
        rows = _readings_for_date(db, target)
        slices = [_orm_to_slice(r) for r in rows]
        result = compute_daily_summary(slices)

        history.append(
            HistoryPoint(
                date=str(target),
                pct_good_posture=result.pct_good_posture,
                slouch_per_hour=result.slouch_events_per_hour,
                sitting_min=result.total_sitting_minutes,
            )
        )

    return HistoryResponse(history=history)


@router.get(
    "/api/desk/current",
    response_model=DeskSnapshot,
    summary="Latest desk station reading",
)
def get_desk_current(db: Session = Depends(get_db)):
    """
    Return the most-recent desk station reading with ergonomic flags.

    Flags computed server-side:
      too_close  — screen_distance_cm < 50 cm
                   (based on display ergonomics / ophthalmology guidelines)
      too_dark   — lux < 200
                   (ISO 9241-6 office-lighting minimum for sustained screen work)
    """
    row: Optional[DeskReading] = (
        db.query(DeskReading).order_by(DeskReading.timestamp.desc()).first()
    )

    if not row:
        return DeskSnapshot(
            timestamp=None,
            screen_distance_cm=None,
            lux=None,
            temperature_c=None,
            humidity_pct=None,
            flags={"too_close": False, "too_dark": False},
        )

    return DeskSnapshot(
        timestamp=row.timestamp,
        screen_distance_cm=row.screen_distance_cm,
        lux=row.lux,
        temperature_c=row.temperature_c,
        humidity_pct=row.humidity_pct,
        flags={
            "too_close": (
                row.screen_distance_cm is not None and row.screen_distance_cm < 50
            ),
            "too_dark": row.lux is not None and row.lux < 200,
        },
    )
