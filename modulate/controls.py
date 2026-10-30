"""Trusted physical inputs; generated applications receive only poll() values.

Driver contracts: Adafruit seesaw (MIT), SparkFun Qwiic Joystick (MIT).
https://learn.adafruit.com/adafruit-i2c-qt-rotary-encoder/python-circuitpython
https://docs.sparkfun.com/qwiic_joystick_py/classqwiic__joystick_1_1_qwiic_joystick.html
Polling never writes addresses/EEPROM or resets encoders. The separate trusted
repair worker alone may invoke the fixed ButtonDiagnostics address operation.
"""

import errno
from functools import wraps
import math
import threading
import uuid
from .imu import IMU_DEFAULTS, IMU_DESCRIPTION, motion_sample, open_imu


JOYSTICK_ADDRESS = 0x20
ENCODER_ADDRESS = 0x36
BUTTON_TARGETS = (0x6E, 0x6D, 0x6C, 0x6B, 0x69, 0x68, 0x67, 0x66,
                  0x65, 0x64, 0x63, 0x62, 0x61, 0x60)
BUTTON_ADDRESSES = frozenset((0x6F, *BUTTON_TARGETS))
# Eight stationary readings on the user's board, 2026-10-28. Do not calibrate
# automatically on startup: a held stick must never become the new center.
JOYSTICK_CENTER = (516, 504)


def neutral_input():
    return {"joystick_x": 0.0, "joystick_y": 0.0, "encoder_delta": 0,
            "button_a": False, "button_b": False, "encoder_pressed": False, **IMU_DEFAULTS}


def _locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.bus_lock:
            return method(self, *args, **kwargs)
    return call


class ButtonDiagnostics:
    """Fixed SparkFun register operations; used only by the trusted repair worker.

    Identity/address layout: sparkfun/qwiic_button_py and Qwiic_Button firmware.
    No reset, LED, debounce, queue, or firmware operations are exposed.
    """
    def __init__(self, driver=None):
        if driver is None:
            import qwiic_i2c
            driver = qwiic_i2c.getI2CDriver()
        if driver is None or getattr(driver, "i2cbus", None) is None:
            raise OSError("I2C bus unavailable")
        self.driver = driver

    def scan(self):
        # SparkFun's scan() suppresses every bus error. Distinguish a normal
        # address NACK from a failed adapter instead of reporting a false empty bus.
        addresses = []
        for address in range(0x08, 0x78):
            try:
                # Match i2cdetect's default probe policy: quick writes can
                # corrupt some EEPROMs; receive-byte probes are used in these
                # ranges. Neither policy promises harmless discovery of every
                # arbitrary peripheral; this tool targets the documented assembly.
                if 0x30 <= address <= 0x37 or 0x50 <= address <= 0x5F:
                    self.driver.i2cbus.read_byte(address)
                else:
                    self.driver.i2cbus.write_quick(address)  # No data bytes.
            except OSError as error:
                if error.errno not in (errno.ENXIO, getattr(errno, "EREMOTEIO", 121)):
                    raise
            else:
                addresses.append(address)
        return addresses

    def button(self, address):
        if address not in BUTTON_ADDRESSES:
            raise ValueError("Unsupported button address")
        identity = self.driver.readByte(address, 0x00)
        if identity != 0x5D:
            return None
        minor = self.driver.readByte(address, 0x01)
        major = self.driver.readByte(address, 0x02)
        configured = self.driver.readByte(address, 0x1F)
        if any(type(value) is not int or not 0 <= value <= 255
               for value in (identity, minor, major, configured)):
            raise ValueError("Invalid button registers")
        return {"address": address, "id": identity, "firmware": major << 8 | minor,
                "configured_address": configured}

    def imu_identity(self):
        # Read the documented WHO_AM_I register; no optional sensor driver or
        # configuration writes are needed to identify an installable module.
        for address in (0x6A, 0x6B):
            try:
                identity = self.driver.readByte(address, 0x0F)
                if type(identity) is int and identity == 0x6A:
                    return {"address": address, "who_am_i": identity}
            except OSError:
                continue
        return None

    def readdress_factory_button(self, target):
        if type(target) is not int or target not in BUTTON_TARGETS:
            raise ValueError("Unsupported target")
        # One write, with no driver retries. Never trust its return value.
        self.driver.writeByte(0x6F, 0x1F, target)


