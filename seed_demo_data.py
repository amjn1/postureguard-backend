#!/usr/bin/env python3
"""
seed_demo_data.py — Populate PostureGuard with realistic demo data.

Run this immediately after deploying to Render so the dashboard has data
to display before the ESP32 hardware is ready.

Usage — against the live Render deployment:
    python seed_demo_data.py \\
        --url https://postureguard-api.onrender.com \\
        --key your-api-key

Usage — against a local development server:
    python seed_demo_data.py --url http://localhost:8000 --key testkey

Options:
    --url   Base URL of the deployed API (no trailing slash).
    --key   API key (must match the API_KEY env var on the server).
    --days  How many past days to seed (default 7).

The script generates data at 30-second intervals (quick but realistic enough
for the charts).  Total requests: ~1 500 for a 7-day seed.
Estimated time: 30–90 s depending on network latency to Render.

Note on Render free-tier cold starts:
    If the service was idle, the first request may take 30–60 seconds.
    The script detects this and waits automatically (--warmup flag).
"""

import argparse
import random
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

# ─── Simulation parameters ────────────────────────────────────────────────────

WEARABLE_DEVICE = "wearable_01"
DESK_DEVICE     = "desk_01"

PHI_BASELINE        = 5.0   # neutral spinal angle (degrees)
ALERT_THRESHOLD     = 15.0  # φ_th from the proposal (degrees)
READING_INTERVAL_S  = 30    # seconds between simulated readings
DESK_INTERVAL_S     = 30    # seconds between desk readings

# Session schedule: list of (hour_start, duration_hours, good_posture_fraction)
DAILY_SESSIONS = [
    (9.0,  2.5, 0.75),   # Morning   — 9:00–11:30, 75% good
    (13.5, 3.0, 0.65),   # Afternoon — 13:30–16:30, 65% good (post-lunch dip)
]


# ─── Data generators ──────────────────────────────────────────────────────────

def generate_wearable_session(
    date_utc: datetime,
    hour_start: float,
    duration_h: float,
    good_frac: float,
) -> list[dict]:
    """
    Simulate one seated session of wearable readings.

    State machine:
      - Mostly GOOD posture; occasionally lapses into SLOUCH.
      - Alert fires on the first reading 20 s into a SLOUCH episode.
      - Occasionally transitions to WALKING for short bursts.

    Parameters
    ----------
    date_utc    Midnight UTC of the target day.
    hour_start  Session start offset from midnight (e.g., 9.5 = 09:30).
    duration_h  Session length in hours.
    good_frac   Fraction of SEATED time that should be GOOD (0–1).
    """
    readings = []

    start = date_utc + timedelta(hours=hour_start)
    end   = start + timedelta(hours=duration_h)
    t     = start

    # State variables
    posture       = "GOOD"
    activity      = "SEATED"
    state_secs    = 0       # seconds in current posture state
    alert_active  = False   # is the alert currently firing?
    prev_alert    = False   # for rising-edge detection

    while t < end:
        # ── Activity transitions ──────────────────────────────────────────
        # Small probability of switching to/from WALKING each interval
        if activity == "SEATED" and random.random() < 0.01:
            activity = "TRANSITION"
        elif activity == "TRANSITION":
            activity = "WALKING" if random.random() < 0.5 else "SEATED"
        elif activity == "WALKING" and random.random() < 0.15:
            activity = "TRANSITION"

        # ── Posture transitions (only while SEATED) ───────────────────────
        if activity == "SEATED":
            # Probability of starting to slouch inversely proportional to good_frac
            if posture == "GOOD" and random.random() < (1 - good_frac) * 0.03:
                posture = "SLOUCH"
                state_secs = 0
                alert_active = False
            # Probability of correcting posture
            elif posture == "SLOUCH" and random.random() < 0.04:
                posture = "GOOD"
                state_secs = 0
                alert_active = False
        else:
            # Reset alert when not seated
            alert_active = False

        state_secs += READING_INTERVAL_S

        # Alert fires after 20 s of continuous slouching
        if activity == "SEATED" and posture == "SLOUCH" and state_secs >= 20:
            alert_active = True

        # Rising edge of alert_fired
        alert_fired = alert_active and not prev_alert
        prev_alert  = alert_active

        # ── Compute φ with realistic noise ────────────────────────────────
        if activity != "SEATED":
            # Movement: angle varies as body shifts; alert doesn't apply
            phi = PHI_BASELINE + random.gauss(2, 3)
            effective_posture = "GOOD"
            alert_fired = False
        elif posture == "GOOD":
            # Good posture: φ ≈ baseline + small positive offset
            phi = PHI_BASELINE + max(0, random.gauss(3.5, 1.5))
            effective_posture = "GOOD"
        else:
            # Slouch: φ = baseline + threshold + extra
            phi = PHI_BASELINE + ALERT_THRESHOLD + max(0, random.gauss(5, 2))
            effective_posture = "SLOUCH"

        readings.append({
            "device_id":     WEARABLE_DEVICE,
            "timestamp":     t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "phi":           round(max(0, phi), 2),
            "phi_baseline":  PHI_BASELINE,
            "posture_state": effective_posture,
            "activity_state": activity,
            "alert_fired":   alert_fired,
        })

        t += timedelta(seconds=READING_INTERVAL_S)

    return readings


