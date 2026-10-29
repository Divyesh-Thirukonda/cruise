"""Native-resolution, offline checks for Muse cards; no device or model calls."""

from contextlib import contextmanager
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from modulate import muse_screen
from modulate.rendering import font


def content(text):
    """Ignore wrapping whitespace, while preserving every visible character."""
    return "".join(text.split())


@contextmanager
def text_draws():
    """Observe the real rendered text and retain the actual Pillow drawing."""
    recorded = []
    original = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        face = kwargs.get("font")
        recorded.append({"text": text, "size": getattr(face, "size", None),
                         "bounds": draw.textbbox(xy, text, font=face)})
        return original(draw, xy, text, *args, **kwargs)

    with patch.object(ImageDraw.ImageDraw, "text", capture):
        yield recorded


class MuseScreenTests(unittest.TestCase):
    def test_all_character_states_render_as_native_display_rgb(self):
        for mode in muse_screen.ACCENTS:
            with self.subTest(mode=mode):
                card = muse_screen.render_card(mode, "Listening", "Speak your request", now=0)
                self.assertEqual(card.size, (240, 135))
                self.assertEqual(card.mode, "RGB")
                character = muse_screen.render_character(mode, now=0)
                self.assertEqual(character.size, (104, 112))
                self.assertEqual(character.mode, "RGBA")
                self.assertIsNotNone(character.getbbox())

    def test_preview_scaling_does_not_change_native_render_or_cache(self):
        native = muse_screen.render_card("listening", "Listening", "Speak now", now=1)
        preview = muse_screen.render_card("listening", "Listening", "Speak now",
                                         now=1, width=960, height=540)
        self.assertEqual(preview.size, (960, 540))
        self.assertEqual(preview.mode, "RGB")
        self.assertEqual(preview.resize(native.size, Image.Resampling.NEAREST).tobytes(),
                         native.tobytes())

    def test_unknown_mode_has_a_drawable_idle_fallback(self):
        unknown = muse_screen.render_card("new-unrecognized-state", "Ready", "Say Hey Meta", now=0)
        idle = muse_screen.render_card("idle", "Ready", "Say Hey Meta", now=0)
        self.assertEqual(unknown.tobytes(), idle.tobytes())

    def test_mutating_returned_character_cannot_poison_cached_frames(self):
        for size in ((104, 112), (57, 61)):
            with self.subTest(size=size):
                image = muse_screen.render_character("speaking", now=0.25, size=size)
                original = image.tobytes()
                image.paste((255, 0, 0, 255), (0, 0, *image.size))
                again = muse_screen.render_character("speaking", now=0.25, size=size)
                self.assertEqual(again.tobytes(), original)
                self.assertNotEqual(image.tobytes(), original)

    def test_animation_is_stable_within_a_frame_and_moves_across_frames(self):
        for mode in muse_screen.ACCENTS:
            with self.subTest(mode=mode):
                first = muse_screen.render_character(mode, now=0.01).tobytes()
                held = muse_screen.render_character(mode, now=0.10).tobytes()
                self.assertEqual(first, held)
                frames = {muse_screen.render_character(mode, now=step / 8).tobytes()
                          for step in (0, 1, 4, 8, 16, 25)}
                self.assertGreater(len(frames), 2)

    def test_listening_gesture_and_speaking_mouth_are_distinct_and_animated(self):
        listening = muse_screen.render_character("listening", now=0)
        speaking = muse_screen.render_character("speaking", now=0)
        # The raised hand/ear region distinguishes listening from a talking pose.
        gesture = (72, 16, 104, 60)
        self.assertNotEqual(listening.crop(gesture).tobytes(), speaking.crop(gesture).tobytes())
        # Speech animation must change the face, not only a loading decoration.
        mouth = (45, 43, 58, 55)
        second = muse_screen.render_character("speaking", now=1 / 8)
        self.assertNotEqual(speaking.crop(mouth).tobytes(), second.crop(mouth).tobytes())
        later = muse_screen.render_character("listening", now=0.5)
        self.assertNotEqual(listening.crop(gesture).tobytes(), later.crop(gesture).tobytes())

    def test_wrap_preserves_long_tokens_unicode_and_explicit_paragraphs(self):
        samples = (
            "Hold both screen buttons, then say Hey Meta to cancel.",
            "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW end",
            "First instruction.\n\nSecond instruction with café and curly ‘quotes’.",
            "é" * 85 + " -- final instruction",
            "",
        )
        metric = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        for text in samples:
            for size, width in ((14, 128), (14, 156), (11, 128), (11, 216), (9, 218)):
                with self.subTest(text=text, size=size, width=width):
                    lines = muse_screen._wrap(text, size, width)
                    self.assertTrue(lines)
                    self.assertEqual(content("".join(lines)), content(text))
                    for line in lines:
                        self.assertLessEqual(metric.textlength(line, font=font(size)), width)

    def test_actual_render_pages_retain_every_title_detail_and_footer_character(self):
        title = "Build could not start because a required control is disconnected"
        detail = ("Your saved app is safe. Connect the green button, then tell me when it is ready. "
                  "Keep the red button disconnected until its address has been checked. "
                  "Do not change the wiring while the device is powered on. "
                  "Address 0x6E belongs to the green button, and 0x6F belongs to the red button.")
        footer = "After reconnecting, say Hey Meta followed by Check my hardware to continue safely."
        layout = muse_screen.card_layout("error", title, detail, footer)
        fields = (("title_pages", title, 14), ("detail_pages", detail, 11),
                  ("footer_pages", footer, 9))
        self.assertTrue(all(len(layout[key]) > 1 for key, _, _ in fields))
        shown = {key: [] for key, _, _ in fields}
        for page in range(max(len(layout[key]) for key, _, _ in fields)):
            with text_draws() as drawn:
                muse_screen.render_card("error", title, detail, footer, now=page * 3.5)
            for key, _, size in fields:
                if page < len(layout[key]):
                    shown[key].extend(item["text"] for item in drawn if item["size"] == size)
        for key, original, _ in fields:
            with self.subTest(field=key):
                self.assertEqual(content("".join(shown[key])), content(original))

    def test_text_ink_stays_inside_native_canvas_on_every_page(self):
        cases = (
            ("listening", "Listening", "Speak your request", ""),
            ("speaking", "Replying aloud", "B: stop speaking\nBoth screen buttons: talk", ""),
            ("building", "Verifying your new game", "Reviewer / verify candidate",
             'Say "Hey Meta, cancel rebuild"'),
            ("error", "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW",
             "An unavailable module paused the saved application. Please reconnect the required controls.",
             "B: back. Say Hey Meta, check my hardware, to continue."),
            ("clarify", "Quick question", "Would you like me to repair the controller or keep using this app?",
             "Reply after I finish speaking"),
        )
        for mode, title, detail, footer in cases:
            layout = muse_screen.card_layout(mode, title, detail, footer)
            count = max(len(layout[key]) for key in ("title_pages", "detail_pages", "footer_pages"))
            for page in range(count):
                with self.subTest(mode=mode, page=page):
                    with text_draws() as drawn:
                        muse_screen.render_card(mode, title, detail, footer, now=page * 3.5)
                    for item in drawn:
                        left, top, right, bottom = item["bounds"]
                        self.assertGreaterEqual(left, 0, item["text"])
                        self.assertGreaterEqual(top, 0, item["text"])
                        self.assertLessEqual(right, 240, item["text"])
                        self.assertLessEqual(bottom, 135, item["text"])


if __name__ == "__main__":
    unittest.main()
