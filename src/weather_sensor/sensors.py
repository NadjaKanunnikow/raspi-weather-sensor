"""Sensor adapters.

Use MockSensor on a laptop. Use DhtSensor on the Raspberry Pi with a DHT11 or DHT22.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
import time


@dataclass(frozen=True)
class SensorReading:
    temperature_c: float
    humidity_percent: float


class WeatherSensor:
    def read(self) -> SensorReading:
        raise NotImplementedError


class MockSensor(WeatherSensor):
    """Fake readings for local development without Raspberry Pi hardware."""

    def read(self) -> SensorReading:
        return SensorReading(
            temperature_c=round(random.uniform(19.0, 24.0), 2),
            humidity_percent=round(random.uniform(35.0, 65.0), 2),
        )


class DhtSensor(WeatherSensor):
    """Read a DHT11 or DHT22 sensor via Adafruit CircuitPython."""

    def __init__(self, sensor_type: str, pin_name: str) -> None:
        try:
            import adafruit_dht  # type: ignore
            import board  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "DHT dependencies are missing. On the Raspberry Pi install: "
                "pip install -r requirements-pi-dht.txt"
            ) from exc

        if not hasattr(board, pin_name):
            raise ValueError(f"Unknown board pin '{pin_name}'. Example: D4 for GPIO4.")

        pin = getattr(board, pin_name)

        if sensor_type == "dht11":
            self._device = adafruit_dht.DHT11(pin)
            self._sensor_name = "DHT11"
        elif sensor_type == "dht22":
            self._device = adafruit_dht.DHT22(pin)
            self._sensor_name = "DHT22"
        else:
            raise ValueError("sensor_type must be 'dht11' or 'dht22'.")

    def read(self) -> SensorReading:
        # DHT sensors can occasionally return None or transient RuntimeError values.
        # Wait at least 2 seconds before a retry so the library/sensor can provide a fresh value.
        for attempt in range(3):
            try:
                temperature_c = self._device.temperature
                humidity_percent = self._device.humidity
                if temperature_c is not None and humidity_percent is not None:
                    return SensorReading(
                        temperature_c=float(temperature_c),
                        humidity_percent=float(humidity_percent),
                    )
            except RuntimeError:
                if attempt == 2:
                    raise
                time.sleep(2)

        raise RuntimeError(f"{self._sensor_name} did not return a valid reading")


def create_sensor(sensor_type: str, dht_pin: str) -> WeatherSensor:
    normalized_sensor_type = sensor_type.strip().lower()

    if normalized_sensor_type == "mock":
        return MockSensor()

    if normalized_sensor_type in {"dht11", "dht22"}:
        return DhtSensor(normalized_sensor_type, dht_pin)

    raise ValueError(
        f"Unsupported SENSOR_TYPE '{sensor_type}'. Use 'mock', 'dht11', or 'dht22'."
    )
