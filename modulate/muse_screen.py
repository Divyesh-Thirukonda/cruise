"""Local, animated Muse-inspired state cards for the 240×135 PiTFT.

The illustration is a custom Modulate adaptation of Meta's public Muse mascot,
not Meta's avatar renderer. No model call, downloaded asset or audio analysis is
needed to draw a frame. The caller chooses the mood from real device state.
"""
from functools import lru_cache
from math import pi, sin
import random
import time

from PIL import Image, ImageDraw, ImageFilter

from .rendering import font


FPS = 8
FRAMES = 32
BG = "#12151E"
INK = "#F5F2EB"
MUTED = "#B8BECF"
ACCENTS = {
    "idle": "#BBA8FF", "listening": "#8CE1D5", "thinking": "#BBA8FF",
    "speaking": "#93BEFF", "building": "#BBA8FF", "clarify": "#FFD58F",
    "error": "#FFB4A5", "success": "#A3E6AE", "instructions": "#93BEFF",
}
LABELS = {
    "idle": "MUSE", "listening": "ALL EARS", "thinking": "ONE MOMENT",
    "speaking": "LET’S TALK", "building": "MAKING IT", "clarify": "LET’S FIGURE IT OUT",
    "error": "LET’S FIX IT", "success": "READY TO GO", "instructions": "TOGETHER",
}


def _phase(now):
    return int((time.monotonic() if now is None else now) * FPS) % FRAMES


def _curve(points, steps=12):
    """Cubic path: initial point followed by groups of three control/end points."""
    result = [points[0]]
    start = points[0]
    for i in range(1, len(points), 3):
        a, b, end = points[i:i + 3]
        for j in range(1, steps + 1):
            t = j / steps
            u = 1 - t
            result.append((u**3 * start[0] + 3*u*u*t*a[0] + 3*u*t*t*b[0] + t**3*end[0],
                           u**3 * start[1] + 3*u*u*t*a[1] + 3*u*t*t*b[1] + t**3*end[1]))
        start = end
    return result


@lru_cache(maxsize=1)
def _fur():
    rng = random.Random(41)
    # Stable texture: fur doesn't sparkle/change randomly between frames.
    return tuple((rng.uniform(12, 90), rng.uniform(8, 104), rng.uniform(.3, .8),
                  rng.choice(("#EADFCB", "#FFF8E5", "#E4D7BF"))) for _ in range(850))


