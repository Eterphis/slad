# Icons

The set lives in `assets/icons/`: `icons.svg` (sprite, ids `ct-i-<name>`), `icons.json`
(path data for code), and `svg/ct-i-<name>.svg` (standalone files, firn ink).

The set (24): home, search, menu, close, add, check, chevron, arrow, download, upload,
settings, user, alerts, mail, calendar, delete, edit, lock, show, info, warning, link,
refresh, power.

## Using them

- `<svg class="ct-icon" aria-hidden="true"><use href="…/icons.svg#ct-i-search"/></svg>`
  inherits `currentColor`; size 16, 24 (default) or 32 via width/height.
- Icon-only controls need `aria-label` on the control, not on the svg.
- States: rest in the surrounding ink; hover or focus on the parent turns the stroke signal
  and lights the via (`--ct-via`); on = `.is-on` (via live); fault = `.is-fault` (copper).
- At 16px, drop the via unless it is the glyph's dot (info, warning, the lock's keyhole).
- Don't recolour icons with aurora colours at rest. Colour shows state, it's not decoration.

## Drawing a new one

Every new icon must look like it came off the same board.

1. **Grid**: 24 × 24 with a 2px margin; draw inside the 20px live area. Snap points to whole
   or half pixels.
2. **Stroke**: 1.5px, miter joins, flat (butt) ends. Outline only, one weight, no fills
   except the via.
3. **Angles**: 0°, 45° and 90° only. A curve becomes a chamfer; a round object becomes an
   octagon (see search's lens, user's head, power's ring).
4. **Corners**: closed shapes cut top-left and bottom-right by 3–4px. Round objects cut all
   four corners.
5. **Via**: at most one, radius 2 (1.5 for a dot), where the current enters: a free line
   end (arrow's tail, search's handle), a crossing (close, add) or the glyph's dot (info,
   warning, keyhole). Pure direction marks (chevron) carry none. In the sprite the via is
   `<circle … style="fill: var(--ct-via, var(--ct-panel))"/>`.
6. **Metaphor**: the plainest object people recognize. Prefer an object to an abstraction.
   Draw from the chip-and-fjord world only when the meaning stays obvious.
7. **Name**: what people do with it, `ct-i-` plus a lower-case noun. Check that it reads
   at 16px in one colour, and that no icon in the set already means the same thing.

Add a new icon to all three places: the sprite, `icons.json`, and `svg/`.

Path data for reference (24 grid):

| id | path | via (cx, cy, r) |
|---|---|---|
| home | `M2,12 L12,2 L22,12 M5,9 V21 H16 L19,18 V9` | 12, 16, 2 |
| search | `M7,3 H17 V13 L14,16 H3 V7 Z M15.5,14.5 L19.5,18.5` | 19.5, 18.5, 2 |
| close | `M5,5 L19,19 M19,5 L5,19` | 12, 12, 2 |
| lock | `M8,10 V6 L10,4 H14 L16,6 V10 M7,10 H20 V18 L17,21 H4 V13 Z` | 12, 15.5, 2 |
| chevron | `M9,5 L16,12 L9,19` | none |

The rest are in `icons.json`.

The files in this group are standalone SVGs drawn in firn ink (#EAF3F7) with a black via fill, for dark grounds. In code, use the sprite or inline paths so icons take `currentColor` and work in both modes.
