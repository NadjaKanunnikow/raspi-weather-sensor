"""Read weather data, write JSON, and send it to the backend."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from typing import Any

import requests

from weather_sensor.config import load_settings, Settings
from weather_sensor.dew_point import calculate_dew_point_celsius
from weather_sensor.sensors import create_sensor, WeatherSensor


def build_payload(settings: Settings, sensor: WeatherSensor) -> dict[str, Any]:
    reading = sensor.read()
    dew_point_c = calculate_dew_point_celsius(
        reading.temperature_c,
        reading.humidity_percent,
    )

    return {
        "sensor_id": settings.sensor_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "temperature_c": round(reading.temperature_c, 2),
        "humidity_percent": round(reading.humidity_percent, 2),
        "dew_point_c": round(dew_point_c, 2),
    }


def write_json_file(path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def send_payload(settings: Settings, payload: dict[str, Any]) -> None:
    if not settings.endpoint_url:
        print("No ENDPOINT_URL configured; skipped POST.")
        return

    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["X-API-Key"] = settings.api_key

    response = requests.post(
        settings.endpoint_url,
        json=payload,
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    print(f"POST ok: {response.status_code}")


def run_once(settings: Settings, sensor: WeatherSensor) -> None:
    payload = build_payload(settings, sensor)
    write_json_file(settings.output_path, payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    send_payload(settings, payload)


def main() -> None:
    settings = load_settings()
    sensor = create_sensor(settings.sensor_type, settings.dht_pin)

    while True:
        try:
            run_once(settings, sensor)
        except Exception as exc:  # Keep the station alive during transient sensor/API errors.
            print(f"ERROR: {exc}")

        if settings.run_once:
            break

        time.sleep(settings.interval_seconds)


if __name__ == "__main__":
    main()
