# PostureGuard — Cloud Dashboard

> **Atharva Mahajan's component** (Cloud Dashboard, Data Logging & Session Analytics)
> EEE F411 IoT Lab · BITS Pilani Hyderabad · 2026–27 Semester I

A production-ready cloud backend (FastAPI + PostgreSQL) and a mobile-first
dashboard for the **PostureGuard** wearable posture monitor.  Deployed free on
[Render.com](https://render.com) — no laptop needs to stay on.

---

## Architecture

```
ESP32 (wearable node)          NodeMCU (desk station)
        │  POST /api/wearable          │  POST /api/desk
        │  ~1 Hz, X-API-Key header     │  ~every 30 s
        └──────────────┬───────────────┘
                       ▼
             ┌─────────────────────┐
             │  FastAPI (Render)   │  ← also serves /dashboard/
             │  backend/main.py    │
             └────────┬────────────┘
                      │ SQLAlchemy ORM
                      ▼
             ┌─────────────────────┐
             │  PostgreSQL (Render)│
             │  free-tier DB       │
             └─────────────────────┘
                      │ GET /api/*
                      ▼
             ┌─────────────────────┐
             │  Dashboard browser  │  ← phones, laptops
             │  dashboard/index.html│
             └─────────────────────┘
```

---

## Project Structure

```
├── backend/
│   ├── main.py          FastAPI app; mounts dashboard as static site
│   ├── database.py      SQLAlchemy engine + session factory
│   ├── models.py        ORM tables: wearable_readings, desk_readings
│   ├── auth.py          X-API-Key dependency (shared by all routes)
│   ├── schemas.py       Pydantic v2 request/response models
│   ├── scoring.py       Posture scoring logic (isolated, documented)
│   └── routers/
│       ├── ingest.py    POST /api/wearable, POST /api/desk
│       └── query.py     GET  /api/session/*, /api/history, /api/desk/current
├── dashboard/
│   ├── index.html       Single-page dashboard (mobile-first)
│   └── app.js           Plain JS: polling, Chart.js charts, localStorage key
├── render.yaml          Render Blueprint (one-click deploy)
├── requirements.txt     Python dependencies
├── .env.example         Environment variable template
├── seed_demo_data.py    Seed the DB with realistic demo data
└── README.md            ← you are here
```

---

## Deploy to Render (step-by-step)

### Prerequisites
- A free [Render.com](https://render.com) account
- Your code pushed to a GitHub or GitLab repository

### Step 1 — Connect the repository

1. Go to [dashboard.render.com](https://dashboard.render.com).
2. Click **New → Blueprint**.
3. Connect your GitHub account if prompted, then select your **PostureGuard** repository.
4. Render reads `render.yaml` and shows you two services to create:
   - `postureguard-api` (web service)
   - `postureguard-db`  (PostgreSQL database)
5. Click **Apply**.  Render provisions both and kicks off the first build.

The build installs `requirements.txt` and starts the server.  It takes about
2–3 minutes.  Watch the build logs in real time at
`https://dashboard.render.com/web/<your-service-id>/logs`.

### Step 2 — Set the API key

After the first deploy succeeds:

1. In the Render dashboard, click **postureguard-api → Environment**.
2. Click **Add Environment Variable**.
3. Key: `API_KEY`, Value: a strong random string — generate one with:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
4. Click **Save Changes**, then click **Manual Deploy → Deploy latest commit**.

> [!IMPORTANT]
> Without `API_KEY` set, every ingest request will return HTTP 500.
> Always set it before pointing your devices at the service.

### Step 3 — Confirm it's alive

```bash
curl https://postureguard-api.onrender.com/health
# Expected: {"status":"ok","service":"postureguard-api"}
```

### Step 4 — Open the dashboard

```
https://postureguard-api.onrender.com/dashboard/
```

The page will ask for your API key the first time.  Enter it once — it's
stored in your browser's `localStorage` and you won't be asked again on
that device.

### Step 5 — Seed demo data

Before your hardware is ready, populate the dashboard with realistic fake data:

```bash
# Install httpx if you haven't already
pip install httpx

python seed_demo_data.py \
    --url https://postureguard-api.onrender.com \
    --key YOUR_API_KEY \
    --days 7
```

The script wakes up the Render service automatically (free-tier cold start),
then posts ~7 days of simulated sessions.  Refresh the dashboard when done.

---

## Test with curl (before hardware is ready)

### POST a wearable reading (GOOD posture)
```bash
curl -X POST https://postureguard-api.onrender.com/api/wearable \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "device_id":      "wearable_01",
    "timestamp":      "2026-09-21T10:15:30Z",
    "phi":            6.2,
    "phi_baseline":   5.0,
    "posture_state":  "GOOD",
    "activity_state": "SEATED",
    "alert_fired":    false
  }'
# Expected: {"status":"ok"}
```

### POST a slouch reading (alert fired)
```bash
curl -X POST https://postureguard-api.onrender.com/api/wearable \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "device_id":      "wearable_01",
    "timestamp":      "2026-09-21T10:16:00Z",
    "phi":            22.5,
    "phi_baseline":   5.0,
    "posture_state":  "SLOUCH",
    "activity_state": "SEATED",
    "alert_fired":    true
  }'
```

### POST a desk reading
```bash
curl -X POST https://postureguard-api.onrender.com/api/desk \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "device_id":          "desk_01",
    "timestamp":          "2026-09-21T10:15:30Z",
    "screen_distance_cm": 55.2,
    "lux":                310,
    "temperature_c":      24.1,
    "humidity_pct":       48.0
  }'
```

### Query today's summary
```bash
curl https://postureguard-api.onrender.com/api/session/2026-09-21 \
  -H "X-API-Key: YOUR_API_KEY"
```

---

## Point your ESP32 / NodeMCU at the live URL

In your teammate's firmware, replace the placeholder server URL and key with:

```cpp
const char* SERVER_URL = "https://postureguard-api.onrender.com";
const char* API_KEY    = "YOUR_API_KEY";

// Wearable POST:
// POST https://postureguard-api.onrender.com/api/wearable
// Header: X-API-Key: <key>
// Body:   JSON as specified in the proposal

// Desk station POST:
// POST https://postureguard-api.onrender.com/api/desk
```

> [!NOTE]
> Render free-tier web services spin down after ~15 minutes of inactivity.
> The first POST after a spin-down may take 30–60 s while the container starts.
> Subsequent requests are fast.  The dashboard's auto-refresh will wake the
> service if you check it before the ESP32 sends its first packet.

---

## Known Limitation — Render Free-Tier Spin-Down

Render's free web service goes to sleep after ~15 minutes of no traffic.
The next request (from the ESP32 or your phone) triggers a cold start that
takes 30–60 seconds — during which the ESP32 POST will time out once.

**Mitigation (free, no code changes):**

Use [UptimeRobot](https://uptimerobot.com) (free tier, up to 50 monitors):

1. Create a free account at uptimerobot.com.
2. Add a new **HTTP(s) monitor**:
   - URL: `https://postureguard-api.onrender.com/health`
   - Interval: **every 5 minutes**
3. UptimeRobot pings `/health` every 5 minutes, keeping the service warm.

Alternatively, [cron-job.org](https://cron-job.org) (also free) can be used
the same way with a cron expression `*/5 * * * *`.

> [!NOTE]
> Render's **free PostgreSQL** database is available for **90 days** from
> creation before it is deleted.  Back up your data before that deadline
> (`pg_dump`) or upgrade to a paid plan.

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
| `GET`  | `/docs`   | — | Interactive OpenAPI docs |

Auth = requires `X-API-Key` header.

---

## Local Development

```bash
# 1. Clone the repo and create a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy env template and fill in your local Postgres URL
copy .env.example .env          # Windows
# cp .env.example .env           # macOS / Linux

# 4. Start the server
uvicorn backend.main:app --reload --port 8000

# 5. Open the dashboard
#    http://localhost:8000/dashboard/
# 6. Open the interactive API docs
#    http://localhost:8000/docs

# 7. Seed local DB with demo data
python seed_demo_data.py --url http://localhost:8000 --key testkey --no-warmup
```

---

## Posture Scoring — Formulas (for the Project Report)

This section explains the scoring algorithms in plain terms, suitable for
inclusion in the EEE F411 project report.  All formulas live in
[`backend/scoring.py`](backend/scoring.py) with full docstrings.

### Session Definition

A **session** is a contiguous block of wearable readings in which no two
consecutive readings are more than **5 minutes** apart.  A lunch break or
a long WiFi drop ends the session; a momentary 30-second disconnection does not.

### % Time in Good Posture

$$
\text{Good Posture \%} = \frac{\sum \text{seconds in GOOD state while SEATED}}{\sum \text{seconds in SEATED state}} \times 100
$$

**Why WALKING and TRANSITION are excluded from the denominator:**
Posture while walking or transitioning is biomechanically different from
seated posture; including it would dilute the metric and make it hard to
interpret.  The score answers the question: *"of the time I was sitting at
my desk, what fraction was in good posture?"*

### Slouch Events per Hour

A **slouch event** is counted on the *rising edge* of `alert_fired` — the
first reading where `alert_fired = True` after one or more `False` readings.
A prolonged slouch spanning many readings (say, 3 minutes) counts as **one**
event, not N.

$$
\text{Slouch events / hour} = \frac{\text{number of distinct alert episodes}}{\text{total SEATED hours in session/day}}
$$

Normalising per hour makes the rate comparable across sessions of different
lengths.  Slouching 3 times in 30 minutes (6 events/h) is clearly worse
than 3 times in 3 hours (1 event/h).

### Why Two Metrics?

**% good posture** tells you the *quality* of your seated time — it answers
"how well did I sit?"

**Slouch events/hour** tells you the *frequency of lapses* — it answers
"how often did I forget to sit straight?"

A user could have 70% good posture but a high event rate (they corrected
themselves quickly each time) or a low event rate but 50% good posture
(they slouched for long uninterrupted periods).  Both metrics together give
a richer picture of posture behaviour.
