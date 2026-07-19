# Theme & Frontend Style Spec

Reusable brief for theming a shadcn/Tailwind (or equivalent CSS-variable-based)
app to this brand. Hand this file to an agent along with "theme this app" —
no further explanation should be needed.

## Brand

- Single brand hue: navy blue `#4b6195` (HSL `222 35% 44%`).
- No secondary accent hue. Ever. If a design needs "more color," get it from
  saturation/lightness variation on this one hue, or from status colors
  (below) — not a second brand hue.
- Reads as: restrained, muted, engineering-tool. Not marketing-forward, not
  colorful.

## Principles

1. **No pure black, no pure white.** Every neutral — background, foreground,
   card, border — carries a slight cool tint derived from the brand hue
   (~H 218-222). `0%` saturation anywhere in the palette is a defect, not a
   stylistic choice.
2. **Soften the extremes.** Foreground text is never `L 0-5%` or `L 95-100%`;
   dark-mode background is never near-black (`L < 8%`); light-mode background
   is never stark white (`L > 98%` — reserve that for elevated cards, not the
   page canvas).
3. **One hue does the work of color.** Primary actions, active nav state,
   focus rings, and links all use the brand hue at varying `L`. Hover/active
   surface states (`accent`) use a *light tint* of the brand hue rather than
   plain gray — this is what makes brand presence show up in interaction,
   not just in buttons.
4. **Status colors are not brand colors.** Destructive/error (red) and
   warning (amber) stay semantically separate from the brand hue. `info` may
   reuse the brand hue (blue reads as "info" universally) — that's the one
   place status and brand are allowed to overlap. Never repurpose a status
   hue as a decorative accent.
5. **Elevation via lightness, not shadow-heavy.** Card surfaces sit one step
   lighter than the page background in both modes — enough to read as a
   distinct surface without a heavy drop shadow.
6. **Scrims are the one sanctioned pure-black exception.** A modal backdrop
   (`bg-black/80` or equivalent) is a compositing overlay, not a themed
   surface — leave it alone.

## Token recipe (HSL, `H S% L%`)

Given brand `H_b S_b L_b` (here `222 35% 44%`):

| Token | Light | Dark |
|---|---|---|
| `background` | `H_b±4 S_b-10% L 93-95%` | `H_b S_b-10% L 10-13%` |
| `card` | `H_b-8 S_b L 98-99%` | `H_b S_b-10% L 14-16%` (one step lighter than bg) |
| `foreground` | `H_b S_b-15% L 18-22%` | `H_b-2 S_b-15% L 87-90%` |
| `primary` | brand as-is | brand, `L` raised ~20pt for legibility (`L 60-68%`) |
| `secondary` / `muted` | `H_b S_b-15% L 88-92%` | `H_b S_b-15% L 17-20%` |
| `muted-foreground` | `H_b S_b-25% L 40-46%` | `H_b S_b-25% L 58-64%` |
| `accent` | brand tint, `L 92-94%` (visible tint, not gray) | brand shade, `L 22-26%` |
| `border` / `input` | `H_b S_b-20% L 80-84%` | `H_b S_b-20% L 20-23%` |
| `ring` | = `primary` | = `primary` |
| `destructive` | `H 4 S~62% L~51%` | same, `L` +2-4pt |

Status/log severity (kept off the brand hue except `info`):

- `debug` → neutral, `S~10% L~48%` (light) / `L~58%` (dark)
- `info` → brand hue, `L~55%` (light) / `L~65%` (dark)
- `warning` → amber `H~36 S~80% L~46%` (light) / `L~56%` (dark) — **pair with
  a dedicated `-foreground` token** (dark text); white-on-amber fails WCAG
- `error` → = `destructive`

## Anti-patterns (reject these)

- Any HSL/hex with `0%` saturation used for a themed surface (background,
  card, border, muted).
- A second accent hue "just for variety."
- White text on amber/yellow without a dedicated foreground token.
- Hardcoded `bg-black`, `text-white`, `gray-*`/`zinc-*`/`slate-*` Tailwind
  utilities in app code — everything routes through the CSS-variable tokens
  so both themes and future re-brands are a one-file change.
- A `tailwind.config` (or equivalent) color palette that duplicates what the
  CSS variables already express.

## Verification checklist

- [ ] Every token in `:root` / `.dark` (or platform equivalent) carries the
      brand hue or a deliberate status hue — no `0%` saturation.
- [ ] `grep` for hardcoded
      `bg-black|text-white|gray-[0-9]|zinc-[0-9]|slate-[0-9]|neutral-[0-9]`
      in component code returns only sanctioned exceptions (scrims).
- [ ] Contrast: body text ≥ 4.5:1, badge/small-bold text ≥ 3:1, in both
      themes (check `warning` and `info` badges specifically — they're the
      ones most likely to fail).
- [ ] Visual check in both light and dark: sidebar/nav active state, primary
      button, focus ring, at least one data table/card list, and any
      severity/status badges.

## Reference implementation

Parolesub's current theme ("Ayu Tint") is the worked example of this
recipe — see `frontend/src/index.css`. Brand `222 35% 44%`, light bg
`218 28% 94%`, dark bg `222 26% 11%`. Copy that file's `:root`/`.dark` block
as a starting point when re-deriving for a new brand hue; just substitute
`H_b` throughout.
