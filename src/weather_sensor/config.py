"""Configuration loaded from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    sensor_type: str
    device_id: str
    dht_pin: str
    endpoint_url: Optional[str]
    api_key: Optional[str]
    interval_seconds: int
    output_path: Path
    run_once: bool


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_settings() -> Settings:
    load_dotenv()

    endpoint_url = os.getenv("ENDPOINT_URL") or None
    api_key = os.getenv("API_KEY") or None

    # DEVICE_ID is the preferred variable because the C# backend expects DeviceId.
    # SENSOR_ID is kept as a fallback for older .env files.
    device_id = os.getenv("DEVICE_ID") or os.getenv("SENSOR_ID") or "joypi-01"

    return Settings(
        sensor_type=os.getenv("SENSOR_TYPE", "mock").strip().lower(),
        device_id=device_id.strip(),
        dht_pin=os.getenv("DHT_PIN", "4").strip(),
        endpoint_url=endpoint_url,
        api_key=api_key,
        interval_seconds=int(os.getenv("INTERVAL_SECONDS", "60")),
        output_path=Path(os.getenv("OUTPUT_PATH", "data/latest_measurement.json")),
        run_once=_get_bool("RUN_ONCE", True),
    )