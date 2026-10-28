"""Actual pixels and fractional-boundary regressions for the trusted renderer."""
import copy
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image

from modulate.game_runtime import validate_commands
from modulate.rendering import Renderer, font, png


SPRITE = {"width": 2, "height": 2,
          "palette": ["transparent", "#ff0000", "#0000ff", "#00ff00"],
          "pixels": [[1, 0], [2, 3]]}
PACKAGE = {"assets": {"sprites": {"original": SPRITE}}}


class RenderingTests(unittest.TestCase):
    def render(self, commands):
        validate_commands(commands, PACKAGE["assets"]["sprites"])
        return Renderer(PACKAGE).render(commands)

    def test_tiny_valid_rectangles_at_coordinate_extremes_never_raise(self):
        # Includes positive subnormal floats: x+w may equal x in floating point.
        for position in (-1024, -0.6, -0.1, 0, 0.49, 0.5, 134.9, 239.9, 1024):
            for width, height in ((5e-324, 5e-324), (0.01, 0.1), (0.99, 0.99),
                                  (0, 1), (1, 0), (0.1, 1024), (1024, 0.1)):
                with self.subTest(position=position, width=width, height=height):
                    image = self.render([{"op": "rect", "x": position, "y": position,
                                          "w": width, "h": height, "color": "#ffffff"}])
                    self.assertEqual(image.size, (240, 135))

    def test_fractional_rectangles_round_edges_and_skip_empty_coverage(self):
        image = self.render([
            {"op": "rect", "x": 2.4, "y": 3.4, "w": 1.2, "h": 1.2, "color": "#ff0000"},
            {"op": "rect", "x": 10, "y": 10, "w": 0.1, "h": 0.1, "color": "#ffffff"},
        ])
        self.assertEqual(image.getpixel((2, 3)), (255, 0, 0))
        self.assertEqual(image.getpixel((3, 4)), (255, 0, 0))
        self.assertEqual(image.getpixel((4, 4)), (0, 0, 0))
        self.assertEqual(image.getpixel((10, 10)), (0, 0, 0))
        self.assertEqual(sum(count for count, pixel in image.getcolors() if pixel != (0, 0, 0)), 4)

    def test_rectangles_clip_without_wrapping_and_clear_replaces_old_frame(self):
        renderer = Renderer(PACKAGE)
        commands = [{"op": "rect", "x": -0.6, "y": -0.6, "w": 2.2, "h": 2.2, "color": "#ffffff"},
                    {"op": "rect", "x": 239.4, "y": 134.4, "w": 1024, "h": 1024, "color": "#ff0000"},
                    {"op": "rect", "x": 1024, "y": 1024, "w": 0.01, "h": 0.01, "color": "#0000ff"}]
        validate_commands(commands, PACKAGE["assets"]["sprites"])
        image = renderer.render(commands)
        self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(image.getpixel((1, 1)), (255, 255, 255))
        self.assertEqual(image.getpixel((239, 134)), (255, 0, 0))
        self.assertEqual(image.getpixel((238, 134)), (0, 0, 0))
        self.assertEqual(renderer.render([{"op": "clear", "color": "#112233"}]).getextrema(),
                         ((17, 17), (34, 34), (51, 51)))

    def test_sprite_nearest_scaling_preserves_original_colors_and_transparency(self):
        original = copy.deepcopy(PACKAGE)
        image = self.render([{"op": "clear", "color": "#112233"},
                             {"op": "sprite", "id": "original", "x": 4, "y": 5, "scale": 3}])
        colors = {(255, 0, 0), (0, 0, 255), (0, 255, 0), (17, 34, 51)}
        self.assertEqual({pixel for _, pixel in image.getcolors()}, colors)
        self.assertEqual(image.getpixel((4, 5)), (255, 0, 0))
        self.assertEqual(image.getpixel((6, 7)), (255, 0, 0))
        self.assertEqual(image.getpixel((7, 5)), (17, 34, 51))
        self.assertEqual(image.getpixel((4, 8)), (0, 0, 255))
        self.assertEqual(image.getpixel((7, 8)), (0, 255, 0))
        self.assertEqual(PACKAGE, original)

    def test_sprite_fractional_origin_and_negative_clipping_keep_alpha(self):
        image = self.render([{"op": "clear", "color": "#ffffff"},
                             {"op": "sprite", "id": "original", "x": -0.6, "y": -0.6, "scale": 2}])
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(image.getpixel((1, 0)), (255, 255, 255))
        self.assertEqual(image.getpixel((0, 1)), (0, 0, 255))
        self.assertEqual(image.getpixel((1, 1)), (0, 255, 0))
        self.assertEqual(image.getpixel((3, 3)), (255, 255, 255))

    def test_finite_fractional_primitives_at_all_bounds_and_png_roundtrip(self):
        commands = [{"op": "line", "x1": -1024, "y1": 10.4, "x2": 1024, "y2": 10.4, "color": "#ffffff"},
                    {"op": "circle", "x": -1024, "y": 1024, "r": 512, "color": "#ffffff"},
                    {"op": "circle", "x": 30.4, "y": 30.4, "r": 0.01, "color": "#ff0000"},
                    {"op": "text", "x": 1024, "y": -1024, "text": "Off screen", "color": "#ffffff", "size": 8},
                    {"op": "sprite", "id": "original", "x": -1024, "y": 1024, "scale": 8}]
        image = self.render(commands)
        self.assertEqual(image.getpixel((0, 10)), (255, 255, 255))
        self.assertEqual(image.getpixel((239, 10)), (255, 255, 255))
        with Image.open(BytesIO(png(image))) as decoded:
            self.assertEqual(decoded.size, image.size)
            self.assertEqual(decoded.tobytes(), image.tobytes())

    def test_pillow_94_font_fallback_accepts_old_no_size_api(self):
        fallback = object()
        font.cache_clear()
        try:
            with patch("modulate.rendering.Path.is_file", return_value=False), \
                 patch("modulate.rendering.ImageFont.load_default", side_effect=[TypeError("no size"), fallback]) as loader:
                self.assertIs(font(12), fallback)
                self.assertEqual(loader.call_count, 2)
                self.assertEqual(loader.call_args.kwargs, {})
        finally:
            font.cache_clear()


if __name__ == "__main__":
    unittest.main()
