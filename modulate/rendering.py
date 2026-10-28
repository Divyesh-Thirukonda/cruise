"""Trusted drawing adapter for validated game frames and generated pixel assets."""
from functools import lru_cache
from io import BytesIO
from math import floor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


@lru_cache(maxsize=24)
def font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Monaco.ttf"):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow 9.4 on the Pi has no size argument.
        return ImageFont.load_default()


def _pixel(value):
    """Round continuous coordinates to integer pixels, including half pixels."""
    return floor(value + 0.5)


class Renderer:
    def __init__(self, package):
        self.sprites = {}
        for name, sprite in package.get("assets", {}).get("sprites", {}).items():
            image = Image.new("RGBA", (sprite["width"], sprite["height"]))
            image.putdata([((0, 0, 0, 0) if sprite["palette"][index] == "transparent"
                            else tuple(int(sprite["palette"][index][i:i + 2], 16) for i in (1, 3, 5)) + (255,))
                           for row in sprite["pixels"] for index in row])
            self.sprites[name] = image
        self.scaled = {}

    def render(self, commands):
        image = Image.new("RGB", (240, 135), "black")
        draw = ImageDraw.Draw(image)
        for command in commands:
            op = command["op"]
            if op == "clear":
                draw.rectangle((0, 0, 239, 134), fill=command["color"])
            elif op == "rect":
                x, y, w, h = (command[k] for k in ("x", "y", "w", "h"))
                # Rasterize half-open edges before converting to Pillow's
                # inclusive box. Tiny positive shapes may cover no pixels;
                # they must not produce a reversed/invalid rectangle.
                left, top = max(0, _pixel(x)), max(0, _pixel(y))
                right, bottom = min(image.width, _pixel(x + w)), min(image.height, _pixel(y + h))
                if left < right and top < bottom:
                    draw.rectangle((left, top, right - 1, bottom - 1), fill=command["color"])
            elif op == "circle":
                x, y, r = (command[k] for k in ("x", "y", "r"))
                draw.ellipse(tuple(_pixel(v) for v in (x - r, y - r, x + r, y + r)), fill=command["color"])
            elif op == "line":
                draw.line(tuple(_pixel(command[k]) for k in ("x1", "y1", "x2", "y2")), fill=command["color"])
            elif op == "text":
                draw.text((_pixel(command["x"]), _pixel(command["y"])), command["text"], font=font(command.get("size", 10)), fill=command["color"])
            elif op == "sprite":
                name, scale = command["id"], command.get("scale", 1)
                key = name, scale
                if key not in self.scaled:
                    sprite = self.sprites[name]
                    self.scaled[key] = sprite.resize((sprite.width * scale, sprite.height * scale), Image.Resampling.NEAREST)
                sprite = self.scaled[key]
                image.paste(sprite, (_pixel(command["x"]), _pixel(command["y"])), sprite)
        return image


def png(image):
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()
