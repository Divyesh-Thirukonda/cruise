"""Physical input normalization/failure tests using fake read-only drivers."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modulate.controls import Controls, _open_encoder, _open_joystick, neutral_input


class Button:
    def __init__(self, value=True):
        self.current = value
        self.error = False

    @property
    def value(self):
        if self.error:
            raise OSError("disconnected")
        return self.current


class Encoder:
    def __init__(self):
        self.current = 0
        self.error = False

    @property
    def position(self):
        if self.error:
            raise OSError("disconnected")
        return self.current


class Joystick:
    def __init__(self):
        self.x = 516
        self.y = 504
        self.error = False

    def get_horizontal(self):
        if self.error:
            raise OSError("disconnected")
        return self.x

    def get_vertical(self):
        return self.y


class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.buttons = [Button(), Button()]
        self.screen = SimpleNamespace(buttons=self.buttons)
        self.encoder, self.press, self.joystick = Encoder(), Button(), Joystick()
        self.bus = Mock()
        self.encoder_factory = patch("modulate.controls._open_encoder",
                                     return_value=(self.encoder, self.press, self.bus)).start()
        self.joystick_factory = patch("modulate.controls._open_joystick", return_value=self.joystick).start()
        self.external_factory = patch("modulate.controls._open_external_buttons", side_effect=OSError("not configured")).start()
        self.addCleanup(patch.stopall)
        self.controls = Controls(self.screen)

    def statuses(self):
        return {device["id"]: device["status"] for device in self.controls.capabilities()["devices"]}

    def test_stationary_bench_center_is_neutral_with_exact_input_keys_and_types(self):
        self.assertEqual(self.controls.poll(), neutral_input())
        self.assertIs(type(self.controls.poll()["joystick_x"]), float)
        self.assertEqual(self.controls.capabilities()["controls"],
                         ["joystick", "encoder", "encoder_pressed", "button_a", "button_b"])
        self.assertEqual(self.statuses()["qwiic_buttons"], "disabled_address_collision")
        self.assertTrue(any("0x6f" in warning for warning in self.controls.capabilities()["warnings"]))

    def test_joystick_deadzone_and_asymmetric_endpoint_normalization(self):
        self.joystick.x, self.joystick.y = 521, 498
        self.assertEqual(self.controls.poll()["joystick_x"], 0.0)
        self.assertEqual(self.controls.poll()["joystick_y"], 0.0)
        self.joystick.x, self.joystick.y = 0, 1023
        sample = self.controls.poll()
        self.assertEqual((sample["joystick_x"], sample["joystick_y"]), (-1.0, 1.0))
        self.joystick.x, self.joystick.y = 1023, 0
        sample = self.controls.poll()
        self.assertEqual((sample["joystick_x"], sample["joystick_y"]), (1.0, -1.0))

    def test_buttons_reuse_screen_handles_and_are_active_low(self):
        self.buttons[0].current = False
        self.press.current = False
        sample = self.controls.poll()
        self.assertTrue(sample["button_a"])
        self.assertFalse(sample["button_b"])
        self.assertTrue(sample["encoder_pressed"])
        self.buttons[1].current = False
        self.assertTrue(self.controls.poll()["button_b"])

    def test_distinct_external_buttons_alias_game_inputs_but_do_not_change_tft_pins(self):
        green, red = Mock(), Mock()
        green.is_button_pressed.return_value = True
        red.is_button_pressed.return_value = False
        self.external_factory.side_effect = None
        self.external_factory.return_value = green, red
        controls = Controls(self.screen)
        sample = controls.poll()
        self.assertTrue(sample["button_a"])
        self.assertFalse(sample["button_b"])
        self.assertTrue(self.buttons[0].current)
        self.assertEqual(next(d for d in controls.capabilities()["devices"] if d["id"] == "qwiic_buttons")["status"], "ready")
        red.is_button_pressed.side_effect = OSError("disconnected")
        sample = controls.poll()
        self.assertFalse(sample["button_a"])
        self.assertFalse(sample["button_b"])
        self.buttons[1].current = False
        self.assertTrue(controls.poll()["button_b"])

    def test_encoder_outputs_relative_inverted_delta_once(self):
        self.encoder.current = -3
        self.assertEqual(self.controls.poll()["encoder_delta"], 3)
        self.assertEqual(self.controls.poll()["encoder_delta"], 0)
        self.encoder.current = 1
        self.assertEqual(self.controls.poll()["encoder_delta"], -4)

    def test_encoder_startup_does_not_replay_existing_position(self):
        self.encoder.current = 400
        controls = Controls(self.screen)
        self.assertEqual(controls.poll()["encoder_delta"], 0)

    def test_partial_joystick_failure_drops_both_axes_and_removes_capability(self):
        self.joystick.x, self.joystick.y = 0, 1023
        self.assertEqual(self.controls.poll()["joystick_x"], -1.0)
        self.joystick.y = None
        sample = self.controls.poll()
        self.assertEqual((sample["joystick_x"], sample["joystick_y"]), (0.0, 0.0))
        self.assertEqual(self.statuses()["joystick"], "read_error")
        self.assertNotIn("joystick", self.controls.capabilities()["controls"])
        self.joystick.x, self.joystick.y = 516, 504
        self.controls.poll()
        self.assertIn("joystick", self.controls.capabilities()["controls"])

    def test_invalid_joystick_readings_do_not_escape_as_motion(self):
        for invalid in (-1, 1024, 512.0, True, None):
            with self.subTest(value=invalid):
                self.joystick.x = invalid
                sample = self.controls.poll()
                self.assertEqual(sample["joystick_x"], 0.0)
                self.assertEqual(self.statuses()["joystick"], "read_error")

    def test_failed_button_read_does_not_preserve_pressed_state_or_partial_chord(self):
        for button in self.buttons:
            button.current = False
        self.assertTrue(self.controls.poll()["button_b"])
        self.buttons[1].error = True
        sample = self.controls.poll()
        self.assertFalse(sample["button_a"])
        self.assertFalse(sample["button_b"])
        self.assertNotIn("button_a", self.controls.capabilities()["controls"])

    def test_encoder_failure_and_recovery_discard_unobserved_turns(self):
        self.encoder.current = -2
        self.press.current = False
        self.assertEqual(self.controls.poll()["encoder_delta"], 2)
        self.encoder.error = True
        sample = self.controls.poll()
        self.assertEqual(sample["encoder_delta"], 0)
        self.assertFalse(sample["encoder_pressed"])
        self.assertNotIn("encoder", self.controls.capabilities()["controls"])
        self.encoder.current, self.encoder.error = -100, False
        self.assertEqual(self.controls.poll()["encoder_delta"], 0)
        self.encoder.current = -101
        self.assertEqual(self.controls.poll()["encoder_delta"], 1)

    def test_encoder_press_failure_also_drops_motion(self):
        self.encoder.current = -2
        self.press.error = True
        self.assertEqual(self.controls.poll()["encoder_delta"], 0)
        self.assertEqual(self.statuses()["encoder"], "read_error")

    def test_encoder_discontinuity_is_discarded_instead_of_clamped_to_a_host_action(self):
        self.encoder.current = -11
        self.assertEqual(self.controls.poll()["encoder_delta"], 0)
        self.assertEqual(self.statuses()["encoder"], "read_error")
        self.encoder.current = -12
        self.assertEqual(self.controls.poll()["encoder_delta"], 0)
        self.encoder.current = -13
        self.assertEqual(self.controls.poll()["encoder_delta"], 1)

    def test_encoder_signed_32_bit_rollover_is_a_single_pulse(self):
        self.encoder.current = (1 << 31) - 1
        controls = Controls(self.screen)
        self.encoder.current = -(1 << 31)
        self.assertEqual(controls.poll()["encoder_delta"], -1)

    def test_missing_drivers_leave_available_tft_buttons_working(self):
        self.encoder_factory.side_effect = ImportError("no seesaw")
        self.joystick_factory.side_effect = OSError("no joystick")
        controls = Controls(self.screen)
        self.buttons[0].current = False
        self.assertTrue(controls.poll()["button_a"])
        self.assertEqual(controls.capabilities()["controls"], ["button_a", "button_b"])

    def test_close_is_idempotent_and_does_not_close_borrowed_screen(self):
        self.screen.close = Mock()
        self.controls.close()
        self.controls.close()
        self.assertEqual(self.controls.poll(), neutral_input())
        self.assertEqual(self.controls.capabilities()["controls"], [])
        self.bus.deinit.assert_called_once()
        self.screen.close.assert_not_called()

    def test_invalid_calibration_rejected_before_hardware_init(self):
        for kwargs in ({"joystick_center": (0, 500)}, {"joystick_center": (500,)},
                       {"deadzone": float("nan")}, {"deadzone": 0.5},
                       {"max_encoder_delta": 11}, {"max_encoder_delta": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Controls(self.screen, **kwargs)


class DriverSetupTests(unittest.TestCase):
    def test_encoder_setup_disables_reset_and_never_sets_position_or_address(self):
        bus, encoder, button = Mock(), Mock(), Mock()
        device = Mock()
        device.get_version.return_value = 4991 << 16
        device.INPUT_PULLUP = 2
        seesaw = SimpleNamespace(Seesaw=Mock(return_value=device))
        rotaryio = SimpleNamespace(IncrementalEncoder=Mock(return_value=encoder))
        digitalio = SimpleNamespace(DigitalIO=Mock(return_value=button))
        modules = {"board": SimpleNamespace(I2C=Mock(return_value=bus)),
                   "adafruit_seesaw": SimpleNamespace(seesaw=seesaw, rotaryio=rotaryio, digitalio=digitalio)}
        with patch.dict("sys.modules", modules):
            self.assertEqual(_open_encoder(), (encoder, button, bus))
        seesaw.Seesaw.assert_called_once_with(bus, addr=0x36, reset=False)
        device.pin_mode.assert_called_once_with(24, 2)
        device.sw_reset.assert_not_called()
        device.set_encoder_position.assert_not_called()
        device.set_i2c_addr.assert_not_called()

    def test_unexpected_encoder_firmware_is_not_claimed_as_input(self):
        bus, device = Mock(), Mock()
        device.get_version.return_value = 1234 << 16
        modules = {"board": SimpleNamespace(I2C=Mock(return_value=bus)),
                   "adafruit_seesaw": SimpleNamespace(seesaw=SimpleNamespace(Seesaw=Mock(return_value=device)),
                                                       rotaryio=Mock(), digitalio=Mock())}
        with patch.dict("sys.modules", modules), self.assertRaises(ValueError):
            _open_encoder()
        bus.deinit.assert_called_once()
        device.pin_mode.assert_not_called()

    def test_joystick_setup_only_checks_presence_and_does_not_change_address(self):
        joystick = Mock()
        constructor = Mock(return_value=joystick)
        with patch.dict("sys.modules", {"qwiic_joystick": SimpleNamespace(QwiicJoystick=constructor)}):
            self.assertIs(_open_joystick(), joystick)
        constructor.assert_called_once_with(address=0x20)
        self.assertEqual(joystick.method_calls, [("begin", (), {})])


if __name__ == "__main__":
    unittest.main()
