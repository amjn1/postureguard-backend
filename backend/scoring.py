"""
scoring.py — PostureGuard session analytics and posture scoring.

This module is intentionally isolated from the FastAPI and SQLAlchemy layers
so that:
  1. Every formula can be clearly explained in the project report with a
     direct reference to a function and its docstring.
  2. The logic can be unit-tested without a database connection.
  3. Changes to the scoring rules do not require touching API or DB code.

────────────────────────────────────────────────────────────────────────────
Key Definitions
────────────────────────────────────────────────────────────────────────────

Session
    A contiguous block of wearable readings in which no two consecutive
    readings are separated by more than SESSION_GAP_SECONDS (5 minutes).
    A user going for a lunch break breaks the session; a momentary WiFi
    drop shorter than 5 minutes does not.

% Good Posture  (the primary metric)
    Formula:
        Σ seconds in GOOD posture while SEATED
        ────────────────────────────────────── × 100
        Σ seconds in SEATED activity state

    WALKING and TRANSITION time is excluded from both numerator and
    denominator.  The reasoning: posture while walking is biomechanically
    different from posture while seated; including it would dilute the
    metric and make it harder to interpret.  The question the score answers
    is "of the time I was sitting at my desk, what fraction of it was in
    good posture?"

Slouch Event  (discrete alert episode)
    The firmware fires a haptic alert when φ − φ_baseline > φ_th is
    sustained for longer than t_hold (~20 s) — the result arrives as
    alert_fired = True.  We count a RISING EDGE of alert_fired as one
    slouch event, so a prolonged slouch spanning many readings registers
    as ONE event (not N).  This is more useful than counting samples
    because it answers "how many times did I start slouching?" not
    "how many seconds was I being alerted?"

Slouch Events per Hour
    Formula:
        number of distinct slouch events
        ────────────────────────────────────── 
        total SEATED hours in the session / day

    Normalising per hour makes the rate comparable across sessions of
    different lengths (3 events in 30 min = 6/h, worse than 3 in 3 h = 1/h).
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# ─── Constants ────────────────────────────────────────────────────────────────

# Gaps longer than this between consecutive readings mark a session boundary.
SESSION_GAP_SECONDS: int = 5 * 60  # 5 minutes

# Alert-threshold angle added on top of the user's per-session baseline.
# Mirrors the firmware design value φ_th ≈ 15° from the project proposal.
ALERT_THRESHOLD_DEGREES: float = 15.0


# ─── Lightweight data class ───────────────────────────────────────────────────


@dataclass
class ReadingSlice:
    """
    Minimal representation of one wearable reading used for scoring.

    The query layer converts ORM rows into ReadingSlice objects before calling
    scoring functions, keeping this module free of SQLAlchemy imports.
    """

    timestamp: datetime
    phi: float
    phi_baseline: float
    posture_state: str  # "GOOD" | "SLOUCH"
    activity_state: str  # "SEATED" | "TRANSITION" | "WALKING"
    alert_fired: bool


# ─── Session splitting ────────────────────────────────────────────────────────


def split_into_sessions(
    readings: list[ReadingSlice],
) -> list[list[ReadingSlice]]:
    """
    Partition a chronologically-sorted reading list into sessions.

    A new session begins whenever two consecutive readings are more than
    SESSION_GAP_SECONDS apart.

    Parameters
    ----------
    readings:
        All readings for a calendar day, sorted ascending by timestamp.

    Returns
    -------
    A list of sessions; each session is a non-empty list[ReadingSlice].
    Returns [] if readings is empty.

    Example
    -------
    >>> sessions = split_into_sessions(day_readings)
    >>> len(sessions)       # typically 1–3 for a normal workday
    2
    """
    if not readings:
        return []

    sessions: list[list[ReadingSlice]] = [[readings[0]]]

    for i in range(1, len(readings)):
        gap_s = (
            readings[i].timestamp - readings[i - 1].timestamp
        ).total_seconds()
        if gap_s > SESSION_GAP_SECONDS:
            sessions.append([])  # start a new session bucket
        sessions[-1].append(readings[i])

    return sessions


# ─── Slouch-event detection ───────────────────────────────────────────────────


def detect_slouch_events(readings: list[ReadingSlice]) -> int:
    """
    Count the number of distinct alert episodes in a reading list.

    An episode is counted on the RISING EDGE of alert_fired — the first
    reading where alert_fired=True after one or more False readings.

    Parameters
    ----------
    readings:
        Readings in chronological order (any span — session, day, or hour).

    Returns
    -------
    int — number of distinct episodes where a haptic alert fired.

    Example
    -------
    Sequence: F F F T T T F F T T → two rising edges → returns 2
    """
    count = 0
    prev_alert = False
    for r in readings:
        if r.alert_fired and not prev_alert:
            count += 1
        prev_alert = r.alert_fired
    return count


# ─── Per-session metrics ──────────────────────────────────────────────────────


def compute_session_metrics(session: list[ReadingSlice]) -> dict:
    """
    Compute posture metrics for a single session.

    Metrics are accumulated over the TIME INTERVALS between consecutive
    readings, not per-reading.  The interval is attributed to the EARLIER
    reading's state (i.e. we ask "for how long was the user in this state
    before the next reading arrived?").  Intervals longer than
    SESSION_GAP_SECONDS are capped as a safety guard — they should not
    appear within a correctly split session.

    Parameters
    ----------
    session:
        A single session (no gaps > SESSION_GAP_SECONDS), sorted ascending.

    Returns
    -------
    dict with:
        total_seated_sec  float   — seconds with activity_state == "SEATED"
        good_seated_sec   float   — seconds with GOOD posture while SEATED
        slouch_events     int     — distinct alert episodes
        session_start     datetime | None
        session_end       datetime | None
        duration_sec      float   — wall-clock length (end − start)
    """
    if not session:
        return {
            "total_seated_sec": 0.0,
            "good_seated_sec": 0.0,
            "slouch_events": 0,
            "session_start": None,
            "session_end": None,
            "duration_sec": 0.0,
        }

    total_seated_sec = 0.0
    good_seated_sec = 0.0

    for i in range(1, len(session)):
        prev = session[i - 1]
        gap_s = (session[i].timestamp - prev.timestamp).total_seconds()
        gap_s = min(gap_s, SESSION_GAP_SECONDS)  # safety cap

        if prev.activity_state == "SEATED":
            total_seated_sec += gap_s
            if prev.posture_state == "GOOD":
                good_seated_sec += gap_s

    return {
        "total_seated_sec": total_seated_sec,
        "good_seated_sec": good_seated_sec,
        "slouch_events": detect_slouch_events(session),
        "session_start": session[0].timestamp,
        "session_end": session[-1].timestamp,
        "duration_sec": (
            session[-1].timestamp - session[0].timestamp
        ).total_seconds(),
    }


# ─── Daily summary ────────────────────────────────────────────────────────────


@dataclass
class DailySummaryResult:
    """Return type of compute_daily_summary."""

    # None when there is no seated time to compute a ratio from.
    pct_good_posture: Optional[float]
    slouch_events_per_hour: Optional[float]
    total_sitting_minutes: float
    session_count: int


def compute_daily_summary(readings: list[ReadingSlice]) -> DailySummaryResult:
    """
    Aggregate posture metrics across all sessions in a single calendar day.

    % good posture (day level):
        Σ good_seated_sec across sessions
        ─────────────────────────────────  × 100
        Σ total_seated_sec across sessions

    Slouch events per hour (day level):
        Σ slouch_events across sessions
        ───────────────────────────────────────────
        Σ total_seated_sec across sessions / 3600

    Both metrics return None if there is no SEATED time on the day
    (avoids division by zero and clearly signals "no data").

    Parameters
    ----------
    readings:
        All wearable readings for one UTC calendar day, sorted ascending.

    Returns
    -------
    DailySummaryResult — see dataclass definition above.
    """
    if not readings:
        return DailySummaryResult(
            pct_good_posture=None,
            slouch_events_per_hour=None,
            total_sitting_minutes=0.0,
            session_count=0,
        )

    sessions = split_into_sessions(readings)

    # Accumulate across all sessions.
    agg_total_seated = 0.0
    agg_good_seated = 0.0
    agg_slouch_events = 0

    for session in sessions:
        m = compute_session_metrics(session)
        agg_total_seated += m["total_seated_sec"]
        agg_good_seated += m["good_seated_sec"]
        agg_slouch_events += m["slouch_events"]

    # Compute derived metrics — guard against zero-denominator.
    pct_good = (
        round(agg_good_seated / agg_total_seated * 100.0, 1)
        if agg_total_seated > 0
        else None
    )

    seated_hours = agg_total_seated / 3600.0
    slouch_per_hour = (
        round(agg_slouch_events / seated_hours, 2)
        if seated_hours > 0
        else None
    )

    return DailySummaryResult(
        pct_good_posture=pct_good,
        slouch_events_per_hour=slouch_per_hour,
        total_sitting_minutes=round(agg_total_seated / 60.0, 1),
        session_count=len(sessions),
    )
