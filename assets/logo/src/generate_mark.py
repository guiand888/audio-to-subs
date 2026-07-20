#!/usr/bin/env python3
"""
Generates the ParoleSub brand mark (icon + wordmark lockups) as a set of
static SVG/PNG assets, all derived from one pixel-grid source of truth.

Design system, for future sibling apps (podcast transcription, file-upload
transcription, ...):

  - Shared "container": a pixel-grid speech/subtitle bubble silhouette
    (rounded rect + stair-step tail), outlined in 1 dark cell, filled with
    a 4-band diagonal gradient of the single brand hue (H 222, per
    docs/dev/reference/THEME_SPEC.md). This shell stays identical across
    every app in the family.
  - Swappable "glyph": whatever sits inside the bubble is app-specific.
    ParoleSub uses three shrinking caption bars (subtitles). A future
    podcast app could use an equalizer/soundwave glyph; a file-upload app
    could use an upload-arrow glyph, etc. Keep the same grid unit, the same
    4-band palette, and the same outline color so the family reads as one
    brand.

Run `python3 generate_mark.py` to regenerate every file in this directory.
Requires only Pillow (already a transitive dep in this environment).
"""
import colorsys
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Pixel grid — the shared "container" (bubble + tail)
# ---------------------------------------------------------------------------
BODY_W, BODY_H = 28, 20
CORNER_R = 5
TAIL_ROWS = 3
TAIL_WIDTHS = [6, 4, 2]
TAIL_LEFT = 4
PAD = 1  # margin reserved for the outline ring

# App-specific "glyph": three shrinking caption/subtitle bars.
BARS = [(6, 6, 16), (9, 6, 12), (12, 6, 8)]  # (row, col, width) in body coords
BAR_HEIGHT = 2

CELL = 32  # px per grid cell for the hero raster export


def hsl(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    return (round(r * 255), round(g * 255), round(b * 255), 255)


# Brand hue H222 only (docs/dev/reference/THEME_SPEC.md) — 4 diagonal bands,
# light-to-dark, band[2] equals the theme's `--primary` as-is.
BANDS = [
    hsl(222, 28, 74),
    hsl(222, 32, 58),
    hsl(222, 35, 44),
    hsl(222, 30, 28),
]
FLAT_FILL = BANDS[2]
BAR_COLOR = hsl(210, 35, 97)  # matches the theme's light `--card` token
OUTLINE_COLOR = hsl(222, 30, 14)
TILE_BG = hsl(222, 26, 11)  # matches the theme's dark-mode `--background`

FONT_PATH = "/usr/share/fonts/liberation-mono-fonts/LiberationMono-Bold.ttf"
WORDMARK = "ParoleSub"


# ---------------------------------------------------------------------------
# Grid construction
# ---------------------------------------------------------------------------
def in_rounded_rect(x, y, w, h, r):
    cx, cy = x + 0.5, y + 0.5
    left, right = cx < r, cx > w - r
    top, bottom = cy < r, cy > h - r
    if left and top:
        return (cx - r) ** 2 + (cy - r) ** 2 <= r * r
    if right and top:
        return (cx - (w - r)) ** 2 + (cy - r) ** 2 <= r * r
    if left and bottom:
        return (cx - r) ** 2 + (cy - (h - r)) ** 2 <= r * r
    if right and bottom:
        return (cx - (w - r)) ** 2 + (cy - (h - r)) ** 2 <= r * r
    return True


def add_outline(grid):
    h, w = len(grid), len(grid[0])
    to_outline = []
    for y in range(h):
        for x in range(w):
            if grid[y][x] is not None:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and grid[ny][nx] is not None:
                        to_outline.append((y, x))
                        break
                else:
                    continue
                break
    for y, x in to_outline:
        grid[y][x] = "outline"


def build_grid(with_bars=True):
    """Returns the pixel grid — cells are None / 'body' / 'bar'."""
    w_total = BODY_W + 2 * PAD
    h_total = BODY_H + TAIL_ROWS + 2 * PAD
    grid = [[None] * w_total for _ in range(h_total)]
    for y in range(BODY_H):
        for x in range(BODY_W):
            if in_rounded_rect(x, y, BODY_W, BODY_H, CORNER_R):
                grid[y + PAD][x + PAD] = "body"
    for i, w in enumerate(TAIL_WIDTHS):
        y = BODY_H + i
        left = TAIL_LEFT + i
        for x in range(left, left + w):
            grid[y + PAD][x + PAD] = "body"
    if with_bars:
        for row, col, width in BARS:
            for dy in range(BAR_HEIGHT):
                for x in range(col, col + width):
                    grid[row + dy + PAD][x + PAD] = "bar"
    add_outline(grid)
    return grid


def band_color(x, y):
    """x, y are body-local coords (PAD already removed)."""
    norm = (x + y) / (BODY_W - 1 + BODY_H - 1)
    idx = min(int(norm * len(BANDS)), len(BANDS) - 1)
    return BANDS[idx]


def cell_color(grid, x, y, flat=False):
    cell = grid[y][x]
    if cell is None:
        return None
    if cell == "bar":
        return BAR_COLOR
    if cell == "outline":
        return OUTLINE_COLOR
    return FLAT_FILL if flat else band_color(x - PAD, y - PAD)


# ---------------------------------------------------------------------------
# Raster export
# ---------------------------------------------------------------------------
def render_mark_png(grid, path, cell=CELL, flat=False):
    w, h = len(grid[0]), len(grid)
    img = Image.new("RGBA", (w * cell, h * cell), (0, 0, 0, 0))
    px = img.load()
    for y in range(h):
        for x in range(w):
            color = cell_color(grid, x, y, flat=flat)
            if color is None:
                continue
            for dy in range(cell):
                for dx in range(cell):
                    px[x * cell + dx, y * cell + dy] = color
    if path is not None:
        img.save(path)
    return img


def render_mark_svg(grid, path, flat=False):
    w, h = len(grid[0]), len(grid)
    rects = []
    for y in range(h):
        for x in range(w):
            color = cell_color(grid, x, y, flat=flat)
            if color is None:
                continue
            r, g, b, _ = color
            rects.append(
                f'<rect x="{x}" y="{y}" width="1" height="1" fill="rgb({r},{g},{b})"/>'
            )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'shape-rendering="crispEdges">\n  '
        + "\n  ".join(rects)
        + "\n</svg>\n"
    )
    with open(path, "w") as f:
        f.write(svg)


