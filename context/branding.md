# Website identity — October 29, 2026

The user's approved revision 16 uses three matching interlocking cube modules,
each with a broad inward end. The mark is monochrome; the red/blue/yellow palette is
for websites only, including the local companion and the public Connect app.
This does not recolor generated games, Pi screens, Muse animation, or hardware.

## Palette

- Blue `#1DAAF0`: primary actions, focus and active controls. Use dark text on fills.
- Yellow `#F0EB1D`: small highlights, favorites, completed setup steps and warnings.
- Red `#F01E27`: restrained destructive/error accents and decorative button detail.
- Dark neutral surfaces and readable light tints support those three brand colors.
  Error messages also have labels; color is not the only indicator.

## Logo asset and attribution

The user approved the programmatic integrated cube (gallery revision 16) on
October 29. `assets/brand/draw_logo_legs.py` builds one rounded filled module and
two exact 120° rotations, with equal seams. No image-generation model was used
for this approved revision. The canonical transparent SVG is
`assets/brand/modulate-loop-cube-legs.svg`.

The exact SVG is copied to:

- `modulate/web/logo.svg` — local Studio and focused setup
- `webapp/connect-app-code/public/brand/modulate-cube.svg` — public web wordmark

`webapp/connect-app-code/src/app/icon.svg` adds a dark tile behind that geometry
for the browser favicon. `modulate/web/logo.png` is its raster equivalent for
local browser icons. Transparent marks need no CSS blend-mode workaround. The
website palette and separate Meta attribution mark remain unchanged. This is
Modulate's custom mark, not an official Runpod or Meta asset.

## Historical generated draft

The earlier PNG was generated with OpenAI's built-in image-generation tool on
October 29, 2026. The user supplied Runpod as a rounded geometric style reference
and an impossible-triangle photograph as a subject reference. Neither reference
image is shipped in the repository. The generated logo is not an official Runpod
or Meta asset. The Meta attribution mark retains its separate identity.

That earlier output was previously used at:

- `modulate/web/logo.png` — local web pages
- `webapp/connect-app-code/public/brand/modulate-cube.png` — public header/wordmark
- `webapp/connect-app-code/src/app/icon.png` — browser icon

It had a black background and used CSS `mix-blend-mode: screen`. It has been
replaced by the approved vector above. The original generation prompt below is
retained as historical provenance, not the construction of the current logo.

### Earlier draft generation prompt

> Create one pristine flat logo: a rounded white isometric CUBE OUTLINE enclosing
> a smaller complete white PENROSE IMPOSSIBLE TRIANGLE. Solid pure BLACK #000000
> background everywhere else. Crisp vector-export appearance. The outer cube
> resembles a friendly geometric tech logo: hexagonal silhouette with softly
> rounded six corners, 3 subtle inward cube edge stubs, thick even white outline.
> Within that box, centered and separate with generous BLACK space around it,
> place a complete compact impossible triangle pointing upward, with three broad
> interconnected beams and crisp BLACK separation seams implying cyclical
> impossible over-under geometry. Cube and triangular core must both be instantly
> identifiable. Solid WHITE #FFFFFF shapes only, pure black negative spaces. NO
> shades or gradients, NO grain, NO surface texture, NO speckling, NO paper, NO
> transparency, NO thin outline artifacts, NO text. No tiny details. Generous
> clear space around the cube. Single centered icon, square canvas, logo about
> 76% of canvas height. Professional minimal icon for Modulate. One integrated
> cube enclosing impossible triangular core.
