"""
routers/ingest.py — Data ingestion endpoints.

POST /api/wearable   Accepts readings from the ESP32 wearable node (~1 Hz)
POST /api/desk       Accepts readings from the NodeMCU desk station (~every 30 s)

Both routes:
  • Require the X-API-Key header (via the require_api_key dependency).
  • Validate the JSON body with the corresponding Pydantic schema — any
    malformed payload returns HTTP 422 with a descriptive error before the
    database is touched.
  • Write a single row and return {"status": "ok"} with HTTP 201.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..auth import require_api_key
from ..database import get_db
from ..models import DeskReading, WearableReading
from ..schemas import DeskPayload, WearablePayload

router = APIRouter(tags=["ingest"])


@router.post(
    "/api/wearable",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
    summary="Ingest a wearable node reading",
    response_description="Row written successfully",
)
def ingest_wearable(payload: WearablePayload, db: Session = Depends(get_db)):
    """
    Called by the ESP32 wearable node approximately once per second while active.

    The firmware handles all sensor fusion (complementary filter), differential
    angle computation (φ = θ_upper − θ_lower), motion gating, and the t_hold
    timer before sending this payload.  This endpoint simply persists the
    already-processed result — no re-computation on the server side.
    """
    row = WearableReading(
        device_id=payload.device_id,
        timestamp=payload.timestamp,
        phi=payload.phi,
        phi_baseline=payload.phi_baseline,
        posture_state=payload.posture_state,
        activity_state=payload.activity_state,
        alert_fired=payload.alert_fired,
    )
    db.add(row)
    db.commit()
    return {"status": "ok"}


@router.post(
    "/api/desk",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
    summary="Ingest a desk station reading",
    response_description="Row written successfully",
)
def ingest_desk(payload: DeskPayload, db: Session = Depends(get_db)):
    """
    Called by the NodeMCU desk station approximately every 30 seconds.

    All sensor fields (screen distance, lux, temperature, humidity) are
    nullable — the NodeMCU may omit sensors that are not wired, and partial
    readings are still worth storing for trend analysis.
    """
    row = DeskReading(
        device_id=payload.device_id,
        timestamp=payload.timestamp,
        screen_distance_cm=payload.screen_distance_cm,
        lux=payload.lux,
        temperature_c=payload.temperature_c,
        humidity_pct=payload.humidity_pct,
    )
    db.add(row)
    db.commit()
    return {"status": "ok"}
