# PostureGuard — Cloud Dashboard

> **Atharva Mahajan's component** (Cloud Dashboard, Data Logging & Session Analytics)
> EEE F411 IoT Lab · BITS Pilani Hyderabad · 2026–27 Semester I

A FastAPI + SQLite backend and a mobile-first dashboard for the **PostureGuard** wearable
posture monitor, exposed to the internet via a **Cloudflare Tunnel** running on your laptop.
No cloud account, no credit card, no server needed — just leave a terminal open during wear
trials.

---

## Architecture

```
ESP32 (wearable node)            NodeMCU (desk station)
        │  POST /api/wearable             │  POST /api/desk
        │  X-API-Key header               │  X-API-Key header
        └──────────────┬──────────────────┘
                       │  HTTPS (Cloudflare edge)
                       ▼
             ┌──────────────────────┐
             │  cloudflared         │  ← free tunnel process on your laptop
             │  (tunnel daemon)     │
             └────────┬─────────────┘
                      │  HTTP (localhost)
                      ▼
             ┌──────────────────────┐
             │  uvicorn / FastAPI   │  ← also serves /dashboard/
             │  localhost:8000      │
             └────────┬─────────────┘
                      │  SQLAlchemy ORM
                      ▼
             ┌──────────────────────┐
             │  SQLite              │  ← postureguard.db (project folder)
             │  (local file)        │
             └──────────────────────┘
                      │  GET /api/*
                      ▼
             ┌──────────────────────┐
             │  Dashboard browser   │  ← your phone, any device
             └──────────────────────┘
```

---

## Project Structure

```
├── backend/
│   ├── main.py          FastAPI app; mounts dashboard as static site
│   ├── database.py      SQLAlchemy engine (SQLite by default)
│   ├── models.py        ORM tables: wearable_readings, desk_readings
│   ├── auth.py          X-API-Key dependency
│   ├── schemas.py       Pydantic v2 request/response models
│   ├── scoring.py       Posture scoring logic (isolated, documented)
│   └── routers/
│       ├── ingest.py    POST /api/wearable, POST /api/desk
│       └── query.py     GET  /api/session/*, /api/history, /api/desk/current
├── dashboard/
│   ├── index.html       Single-page dashboard (mobile-first)
│   └── app.js           Polling, Chart.js, localStorage API-key flow
├── render.yaml          Kept for reference — NOT the active deploy path
├── requirements.txt     Python dependencies (no DB driver needed for SQLite)
├── .env.example         Environment variable template
├── seed_demo_data.py    Populate the DB with realistic demo data
└── README.md            ← you are here
```

---

## Step 1 — Install cloudflared

`cloudflared` is the free Cloudflare tunnel daemon. Install it once; it gives any
localhost port a real public HTTPS URL instantly.

### Option A — winget (Windows 10/11, recommended)
```powershell
winget install --id Cloudflare.cloudflared -e
```
Then open a **new** terminal so the PATH update takes effect.

### Option B — Chocolatey
```powershell
choco install cloudflared
```

