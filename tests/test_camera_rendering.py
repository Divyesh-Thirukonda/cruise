"""Actual rendering of synthetic JPEGs only; no physical camera or user images."""

import copy
from io import BytesIO
import unittest

from PIL import Image

from modulate.game_runtime import validate_commands
from modulate.rendering import Renderer
from tests.test_game_runtime import camera_command, fixture


def synthetic_jpeg(image):
    data = BytesIO()
    image.save(data, format="JPEG", quality=100, subsampling=0)
    with Image.open(BytesIO(data.getvalue())) as decoded:
        return decoded.convert("RGB")


class CameraRenderingTests(unittest.TestCase):
    def setUp(self):
        self.package = {**fixture(), "camera": {"target": "a" * 32}}
        self.renderer = Renderer(self.package)

    def render(self, command=None, camera=None, overlays=None):
        commands = [{"op": "clear", "color": "#112233"}, command or camera_command(), *(overlays or [])]
        validate_commands(commands, self.package["assets"]["sprites"], allow_camera=True)
        return self.renderer.render(commands, camera=camera)

    def test_actual_jpeg_pixels_and_mirror_reach_display_without_changing_source(self):
        source = Image.new("RGB", (240, 135), "red")
        source.paste("blue", (120, 0, 240, 135))
        camera = synthetic_jpeg(source)
        original = camera.tobytes()
        normal = self.render(camera=camera)
        mirrored = self.render(camera_command(mirror=True), camera)
        self.assertGreater(normal.getpixel((30, 60))[0], 245)
        self.assertGreater(normal.getpixel((210, 60))[2], 245)
        self.assertEqual(mirrored.getpixel((30, 60)), normal.getpixel((209, 60)))
        self.assertEqual(mirrored.getpixel((210, 60)), normal.getpixel((29, 60)))
        self.assertEqual(camera.tobytes(), original)

    def test_palette_effects_transform_decoded_brightness_and_keep_frame_size(self):
        source = Image.new("RGB", (240, 135), "black")
        source.paste("white", (120, 0, 240, 135))
        camera = synthetic_jpeg(source)
        expected = {"mono": ((16, 24, 32), (242, 248, 239)),
                    "neon": ((36, 6, 79), (100, 255, 196)),
                    "warm": ((53, 16, 48), (255, 204, 101))}
        for palette, (dark, light) in expected.items():
            with self.subTest(palette=palette):
                rendered = self.render(camera_command(palette=palette), camera)
                self.assertEqual(rendered.size, (240, 135))
                self.assertEqual(rendered.getpixel((30, 65)), dark)
                self.assertEqual(rendered.getpixel((210, 65)), light)

    def test_pixelation_coarsens_live_image_and_generated_sprite_overlays_it(self):
        source = Image.new("RGB", (240, 135))
        source.putdata([((x * 11) % 256, (y * 17) % 256, (x + y) % 256)
                        for y in range(135) for x in range(240)])
        camera = synthetic_jpeg(source)
        natural = self.render(camera=camera)
        pixelated = self.render(camera_command(pixelate=16), camera)
        self.assertLessEqual(len(pixelated.getcolors(240 * 135)), (240 // 16) * (135 // 16))
        self.assertNotEqual(natural.tobytes(), pixelated.tobytes())
        overlay = {"op": "sprite", "id": "ship", "x": 20, "y": 20, "scale": 1}
        result = self.render(camera=camera, overlays=[overlay])
        self.assertEqual(result.getpixel((21, 20)), (255, 51, 0))
        self.assertEqual(result.getpixel((20, 20)), natural.getpixel((20, 20)))

    def test_camera_viewport_clips_at_display_bounds(self):
        camera = synthetic_jpeg(Image.new("RGB", (240, 135), "white"))
        commands = [camera_command(x=-5, y=-5, w=10, h=10),
                    camera_command(x=235, y=130, w=10, h=10)]
        for command, visible, outside in ((commands[0], (0, 0), (5, 5)),
                                          (commands[1], (239, 134), (234, 129))):
            with self.subTest(command=command):
                result = self.render(command, camera)
                self.assertEqual(result.getpixel(visible), (255, 255, 255))
                self.assertEqual(result.getpixel(outside), (17, 34, 51))
        for x, y in ((-1024, -1024), (1024, 1024), (-.6, .4)):
            self.assertEqual(self.render(camera_command(x=x, y=y), camera).size, (240, 135))

    def test_missing_frame_shows_placeholder_instead_of_previous_camera_pixels(self):
        command = camera_command()
        original = copy.deepcopy(command)
        bright = synthetic_jpeg(Image.new("RGB", (240, 135), "red"))
        result = self.render(command, bright)
        self.assertGreater(result.getpixel((239, 134))[0], 245)
        missing = self.render(command)
        self.assertEqual(missing.getpixel((239, 134)), (23, 36, 47))
        self.assertNotEqual(missing.tobytes(), result.tobytes())
        self.assertEqual(command, original)
        new_frame = synthetic_jpeg(Image.new("RGB", (240, 135), "blue"))
        self.assertGreater(self.render(command, new_frame).getpixel((239, 134))[2], 245)


if __name__ == "__main__":
    unittest.main()
