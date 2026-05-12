import time
import board
import adafruit_dht

sensor = adafruit_dht.DHT22(board.D4, use_pulseio=False)

while True:
    try:
        temperature = sensor.temperature
        humidity = sensor.humidity

        print("temperature:", temperature, "humidity:", humidity)

    except RuntimeError as error:
        print("RuntimeError:", error)

    except Exception as error:
        sensor.exit()
        raise error

    time.sleep(2)
import time
import board
import adafruit_dht

sensor = adafruit_dht.DHT22(board.D4, use_pulseio=False)

while True:
    try:
        temperature = sensor.temperature
        humidity = sensor.humidity

        print("temperature:", temperature, "humidity:", humidity)

    except RuntimeError as error:
        print("RuntimeError:", error)

    except Exception as error:
        sensor.exit()
        raise error

    time.sleep(2)
