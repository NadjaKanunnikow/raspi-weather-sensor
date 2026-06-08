import math

import time

from datetime import datetime, timezone
 
import requests

import board

import adafruit_dht

import RPi.GPIO as GPIO
 
# ============================================================

# Backend Verbindung

# ============================================================
 
API_BASE_URL = "https://taupunkt-dashboard.onrender.com"

API_KEY = "uPjeeFqBfG/9V5ddXLzZ2pCCATf2Bc9JpbPvrO5t7hs="
 
MEASUREMENTS_API_URL = f"{API_BASE_URL}/api/measurements"
 
API_HEADERS = {

    "X-API-Key": API_KEY,

    "Content-Type": "application/json",

}
 
# ============================================================

# GPIO Pins

# ============================================================
 
INSIDE_PIN = board.D4

OUTSIDE_PIN = board.D26
 
FAN_PIN = 21
 
# ============================================================

# Logik

# ============================================================
 
DEWPOINT_DIFF_ON = 4.0

DEWPOINT_DIFF_OFF = 3.0
 
MEASUREMENT_INTERVAL_SECONDS = 5

SENSOR_DELAY_SECONDS = 2
 
 
def dew_point_c(temp_c: float, hum_percent: float) -> float:

    a = 17.62

    b = 243.12

    gamma = (a * temp_c) / (b + temp_c) + math.log(hum_percent / 100.0)

    return (b * gamma) / (a - gamma)
 
 
def plausible(temp_c: float, hum_percent: float) -> bool:

    return (-10.0 <= temp_c <= 60.0) and (1.0 <= hum_percent <= 100.0)
 
 
def save_measurement(

    device_id: str,

    measurement_location: str,

    temperature: float,

    humidity: float,

    dew_point: float,

    fan_on: bool,

    measured_at: str

) -> None:

    payload = {

        "deviceId": device_id,
 
        # Важно для backend/frontend:

        # inside  = Innen

        # outside = Außen

        "measurementLocation": measurement_location,
 
        # Эти поля backend читает напрямую

        "temperature": temperature,

        "humidity": humidity,

        "measuredAt": measured_at,
 
        # Дополнительные данные.

        # Backend сохранит их в raw payload, если используется PostgreSQL.

        "dewPointC": dew_point,

        "fanOn": fan_on

    }
 
    response = requests.post(

        MEASUREMENTS_API_URL,

        headers=API_HEADERS,

        json=payload,

        timeout=10

    )
 
    if response.status_code not in (200, 201, 204):

        print(f"Backend Fehler ({measurement_location}): {response.status_code}")

        print(response.text)

        return
 
    print(f"Gespeichert: {measurement_location}")
 
 
def main():

    GPIO.setwarnings(False)

    GPIO.setmode(GPIO.BCM)

    GPIO.cleanup()
 
    GPIO.setup(FAN_PIN, GPIO.OUT)
 
    # Relais vermutlich active-low:

    # HIGH = AUS

    # LOW = EIN

    GPIO.output(FAN_PIN, GPIO.HIGH)
 
    dht_inside = adafruit_dht.DHT22(INSIDE_PIN)

    dht_outside = adafruit_dht.DHT22(OUTSIDE_PIN)
 
    fan_on = False
 
    print("Taupunkt Messung gestartet")

    print(f"Backend URL: {MEASUREMENTS_API_URL}")

    print("=" * 50)
 
    while True:

        try:

            # Innen messen

            temperature_inside = dht_inside.temperature

            humidity_inside = dht_inside.humidity
 
            time.sleep(SENSOR_DELAY_SECONDS)
 
            # Außen messen

            temperature_outside = dht_outside.temperature

            humidity_outside = dht_outside.humidity
 
            if None in (

                temperature_inside,

                humidity_inside,

                temperature_outside,

                humidity_outside

            ):

                print("Sensor liefert None, retry...")

                time.sleep(SENSOR_DELAY_SECONDS)

                continue
 
            if (

                not plausible(temperature_inside, humidity_inside) or

                not plausible(temperature_outside, humidity_outside)

            ):

                print("Unplausible Werte, übersprungen")

                time.sleep(SENSOR_DELAY_SECONDS)

                continue
 
            dew_point_inside = dew_point_c(temperature_inside, humidity_inside)

            dew_point_outside = dew_point_c(temperature_outside, humidity_outside)
 
            dew_point_difference = dew_point_inside - dew_point_outside
 
            if not fan_on and dew_point_difference >= DEWPOINT_DIFF_ON:

                fan_on = True

                GPIO.output(FAN_PIN, GPIO.LOW)   # EIN
 
            elif fan_on and dew_point_difference <= DEWPOINT_DIFF_OFF:

                fan_on = False

                GPIO.output(FAN_PIN, GPIO.HIGH)  # AUS
 
            measured_at = datetime.now(timezone.utc).isoformat()
 
            print(f"Zeit:              {measured_at}")

            print("-" * 50)

            print(f"Innen Temp:        {temperature_inside:5.1f} °C")

            print(f"Innen Feuchte:     {humidity_inside:5.1f} %")

            print(f"Innen Taupunkt:    {dew_point_inside:5.1f} °C")

            print("-" * 50)

            print(f"Außen Temp:        {temperature_outside:5.1f} °C")

            print(f"Außen Feuchte:     {humidity_outside:5.1f} %")

            print(f"Außen Taupunkt:    {dew_point_outside:5.1f} °C")

            print("-" * 50)

            print(f"Differenz:         {dew_point_difference:5.2f} °C")

            print(f"Lüfter:            {'AN' if fan_on else 'AUS'}")

            print("=" * 50)
 
            save_measurement(

                device_id="raspberry-pi-inside",

                measurement_location="inside",

                temperature=temperature_inside,

                humidity=humidity_inside,

                dew_point=dew_point_inside,

                fan_on=fan_on,

                measured_at=measured_at

            )
 
            save_measurement(

                device_id="raspberry-pi-outside",

                measurement_location="outside",

                temperature=temperature_outside,

                humidity=humidity_outside,

                dew_point=dew_point_outside,

                fan_on=fan_on,

                measured_at=measured_at

            )
 
            print("Alle Messwerte gespeichert\n")
 
        except RuntimeError as error:

            print("Sensorfehler:", error)
 
        except Exception as error:

            print("Fataler Fehler:", error)
 
            GPIO.output(FAN_PIN, GPIO.HIGH)

            GPIO.cleanup()

            break
 
        time.sleep(MEASUREMENT_INTERVAL_SECONDS)
 
 
if __name__ == "__main__":

    main()
 