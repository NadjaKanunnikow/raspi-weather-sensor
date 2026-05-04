from weather_sensor.dew_point import calculate_dew_point_celsius


def test_calculate_dew_point_celsius_when_valid_input_should_return_expected_value():
    result = calculate_dew_point_celsius(20.0, 50.0)

    assert round(result, 1) == 9.3
