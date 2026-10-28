"""Trusted physical inputs; generated applications receive only poll() values.

Driver contracts: Adafruit seesaw (MIT), SparkFun Qwiic Joystick (MIT).
https://learn.adafruit.com/adafruit-i2c-qt-rotary-encoder/python-circuitpython
https://docs.sparkfun.com/qwiic_joystick_py/classqwiic__joystick_1_1_qwiic_joystick.html
No address/EEPROM writes, encoder resets, or duplicate PiTFT GPIO claims.
"""

import math


JOYSTICK_ADDRESS = 0x20
ENCODER_ADDRESS = 0x36
# Eight stationary readings on the user's board, 2026-10-28. Do not calibrate
# automatically on startup: a held stick must never become the new center.
JOYSTICK_CENTER = (516, 504)


def neutral_input():
    return {"joystick_x": 0.0, "joystick_y": 0.0, "encoder_delta": 0,
            "button_a": False, "button_b": False, "encoder_pressed": False}


def _open_encoder():
    import board
    from adafruit_seesaw import seesaw, rotaryio, digitalio

    bus = board.I2C()
    try:
        device = seesaw.Seesaw(bus, addr=ENCODER_ADDRESS, reset=False)
        if (device.get_version() >> 16) & 0xFFFF != 4991:
            raise ValueError("Unexpected encoder firmware product")
        # Volatile GPIO configuration only; the physical switch is active-low.
        device.pin_mode(24, device.INPUT_PULLUP)
        return rotaryio.IncrementalEncoder(device), digitalio.DigitalIO(device, 24), bus
    except Exception:
        bus.deinit()
        raise


def _open_joystick():
    import qwiic_joystick

    joystick = qwiic_joystick.QwiicJoystick(address=JOYSTICK_ADDRESS)
    # SparkFun begin() only checks address presence. Neither constructor nor
    # begin() writes an address; verify reads independently in Controls.poll.
    if not joystick.begin():
        raise OSError("Joystick did not acknowledge")
    return joystick


def _open_external_buttons():
    import qwiic_button

    # Only enable the pair once both distinct addresses identify as buttons.
    # Address assignment is a separate, physically supervised setup operation.
    green = qwiic_button.QwiicButton(address=0x6E)
    red = qwiic_button.QwiicButton(address=0x6F)
    if not green.begin() or not red.begin():
        raise OSError("Two separately addressed Qwiic buttons are required")
    return green, red


