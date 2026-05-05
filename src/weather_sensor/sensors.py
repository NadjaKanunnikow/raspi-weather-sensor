"""Sensor adapters.

Use MockSensor on a laptop. Use JoyPiDht11Sensor on the Joy-Pi / Raspberry Pi.
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


class JoyPiDht11Sensor(WeatherSensor):
    """Read the built-in Joy-Pi DHT11 sensor.

    The Joy-Pi manual uses BCM GPIO 4 for the DHT11 sensor:

        instance = dht11.DHT11(pin=4)

    The default DHT_PIN in this project is therefore "4".
    """

    def __init__(
        self,
        pin: int = 4,
        max_retries: int = 20,
        retry_delay_seconds: float = 0.5,
    ) -> None:
        try:
            import RPi.GPIO as GPIO  # type: ignore
            import dht11  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Joy-Pi DHT11 dependencies are missing. On the Raspberry Pi install: "
                "pip install -r requirements-pi-dht.txt"
            ) from exc

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.cleanup()

        self._device = dht11.DHT11(pin=pin)
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds

    def read(self) -> SensorReading:
        last_error = None

        for _ in range(self._max_retries):
            result = self._device.read()

            if result.is_valid():
                return SensorReading(
                    temperature_c=float(result.temperature),
                    humidity_percent=float(result.humidity),
                )

            last_error = getattr(result, "error_code", None)
            time.sleep(self._retry_delay_seconds)

        raise RuntimeError(
            f"Could not read valid DHT11 data after {self._max_retries} attempts. "
            f"Last error code: {last_error}"
        )


def _parse_gpio_pin(value: str) -> int:
    """Parse either "4" or legacy values like "D4" into integer BCM pin 4."""
    normalized = value.strip().upper()

    if normalized.startswith("D"):
        normalized = normalized[1:]

    try:
        return int(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Invalid DHT_PIN '{value}'. Use '4' for the Joy-Pi DHT11 sensor."
        ) from exc


def create_sensor(sensor_type: str, dht_pin: str) -> WeatherSensor:
    normalized_sensor_type = sensor_type.strip().lower()

    if normalized_sensor_type == "mock":
        return MockSensor()

    if normalized_sensor_type in {"joypi_dht11", "dht11"}:
        return JoyPiDht11Sensor(pin=_parse_gpio_pin(dht_pin))

    raise ValueError(
        f"Unsupported SENSOR_TYPE '{sensor_type}'. Use 'mock' or 'joypi_dht11'."
    )