@lru_cache(maxsize=96)
def _character_frame(mode, frame):
    scale = 3
    image = Image.new("RGBA", (104 * scale, 112 * scale))
    d = ImageDraw.Draw(image)
    phase = frame / FRAMES * 2 * pi
    bounce = -abs(sin(phase * 2)) * 4 if mode == "success" else sin(phase) * .8

    def box(coords):
        return tuple(round((v + (bounce if i % 2 else 0)) * scale) for i, v in enumerate(coords))

    def points(coords):
        return [(round(x * scale), round((y + bounce) * scale)) for x, y in coords]

    def ellipse(coords, fill, outline=None, width=1):
        d.ellipse(box(coords), fill=fill, outline=outline, width=round(width * scale))

    def line(coords, fill, width=1):
        d.line(points(coords), fill=fill, width=round(width * scale), joint="curve")

    def curve(coords, fill, width=1):
        line(_curve(coords), fill, width)

    # Grounding shadow stays on the floor while the character bounces.
    d.ellipse((24*scale, 102*scale, 81*scale, 108*scale), fill=(2, 4, 12, 75))
    cream, shade = "#F1E6CF", "#C7B99F"
    ellipse((30, 85, 46, 104), shade)
    ellipse((56, 85, 72, 104), shade)
    ellipse((31, 84, 46, 102), cream)
    ellipse((56, 84, 71, 102), cream)

    def arm(coords, width=10):
        path = _curve(coords)
        line(path, shade, width + 1)
        line([(x-.4, y-.7) for x, y in path], cream, width)
        x, y = path[-1]
        ellipse((x-width/2, y-width/2, x+width/2, y+width/2), cream)

    left = [(28, 51), (20, 58), (16, 69), (17, 79)]
    right = [(75, 51), (83, 60), (87, 68), (86, 79)]
    if mode == "success":
        left = [(28, 53), (14, 48), (12, 33), (16, 29)]
        right = [(75, 52), (89, 45), (91, 32), (87, 27)]
    elif mode == "speaking":
        left = [(28, 53), (17, 59), (12, 58), (11, 52 + sin(phase*3)*3)]
        right = [(75, 53), (85, 60), (90, 58), (92, 50 - sin(phase*3)*2)]
    elif mode == "instructions":
        right = [(75, 51), (87, 48), (89, 37), (86+sin(phase*2)*2, 34)]
    arm(left)
    if mode != "listening":
        arm(right)

    contour = _curve([(28, 38), (24, 19), (33, 8), (51, 8),
                      (70, 8), (79, 20), (75, 39),
                      (76, 48), (84, 65), (81, 81),
                      (79, 94), (68, 98), (51, 98),
                      (33, 98), (22, 94), (21, 81),
                      (18, 66), (25, 48), (28, 38)])
    mask = Image.new("L", image.size)
    md = ImageDraw.Draw(mask)
    md.polygon(points(contour), fill=255)
    # Soft radial light and tiny fibers give the low-resolution character a
    # plush surface without a large sprite sheet or a new graphics dependency.
    body = Image.new("RGBA", image.size)
    bd = ImageDraw.Draw(body)
    bd.rectangle((0, 0, *image.size), fill=shade)
    for r in range(95, 4, -2):
        light = max(0, 1 - r / 100)
        color = tuple(round(a + (b-a)*light) for a, b in zip((208, 195, 169), (255, 248, 225)))
        bd.ellipse(((43-r)*scale, (40+bounce-r)*scale, (43+r)*scale, (40+bounce+r)*scale), fill=color)
    for x, y, length, color in _fur():
        bd.line(((x*scale, (y+bounce)*scale), ((x+.25)*scale, (y+bounce+length)*scale)), fill=color, width=1)
    image.paste(body, (0, 0), mask)
    d = ImageDraw.Draw(image)
    # Halo fibers soften the silhouette; they are deliberately subtle at 1×.
    for i, (x, y) in enumerate(contour):
        if i % 2 == 0:
            vx, vy = x-51, y-55
            n = max(1, (vx*vx+vy*vy)**.5)
            line([(x, y), (x+vx/n*.6, y+vy/n*.6)], "#F0E5CF", .4)

    # Peach face, tucked into the fuzzy hood.
    d.rounded_rectangle(box((31, 22, 72, 58)), radius=14*scale, fill="#D0B798")
    d.rounded_rectangle(box((32, 22, 71, 57)), radius=13*scale, fill="#F8DDBB")
    d.rounded_rectangle(box((34, 23, 69, 55)), radius=12*scale, fill="#FAE2C3")
    ellipse((35, 43, 43, 49), "#EDB4A1")
    ellipse((61, 43, 69, 49), "#EDB4A1")
    blink = frame in (25, 26)
    if mode == "success":
        curve([(39, 39), (40, 35), (43, 35), (44, 39)], "#382D28", 1.7)
        curve([(59, 39), (60, 35), (63, 35), (64, 39)], "#382D28", 1.7)
    elif blink:
        curve([(39, 38), (41, 40), (42, 40), (44, 38)], "#382D28", 1.5)
        curve([(59, 38), (61, 40), (62, 40), (64, 38)], "#382D28", 1.5)
    else:
        offset = 1 if mode in ("thinking", "building") else 0
        ellipse((39+offset, 34, 44+offset, 41), "#302B2A")
        ellipse((59+offset, 34, 64+offset, 41), "#302B2A")
        ellipse((40+offset, 35, 41.5+offset, 36.5), "#FFFFFF")
        ellipse((60+offset, 35, 61.5+offset, 36.5), "#FFFFFF")
    if mode in ("clarify", "error"):
        line([(38, 31), (43, 29)], "#8C6C55", 1)
        line([(60, 29), (65, 31)], "#8C6C55", 1)
        curve([(48, 49), (49, 46), (53, 46), (55, 49)], "#795441", 1)
    elif mode == "speaking":
        openness = (2, 5, 3, 7, 4, 2, 6, 4)[frame % 8]
        ellipse((47, 45, 56, 45+openness), "#6B3F37")
        if openness > 4:
            ellipse((49, 48, 54, 45+openness), "#EAA094")
    elif mode == "listening":
        curve([(48, 47), (49, 49), (53, 49), (55, 46)], "#795441", 1.2)
    elif mode == "success":
        d.pieslice(box((45, 40, 58, 52)), start=0, end=180, fill="#70473A")
        curve([(48, 49), (50, 47), (54, 47), (56, 49)], "#EEA69B", 1.5)
    else:
        curve([(48, 46), (50, 49), (53, 49), (55, 46)], "#795441", 1.2)

    if mode == "listening":
        arm([(75, 56), (89, 51), (87, 33), (80, 29)], 10)
        # Visible palm/thumb makes the cupped-ear gesture distinct from waving.
        curve([(83, 27), (78, 26), (77, 31), (80, 34)], "#B9A68B", 1)
        ellipse((75, 31, 79, 37), "#F1E6CF")
        for i in range(2):
            alpha = 140 + round(80*sin(phase*2-i))
            d.arc(box((88+i*4, 22-i*4, 97+i*4, 40+i*4)), -65, 65,
                  fill=(140, 225, 213, alpha), width=scale)
    elif mode in ("thinking", "clarify", "error"):
        arm([(76, 57), (77, 65), (64, 61), (59, 56)], 8)
    elif mode == "building":
        arm([(26, 59), (28, 71), (38, 73), (44, 73)], 8)
        arm([(77, 59), (74, 70), (65, 74), (60, 73)], 8)
        ellipse((44, 66, 60, 82), "#514471")
        ellipse((46, 67, 59, 80), "#BBA8FF")
        line([(49, 70), (51, 68), (55, 69)], "#F2EFFF", 1.2)
    if mode in ("success", "building", "thinking"):
        for i, (x, y) in enumerate(((16, 17), (88, 13), (91, 76))):
            r = 1.2 + max(0, sin(phase*2+i))*1.6
            color = ACCENTS[mode]
            line([(x-r, y), (x+r, y)], color, .8)
            line([(x, y-r), (x, y+r)], color, .8)
    return image.resize((104, 112), Image.Resampling.LANCZOS)


