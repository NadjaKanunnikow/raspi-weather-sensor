"""Advanced Joy-Pi dew-point fan controller.

This file intentionally does not replace taupunktMitLuefter.py.  The old file
stays as the last known-good version; this one adds RFID start/stop, a
7-segment clock, backend control polling, and one-minute backend uploads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timezone
import math
import sys
import time
from typing import Any, Optional


# ============================================================
# Backend connection
# ============================================================

# TODO: Insert the new backend endpoint here when the new site/API/database are
# ready again.  The old Render URL and API key are intentionally not used here.
MEASUREMENTS_API_URL = "https://taupunkt-dashboard.onrender.com/api/measurements"

CONTROL_API_URL = "https://taupunkt-dashboard.onrender.com/api/control"

STATUS_API_URL = "https://taupunkt-dashboard.onrender.com/api/status/health"

# APP_API_KEY from Render → Dashboard → taupunkt-dashboard → Environment
API_KEY = "uPjeeFqBfG/9V5ddXLzZ2pCCATf2Bc9JpbPvrO5t7hs="


# ============================================================
# Joy-Pi hardware
# ============================================================

# DHT22 pins use CircuitPython board names, exactly like the working file.
INSIDE_PIN_NAME = "D4"
OUTSIDE_PIN_NAME = "D26"

# RPi.GPIO BCM mode — same physical pins as before, BCM numbering avoids
# conflicts with MFRC522 and adafruit_blinka which also use BCM mode.
# BOARD 40 = BCM 21, BOARD 11 = BCM 17, BOARD 16 = BCM 23
FAN_PIN_BCM = 21

# Joy-Pi module 19, physical board pin 11 = BCM 17.
TOUCH_PIN_BCM = 17

# Joy-Pi module 12, physical board pin 16 = BCM 23.
MOTION_PIN_BCM = 23

# Joy-Pi BH1750 light sensor.  The Joy-Pi manual uses I2C address 0x5c.
LIGHT_SENSOR_ADDRESS = 0x5C

# Any RFID tag/transponder is accepted.
RFID_RELEASE_SECONDS = 0.8
RFID_TOGGLE_COOLDOWN_SECONDS = 2.0


# ============================================================
# Control logic
# ============================================================

DEWPOINT_DIFF_ON = 4.0
DEWPOINT_DIFF_OFF = 3.0
MANUAL_DEWPOINT_DIFF_MIN = -40.0
MANUAL_DEWPOINT_DIFF_MAX = 60.0
DEWPOINT_THRESHOLD_MIN = -40.0
DEWPOINT_THRESHOLD_MAX = 60.0

MEASUREMENT_INTERVAL_SECONDS = 10
CONTROL_POLL_INTERVAL_SECONDS = 5
SENSOR_RETRY_SECONDS = 5
SENSOR_DELAY_SECONDS = 2
MAIN_LOOP_SLEEP_SECONDS = 0.2
TOUCH_LONG_PRESS_SECONDS = 1.0
TOUCH_DEBOUNCE_SECONDS = 0.05
SEGMENT_OVERRIDE_SECONDS = 5.0    # status (touch short) returns to clock after 5 s
SEGMENT_DEW_POINT_SECONDS = 5.0   # dew-point (touch long) returns to clock after 5 s
LCD_MESSAGE_SECONDS = 5.0
MOTION_COOLDOWN_SECONDS = 10.0
LIGHT_POLL_INTERVAL_SECONDS = 2.0
DARK_LUX_THRESHOLD = 10.0

MODE_AUTOMATIC = "automatic"
MODE_MANUAL = "manual"


@dataclass
class ControllerState:
    active: bool = False
    mode: str = MODE_AUTOMATIC
    fan_on: bool = False
    dew_point_diff_on: float = DEWPOINT_DIFF_ON
    dew_point_diff_off: float = DEWPOINT_DIFF_OFF
    manual_dew_point_difference: Optional[float] = None
    display_time_override: Optional[datetime_time] = None
    preserve_manual_settings_in_automatic: bool = False
    next_measurement_at: float = 0.0
    next_control_poll_at: float = 0.0
    last_dew_point_difference: Optional[float] = None


@dataclass(frozen=True)
class SensorSnapshot:
    measured_at: str
    temperature_inside: float
    humidity_inside: float
    dew_point_inside: float
    temperature_outside: float
    humidity_outside: float
    dew_point_outside: float
    dew_point_difference: float


@dataclass(frozen=True)
class TouchEvent:
    pressed_seconds: float


def dew_point_c(temp_c: float, hum_percent: float) -> float:
    a = 17.62
    b = 243.12
    gamma = (a * temp_c) / (b + temp_c) + math.log(hum_percent / 100.0)
    return (b * gamma) / (a - gamma)


def plausible(temp_c: float, hum_percent: float) -> bool:
    return (-10.0 <= temp_c <= 60.0) and (1.0 <= hum_percent <= 100.0)


def format_uid(uid: tuple[int, int, int, int]) -> str:
    return ",".join(str(part) for part in uid)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def current_thresholds(state: ControllerState) -> tuple[float, float]:
    return state.dew_point_diff_on, state.dew_point_diff_off


def control_dew_point_difference(
    state: ControllerState,
    measured_difference: Optional[float],
) -> Optional[float]:
    if state.mode == MODE_MANUAL and state.manual_dew_point_difference is not None:
        return state.manual_dew_point_difference

    return measured_difference


def set_fan(GPIO, state: ControllerState, fan_on: bool) -> None:
    state.fan_on = fan_on
    GPIO.output(FAN_PIN_BCM, GPIO.LOW if fan_on else GPIO.HIGH)


def apply_fan_logic(
    GPIO,
    state: ControllerState,
    dew_point_difference: float,
) -> None:
    control_difference = control_dew_point_difference(state, dew_point_difference)
    if control_difference is None:
        return

    on_threshold, off_threshold = current_thresholds(state)

    if not state.fan_on and control_difference >= on_threshold:
        set_fan(GPIO, state, True)
    elif state.fan_on and control_difference <= off_threshold:
        set_fan(GPIO, state, False)


def parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True

    if text in {"0", "false", "no", "n", "off"}:
        return False

    return None


def parse_backend_time(value: Any) -> Optional[datetime_time]:
    if value is None:
        return None

    text = str(value).strip()
    for time_format in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, time_format).time()
        except ValueError:
            pass

    return None


def first_float(settings: dict[str, Any], names: tuple[str, ...]) -> Optional[float]:
    for name in names:
        value = parse_float(settings.get(name))
        if value is not None:
            return value

    return None


def first_time(
    settings: dict[str, Any],
    names: tuple[str, ...],
) -> Optional[datetime_time]:
    for name in names:
        value = parse_backend_time(settings.get(name))
        if value is not None:
            return value

    return None


def display_now(state: ControllerState) -> datetime:
    now = datetime.now()
    if state.display_time_override is not None:
        return now.replace(
            hour=state.display_time_override.hour,
            minute=state.display_time_override.minute,
        )

    return now


def display_time_source(state: ControllerState) -> str:
    if state.display_time_override is None:
        return "raspberry-pi"

    return "other"


def apply_backend_control(
    GPIO,
    state: ControllerState,
    settings: dict[str, Any],
) -> None:
    raw_mode = settings.get("mode")
    new_mode = state.mode
    if raw_mode is not None:
        new_mode = str(raw_mode).strip().lower()
        if new_mode not in {MODE_AUTOMATIC, MODE_MANUAL}:
            print(f"Ignored unknown backend mode: {new_mode}")
            return

    manual_difference = first_float(
        settings,
        (
            "manualDewPointDifferenceC",
            "manualDewPointDiffC",
            "manualTaupunktDifferenceC",
            "manualTaupunktDiffC",
            "dewPointDifferenceC",
            "taupunktDifferenceC",
            "taupunktDiffC",
        ),
    )
    threshold_on = first_float(
        settings,
        (
            "dewPointDiffOn",
            "dewPointDifferenceOn",
            "fanOnThresholdC",
        ),
    )
    threshold_off = first_float(
        settings,
        (
            "dewPointDiffOff",
            "dewPointDifferenceOff",
            "fanOffThresholdC",
        ),
    )
    manual_display_time = first_time(
        settings,
        (
            "displayTime",
            "time",
            "clockTime",
        ),
    )
    use_pi_time = parse_bool(settings.get("usePiTime"))
    if use_pi_time is None:
        use_pi_time = parse_bool(settings.get("resetDisplayTime"))
    if use_pi_time is None:
        use_pi_time = parse_bool(settings.get("useRaspberryPiTime"))

    previous_mode = state.mode
    previous_manual_difference = state.manual_dew_point_difference
    previous_display_time = state.display_time_override
    previous_thresholds = current_thresholds(state)
    state.mode = new_mode

    switching_manual_to_automatic = (
        previous_mode == MODE_MANUAL and state.mode == MODE_AUTOMATIC
    )

    if state.mode == MODE_MANUAL:
        state.preserve_manual_settings_in_automatic = False
        if manual_difference is not None:
            state.manual_dew_point_difference = clamp(
                manual_difference,
                MANUAL_DEWPOINT_DIFF_MIN,
                MANUAL_DEWPOINT_DIFF_MAX,
            )
    else:
        # In automatic mode the dew-point difference must always come from the
        # real sensor measurement, even if the website still sends a manual
        # dew-point difference from the previous manual mode.
        state.manual_dew_point_difference = None
        if switching_manual_to_automatic:
            # Keep the fan thresholds and display time that were set while the
            # controller was in manual mode.  Some backends send default auto
            # values after the mode switch; those must not overwrite the
            # website-adjusted manual values.
            state.preserve_manual_settings_in_automatic = True

    should_apply_thresholds_and_time = not (
        state.mode == MODE_AUTOMATIC
        and state.preserve_manual_settings_in_automatic
    )

    if should_apply_thresholds_and_time and threshold_on is not None:
        state.dew_point_diff_on = clamp(
            threshold_on,
            DEWPOINT_THRESHOLD_MIN,
            DEWPOINT_THRESHOLD_MAX,
        )

    if should_apply_thresholds_and_time and threshold_off is not None:
        state.dew_point_diff_off = clamp(
            threshold_off,
            DEWPOINT_THRESHOLD_MIN,
            DEWPOINT_THRESHOLD_MAX,
        )

    if should_apply_thresholds_and_time:
        if use_pi_time:
            state.display_time_override = None
        elif manual_display_time is not None:
            state.display_time_override = manual_display_time

    new_thresholds = current_thresholds(state)

    if (
        previous_mode != state.mode
        or previous_manual_difference != state.manual_dew_point_difference
        or previous_display_time != state.display_time_override
        or previous_thresholds != new_thresholds
    ):
        time_text = (
            state.display_time_override.strftime("%H:%M")
            if state.display_time_override is not None
            else "raspberry-pi"
        )
        manual_text = (
            f"{state.manual_dew_point_difference:.1f} C"
            if state.mode == MODE_MANUAL
            and state.manual_dew_point_difference is not None
            else "real sensors"
        )
        print(
            "Backend control: "
            f"mode={state.mode}, "
            f"control dew-point difference={manual_text}, "
            f"fan ON >= {new_thresholds[0]:.1f} C, "
            f"fan OFF <= {new_thresholds[1]:.1f} C, "
            f"display time={time_text}"
        )

    if state.last_dew_point_difference is not None:
        apply_fan_logic(GPIO, state, state.last_dew_point_difference)


def poll_backend_control(GPIO, state: ControllerState) -> None:
    if not CONTROL_API_URL:
        return

    import requests

    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    try:
        response = requests.get(CONTROL_API_URL, headers=headers, timeout=5)
        response.raise_for_status()
        settings = response.json()
    except Exception as error:
        print(f"Backend control error: {error}")
        return

    if not isinstance(settings, dict):
        print("Backend control ignored: response is not a JSON object.")
        return

    apply_backend_control(GPIO, state, settings)


def backend_status_ok() -> bool:
    status_url = STATUS_API_URL or CONTROL_API_URL
    if not status_url:
        return False

    import requests

    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    try:
        response = requests.get(status_url, headers=headers, timeout=5)
    except Exception as error:
        print(f"Backend status error: {error}")
        return False

    return 200 <= response.status_code < 400


def save_measurement(
    device_id: str,
    measurement_location: str,
    temperature: float,
    humidity: float,
    dew_point: float,
    fan_on: bool,
    measured_at: str,
    control_mode: str,
    dew_point_difference: float,
    control_dew_point_difference_c: float,
    manual_dew_point_difference: Optional[float],
    fan_on_threshold_c: float,
    fan_off_threshold_c: float,
    display_time: str,
    display_time_source_value: str,
) -> None:
    if not MEASUREMENTS_API_URL:
        print(f"Backend not configured; skipped POST ({measurement_location}).")
        return

    import requests

    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    payload = {
        "deviceId": device_id,
        "measurementLocation": measurement_location,
        "temperature": temperature,
        "humidity": humidity,
        "measuredAt": measured_at,
        "dewPointC": dew_point,
        "dewPointDifferenceC": dew_point_difference,
        "controlDewPointDifferenceC": control_dew_point_difference_c,
        "manualDewPointDifferenceC": manual_dew_point_difference,
        "fanOnThresholdC": fan_on_threshold_c,
        "fanOffThresholdC": fan_off_threshold_c,
        "displayTime": display_time,
        "displayTimeSource": display_time_source_value,
        "fanOn": fan_on,
        "controlMode": control_mode,
    }

    response = requests.post(
        MEASUREMENTS_API_URL,
        headers=headers,
        json=payload,
        timeout=10,
    )

    if response.status_code not in (200, 201, 204):
        print(f"Backend error ({measurement_location}): {response.status_code}")
        print(response.text)
        return

    print(f"Saved: {measurement_location}")


def save_snapshot(snapshot: SensorSnapshot, state: ControllerState) -> None:
    control_difference = control_dew_point_difference(
        state,
        snapshot.dew_point_difference,
    )
    if control_difference is None:
        control_difference = snapshot.dew_point_difference

    on_threshold, off_threshold = current_thresholds(state)
    used_display_time = display_now(state).strftime("%H:%M")
    used_display_time_source = display_time_source(state)
    manual_difference_for_backend = (
        state.manual_dew_point_difference
        if state.mode == MODE_MANUAL
        else None
    )

    save_measurement(
        device_id="raspberry-pi-inside",
        measurement_location="inside",
        temperature=snapshot.temperature_inside,
        humidity=snapshot.humidity_inside,
        dew_point=snapshot.dew_point_inside,
        fan_on=state.fan_on,
        measured_at=snapshot.measured_at,
        control_mode=state.mode,
        dew_point_difference=snapshot.dew_point_difference,
        control_dew_point_difference_c=control_difference,
        manual_dew_point_difference=manual_difference_for_backend,
        fan_on_threshold_c=on_threshold,
        fan_off_threshold_c=off_threshold,
        display_time=used_display_time,
        display_time_source_value=used_display_time_source,
    )

    save_measurement(
        device_id="raspberry-pi-outside",
        measurement_location="outside",
        temperature=snapshot.temperature_outside,
        humidity=snapshot.humidity_outside,
        dew_point=snapshot.dew_point_outside,
        fan_on=state.fan_on,
        measured_at=snapshot.measured_at,
        control_mode=state.mode,
        dew_point_difference=snapshot.dew_point_difference,
        control_dew_point_difference_c=control_difference,
        manual_dew_point_difference=manual_difference_for_backend,
        fan_on_threshold_c=on_threshold,
        fan_off_threshold_c=off_threshold,
        display_time=used_display_time,
        display_time_source_value=used_display_time_source,
    )


def print_snapshot(snapshot: SensorSnapshot, state: ControllerState) -> None:
    control_difference = control_dew_point_difference(
        state,
        snapshot.dew_point_difference,
    )
    on_threshold, off_threshold = current_thresholds(state)

    print(f"Time:              {snapshot.measured_at}")
    print(f"Mode:              {state.mode.upper()}")
    print(f"Display time:      {display_now(state).strftime('%H:%M')} ({display_time_source(state)})")
    print("-" * 50)
    print(f"Inside temp:       {snapshot.temperature_inside:5.1f} C")
    print(f"Inside humidity:   {snapshot.humidity_inside:5.1f} %")
    print(f"Inside dew point:  {snapshot.dew_point_inside:5.1f} C")
    print("-" * 50)
    print(f"Outside temp:      {snapshot.temperature_outside:5.1f} C")
    print(f"Outside humidity:  {snapshot.humidity_outside:5.1f} %")
    print(f"Outside dew point: {snapshot.dew_point_outside:5.1f} C")
    print("-" * 50)
    print(f"Measured diff:     {snapshot.dew_point_difference:5.2f} C")
    if control_difference is not None and control_difference != snapshot.dew_point_difference:
        print(f"Control diff:      {control_difference:5.2f} C")
    print(f"Fan:               {'ON' if state.fan_on else 'OFF'}")
    print(f"Fan ON threshold:  {on_threshold:5.1f} C")
    print(f"Fan OFF threshold: {off_threshold:5.1f} C")
    print("=" * 50)


def setup_dht_sensors():
    import adafruit_dht
    import board

    inside_pin = getattr(board, INSIDE_PIN_NAME)
    outside_pin = getattr(board, OUTSIDE_PIN_NAME)

    return adafruit_dht.DHT22(inside_pin), adafruit_dht.DHT22(outside_pin)


def read_snapshot(dht_inside, dht_outside) -> Optional[SensorSnapshot]:
    temperature_inside = dht_inside.temperature
    humidity_inside = dht_inside.humidity

    time.sleep(SENSOR_DELAY_SECONDS)

    temperature_outside = dht_outside.temperature
    humidity_outside = dht_outside.humidity

    if None in (
        temperature_inside,
        humidity_inside,
        temperature_outside,
        humidity_outside,
    ):
        print("Sensor returned None, retry later.")
        return None

    if (
        not plausible(temperature_inside, humidity_inside)
        or not plausible(temperature_outside, humidity_outside)
    ):
        print("Implausible sensor values, skipped.")
        return None

    dew_point_inside = dew_point_c(temperature_inside, humidity_inside)
    dew_point_outside = dew_point_c(temperature_outside, humidity_outside)

    return SensorSnapshot(
        measured_at=datetime.now(timezone.utc).isoformat(),
        temperature_inside=temperature_inside,
        humidity_inside=humidity_inside,
        dew_point_inside=dew_point_inside,
        temperature_outside=temperature_outside,
        humidity_outside=humidity_outside,
        dew_point_outside=dew_point_outside,
        dew_point_difference=dew_point_inside - dew_point_outside,
    )


def perform_measurement(GPIO, dht_inside, dht_outside, state: ControllerState) -> bool:
    try:
        snapshot = read_snapshot(dht_inside, dht_outside)
    except RuntimeError as error:
        print("Sensor error:", error)
        return False

    if snapshot is None:
        return False

    state.last_dew_point_difference = snapshot.dew_point_difference
    apply_fan_logic(GPIO, state, snapshot.dew_point_difference)
    print_snapshot(snapshot, state)
    save_snapshot(snapshot, state)
    print("Measurement cycle finished.\n")
    return True


class SegmentClock:
    def __init__(self) -> None:
        self._segment = None
        self._last_second: Optional[int] = None
        self._override_until = 0.0

        try:
            import board
            from adafruit_ht16k33.segments import Seg7x4

            self._segment = Seg7x4(board.I2C(), address=0x70)
            self._segment.fill(0)
            self._segment.show()
        except Exception as error:
            print(f"7-segment display disabled: {error}")

    def _write_text(self, text: str) -> None:
        if self._segment is None:
            return

        text = text[:4].ljust(4)
        self._segment.fill(0)
        self._segment.colon = False

        try:
            print_method = getattr(self._segment, "print")
            print_method(text.strip())
        except Exception:
            for index, char in enumerate(text):
                self._segment[index] = char

        self._segment.show()

    def _write_time(self, now: datetime) -> None:
        if self._segment is None:
            return

        self._segment.fill(0)
        self._segment[0] = str(now.hour // 10)
        self._segment[1] = str(now.hour % 10)
        self._segment[2] = str(now.minute // 10)
        self._segment[3] = str(now.minute % 10)
        self._segment.colon = now.second % 2 == 0
        self._segment.show()

    def update(self, state: ControllerState) -> None:
        if self._segment is None:
            return

        if time.monotonic() < self._override_until:
            return

        now = display_now(state)
        if now.second == self._last_second:
            return

        self._last_second = now.second
        self._write_time(now)

    def show_status(self, ok: bool) -> None:
        self._override_until = time.monotonic() + SEGMENT_OVERRIDE_SECONDS
        self._last_second = None
        self._write_text("GOOD" if ok else "Err")

    def show_dew_point_difference(self, value: Optional[float]) -> None:
        self._override_until = time.monotonic() + SEGMENT_DEW_POINT_SECONDS
        self._last_second = None

        if value is None:
            self._write_text("----")
            return

        self._write_text(f"{value:4.1f}")

    def clear(self) -> None:
        if self._segment is None:
            return

        self._segment.fill(0)
        self._segment.colon = False
        self._segment.show()


class RfidReader:
    def __init__(self) -> None:
        self._reader = None

        try:
            import MFRC522

            self._reader = MFRC522.MFRC522()
        except Exception as error:
            print(f"RFID disabled: {error}")

    def read_uid(self) -> Optional[tuple[int, int, int, int]]:
        if self._reader is None:
            return None

        try:
            status, _tag_type = self._reader.MFRC522_Request(
                self._reader.PICC_REQIDL
            )
            if status != self._reader.MI_OK:
                return None

            status, uid = self._reader.MFRC522_Anticoll()
            if status == self._reader.MI_OK and uid:
                return tuple(int(part) for part in uid[:4])
        except Exception as error:
            print(f"RFID read error: {error}")

        return None


class RfidToggleDebouncer:
    def __init__(self) -> None:
        self._armed = True
        self._last_seen_at = 0.0
        self._last_toggle_at = 0.0

    def poll(self, reader: RfidReader) -> Optional[tuple[int, int, int, int]]:
        uid = reader.read_uid()
        now = time.monotonic()

        if uid is None:
            if now - self._last_seen_at >= RFID_RELEASE_SECONDS:
                self._armed = True
            return None

        self._last_seen_at = now

        if not self._armed:
            return None

        if now - self._last_toggle_at < RFID_TOGGLE_COOLDOWN_SECONDS:
            return None

        self._armed = False
        self._last_toggle_at = now
        return uid


class TouchSensor:
    def __init__(self, GPIO) -> None:
        self._GPIO = GPIO
        self._last_raw_pressed = False
        self._stable_pressed = False
        self._last_raw_change_at = time.monotonic()
        self._pressed_at = 0.0

    def poll(self) -> Optional[TouchEvent]:
        now = time.monotonic()
        raw_pressed = self._GPIO.input(TOUCH_PIN_BCM) == self._GPIO.LOW

        if raw_pressed != self._last_raw_pressed:
            self._last_raw_pressed = raw_pressed
            self._last_raw_change_at = now
            return None

        if now - self._last_raw_change_at < TOUCH_DEBOUNCE_SECONDS:
            return None

        if raw_pressed == self._stable_pressed:
            return None

        self._stable_pressed = raw_pressed
        if raw_pressed:
            self._pressed_at = now
            return None

        return TouchEvent(pressed_seconds=now - self._pressed_at)


def handle_touch_event(
    clock: SegmentClock,
    state: ControllerState,
    event: TouchEvent,
) -> None:
    if event.pressed_seconds >= TOUCH_LONG_PRESS_SECONDS:
        clock.show_dew_point_difference(
            control_dew_point_difference(
                state,
                state.last_dew_point_difference,
            )
        )
        print("Touch: showing current dew-point difference on 7-segment.")
        return

    ok = backend_status_ok()
    clock.show_status(ok)
    print(f"Touch: backend status is {'GOOD' if ok else 'Err'}.")


class LcdDisplay:
    def __init__(self) -> None:
        self._lcd = None
        self._message_until: Optional[float] = None
        self._current_message = ""

        try:
            import adafruit_character_lcd.character_lcd_i2c as character_lcd
            import board
            import busio

            i2c = busio.I2C(board.SCL, board.SDA)
            self._lcd = character_lcd.Character_LCD_I2C(i2c, 16, 2)
            self._lcd.clear()
            self._lcd.backlight = False
        except Exception as error:
            print(f"LCD display disabled: {error}")

    def show_message(
        self,
        line1: str,
        line2: str = "",
        duration_seconds: Optional[float] = None,
    ) -> None:
        if self._lcd is None:
            return

        message = f"{line1[:16].ljust(16)}\n{line2[:16].ljust(16)}"
        if message == self._current_message:
            if duration_seconds is not None:
                self._message_until = time.monotonic() + duration_seconds
            return

        self._lcd.backlight = True
        self._lcd.clear()
        self._lcd.message = message
        self._current_message = message
        self._message_until = (
            time.monotonic() + duration_seconds
            if duration_seconds is not None
            else None
        )

    def clear(self) -> None:
        if self._lcd is None:
            return

        if self._current_message:
            self._lcd.clear()
            self._lcd.backlight = False
            self._current_message = ""
            self._message_until = None

    def update(self) -> None:
        if self._message_until is None:
            return

        if time.monotonic() >= self._message_until:
            self.clear()


class LightSensor:
    def __init__(self) -> None:
        self._bus = None

        try:
            try:
                import smbus
            except ImportError:
                import smbus2 as smbus

            self._bus = smbus.SMBus(1)
        except Exception as error:
            print(f"Light sensor disabled: {error}")

    def read_lux(self) -> Optional[float]:
        if self._bus is None:
            return None

        try:
            data = self._bus.read_i2c_block_data(LIGHT_SENSOR_ADDRESS, 0x20, 2)
        except Exception as error:
            print(f"Light sensor error: {error}")
            return None

        return ((data[0] << 8) + data[1]) / 1.2


class MotionSensor:
    def __init__(self, GPIO) -> None:
        self._GPIO = GPIO
        self._last_motion = False

    def poll_motion_started(self) -> bool:
        motion = self._GPIO.input(MOTION_PIN_BCM) == self._GPIO.HIGH
        started = motion and not self._last_motion
        self._last_motion = motion
        return started


def greeting_for(now: datetime) -> str:
    if 5 <= now.hour < 9:
        return "Guten Morgen!"

    if 9 <= now.hour < 17:
        return "Moin"

    if 17 <= now.hour < 22:
        return "Guten Abend!"

    return "Gute Nacht!"


class MotionLcdController:
    def __init__(
        self,
        lcd: LcdDisplay,
        motion: MotionSensor,
        light: LightSensor,
    ) -> None:
        self._lcd = lcd
        self._motion = motion
        self._light = light
        self._is_dark = False
        self._light_reminder_active = False
        self._next_light_read_at = 0.0
        self._last_motion_message_at = 0.0

    def _read_light_if_needed(self, now: float) -> None:
        if now < self._next_light_read_at:
            return

        self._next_light_read_at = now + LIGHT_POLL_INTERVAL_SECONDS
        lux = self._light.read_lux()
        if lux is None:
            return

        self._is_dark = lux < DARK_LUX_THRESHOLD

        if self._light_reminder_active and not self._is_dark:
            self._light_reminder_active = False
            self._lcd.clear()

    def update(self, state: ControllerState) -> None:
        now = time.monotonic()
        self._lcd.update()
        self._read_light_if_needed(now)

        if not self._motion.poll_motion_started():
            return

        if now - self._last_motion_message_at < MOTION_COOLDOWN_SECONDS:
            return

        self._last_motion_message_at = now

        if self._is_dark:
            self._light_reminder_active = True
            self._lcd.show_message("Bitte Licht", "einschalten")
            return

        self._light_reminder_active = False
        self._lcd.show_message(
            greeting_for(display_now(state)),
            duration_seconds=LCD_MESSAGE_SECONDS,
        )


def handle_rfid_toggle(
    GPIO,
    state: ControllerState,
    uid: tuple[int, int, int, int],
) -> None:
    if state.active:
        # Second tap: shut down completely.
        # GPIO cleanup and clock.clear() run in the finally block of main().
        set_fan(GPIO, state, False)
        print(f"RFID UID {format_uid(uid)}: controller stopped; fan OFF. Shutting down.")
        sys.exit(0)

    state.active = True
    now = time.monotonic()
    state.next_control_poll_at = now
    state.next_measurement_at = now + MEASUREMENT_INTERVAL_SECONDS
    print(
        f"RFID UID {format_uid(uid)}: controller started; "
        "first measurement in 60 seconds."
    )


def main() -> None:
    GPIO = None
    state = ControllerState()
    clock = SegmentClock()
    lcd = LcdDisplay()

    try:
        import RPi.GPIO as GPIO

        # setup_dht_sensors() imports adafruit_blinka (board) which calls
        # GPIO.setmode(GPIO.BCM) internally. We must do it first, then
        # clean up and switch to BOARD mode for our relay/touch/motion pins.
        dht_inside, dht_outside = setup_dht_sensors()

        GPIO.setwarnings(False)
        GPIO.cleanup()
        GPIO.setmode(GPIO.BCM)

        GPIO.setup(FAN_PIN_BCM, GPIO.OUT)
        GPIO.output(FAN_PIN_BCM, GPIO.HIGH)
        GPIO.setup(TOUCH_PIN_BCM, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(MOTION_PIN_BCM, GPIO.IN)
        rfid_reader = RfidReader()
        rfid_debouncer = RfidToggleDebouncer()
        touch_sensor = TouchSensor(GPIO)
        motion_sensor = MotionSensor(GPIO)
        light_sensor = LightSensor()
        motion_lcd = MotionLcdController(lcd, motion_sensor, light_sensor)

        print("Advanced taupunkt controller ready.")
        print("Standby: touch any RFID transponder to start.")
        print(f"Measurements endpoint configured: {bool(MEASUREMENTS_API_URL)}")
        print(f"Control endpoint configured: {bool(CONTROL_API_URL)}")
        print("=" * 50)

        while True:
            clock.update(state)
            motion_lcd.update(state)

            touch_event = touch_sensor.poll()
            if touch_event is not None:
                handle_touch_event(clock, state, touch_event)

            uid = rfid_debouncer.poll(rfid_reader)
            if uid is not None:
                handle_rfid_toggle(GPIO, state, uid)

            now = time.monotonic()

            if state.active and now >= state.next_control_poll_at:
                poll_backend_control(GPIO, state)
                state.next_control_poll_at = now + CONTROL_POLL_INTERVAL_SECONDS

            if state.active and now >= state.next_measurement_at:
                success = perform_measurement(GPIO, dht_inside, dht_outside, state)
                delay = (
                    MEASUREMENT_INTERVAL_SECONDS
                    if success
                    else SENSOR_RETRY_SECONDS
                )
                state.next_measurement_at = time.monotonic() + delay

            time.sleep(MAIN_LOOP_SLEEP_SECONDS)

    except KeyboardInterrupt:
        print("Stopped by keyboard.")
    except Exception as error:
        print("Fatal error:", error)
    finally:
        if GPIO is not None:
            try:
                GPIO.output(FAN_PIN_BCM, GPIO.HIGH)
                GPIO.cleanup()
            except Exception:
                pass

        clock.clear()


if __name__ == "__main__":
    main()
