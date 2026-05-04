import time
from dataclasses import dataclass
from random import uniform


@dataclass
class SensorReading:
    temperature_c: float
    humidity_percent: float


class MockSensor:
    def read(self) -> SensorReading:
        return SensorReading(
            temperature_c=round(uniform(20.0, 26.0), 2),
            humidity_percent=round(uniform(35.0, 65.0), 2),
        )


class JoyPiDht11Sensor:
    def __init__(self, pin: int = 4, max_retries: int = 20, retry_delay_seconds: float = 0.5):
        import RPi.GPIO as GPIO
        import dht11

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.cleanup()

        self._instance = dht11.DHT11(pin=pin)
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds

    def read(self) -> SensorReading:
        last_result = None

        for _ in range(self._max_retries):
            result = self._instance.read()
            last_result = result

            if result.is_valid():
                return SensorReading(
                    temperature_c=float(result.temperature),
                    humidity_percent=float(result.humidity),
                )

            time.sleep(self._retry_delay_seconds)

        raise RuntimeError(f"Could not read valid DHT11 data. Last result: {last_result}")


def create_sensor(sensor_type: str, dht_pin: str):
    normalized_sensor_type = sensor_type.lower().strip()

    if normalized_sensor_type == "mock":
        return MockSensor()

    if normalized_sensor_type in ("joypi_dht11", "dht11"):
        return JoyPiDht11Sensor(pin=int(dht_pin))

    raise ValueError(f"Unsupported SENSOR_TYPE: {sensor_type}")