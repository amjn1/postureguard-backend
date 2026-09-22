"""
models.py — SQLAlchemy ORM table definitions.

Two tables mirror the two device types in the PostureGuard system:

  wearable_readings  — one row per ESP32 POST  (~1 Hz while the user is active)
  desk_readings      — one row per NodeMCU POST (~every 30 s)

Both tables include a server-side `received_at` column so latency between
the device clock and server receipt can be diagnosed without any firmware
changes.

Tables are created automatically on startup via Base.metadata.create_all()
in main.py — no separate migration step is required for a fresh deploy.
"""

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, func

from .database import Base


class WearableReading(Base):
    """
    One row per reading from the ESP32 wearable node.

    Fields mirror the JSON the firmware POSTs (see schemas.WearablePayload).
    The `received_at` column is set by the database server, not the device.
    """

    __tablename__ = "wearable_readings"

    id = Column(Integer, primary_key=True, index=True)

    # Which device sent this (allows multiple wearables in the future).
    device_id = Column(String(64), nullable=False, index=True)

    # Device-reported UTC timestamp, parsed from the firmware's ISO-8601 string.
    # Indexed because every query filters or orders by this column.
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    # φ = θ_upper − θ_lower  (spinal flexion angle, degrees)
    # See proposal §2.3 for the complementary-filter derivation.
    phi = Column(Float, nullable=False)

    # Per-user neutral baseline captured during the one-press calibration.
    phi_baseline = Column(Float, nullable=False)

    # Firmware-classified posture state: "GOOD" or "SLOUCH".
    # SLOUCH is declared when φ − φ_baseline > φ_th sustained for t > t_hold.
    posture_state = Column(String(16), nullable=False)

    # Firmware-classified activity state: "SEATED", "TRANSITION", or "WALKING".
    # Derived from gyroscope angular-rate magnitude (motion gating).
    activity_state = Column(String(16), nullable=False)

    # True for the sample(s) on which the haptic vibration alert fires.
    # The firmware already applies the t_hold timer; this field is the result.
    alert_fired = Column(Boolean, nullable=False, default=False)

    # Server-side receipt time — compare with `timestamp` to measure latency.
    received_at = Column(DateTime(timezone=True), server_default=func.now())


class DeskReading(Base):
    """
    One row per reading from the NodeMCU desk-station node.

    All sensor fields are nullable — the NodeMCU may omit sensors that are
    not wired in a given hardware configuration, and partial readings are
    still worth storing.
    """

    __tablename__ = "desk_readings"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(64), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    # HC-SR04 ultrasonic — head-to-screen distance in centimetres.
    screen_distance_cm = Column(Float, nullable=True)

    # LDR-derived illuminance proxy in lux.
    lux = Column(Float, nullable=True)

    # DHT22 — ambient temperature (°C) and relative humidity (%).
    temperature_c = Column(Float, nullable=True)
    humidity_pct = Column(Float, nullable=True)

    received_at = Column(DateTime(timezone=True), server_default=func.now())