def generate_desk_session(
    date_utc: datetime,
    hour_start: float,
    duration_h: float,
) -> list[dict]:
    """Generate desk station readings for one session."""
    readings = []
    start = date_utc + timedelta(hours=hour_start)
    end   = start + timedelta(hours=duration_h)
    t     = start

    while t < end:
        readings.append({
            "device_id":          DESK_DEVICE,
            "timestamp":          t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "screen_distance_cm": round(max(30, random.gauss(55, 6)), 1),
            "lux":                round(max(50, random.gauss(300, 60))),
            "temperature_c":      round(random.gauss(24.0, 0.8), 1),
            "humidity_pct":       round(max(20, min(80, random.gauss(50, 5))), 1),
        })
        t += timedelta(seconds=DESK_INTERVAL_S)

    return readings


# ─── HTTP posting ─────────────────────────────────────────────────────────────

def post_one(client: httpx.Client, url: str, endpoint: str, payload: dict, key: str) -> bool:
    """POST one reading; return True on success."""
    try:
        resp = client.post(
            f"{url}{endpoint}",
            json=payload,
            headers={"X-API-Key": key},
            timeout=60,
        )
        resp.raise_for_status()
        return True
    except httpx.HTTPStatusError as e:
        print(f"\n  HTTP {e.response.status_code}: {e.response.text[:200]}")
        return False
    except Exception as e:
        print(f"\n  Network error: {e}")
        return False


def post_batch(
    client: httpx.Client,
    url: str,
    endpoint: str,
    readings: list[dict],
    key: str,
    label: str,
) -> None:
    """POST a list of readings with a progress counter."""
    total = len(readings)
    if total == 0:
        return
    print(f"  Posting {total} {label} readings…")
    failed = 0
    for i, r in enumerate(readings, 1):
        ok = post_one(client, url, endpoint, r, key)
        if not ok:
            failed += 1
        if i % 20 == 0 or i == total:
            bar = "█" * (i * 20 // total) + "░" * (20 - i * 20 // total)
            print(f"  [{bar}] {i}/{total}   ", end="\r")
        time.sleep(0.05)  # ~20 req/s — be kind to Render's free tier
    print(f"  [{('█'*20)}] {total}/{total}  {'✓' if failed == 0 else f'⚠ {failed} failed'}")


# ─── Warmup ───────────────────────────────────────────────────────────────────

def warmup(url: str, key: str) -> bool:
    """
    Ping /health and wait up to 90 s for the Render service to wake up.
    Returns True if the service is responsive.
    """
    print("⏳ Waking up Render service (free tier may take 30–60 s)…")
    deadline = time.time() + 90
    with httpx.Client() as client:
        while time.time() < deadline:
            try:
                resp = client.get(
                    f"{url}/health",
                    headers={"X-API-Key": key},
                    timeout=10,
                )
                if resp.status_code == 200:
                    print("✅ Service is up!\n")
                    return True
            except Exception:
                pass
            print("   Still waiting…", end="\r")
            time.sleep(5)
    print("❌ Service did not respond within 90 s.")
    return False


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seed PostureGuard with demo data")
    parser.add_argument("--url",  default="http://localhost:8000",
                        help="API base URL (no trailing slash)")
    parser.add_argument("--key",  required=True, help="API key (X-API-Key value)")
    parser.add_argument("--days", type=int, default=7,
                        help="Number of past days to seed (default 7)")
    parser.add_argument("--no-warmup", action="store_true",
                        help="Skip the Render cold-start warmup ping")
    args = parser.parse_args()

    if not args.no_warmup and "localhost" not in args.url:
        ok = warmup(args.url, args.key)
        if not ok:
            sys.exit(1)

    today_utc = datetime.now(tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    print(f"🌱 Seeding {args.days} days of demo data → {args.url}\n")

    with httpx.Client() as client:
        for day_offset in range(args.days - 1, -1, -1):
            day = today_utc - timedelta(days=day_offset)
            day_label = day.strftime("%A %Y-%m-%d")

            # Vary quality slightly by day so the bar chart shows variation
            day_jitter = random.uniform(-0.08, 0.08)

            print(f"📅 {day_label}")

            for hour_start, duration_h, good_frac in DAILY_SESSIONS:
                session_good = min(0.95, max(0.30, good_frac + day_jitter))
                label = "AM" if hour_start < 12 else "PM"

                wearable_rows = generate_wearable_session(
                    day, hour_start, duration_h, session_good
                )
                desk_rows = generate_desk_session(day, hour_start, duration_h)

                print(f"  [{label} session | {duration_h}h | {session_good:.0%} good]")
                post_batch(client, args.url, "/api/wearable", wearable_rows, args.key, "wearable")
                post_batch(client, args.url, "/api/desk",     desk_rows,     args.key, "desk")

            print()

    print("🎉 Seeding complete!  Refresh your dashboard to see the data.")
    print(f"   Dashboard URL: {args.url}/dashboard/")


if __name__ == "__main__":
    main()