class Controls:
    """Read available controls; any failed device contributes neutral input.

    `screen` is the existing hardware.Screen: its two active-low button handles
    are borrowed, never opened or deinitialized here. Manifest availability is
    based on the latest read, not an address scan. Missing startup devices need
    a service restart; transient read failures can recover on the next poll.
    """

    def __init__(self, screen, *, joystick_center=JOYSTICK_CENTER, deadzone=0.08,
                 max_encoder_delta=10):
        if (not isinstance(joystick_center, (tuple, list)) or len(joystick_center) != 2
                or any(type(v) is not int or not 1 <= v <= 1022 for v in joystick_center)):
            raise ValueError("Joystick center must contain two 10-bit interior integers")
        if type(deadzone) not in (int, float) or not math.isfinite(deadzone) or not 0 <= deadzone < 0.5:
            raise ValueError("Joystick deadzone must be from 0 to less than 0.5")
        if type(max_encoder_delta) is not int or not 1 <= max_encoder_delta <= 10:
            raise ValueError("Maximum encoder delta must be from 1 to 10")
        self.screen = screen
        self.center = tuple(joystick_center)
        self.deadzone = deadzone
        self.max_encoder_delta = max_encoder_delta
        self._encoder = self._encoder_button = self._bus = self._joystick = None
        self._external_buttons = None
        self._position = None
        self._closed = False
        self._status = {"encoder": "unavailable", "joystick": "unavailable",
                        "pitft_buttons": "unavailable", "qwiic_buttons": "disabled_address_collision"}
        try:
            self._encoder, self._encoder_button, self._bus = _open_encoder()
        except Exception:
            pass
        try:
            self._joystick = _open_joystick()
        except Exception:
            pass
        try:
            self._external_buttons = _open_external_buttons()
        except Exception:
            pass
        self.poll()  # Establish encoder baseline and a read-backed manifest.

    def _axis(self, raw, center):
        if type(raw) is not int or not 0 <= raw <= 1023:
            raise ValueError("Invalid 10-bit joystick reading")
        value = (raw - center) / (1023 - center if raw >= center else center)
        if abs(value) <= self.deadzone:
            return 0.0
        normalized = (abs(value) - self.deadzone) / (1 - self.deadzone)
        return math.copysign(min(1.0, normalized), value)

    @staticmethod
    def _pressed(button):
        value = button.value
        if type(value) is not bool:
            raise ValueError("Invalid digital input reading")
        return not value

    def poll(self):
        sample = neutral_input()
        if self._closed:
            return sample
        buttons = getattr(self.screen, "buttons", [])
        if len(buttons) >= 2:
            try:
                # Read both before publishing either: a partial failure must
                # not produce a false two-button push-to-talk chord.
                a, b = self._pressed(buttons[0]), self._pressed(buttons[1])
                sample.update(button_a=a, button_b=b)
                self._status["pitft_buttons"] = "ready"
            except Exception:
                self._status["pitft_buttons"] = "read_error"
        else:
            self._status["pitft_buttons"] = "unavailable"

        if self._external_buttons is not None:
            try:
                green, red = (button.is_button_pressed() for button in self._external_buttons)
                if type(green) is not bool or type(red) is not bool:
                    raise ValueError("Invalid external button read")
                sample["button_a"] = sample["button_a"] or green
                sample["button_b"] = sample["button_b"] or red
                self._status["qwiic_buttons"] = "ready"
            except Exception:
                self._status["qwiic_buttons"] = "read_error"

        if self._joystick is not None:
            try:
                x = self._axis(self._joystick.get_horizontal(), self.center[0])
                y = self._axis(self._joystick.get_vertical(), self.center[1])
                sample.update(joystick_x=x, joystick_y=y)
                self._status["joystick"] = "ready"
            except Exception:
                self._status["joystick"] = "read_error"

        if self._encoder is not None:
            try:
                position = self._encoder.position
                if type(position) is not int or not -(1 << 31) <= position < (1 << 31):
                    raise ValueError("Invalid encoder position")
                pressed = self._pressed(self._encoder_button)
                delta = 0
                if self._position is not None:
                    # 32-bit rollover is one pulse, not a giant jump. #5880's
                    # direction is inverted per the manufacturer's guide.
                    raw_delta = ((position - self._position + (1 << 31)) % (1 << 32)) - (1 << 31)
                    delta = -raw_delta
                self._position = position
                if abs(delta) > self.max_encoder_delta:
                    raise ValueError("Encoder discontinuity; discard rather than apply a large action")
                sample.update(encoder_delta=delta, encoder_pressed=pressed)
                self._status["encoder"] = "ready"
            except Exception:
                self._status["encoder"] = "read_error"
                # A recovered device starts a new baseline; never replay turns
                # that accumulated while its reads were unavailable.
                self._position = None
        return sample

    def capabilities(self):
        controls = []
        if self._status["joystick"] == "ready":
            controls.append("joystick")
        if self._status["encoder"] == "ready":
            controls.extend(("encoder", "encoder_pressed"))
        if self._status["pitft_buttons"] == "ready" or self._status["qwiic_buttons"] == "ready":
            controls.extend(("button_a", "button_b"))
        warnings = ["Joystick travel and axis direction, and encoder clockwise direction, still need a physical movement test."]
        if self._status["qwiic_buttons"] == "disabled_address_collision":
            warnings.append("Qwiic buttons are disabled until both 0x6e and 0x6f are independently identified; a shared 0x6f address is ambiguous.")
        for device, status in self._status.items():
            if status in ("unavailable", "read_error", "closed"):
                warnings.append(f"{device}: {status}; its input is neutral.")
        return {"controls": controls,
                "devices": [{"id": device, "address": address, "status": self._status[device]}
                            for device, address in (("joystick", "0x20"), ("encoder", "0x36"),
                                                    ("pitft_buttons", None), ("qwiic_buttons", "0x6e / 0x6f"))],
                "button_sources": {"button_a": "PiTFT A or green Qwiic 0x6e", "button_b": "PiTFT B or red Qwiic 0x6f"},
                "warnings": warnings}

    def close(self):
        self._closed = True
        self._position = None
        for device in ("joystick", "encoder", "pitft_buttons", "qwiic_buttons"):
            self._status[device] = "closed"
        if self._bus is not None:
            bus, self._bus = self._bus, None
            bus.deinit()
        # Screen owns its GPIO handles; never deinitialize them here.