def render_character(mode="idle", now=None, size=(104, 112)):
    """Return an owned RGBA image; callers cannot mutate the cached frame."""
    mode = mode if mode in ACCENTS else "idle"
    frame = _character_frame(mode, _phase(now))
    return frame.copy() if size == frame.size else frame.resize(size, Image.Resampling.LANCZOS)


@lru_cache(maxsize=192)
def _wrap(text, size, width):
    """Wrap by actual font metrics; preserve all words, including long tokens."""
    face = font(size)
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = []
    for paragraph in str(text).splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = (line + " " + word).strip()
            if draw.textlength(candidate, font=face) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = ""
            for char in word:
                if line and draw.textlength(line + char, font=face) > width:
                    lines.append(line)
                    line = ""
                line += char
        lines.append(line)
    return tuple(lines)


def card_layout(mode, title, detail, footer=""):
    """Text layout exposed for lossless paging checks, using native Pi dimensions."""
    titles = _wrap(str(title), 14, 148)
    # Full-width copy leaves enough room for spoken questions/error details;
    # compact cards leave the large character the whole left side.
    compact = len(_wrap(str(detail), 11, 128)) > 3 or len(titles) > 2 or mode in ("error", "clarify")
    title_width = 156 if compact else 128
    title_lines = _wrap(str(title), 14, title_width)
    detail_lines = _wrap(str(detail), 11, 216 if compact else 128)
    title_pages = tuple(tuple(title_lines[i:i+2]) for i in range(0, len(title_lines), 2))
    detail_pages = tuple(tuple(detail_lines[i:i+3]) for i in range(0, len(detail_lines), 3))
    footer_lines = _wrap(str(footer), 9, 218)
    return {"compact": compact, "title_pages": title_pages, "detail_pages": detail_pages,
            "footer_pages": tuple((line,) for line in footer_lines)}


def render_card(mode, title, detail, footer="", now=None, width=240, height=135):
    """Render a state card. Overflow copy pages, rather than being discarded.

    The native canvas remains 240×135. Other sizes scale that canvas for previews;
    the caller should pass time relative to card entry so each begins at page 1.
    """
    mode = mode if mode in ACCENTS else "idle"
    now = time.monotonic() if now is None else max(0, now)
    layout = card_layout(mode, str(title), str(detail), str(footer))
    image = Image.new("RGB", (240, 135), BG)
    draw = ImageDraw.Draw(image)
    accent = ACCENTS[mode]
    draw.text((10, 5), LABELS[mode], font=font(8), fill=accent)
    draw.ellipse((225, 8, 228, 11), fill=accent)
    page_time = 3.5
    page_index = int(now / page_time)
    titles = layout["title_pages"][page_index % len(layout["title_pages"])]
    details = layout["detail_pages"][page_index % len(layout["detail_pages"])]
    footer_page = layout["footer_pages"][page_index % len(layout["footer_pages"])]
    if layout["compact"]:
        mascot = render_character(mode, now=now, size=(53, 57))
        image.paste(mascot, (9, 15), mascot)
        title_x, title_y, detail_x, detail_y = 74, 22, 12, 74
    else:
        # Gentle pool of light behind the plush character.
        glow = Image.new("RGBA", image.size)
        ImageDraw.Draw(glow).ellipse((4, 27, 95, 111), fill=(*tuple(int(accent[i:i+2], 16) for i in (1,3,5)), 14))
        glow = glow.filter(ImageFilter.GaussianBlur(13))
        image.paste(glow, (0, 0), glow)
        mascot = render_character(mode, now=now, size=(94, 101))
        image.paste(mascot, (3, 16), mascot)
        title_x, title_y, detail_x, detail_y = 102, 25, 102, 64
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(titles):
        draw.text((title_x, title_y + i*17), line, font=font(14), fill=INK)
    for i, line in enumerate(details):
        draw.text((detail_x, detail_y + i*13), line, font=font(11), fill=MUTED)
    page_count = max(len(layout["detail_pages"]), len(layout["title_pages"]), len(layout["footer_pages"]))
    if page_count > 1:
        # Tiny page bars retain the footer for essential button/voice guidance.
        count = min(page_count, 8)
        for i in range(count):
            x = 190 + i*4
            draw.line((x, 15, x+2, 15), fill=accent if i == page_index % page_count else "#414655")
    draw.line((10, 117, 230, 117), fill="#303440")
    draw.text((11, 120), footer_page[0], font=font(9), fill="#CFD3DF")
    if (width, height) != image.size:
        return image.resize((width, height), Image.Resampling.NEAREST)
    return image
