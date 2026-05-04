# Raspberry Pi Weather Sensor

Reads temperature and humidity, calculates the dew point, writes the latest reading to a JSON file, and sends it to a backend endpoint.

## Important hardware note

A Raspberry Pi does **not** have a built-in air humidity sensor. You need an external sensor.

This starter repo supports:

- `mock` mode for local testing without hardware
- `dht11` mode for a Raspberry Pi with a DHT11 sensor
- `dht22` mode for a Raspberry Pi with a DHT22/AM2302 sensor

For your current project, use `dht11`.

## Local test on your laptop

Use mock mode on your laptop, because the DHT11 is only connected to the Raspberry Pi.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
cp .env.example .env
```

Change this in `.env` for local testing:

```env
SENSOR_TYPE=mock
ENDPOINT_URL=http://localhost:3000/api/readings
```

Start once:

```bash
python -m weather_sensor.main
```

If you run the Express backend locally at `http://localhost:3000`, the script posts to `/api/readings`.

## Raspberry Pi setup for DHT11

Example wiring for DHT11:

| DHT11 pin | Raspberry Pi |
|---|---|
| VCC / + | 3.3V or 5V depending on your module |
| DATA / OUT | GPIO4 |
| GND / - | GND |

In the `.env`, GPIO4 is written as:

```env
DHT_PIN=D4
```

Many DHT11 modules already include a pull-up resistor. If you use a bare DHT11 sensor, add a pull-up resistor between VCC and DATA.

```bash
git clone YOUR_SENSOR_REPO_URL
cd YOUR_SENSOR_REPO
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-pi-dht.txt
pip install -e .
cp .env.example .env
nano .env
```

Set:

```env
SENSOR_TYPE=dht11
DHT_PIN=D4
ENDPOINT_URL=https://YOUR-RENDER-SERVICE.onrender.com/api/readings
API_KEY=the-same-key-as-in-render
RUN_ONCE=false
INTERVAL_SECONDS=60
```

Start:

```bash
python -m weather_sensor.main
```

## Output JSON example

```json
{
  "sensor_id": "classroom-pi-01",
  "timestamp": "2026-05-04T12:00:00+00:00",
  "temperature_c": 22.0,
  "humidity_percent": 51.0,
  "dew_point_c": 11.6
}
```

## Notes about DHT11

The DHT11 is okay for a school project, but it is less precise than a DHT22 or BME280. For this project that is fine, because the goal is to learn the full chain: sensor -> Python -> JSON -> HTTP endpoint -> database -> chart.
