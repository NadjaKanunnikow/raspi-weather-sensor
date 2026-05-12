"""Sensor adapters.

Use MockSensor on a laptop.
Use Dht22Sensor on the Raspberry Pi / Joy-Pi when using DHT22 or AM2302.
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


class Dht22Sensor(WeatherSensor):
    """Read a DHT22 / AM2302 compatible sensor.

    For GPIO4 use DHT_PIN=4 or DHT_PIN=D4 in the .env file.
    """

    def __init__(
        self,
        pin_name: str = "D4",
        max_retries: int = 20,
        retry_delay_seconds: float = 2.0,
    ) -> None:
        try:
            import adafruit_dht  # type: ignore
            import board  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "DHT22 dependencies are missing. Install them with: "
                "pip install -r requirements-pi-dht.txt"
            ) from exc

        normalized_pin_name = _normalize_board_pin(pin_name)

        if not hasattr(board, normalized_pin_name):
            raise ValueError(
                f"Board pin '{normalized_pin_name}' does not exist. "
                "For GPIO4 use DHT_PIN=4 or DHT_PIN=D4."
            )

        board_pin = getattr(board, normalized_pin_name)

        self._device = adafruit_dht.DHT22(board_pin, use_pulseio=False)
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds

        time.sleep(2.0)

    def read(self) -> SensorReading:
        last_error = None

        for attempt in range(1, self._max_retries + 1):
            try:
                temperature = self._device.temperature
                humidity = self._device.humidity

                if temperature is None or humidity is None:
                    last_error = f"empty reading on attempt {attempt}"
                    print(f"Rejected DHT22 reading: {last_error}")

                elif _is_plausible(float(temperature), float(humidity)):
                    return SensorReading(
                        temperature_c=float(temperature),
                        humidity_percent=float(humidity),
                    )

                else:
                    last_error = (
                        f"implausible reading on attempt {attempt}: "
                        f"temperature={temperature}, humidity={humidity}"
                    )
                    print(f"Rejected DHT22 reading: {last_error}")

            except RuntimeError as exc:
                last_error = str(exc)
                print(f"Rejected DHT22 reading on attempt {attempt}: {exc}")

            time.sleep(self._retry_delay_seconds)

        raise RuntimeError(
            f"Could not read plausible DHT22 data after "
            f"{self._max_retries} attempts. Last error: {last_error}"
        )


def _is_plausible(temperature: float, humidity: float) -> bool:
    """Reject obviously wrong indoor readings."""
    return 5.0 <= temperature <= 45.0 and 10.0 <= humidity <= 100.0


def _normalize_board_pin(value: str) -> str:
    """Convert '4' or 'D4' to board pin name 'D4'."""
    normalized = value.strip().upper()

    if normalized.startswith("D"):
        return normalized

    return f"D{normalized}"


def create_sensor(sensor_type: str, dht_pin: str) -> WeatherSensor:
    normalized_sensor_type = sensor_type.strip().lower()

    if normalized_sensor_type == "mock":
        return MockSensor()

    if normalized_sensor_type in {"dht22", "am2302"}:
        return Dht22Sensor(pin_name=dht_pin)

    raise ValueError(
        f"Unsupported SENSOR_TYPE '{sensor_type}'. "
        "Use 'mock', 'dht22', or 'am2302'."
    )
