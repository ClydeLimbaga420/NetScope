"""Render assets/netscope.ico from the NetScope icon design.

The geometry here mirrors assets/netscope.svg (the browser favicon and the
single source of truth for the artwork). Pillow is used so the build has no
external SVG/browser dependency. Run from the repository root:

    python build_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent

SIZE = 256
SCALE = 4
RES = SIZE * SCALE

OUT_ICO = ROOT / "assets" / "netscope.ico"
OUT_PNG = ROOT / "assets" / "netscope.png"

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

WHITE = (255, 255, 255, 255)
BLUE_CENTER = (45, 91, 238, 255)


def _mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _ramp(stops, t):
    t = min(max(t, 0.0), 1.0)
    for i in range(len(stops) - 1):
        o0, c0 = stops[i]
        o1, c1 = stops[i + 1]
        if t <= o1:
            local = 0.0 if o1 == o0 else (t - o0) / (o1 - o0)
            return _mix(c0, c1, local)
    return stops[-1][1]


def _background():
    x0, y0, x1, y1 = 24, 16, 236, 240
    dx, dy = x1 - x0, y1 - y0
    denom = dx * dx + dy * dy
    stops = [
        (0.0, (120, 199, 255)),
        (0.45, (76, 141, 255)),
        (1.0, (30, 63, 191)),
    ]
    img = Image.new("RGB", (SIZE, SIZE))
    px = img.load()
    for y in range(SIZE):
        for x in range(SIZE):
            t = ((x - x0) * dx + (y - y0) * dy) / denom
            px[x, y] = _ramp(stops, t)
    return img.resize((RES, RES), Image.LANCZOS).convert("RGBA")


def _cubic(p0, c1, c2, p1, steps=480):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p1[0]
        y = u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p1[1]
        pts.append((x, y))
    return pts


def _stroke(img, points, width, color, alpha_ramp=None):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    scaled = [(x * SCALE, y * SCALE) for x, y in points]
    radius = width * SCALE / 2.0
    draw.line(
        scaled,
        fill=color,
        width=max(1, int(round(width * SCALE))),
        joint="curve",
    )
    last = max(1, len(scaled) - 1)
    for index, (x, y) in enumerate(scaled):
        fill = color
        if alpha_ramp is not None:
            fill = color[:3] + (int(round(color[3] * alpha_ramp(index / last))),)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
    img.alpha_composite(layer)


def _disc(img, center, radius, color):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy, r = center[0] * SCALE, center[1] * SCALE, radius * SCALE
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    img.alpha_composite(layer)


def _ring(img, center, radius, width, color):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy, r = center[0] * SCALE, center[1] * SCALE, radius * SCALE
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        outline=color,
        width=max(1, int(round(width * SCALE))),
    )
    img.alpha_composite(layer)


def render():
    base = Image.new("RGBA", (RES, RES), (0, 0, 0, 0))

    mask = Image.new("L", (RES, RES), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (14 * SCALE, 14 * SCALE, 242 * SCALE, 242 * SCALE),
        radius=60 * SCALE,
        fill=255,
    )
    base.paste(_background(), (0, 0), mask)

    arcs = [
        (
            _cubic((40, 174), (65, 136), (97, 117), (128, 117))
            + _cubic((128, 117), (159, 117), (191, 136), (216, 174))[1:],
            18,
            235,
        ),
        (
            _cubic((62, 196), (80, 173), (103, 161), (128, 161))
            + _cubic((128, 161), (153, 161), (176, 173), (194, 196))[1:],
            16,
            199,
        ),
        (
            _cubic((93, 214), (100, 205), (110, 201), (122, 201))
            + _cubic((122, 201), (134, 201), (144, 205), (151, 214))[1:],
            12,
            179,
        ),
    ]
    for points, width, alpha in arcs:
        _stroke(base, points, width, (255, 255, 255, alpha))

    _disc(base, (128, 128), 22, (255, 255, 255, 250))
    _disc(base, (128, 128), 8, BLUE_CENTER)

    for points in (
        [(128, 40), (128, 66)],
        [(128, 190), (128, 216)],
        [(40, 128), (66, 128)],
        [(190, 128), (216, 128)],
    ):
        _stroke(base, points, 10, (255, 255, 255, 204))

    _ring(base, (128, 128), 88, 12, (255, 255, 255, 23))

    shine = _cubic((30, 50), (62, 24), (114, 18), (162, 38))
    _stroke(base, shine, 20, (223, 244, 255, 173), alpha_ramp=lambda t: 1 - t)

    return base.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    icon = render()
    icon.save(OUT_PNG, format="PNG")
    icon.save(OUT_ICO, format="ICO", sizes=ICO_SIZES)
    print(f"created {OUT_ICO} and {OUT_PNG}")


if __name__ == "__main__":
    main()
