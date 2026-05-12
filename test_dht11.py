import time
import RPi.GPIO as GPIO
import dht11

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.cleanup()

instance = dht11.DHT11(pin=4)

while True:
    result = instance.read()

    print(
        "valid:",
        result.is_valid(),
        "temperature:",
        getattr(result, "temperature", None),
        "humidity:",
        getattr(result, "humidity", None),
        "error_code:",
        getattr(result, "error_code", None),
    )

    time.sleep(2)
