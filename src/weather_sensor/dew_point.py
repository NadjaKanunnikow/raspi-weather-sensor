"""Dew point calculation utilities."""

from __future__ import annotations

import math


def calculate_dew_point_celsius(temperature_c: float, humidity_percent: float) -> float:
    """Calculate dew point in °C using the Magnus formula.

    The formula is accurate enough for a classroom weather-station project.
    Relative humidity must be between 0 and 100 percent.
    """
    if humidity_percent <= 0 or humidity_percent > 100:
        raise ValueError("humidity_percent must be > 0 and <= 100")

    magnus_a = 17.62
    magnus_b_celsius = 243.12

    gamma = math.log(humidity_percent / 100.0) + (
        magnus_a * temperature_c / (magnus_b_celsius + temperature_c)
    )
    return (magnus_b_celsius * gamma) / (magnus_a - gamma)
