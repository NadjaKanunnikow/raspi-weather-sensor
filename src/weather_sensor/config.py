"""Configuration loaded from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    sensor_type: str
    sensor_id: str
    dht_pin: str
    endpoint_url: str | None
    api_key: str | None
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

    return Settings(
        sensor_type=os.getenv("SENSOR_TYPE", "mock").strip().lower(),
        sensor_id=os.getenv("SENSOR_ID", "classroom-pi-01"),
        dht_pin=os.getenv("DHT_PIN", "D4"),
        endpoint_url=endpoint_url,
        api_key=api_key,
        interval_seconds=int(os.getenv("INTERVAL_SECONDS", "60")),
        output_path=Path(os.getenv("OUTPUT_PATH", "data/latest_reading.json")),
        run_once=_get_bool("RUN_ONCE", True),
    )
