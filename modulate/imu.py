"""Bounded LSM6DS3TR-C observations, separate from generated control choices.

Uses Adafruit's MIT driver; units/identity are defined by the sensor, not a game.
https://docs.circuitpython.org/projects/lsm6dsox/en/latest/api.html
"""
import math

IMU_DEFAULTS = {name: 0.0 for name in
                ("imu_ax", "imu_ay", "imu_az", "imu_gx", "imu_gy", "imu_gz", "tilt_x", "tilt_y")}
IMU_DESCRIPTION = {
    "model": "LSM6DS3TR-C", "sensing": ["acceleration", "angular_velocity", "gravity_tilt"],
    "inputs": {"imu_ax/imu_ay/imu_az": "sensor X/Y/Z acceleration including gravity, m/s^2, -40..40",
               "imu_gx/imu_gy/imu_gz": "sensor X/Y/Z angular velocity, radians/s, -40..40",
               "tilt_x/tilt_y": "gravity inclination of sensor X/Y, -1..1, full scale +/-45 degrees"},
    "orientation": "Sensor axes, not assumed screen axes. Choose/calibrate the useful axis in the generated app.",
    "limits": "No absolute heading or position tracking; fast acceleration affects gravity tilt.",
}


def motion_sample(acceleration, gyro):
    vectors = []
    for vector in (acceleration, gyro):
        if (not isinstance(vector, (tuple, list)) or len(vector) != 3 or
                any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 40 for v in vector)):
            raise ValueError("Invalid IMU observation")
        vectors.append(tuple(float(v) for v in vector))
    (x, y, z), (gx, gy, gz) = vectors
    magnitude = math.sqrt(x*x + y*y + z*z)
    # At/near freefall there is no trustworthy gravity direction.
    tx = math.atan2(x, math.hypot(y, z)) / (math.pi / 4) if magnitude >= 2 else 0.0
    ty = math.atan2(y, math.hypot(x, z)) / (math.pi / 4) if magnitude >= 2 else 0.0
    return dict(zip(IMU_DEFAULTS, (x, y, z, gx, gy, gz,
                                  max(-1.0, min(1.0, tx)), max(-1.0, min(1.0, ty)))))


def open_imu(bus=None):
    import board
    from adafruit_lsm6ds import AccelRange, GyroRange, Rate
    from adafruit_lsm6ds.lsm6ds3trc import LSM6DS3TRC
    owns_bus = bus is None
    bus = board.I2C() if owns_bus else bus
    try:
        for address in (0x6A, 0x6B):
            try:
                # The maintained driver checks WHO_AM_I before configuration.
                sensor = LSM6DS3TRC(bus, address=address)
                sensor.accelerometer_range = AccelRange.RANGE_2G
                sensor.gyro_range = GyroRange.RANGE_250_DPS
                sensor.accelerometer_data_rate = Rate.RATE_52_HZ
                sensor.gyro_data_rate = Rate.RATE_52_HZ
                return sensor, bus, address
            except (OSError, ValueError, RuntimeError):
                continue
        raise OSError("Supported IMU not identified")
    except Exception:
        if owns_bus:
            bus.deinit()
        raise