def _open_encoder(bus=None):
    import board
    from adafruit_seesaw import seesaw, rotaryio, digitalio

    owns_bus = bus is None
    bus = board.I2C() if owns_bus else bus
    try:
        device = seesaw.Seesaw(bus, addr=ENCODER_ADDRESS, reset=False)
        if (device.get_version() >> 16) & 0xFFFF != 4991:
            raise ValueError("Unexpected encoder firmware product")
        # Volatile GPIO configuration only; the physical switch is active-low.
        device.pin_mode(24, device.INPUT_PULLUP)
        return rotaryio.IncrementalEncoder(device), digitalio.DigitalIO(device, 24), bus
    except Exception:
        if owns_bus:
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
    based on the latest read, not an address scan. A trusted reinitialize can
    reopen missing drivers; transient read failures recover on the next poll.
    """

    def __init__(self, screen, *, joystick_center=JOYSTICK_CENTER, deadzone=0.08,
                 max_encoder_delta=10, diagnostic_backend=None):
        if (not isinstance(joystick_center, (tuple, list)) or len(joystick_center) != 2
                or any(type(v) is not int or not 1 <= v <= 1022 for v in joystick_center)):
            raise ValueError("Joystick center must contain two 10-bit interior integers")
        if type(deadzone) not in (int, float) or not math.isfinite(deadzone) or not 0 <= deadzone < 0.5:
            raise ValueError("Joystick deadzone must be from 0 to less than 0.5")
        if type(max_encoder_delta) is not int or not 1 <= max_encoder_delta <= 10:
            raise ValueError("Maximum encoder delta must be from 1 to 10")
        self.bus_lock = threading.RLock()
        self._diagnostic_backend = diagnostic_backend
        self.screen = screen
        self.center = tuple(joystick_center)
        self.deadzone = deadzone
        self.max_encoder_delta = max_encoder_delta
        self._encoder = self._encoder_button = self._bus = self._joystick = None
        self._external_buttons = None
        self._imu = None
        self._imu_address = None
        self._position = None
        self._closed = False
        self._status = {"encoder": "unavailable", "joystick": "unavailable",
                        "pitft_buttons": "unavailable", "qwiic_buttons": "unavailable", "imu": "unavailable"}
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
        try:
            self._imu, self._bus, self._imu_address = open_imu(self._bus)
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

    @_locked
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
        if self._imu is not None:
            try:
                sample.update(motion_sample(self._imu.acceleration, self._imu.gyro))
                self._status["imu"] = "ready"
            except Exception:
                self._status["imu"] = "read_error"
        return sample

    def capabilities(self):
        # Status-only cache: network/cancellation delivery must not wait for an
        # I2C scan holding bus_lock. Poll publishes individual string states;
        # this copy is bounded, contains no device I/O and cannot retain inputs.
        status = self._status.copy()
        controls = []
        if status["joystick"] == "ready":
            controls.append("joystick")
        if status["encoder"] == "ready":
            controls.extend(("encoder", "encoder_pressed"))
        if status["pitft_buttons"] == "ready" or status["qwiic_buttons"] == "ready":
            controls.extend(("button_a", "button_b"))
        if status["imu"] == "ready":
            controls.append("imu")
        warnings = []
        if status["qwiic_buttons"] not in ("ready", "closed"):
            warnings.append("Qwiic buttons are unavailable until 0x6e and 0x6f are independently identified; check missing modules, wiring, or a possible address conflict.")
        for device, state in status.items():
            if state in ("unavailable", "read_error", "closed"):
                warnings.append(f"{device}: {state}; its input is neutral.")
        return {"controls": controls,
                "devices": [{"id": device, "address": address, "status": status[device]}
                            for device, address in (("joystick", "0x20"), ("encoder", "0x36"),
                                                    ("pitft_buttons", None), ("qwiic_buttons", "0x6e / 0x6f"))]
                           + [{"id": "imu", "address": hex(self._imu_address) if self._imu_address else None,
                               "status": status["imu"], **IMU_DESCRIPTION}],
                "button_sources": {"button_a": "PiTFT A or green Qwiic 0x6e", "button_b": "PiTFT B or red Qwiic 0x6f"},
                "warnings": warnings}

    @_locked
    def hardware_backend(self):
        if self._closed:
            raise OSError("Controls closed")
        if self._diagnostic_backend is None:
            self._diagnostic_backend = ButtonDiagnostics()
        return self._diagnostic_backend

    @_locked
    def hardware_scan(self, scan_id=None, *, backend=None):
        report = {"addresses": [], "buttons": [], "controls": self.capabilities(),
                  "warnings": [], "bus_available": False,
                  "scan_id": scan_id or uuid.uuid4().hex}
        if self._closed:
            report["warnings"].append("Controls are closed")
            return report
        try:
            backend = backend if backend is not None else self.hardware_backend()
            addresses = backend.scan()
            if (not isinstance(addresses, (list, tuple)) or len(addresses) > 112
                    or any(type(a) is not int or not 0x08 <= a <= 0x77 for a in addresses)
                    or len(set(addresses)) != len(addresses)):
                raise ValueError("Invalid address scan")
            report["addresses"] = sorted(addresses)
            report["bus_available"] = True
        except Exception:
            report["warnings"].append("I2C scan failed; no complete bus inventory is available")
            return report
        for address in report["addresses"]:
            if address not in BUTTON_ADDRESSES:
                continue  # Unknown responders are not guessed from their address.
            try:
                button = backend.button(address)
                if (not isinstance(button, dict) or set(button) !=
                        {"address", "id", "firmware", "configured_address"}
                        or type(button["address"]) is not int or button["address"] != address
                        or type(button["id"]) is not int or button["id"] != 0x5D
                        or type(button["firmware"]) is not int
                        or not 0 <= button["firmware"] <= 65535
                        or type(button["configured_address"]) is not int
                        or button["configured_address"] != address):
                    raise ValueError("Button identity not verified")
                report["buttons"].append(dict(button))
                if address not in (0x6E, 0x6F):
                    report["warnings"].append(f"Button at 0x{address:02x} is diagnostic-only; game aliases remain 0x6e/0x6f")
            except Exception:
                report["warnings"].append(f"Responder at 0x{address:02x} was not verified as a Qwiic Button")
        report["warnings"].append("An address scan cannot count identical devices sharing an address or prove physical isolation")
        return report

    @_locked
    def hardware_reinitialize(self, *, refresh_missing=False):
        if self._closed:
            raise OSError("Controls closed")
        reopened_encoder = False
        if self._encoder is None or self._status["encoder"] == "read_error":
            reopened_encoder = True
            self._encoder = self._encoder_button = None
            self._status["encoder"] = "unavailable"
            try:
                # Rebuild failed driver objects without resetting the encoder
                # or closing a bus still owned by Controls. Reusing the bus also
                # avoids closing board.I2C's singleton beneath a replacement.
                self._encoder, self._encoder_button, self._bus = (
                    _open_encoder(bus=self._bus) if self._bus is not None else _open_encoder())
            except Exception:
                pass
        if self._joystick is None or self._status["joystick"] == "read_error":
            self._joystick = None
            self._status["joystick"] = "unavailable"
            try:
                self._joystick = _open_joystick()
            except Exception:
                pass
        if self._external_buttons is None or self._status["qwiic_buttons"] == "read_error":
            self._external_buttons = None
            self._status["qwiic_buttons"] = "unavailable"
            try:
                self._external_buttons = _open_external_buttons()
            except Exception:
                pass
        if not refresh_missing or reopened_encoder:
            self._position = None  # Reinitialization never replays accumulated turns.
        if self._imu is None or self._status["imu"] == "read_error":
            self._imu = None
            self._imu_address = None
            self._status["imu"] = "unavailable"
            try:
                self._imu, self._bus, self._imu_address = open_imu(self._bus)
            except Exception:
                pass
        if not refresh_missing:
            self.poll()
        # Background discovery must not consume encoder deltas/button events.
        # The normal next input poll establishes read-backed availability.
        return self.capabilities()

    @_locked
    def close(self):
        self._closed = True
        self._position = None
        for device in self._status:
            self._status[device] = "closed"
        if self._bus is not None:
            bus, self._bus = self._bus, None
            bus.deinit()
        # Screen owns its GPIO handles; never deinitialize them here.
