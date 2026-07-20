# ParoleSub brand mark

Pixel-grid speech/subtitle bubble in the app's single brand hue (`H 222`,
navy — see `docs/dev/reference/THEME_SPEC.md`). Retro/pixel-art styling in
the vein of blocky, hard-edged mascot logos (Mistral AI's mark was a style
reference), but built from an original shape (a captioned speech bubble, not
a flame/wind glyph) and restricted to the app's own single-hue palette, so it
doesn't read as a Mistral asset.

All files are generated from one script — **do not hand-edit the SVGs or
PNGs**, edit `generate_mark.py` and re-run it:

```bash
python3 assets/logo/generate_mark.py
```

Requires only Pillow. `WORDMARK`/`FONT_PATH` rendering uses
`LiberationMono-Bold.ttf` (adjust `FONT_PATH` in the script if that font
isn't installed at that path on your machine).

## Design system (for sibling apps)

This is meant to be the **first mark in a family** — the company will ship
more transcription tools (podcast transcription, file-upload transcription,
etc.) and they should all look like siblings, not one-offs. The system
splits in two layers so future marks stay coherent without being identical:

1. **Shared container** (do not change per-app): the rounded, stair-stepped
   speech-bubble silhouette with its down-left tail, a 1-cell dark outline,
   and the 4-band diagonal navy gradient (`BANDS` in `generate_mark.py`,
   `H 222` only — per `THEME_SPEC.md` §"single brand hue", never add a
   second hue here). Same pixel grid unit, same outline color, same bands,
   every app.
2. **Swappable glyph** (change per-app): whatever sits inside the bubble.
   ParoleSub's glyph is three shrinking horizontal bars (`BARS`), reading as
   subtitle/caption lines. A future podcast-transcription app might use a
   small equalizer/soundwave glyph instead; a file-upload-transcription app
   might use an upload-arrow glyph. Keep the glyph on the same grid, using
   only `BAR_COLOR`/`OUTLINE_COLOR` (or the bubble's own bands) — never a new
   hue.

To start a sibling mark: copy `generate_mark.py`, keep `BODY_W/H`,
`CORNER_R`, `TAIL_*`, `PAD`, `BANDS`, `OUTLINE_COLOR`, `CELL` identical, and
only redefine `BARS` (or replace the "glyph" drawing step) with the new
app's icon.

## Files

| File | Use |
|---|---|
| `parolesub-mark.svg` / `.png` | Primary mark, transparent background, 4-band gradient. App icon source, docs headers, anywhere with room to breathe. |
| `parolesub-mark-flat.svg` / `.png` | Single-tone fill (no gradient). Use wherever the gradient would be too costly/noisy to reproduce (embroidery, single-color print, tiny UI glyphs). |
| `parolesub-icon-tile.png` | Flat mark centered on a rounded, dark-navy square tile (matches the theme's dark-mode background). App-icon / avatar treatment for platforms that expect a filled square (favicons, social profile images, PWA icons). |
| `favicon-32.png` | 32px favicon, flat mark with the caption-bar glyph (still legible at this size). |
| `favicon-16.png` | 16px favicon, glyph-free silhouette (bars merge into noise below ~24px, so the tiniest size drops them and keeps just the outlined bubble). |
| `parolesub-lockup-light.svg` / `.png` | Icon + "ParoleSub" wordmark, dark navy text — for light backgrounds. |
| `parolesub-lockup-dark.svg` / `.png` | Same lockup, light/cream text — for dark backgrounds. |

The wordmark in the **PNG** lockups is rendered as true blocky pixel-art
(low-res raster text, nearest-neighbor upscaled) to match the icon's pixel
grid exactly — use these for hero placements (README header, marketing,
socials). The wordmark in the **SVG** lockups is a normal scalable bold
monospace `<text>` node (not hand-vectorized to pixels) so it stays crisp at
any size and is cheap to reuse in-app (e.g. a sidebar header) — use these for
UI/product surfaces.

## Palette

All colors are the brand hue (`H 222`) or the theme's own light `card`
token for the glyph — no colors outside `docs/dev/reference/THEME_SPEC.md`'s
palette were introduced.

| Token | HSL | Role |
|---|---|---|
| Band 0 | `222 28% 74%` | Gradient, lightest (top-left) |
| Band 1 | `222 32% 58%` | Gradient |
| Band 2 | `222 35% 44%` | Gradient — equals theme `--primary` as-is |
| Band 3 | `222 30% 28%` | Gradient, darkest (bottom-right) |
| Flat fill | `222 35% 44%` | `-flat` variants (= Band 2) |
| Glyph / bars | `210 35% 97%` | Caption bars — matches theme light `--card` |
| Outline | `222 30% 14%` | 1-cell silhouette outline |
| Tile background | `222 26% 11%` | `icon-tile.png` backdrop — matches theme dark `--background` |
