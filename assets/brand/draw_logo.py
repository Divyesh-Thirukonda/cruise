"""Draw the Modulate logo study using geometry only. Run with Python 3."""
from math import cos, sin, pi, dist
from pathlib import Path

CENTER = 128
OUTER_RADIUS = 96
INNER_RADIUS = 48
SEAM_WIDTH = 9


def hexagon(radius):
    return [(CENTER + radius * cos(-pi / 2 + i * pi / 3),
             CENTER + radius * sin(-pi / 2 + i * pi / 3)) for i in range(6)]


def rounded_path(points, radius):
    """Round each polygon vertex with an equal-distance quadratic join."""
    corners = []
    for i, point in enumerate(points):
        def toward(other):
            amount = radius / dist(point, other)
            return tuple(p + (q - p) * amount for p, q in zip(point, other))
        corners.append((toward(points[i - 1]), point, toward(points[(i + 1) % len(points)])))
    x, y = corners[-1][2]
    path = f'M{x:.3f} {y:.3f}'
    for (ax, ay), (x, y), (bx, by) in corners:
        path += f' L{ax:.3f} {ay:.3f} Q{x:.3f} {y:.3f} {bx:.3f} {by:.3f}'
    return path + ' Z'


# One seam is repeated exactly at 120° and 240°. Its ends extend past the
# band into transparency, avoiding visible caps or little leftover stubs.
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <title>Modulate — interlocking cube</title>
  <desc>Three matching bent modules around a central opening, with exact 120-degree rotational symmetry.</desc>
  <defs>
    <path id="seam" d="M219.798 141 L155.713 104"/>
    <mask id="openings">
      <rect width="256" height="256" fill="white"/>
      <path d="{rounded_path(hexagon(INNER_RADIUS), 6)}" fill="black"/>
      <g stroke="black" stroke-width="{SEAM_WIDTH}" stroke-linecap="butt">
        <use href="#seam"/>
        <use href="#seam" transform="rotate(120 128 128)"/>
        <use href="#seam" transform="rotate(240 128 128)"/>
      </g>
    </mask>
  </defs>
  <path d="{rounded_path(hexagon(OUTER_RADIUS), 12)}" fill="white" mask="url(#openings)"/>
</svg>
'''
Path(__file__).with_name('modulate-loop-cube.svg').write_text(svg)