### Option C — Direct download (no package manager)
1. Go to https://github.com/cloudflare/cloudflared/releases/latest
2. Download **cloudflared-windows-amd64.exe**
3. Rename it to `cloudflared.exe` and place it anywhere on your PATH
   (e.g. `C:\Windows\System32\` or your project folder).

Verify the install:
```powershell
cloudflared --version
# Expected: cloudflared version 2024.x.x
```

> [!NOTE]
> You do **not** need a Cloudflare account or any configuration file for the
> "quick tunnel" used here. A free Cloudflare account (email only, no credit card)
> is required only if you want a stable named tunnel with a fixed URL — see the
> "Stable URL" note below.

---

## Step 2 — Set up the Python environment

```powershell
# Clone the repo (if you haven't already)
git clone https://github.com/amjn1/postureguard-backend.git
cd postureguard-backend

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # PowerShell / cmd
# source .venv/bin/activate     # macOS / Linux

# Install dependencies (no DB driver needed — SQLite is built into Python)
pip install -r requirements.txt

# Copy the env template and set your API key
copy .env.example .env
```

Edit `.env`:
```
DATABASE_URL=sqlite:///./postureguard.db
API_KEY=paste-your-key-here
```

Generate a strong API key:
```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

> [!IMPORTANT]
> The database file (`postureguard.db`) is created automatically in the project folder
> the first time the server starts. It is excluded from git by `.gitignore` — your data
> stays local.

---

## Step 3 — Start the backend

```powershell
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Confirm it's alive:
```powershell
curl http://localhost:8000/health
# {"status":"ok","service":"postureguard-api"}
```

Open the dashboard locally:
```
http://localhost:8000/dashboard/
```

---

## Step 4 — Start the Cloudflare Tunnel

In a **second terminal**, run:

```powershell
cloudflared tunnel --url http://localhost:8000
```

Watch the output — the public URL appears within a few seconds:

```
2026-09-22T21:00:00Z INF  |  Thank you for trying Cloudflare Tunnel.
2026-09-22T21:00:02Z INF  +--------------------------------------------------+
2026-09-22T21:00:02Z INF  |  Your quick Tunnel has been created! Visit it at  |
2026-09-22T21:00:02Z INF  |  https://example-random-words.trycloudflare.com   |  ← your URL
2026-09-22T21:00:02Z INF  +--------------------------------------------------+
```

The URL format is always `https://<random-words>.trycloudflare.com`.
**Copy that URL** — it's what the ESP32 and dashboard need.

### Spot the URL quickly
The URL always appears on the line containing `trycloudflare.com`. If the output
scrolls, scroll up a few lines or grep for it:
```powershell
cloudflared tunnel --url http://localhost:8000 2>&1 | Tee-Object -Variable tunnelLog
# or after starting, filter in a new terminal:
$tunnelLog | Select-String "trycloudflare"
```

### ⚠️ The URL changes every time you restart

Quick tunnels generate a **new random URL each restart**. This means:

- You must update the firmware URL in the ESP32/NodeMCU sketch each time.
- You must re-enter or update the base URL if you bookmarked the dashboard.

**During active wear trials:** leave both terminals running. The URL is stable
for the entire session.

**For a fixed URL:** create a free Cloudflare account (email only, no credit
card), then follow the "Named Tunnel" guide at
https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/
— you get a permanent subdomain like `postureguard.yourdomain.com`.

---

## Step 5 — Keep it running during wear trials

### Option A — Leave the terminals open (simplest)
Just keep both terminal windows open on your laptop during the trial.
Minimize them — the server keeps running.

### Option B — Windows Task Scheduler (runs in background, survives minimise)

Create a helper script `start_postureguard.bat` in the project folder:

```bat
@echo off
:: Start uvicorn in the background
start "PostureGuard API" /MIN cmd /c "cd /d D:\Code\IOT && .venv\Scripts\activate && uvicorn backend.main:app --host 0.0.0.0 --port 8000"

:: Wait 3 seconds for the server to boot, then start the tunnel
timeout /t 3 /nobreak >nul
start "Cloudflare Tunnel" /MIN cmd /c "cloudflared tunnel --url http://localhost:8000"

echo PostureGuard started. Check the Cloudflare Tunnel window for the public URL.
```

Run it once manually to get the URL, then leave both windows minimised.

To schedule it to start automatically when you log in:
1. Open **Task Scheduler** → Create Basic Task
2. Trigger: **At log on**
3. Action: **Start a program** → browse to `start_postureguard.bat`
4. Finish. The server and tunnel will start automatically next login.

---

## Test with curl (before hardware is ready)

Use `localhost:8000` for quick local tests, or the tunnel URL to test end-to-end:

### POST a GOOD posture reading
```bash
curl -X POST http://localhost:8000/api/wearable \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "device_id":      "wearable_01",
    "timestamp":      "2026-09-22T15:30:00Z",
    "phi":            6.2,
    "phi_baseline":   5.0,
    "posture_state":  "GOOD",
    "activity_state": "SEATED",
    "alert_fired":    false
  }'
```

### POST a SLOUCH reading (alert fired)
```bash
curl -X POST http://localhost:8000/api/wearable \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "device_id":      "wearable_01",
    "timestamp":      "2026-09-22T15:31:00Z",
    "phi":            22.5,
    "phi_baseline":   5.0,
    "posture_state":  "SLOUCH",
    "activity_state": "SEATED",
    "alert_fired":    true
  }'
```

### POST a desk station reading
```bash
curl -X POST http://localhost:8000/api/desk \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "device_id":          "desk_01",
    "timestamp":          "2026-09-22T15:30:00Z",
    "screen_distance_cm": 55.2,
    "lux":                310,
    "temperature_c":      24.1,
    "humidity_pct":       48.0
  }'
```

### Seed 7 days of demo data
```powershell
python seed_demo_data.py --url http://localhost:8000 --key YOUR_API_KEY --no-warmup
```

---

## Point the ESP32 / NodeMCU at the tunnel

In your teammate's firmware, set:

```cpp
// Update this URL each time the tunnel restarts.
// Format: https://<random-words>.trycloudflare.com
const char* SERVER_URL = "https://example-random-words.trycloudflare.com";
const char* API_KEY    = "YOUR_API_KEY";

// Wearable POST:
//   POST <SERVER_URL>/api/wearable
//   Header: X-API-Key: <API_KEY>

// Desk station POST:
//   POST <SERVER_URL>/api/desk
```

> [!TIP]
> To avoid reflashing the ESP32 every time the tunnel URL changes, store the
> server URL in the ESP32's non-volatile storage (Preferences library) and add
> a simple Serial command to update it without recompiling — or just use a named
> Cloudflare tunnel with a fixed URL (see Step 4 above).

---

## API Reference

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/wearable` | ✓ | Ingest wearable reading |
| `POST` | `/api/desk`     | ✓ | Ingest desk station reading |
| `GET`  | `/api/session/current` | ✓ | Live posture snapshot |
| `GET`  | `/api/session/current/chart` | ✓ | φ time-series for session chart |
| `GET`  | `/api/session/{YYYY-MM-DD}` | ✓ | Daily posture analytics |
| `GET`  | `/api/history?range=7d` | ✓ | Multi-day history (bar chart) |
| `GET`  | `/api/desk/current` | ✓ | Latest desk station reading |
| `GET`  | `/health` | — | Liveness check |
| `GET`  | `/docs`   | — | Interactive OpenAPI docs (Swagger UI) |

Auth = requires `X-API-Key` header.

---

## Local Development

```powershell
# Activate your venv, then:
uvicorn backend.main:app --reload --port 8000

# Dashboard: http://localhost:8000/dashboard/
# API docs:  http://localhost:8000/docs
```

`--reload` restarts the server automatically when you edit any Python file.

---

## Posture Scoring — Formulas (for the Project Report)

All scoring logic lives in [`backend/scoring.py`](backend/scoring.py) with full docstrings.

### Session Definition

A **session** is a contiguous block of wearable readings with no gap longer than
**5 minutes** between consecutive readings. A lunch break ends the session;
a brief WiFi dropout does not.

### % Time in Good Posture

$$
\text{Good Posture \%} = \frac{\sum \text{seconds in GOOD state while SEATED}}{\sum \text{seconds in SEATED activity state}} \times 100
$$

**Why WALKING and TRANSITION are excluded:** Seated posture is what the device is
designed to correct. Including walking time would dilute the metric. The score
answers: *"of the time I was sitting at my desk, what fraction was in good posture?"*

### Slouch Events per Hour

A **slouch event** is the *rising edge* of `alert_fired` — the first reading where
`alert_fired = True` after one or more `False` readings. A prolonged slouch counts
as **one** event regardless of how many readings it spans.

$$
\text{Slouch events / hour} = \frac{\text{number of distinct alert episodes}}{\text{total SEATED hours in session/day}}
$$

Normalising per hour makes the rate comparable across sessions of different lengths.

### Why both metrics?

| Metric | Answers |
|--------|---------|
| % good posture | "How well did I sit overall?" |
| Slouch events/hour | "How often did I start slouching?" |

A user can have high % good posture but a high event rate (corrected quickly
each time) or a low event rate but mediocre % (slouched for long uninterrupted
stretches). Both together give a richer picture.

---

## Alternative: Render.com (cloud hosting)

`render.yaml` is kept in the repo for reference. To restore a cloud deployment:

1. Uncomment `psycopg2-binary` in `requirements.txt`
2. Update `DATABASE_URL` in `.env` (and Render env vars) to a `postgresql://` URL
3. Follow the Blueprint deploy steps that were originally in this README
   (they are still documented in `render.yaml` as inline comments)

> [!NOTE]
> Render's free PostgreSQL database expires **90 days** after creation.
> SQLite on your own machine has no such limit.
