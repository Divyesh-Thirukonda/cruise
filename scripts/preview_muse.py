"""Produce an explicitly simulated state-card contact sheet and animation.

Run from the repository root:
    .venv/bin/python -m scripts.preview_muse --output context/evidence
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from modulate.muse_screen import FPS, FRAMES, render_card
from modulate.rendering import font


CARDS = (
    ("idle", "Hey Meta", "What shall we make?", "Both buttons: talk"),
    ("listening", "I’m listening", "Tell me your idea.", "Pause 3 sec to send"),
    ("thinking", "Understanding", "Putting your idea together.", "Hey Meta, cancel"),
    ("speaking", "Speaking", "Here’s what I found.", "B: stop speaking"),
    ("building", "Building", "Making your kart game.", "Hey Meta, cancel rebuild"),
    ("success", "Made for you!", "Your new app is ready.", "Let’s play"),
    ("clarify", "One small thing", "I couldn’t hear the last part. What would you like the knob to control?", "Just answer; no wake phrase"),
    ("error", "Let’s try again", "The screen check failed. Your previous app is still saved.", "Your saved app is safe"),
    ("instructions", "Connect a module", "Power off before changing wires.", "A: continue / B: back"),
)


def sheet(cards, now):
    rows = (len(cards) + 2) // 3
    result = Image.new("RGB", (720, rows * 135 + 22), "#0B0D12")
    for i, card in enumerate(cards):
        result.paste(render_card(*card, now=now), ((i % 3)*240, (i // 3)*135))
    ImageDraw.Draw(result).text((10, rows*135+5), "MODULATE / Illustrated state preview · not a live device capture",
                               font=font(10), fill="#AFB7CA")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/modulate-muse-preview"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sheet(CARDS, .5).save(args.output / "muse-states.png")
    animated = (CARDS[1], CARDS[3], CARDS[4], CARDS[6], CARDS[7], CARDS[5])
    frames = [sheet(animated, i / FPS) for i in range(FRAMES)]
    frames[0].save(args.output / "muse-states.gif", save_all=True, append_images=frames[1:],
                   duration=1000 // FPS, loop=0, optimize=True, disposal=2)
    print(args.output / "muse-states.png")
    print(args.output / "muse-states.gif")


if __name__ == "__main__":
    main()
