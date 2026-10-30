# Programmatic logo study

Created October 29, 2026 following the user's direction to stop image generation
and use a simple, editable construction.

`modulate-loop-cube.svg` is a transparent white mark drawn from rounded hexagonal
geometry and one seam repeated at 120° intervals. All three sections match. The
staggered joins suggest parts rotating into one another. This is a geometric
logo study, not a claim of a mathematically impossible object.

Run `python3 assets/brand/draw_logo.py` to reproduce the SVG. The generator uses
only Python's standard library. `preview.html` shows the wordmark and 24/32/48 px
sizes; `preview.png` records the browser rendering. No image model was used.

The first study remains archived. Revision 16 below is the approved website logo.

## Integrated inward ends — revision 16

The previous small hooks were rejected for looking too thin and leaving a
shoulder where they joined the band. `draw_logo_legs.py` now constructs one
continuous filled module, including a 22-unit-wide inward end. The other two
modules are exact 120°/240° copies. All three seams derive from the same
9-unit width. There are no added strokes, overlapping hook roots or masks.

Run `python3 assets/brand/draw_logo_legs.py` to reproduce
`modulate-loop-cube-legs.svg`. `preview-legs.html` shows the large mark, wordmark
and 24/32/48 px sizes. Gallery #15 preserves the old hooks; #16 is the revision.
The previously shared `15-preview.html` URL now displays the corrected mark.
The user approved revision 16 on October 29. Its exact SVG is now the source for
the public Connect and local Studio/setup marks. Favicons use the same geometry
on a dark tile. See `context/branding.md` for deployed asset paths and provenance.
