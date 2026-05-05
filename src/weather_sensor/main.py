"""Read weather data, write JSON, and send it to the C# backend."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from typing import Any, Dict, Tuple

import requests

from weather_sensor.config import Settings, load_settings
from weather_sensor.dew_point import calculate_dew_point_celsius
from weather_sensor.sensors import WeatherSensor, create_sensor


def build_measurement_request(
    settings: Settings,
    sensor: WeatherSensor,
) -> Tuple[Dict[str, Any], float]:
    """Build the JSON payload for the C# MeasurementRequest DTO.

    C# backend record:

        public record MeasurementRequest(
            string? DeviceId,
            double? Temperature,
            double? Humidity,
            DateTimeOffset? CreatedAt
        );

    ASP.NET Core accepts camelCase JSON, so we send:

        deviceId, temperature, humidity, createdAt

    The dew point is calculated locally and returned separately. It is not sent to
    the backend because the current backend DTO does not contain a DewPoint field.
    """
    reading = sensor.read()
    created_at = datetime.now(timezone.utc).isoformat()

    dew_point_c = calculate_dew_point_celsius(
        reading.temperature_c,
        reading.humidity_percent,
    )

    payload = {
        "deviceId": settings.device_id,
        "temperature": round(reading.temperature_c, 2),
        "humidity": round(reading.humidity_percent, 2),
        "createdAt": created_at,
    }

    return payload, round(dew_point_c, 2)


def write_json_file(path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def send_payload(settings: Settings, payload: Dict[str, Any]) -> None:
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
    payload, dew_point_c = build_measurement_request(settings, sensor)

    write_json_file(settings.output_path, payload)

    print("MeasurementRequest payload:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Calculated dew point locally: {dew_point_c} C")

    send_payload(settings, payload)


def main() -> None:
    settings = load_settings()
    sensor = create_sensor(settings.sensor_type, settings.dht_pin)

    while True:
        try:
            run_once(settings, sensor)
        except Exception as exc:
            # Keep the station alive during transient sensor/API errors.
            print(f"ERROR: {exc}")

        if settings.run_once:
            break

        time.sleep(settings.interval_seconds)


if __name__ == "__main__":
    main()