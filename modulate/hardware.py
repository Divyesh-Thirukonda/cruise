"""Trusted Pi drivers. Generated programs only return a validated Frame."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def record(seconds: int = 6, device: str = "plughw:CARD=Device,DEV=0") -> bytes:
    if not 1 <= seconds <= 10:
        raise ValueError("Recording must be 1–10 seconds")
    # arecord is a fixed trusted command; neither model output nor shell is used.
    with tempfile.TemporaryDirectory(prefix="modulate-audio-") as directory:
        path = Path(directory) / "request.wav"
        subprocess.run(
            ["arecord", "-q", "-D", device, "-f", "S16_LE", "-r", "16000",
             "-c", "1", "-d", str(seconds), str(path)],
            check=True, timeout=seconds + 5, capture_output=True,
        )
        data = path.read_bytes()
    if not 44 < len(data) <= 400_000:
        raise ValueError("Unexpected microphone recording size")
    return data


class Screen:
    def __init__(self, preview: Path, *, simulate: bool = False):
        from PIL import Image, ImageDraw, ImageFont
        self.Image, self.ImageDraw, self.ImageFont = Image, ImageDraw, ImageFont
        self.preview = preview
        self.display = None
        self.pins = []
        self.buttons = []
        if not simulate:
            import board
            import digitalio
            from adafruit_rgb_display.st7789 import ST7789
            self.spi = board.SPI()
            dc = digitalio.DigitalInOut(board.D25)
            backlight = digitalio.DigitalInOut(board.D22)
            self.pins.extend([dc, backlight])
            # Linux spidev0.0 owns and toggles CE0. Do not claim GPIO8 again,
            # or toggle GPIO5 based on the older lab's custom wiring comment.
            self.display = ST7789(self.spi, cs=None, dc=dc, rst=None,
                                  baudrate=24_000_000, width=135, height=240,
                                  x_offset=53, y_offset=40)
            backlight.switch_to_output(value=True)
            for pin in (board.D23, board.D24):
                button = digitalio.DigitalInOut(pin)
                button.switch_to_input(pull=digitalio.Pull.UP)
                self.buttons.append(button)
                self.pins.append(button)

    def font(self, size):
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        try:
            return self.ImageFont.truetype(path, size)
        except OSError:
            return self.ImageFont.load_default()

    def _send(self, image):
        # Driver completion is a software acknowledgement, not optical readback.
        if self.display is not None:
            self.display.image(image, rotation=90)
        self.preview.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.preview.with_suffix(".tmp.png")
        image.save(temporary)
        temporary.replace(self.preview)

    def status(self, title, detail=""):
        image = self.Image.new("RGB", (240, 135), "#101820")
        draw = self.ImageDraw.Draw(image)
        draw.text((10, 8), "MODULATE", font=self.font(13), fill="#64E3B5")
        draw.text((10, 37), str(title)[:22], font=self.font(18), fill="white")
        for index, line in enumerate(str(detail).splitlines()[:3]):
            draw.text((10, 72 + 18 * index), line[:30], font=self.font(12), fill="#D6DFE7")
        self._send(image)

    def render(self, frame, revision="", provider=""):
        image = self.Image.new("RGB", (240, 135), frame.background)
        draw = self.ImageDraw.Draw(image)
        draw.text((8, 6), frame.label, font=self.font(16), fill=frame.foreground)
        number = str(frame.number)
        size = 68
        while size > 20 and draw.textbbox((0, 0), number, font=self.font(size))[2] > 222:
            size -= 2
        font = self.font(size)
        box = draw.textbbox((0, 0), number, font=font)
        draw.text(((240 - box[2]) / 2, 28 - box[1] + (76 - (box[3] - box[1])) / 2),
                  number, font=font, fill=frame.foreground)
        draw.rectangle((0, 114, 240, 135), fill="#101820")
        draw.text((6, 117), f"{provider[:12]}  {revision[:8]}", font=self.font(11), fill="#64E3B5")
        self._send(image)
        return revision

    def pressed(self, index):
        return bool(self.buttons) and not self.buttons[index].value

    def close(self):
        for pin in reversed(self.pins):
            pin.deinit()
        if self.display is not None:
            self.spi.deinit()
