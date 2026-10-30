"""Synthetic sensor/worker checks; physical evidence is recorded separately."""
import math
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modulate.imu import IMU_DEFAULTS, motion_sample, open_imu
from modulate.game_runtime import Game, GameError, validate_input, verify
from tests.test_game_runtime import fixture, GAME_CODE


class MotionTests(unittest.TestCase):
    def test_gravity_inclination_is_bounded_and_does_not_invent_heading(self):
        self.assertEqual(motion_sample((0, 0, 9.8), (0, 0, 0))["tilt_x"], 0)
        self.assertAlmostEqual(motion_sample((4.9, 0, 4.9 * math.sqrt(3)), (0, 0, 0))["tilt_x"], 2/3)
        self.assertEqual(motion_sample((0, -9.8, 0), (0, 0, 0))["tilt_y"], -1)
        self.assertEqual(motion_sample((.1, .2, .3), (0, 0, 0))["tilt_x"], 0)
        self.assertEqual(set(motion_sample((0, 0, 9.8), (0, 0, 0))), set(IMU_DEFAULTS))

    def test_invalid_partial_samples_never_publish(self):
        for bad in ((None, 0, 0), (True, 0, 0), (float("nan"), 0, 0),
                    (float("inf"), 0, 0), (41, 0, 0), (0, 0), "xyz"):
            for args in ((bad, (0, 0, 0)), ((0, 0, 9.8), bad)):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    motion_sample(*args)

    def test_unidentified_sensor_closes_only_owned_bus(self):
        bus = Mock()
        driver = Mock(side_effect=ValueError("Wrong WHO_AM_I"))
        modules = {"board": SimpleNamespace(I2C=lambda: bus),
                   "adafruit_lsm6ds": SimpleNamespace(AccelRange=Mock(), GyroRange=Mock(), Rate=Mock()),
                   "adafruit_lsm6ds.lsm6ds3trc": SimpleNamespace(LSM6DS3TRC=driver)}
        with patch.dict(sys.modules, modules):
            with self.assertRaises(OSError):
                open_imu(bus)
            bus.deinit.assert_not_called()
            with self.assertRaises(OSError):
                open_imu()
            bus.deinit.assert_called_once()
        self.assertEqual([c.kwargs["address"] for c in driver.call_args_list], [0x6A, 0x6B]*2)

    def test_runtime_rejects_out_of_contract_motion_values(self):
        for key in IMU_DEFAULTS:
            for value in (True, float("nan"), float("inf"), None,
                          1.01 if key.startswith("tilt") else 40.01):
                with self.subTest(key=key, value=value), self.assertRaises(GameError):
                    validate_input({key: value})

    def test_isolated_worker_receives_motion_and_verifier_exercises_it(self):
        package = fixture(GAME_CODE.replace("input.joystick_x*60*dt + input.encoder_delta",
                                           "input.tilt_x*60*dt + input.imu_gz"))
        package["controls"] = ["imu"]
        with Game(package) as game:
            left = game.step({"tilt_x": -1})["state"]["x"]
            right = game.step({"tilt_x": 1, "imu_gz": 2})["state"]["x"]
        self.assertGreater(right, left)
        result = verify(package)
        self.assertTrue(result["passed"], result)
        self.assertTrue(any(c["name"] == "representative_inputs" and "76" in c["detail"] for c in result["checks"]))