def render_tile_png(mark_img, path, size=512, margin_ratio=0.16):
    tile = Image.new("RGBA", (size, size), TILE_BG)
    draw = ImageDraw.Draw(tile)
    radius = int(size * 0.22)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=TILE_BG)
    margin = int(size * margin_ratio)
    inner_w = size - 2 * margin
    ratio = min(inner_w / mark_img.width, inner_w / mark_img.height)
    new_size = (int(mark_img.width * ratio), int(mark_img.height * ratio))
    resized = mark_img.resize(new_size, Image.NEAREST)
    pos = ((size - new_size[0]) // 2, (size - new_size[1]) // 2)
    tile.alpha_composite(resized, pos)
    tile.save(path)


# ---------------------------------------------------------------------------
# Wordmark (pixelated raster text, blocky retro look via low-res + NEAREST)
# ---------------------------------------------------------------------------
def render_wordmark(color, upscale=6, font_px=16):
    font = ImageFont.truetype(FONT_PATH, font_px)
    tmp = Image.new("L", (1, 1), 0)
    d = ImageDraw.Draw(tmp)
    bbox = d.textbbox((0, 0), WORDMARK, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 2
    mask = Image.new("L", (w + pad * 2, h + pad * 2), 0)
    d = ImageDraw.Draw(mask)
    d.text((pad - bbox[0], pad - bbox[1]), WORDMARK, font=font, fill=255)
    mask = mask.point(lambda p: 255 if p > 110 else 0)
    mask = mask.resize((mask.width * upscale, mask.height * upscale), Image.NEAREST)
    out = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    solid = Image.new("RGBA", mask.size, color)
    out.paste(solid, (0, 0), mask)
    return out


def render_lockup_png(mark_img, text_color, path, gap=28):
    target_h = int(mark_img.height * 0.62)
    ratio = target_h / mark_img.height
    icon = mark_img.resize(
        (int(mark_img.width * ratio), target_h), Image.NEAREST
    )
    word = render_wordmark(text_color)
    ratio2 = icon.height / word.height * 0.66
    word = word.resize((int(word.width * ratio2), int(word.height * ratio2)), Image.NEAREST)

    pad = 16
    w = pad * 2 + icon.width + gap + word.width
    h = pad * 2 + max(icon.height, word.height)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    icon_y = pad + (h - pad * 2 - icon.height) // 2
    word_y = pad + (h - pad * 2 - word.height) // 2
    canvas.alpha_composite(icon, (pad, icon_y))
    canvas.alpha_composite(word, (pad + icon.width + gap, word_y))
    canvas.save(path)


def render_lockup_svg(icon_svg_path, text_color, path, label_w=560, label_h=160):
    r, g, b, _ = text_color
    with open(icon_svg_path) as f:
        icon_svg = f.read()
    grid_w = BODY_W + 2 * PAD
    grid_h = BODY_H + TAIL_ROWS + 2 * PAD
    icon_h = 100
    icon_w = icon_h * grid_w / grid_h
    total_w = icon_w + 20 + label_w
    total_h = max(icon_h, label_h)
    inner = icon_svg.split(">", 1)[1].rsplit("</svg>", 1)[0]
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w:.1f} {total_h}">
  <g transform="translate(0,{(total_h - icon_h) / 2:.1f}) scale({icon_h / grid_h:.4f})">
    {inner}
  </g>
  <text x="{icon_w + 20:.1f}" y="{total_h / 2:.1f}" dominant-baseline="middle"
        font-family="'Liberation Mono','DejaVu Sans Mono',monospace" font-weight="700"
        font-size="{label_h * 0.62:.1f}" letter-spacing="1"
        fill="rgb({r},{g},{b})">ParoleSub</text>
</svg>
'''
    with open(path, "w") as f:
        f.write(svg)


# ---------------------------------------------------------------------------
def main():
    grid = build_grid()

    render_mark_svg(grid, os.path.join(HERE, "parolesub-mark.svg"), flat=False)
    render_mark_svg(grid, os.path.join(HERE, "parolesub-mark-flat.svg"), flat=True)

    mark_png = render_mark_png(grid, os.path.join(HERE, "parolesub-mark.png"), flat=False)
    flat_png = render_mark_png(
        grid, os.path.join(HERE, "parolesub-mark-flat.png"), cell=CELL, flat=True
    )

    render_tile_png(flat_png, os.path.join(HERE, "parolesub-icon-tile.png"), size=512)

    # 16px favicon drops the caption bars — at that size they just muddy the
    # silhouette; the outlined bubble+tail shape alone stays legible.
    simple_grid = build_grid(with_bars=False)
    simple_png = render_mark_png(simple_grid, None, cell=CELL, flat=True)

    favicon_src = flat_png.resize((flat_png.width // 4, flat_png.height // 4), Image.LANCZOS)
    favicon_src.resize((32, int(32 * favicon_src.height / favicon_src.width)), Image.LANCZOS).save(
        os.path.join(HERE, "favicon-32.png")
    )
    simple_src = simple_png.resize((simple_png.width // 4, simple_png.height // 4), Image.LANCZOS)
    simple_src.resize((16, int(16 * simple_src.height / simple_src.width)), Image.LANCZOS).save(
        os.path.join(HERE, "favicon-16.png")
    )

    dark_text = hsl(222, 22, 20)
    light_text = hsl(210, 35, 96)

    render_lockup_png(mark_png, dark_text, os.path.join(HERE, "parolesub-lockup-light.png"))
    render_lockup_png(mark_png, light_text, os.path.join(HERE, "parolesub-lockup-dark.png"))

    render_lockup_svg(
        os.path.join(HERE, "parolesub-mark.svg"),
        dark_text,
        os.path.join(HERE, "parolesub-lockup-light.svg"),
    )
    render_lockup_svg(
        os.path.join(HERE, "parolesub-mark.svg"),
        light_text,
        os.path.join(HERE, "parolesub-lockup-dark.svg"),
    )

    print("done")


if __name__ == "__main__":
    main()
