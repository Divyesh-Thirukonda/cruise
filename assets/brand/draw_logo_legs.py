"""Draw three matching cube modules with integrated inward ends; no raster model."""
from math import dist, sqrt
from pathlib import Path

ROOT = Path(__file__).parent
CENTER = 128.0
OUTER_RADIUS = 96.0
SEAM = 9.0
LEFT_EDGE = 98.0
RETURN_WIDTH = 22.0
RETURN_DEPTH = 111.0
SIN60 = sqrt(3) / 2


def rounded_path(points, radii):
    """Round corners inside one continuous silhouette, with no overlaid strokes."""
    corners = []
    for index, point in enumerate(points):
        def toward(other):
            amount = min(radii[index] / dist(point, other), 0.45)
            return tuple(p + (q - p) * amount for p, q in zip(point, other))
        corners.append((toward(points[index - 1]), point,
                        toward(points[(index + 1) % len(points)])))
    path = 'M %.5f %.5f' % corners[-1][2]
    for before, point, after in corners:
        path += ' L %.5f %.5f Q %.5f %.5f %.5f %.5f' % (*before, *point, *after)
    return path + ' Z'


def draw():
    outer_right = CENTER + OUTER_RADIUS * SIN60
    # The adjacent copy's diagonal becomes vertical after rotation. Deriving
    # this endpoint from the same seam width keeps all three openings equal.
    seam_end_y = CENTER + (LEFT_EDGE - SEAM - CENTER + OUTER_RADIUS * SIN60 / 2) / SIN60
    inner_peak_y = seam_end_y - OUTER_RADIUS / 2
    return_edge = LEFT_EDGE + RETURN_WIDTH
    points = [
        (LEFT_EDGE, CENTER - OUTER_RADIUS + (CENTER - LEFT_EDGE) / sqrt(3)),
        (CENTER, CENTER - OUTER_RADIUS),
        (outer_right, CENTER - OUTER_RADIUS / 2),
        (outer_right, seam_end_y),
        (CENTER, inner_peak_y),
        (return_edge, inner_peak_y + (CENTER - return_edge) / sqrt(3)),
        (return_edge, RETURN_DEPTH),
        (LEFT_EDGE, RETURN_DEPTH + RETURN_WIDTH / sqrt(3)),
    ]
    module = rounded_path(points, [0, 12, 12, 0, 4, 3, 4, 4])
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <title>Modulate — integrated cube</title>
  <desc>Three identical solid modules with broad inward ends and equal seams. Each complete piece is rotated by exactly 120 degrees.</desc>
  <defs><path id="module" d="{module}"/></defs>
  <g fill="white">
    <use href="#module"/>
    <use href="#module" transform="rotate(120 128 128)"/>
    <use href="#module" transform="rotate(240 128 128)"/>
  </g>
</svg>
'''


if __name__ == '__main__':
    svg = draw()
    (ROOT / 'modulate-loop-cube-legs.svg').write_text(svg)
    preview = ((ROOT / 'preview.html').read_text()
               .replace('modulate-loop-cube.svg', 'modulate-loop-cube-legs.svg')
               .replace('Modulate folded cube logo', 'Modulate cube with integrated inward ends'))
    (ROOT / 'preview-legs.html').write_text(preview)
    (ROOT / 'review').mkdir(exist_ok=True)
    (ROOT / 'review' / '16.svg').write_text(svg)
    (ROOT / 'review' / '16-preview.html').write_text(preview.replace('modulate-loop-cube-legs.svg', '16.svg'))
    # Keep the previously shared preview URL useful; #15 remains archived as SVG.
    (ROOT / 'review' / '15-preview.html').write_text(preview.replace('modulate-loop-cube-legs.svg', '16.svg'))
