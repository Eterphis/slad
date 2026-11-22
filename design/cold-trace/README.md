# Cold Trace

Northern lights, glacier fjords and chip wiring. A chip is etched into the wall of a fjord:
current runs where meltwater ran, and the aurora lights every wire it touches. Night is full
black; daylight is glacier ice. Depth is a hard block of ice under each key, never a shadow.
Colour is current: it lives inside lines.

## Using this system

- **Load** `components/bundle.css` (it imports the two Google fonts, defines every role in
  both modes, and every piece) and `components/bundle.js` (`window.ColdTrace`: one-touch
  throw, switches, curtains, colour mode). Put `class="ct"` on `<body>`; set
  `data-theme="light"` on `<html>` for daylight.
- **Build from the pieces** in Components. Their markup is canonical: copy it, keep the
  class names, change the words.
- **Read only role tokens** (`--ct-ground`, `--ct-panel`, `--ct-ink`, `--ct-ink-2`,
  `--ct-line`, `--ct-rule`, `--ct-well`, `--ct-sock`, `--ct-key`, `--ct-key-ink`,
  `--ct-live`, `--ct-signal`, `--ct-arc`, `--ct-fault`, `--ct-series-1`, `--ct-series-2`).
  Never write a literal colour; both modes swap by role.
- The same kit ships as a **Claude Code skill** (`cold-trace/`, with React, Astro and
  Tailwind adapters and three example pages). This page and the skill share one stylesheet
  and one token file.

## The twelve rules

1. Use role tokens, never literal colours.
2. Colour fills nothing: aurora colours only as 1–2px lines, vias, trace fills, chart lines
   and the hero curtain.
3. Words stay ink; a via or edge beside them carries state. Copper may write its own error.
4. Copper (`--ct-fault`) means fault and is the only warm colour.
5. Chamfer, never round: cut top-left and bottom-right at 45° (6/10/16px). The only circle
   is the via.
6. Lines turn at 0°, 45°, 90° and end in a via.
7. Depth is a hard frosted block, never a shadow, glow or blur.
8. Anybody, always wide (112–150%), for titles, labels, keys and key numbers; Martian Mono
   for body and changing numbers. Sentence case.
9. One prime key per view; one light touch plays the whole throw.
10. Motion is fast, eased and never stepped; a hand's action lands within 250ms.
11. Eight spacing steps (4 to 96px), a 1360px container, 96px between sections.
12. Copy is an instrument log: plain verbs, errors that say how to fix, no exclamation marks.

---

## 1. The idea

A chip etched into the wall of a fjord. Current runs where meltwater ran, and the aurora
lights every wire it touches.

Three worlds meet, and every decision should trace back to one of them:

- **Glacier and fjord**: full black (night) or pale ice (day), cold whites, frost, grit
  like snow under a microscope. Depth comes from hard blocks of ice, never soft shadows.
- **The aurora**: green, cyan and violet light. It lives *inside lines*, as current
  running along traces and outlines, and as hairline curtains in a few big moments.
  It never floods a surface.
- **Chip wiring**: traces that turn at 45° and 90° and end in vias (small rings), packages
  with chamfered corners, pin pitches, etched metal. Everything looks routed, not drawn.

The feel to aim for: icy, crystalline, precise, electric. Heavy where a hand touches it,
weightless everywhere else.

## 2. Voice

The interface talks like an instrument log: short, cold, exact.

- Plain verbs in sentence case. The kit's own verbs are **charge, hold, ground, cut**,
  but in a real product name actions by what they do: "Save changes", "Delete project".
- A key says exactly what happens, and the result repeats the verb: "Publish" then
  "Published"; "Restore line 4" then "Line 4 restored".
- Errors state what broke and how to fix it. No apologies, no exclamation marks, no
  blame: "Too deep. The fjord ends at 1,308 m, so enter that or less."
- Empty states invite the first action; they don't describe mood.
- No emoji, no exclamation marks, no "Oops", no "Awesome".
- Labels are sentence case. All caps is reserved for the page title set in the display face.

## 3. Colour roles

Components read **role tokens only**. Never write a literal colour in a component; if
nothing fits, you're missing a role, so add it to both modes.

| Role | Night | Daylight | Use |
|---|---|---|---|
| `--ct-ground` | #000000 | #D6E5EE ice | The page, under grit |
| `--ct-panel` | #000000 | #F7FBFD snow | Inside frames, fields, toasts, tags |
| `--ct-ink` | #EAF3F7 firn | #000000 | Text, outlines that matter, checked states |
| `--ct-ink-2` | #86A9BD melt | #3B5263 slate | Captions, hints, headers, idle nav |
| `--ct-line` | #4E6E84 wire | #5A7689 | Edges and traces at rest (≥3:1) |
| `--ct-rule` | #1E3546 rime | #A9C0CE hoar | Decoration only: rules, etch |
| `--ct-well` | #081624 fjord | #BCD2DF crevasse | Inside slots and tracks, frosted |
| `--ct-sock` | #1F3A4E | #7FA6BF glacier | The block under keys, frosted |
| `--ct-key` / `--ct-key-ink` | firn / black | black / snow | Prime key face and its word |
| `--ct-flash` | #EAF3F7 | #FFFFFF | Landing spark (animation only) |
| `--ct-live` | #3DF5A0 | #00916A | On, success, charged |
| `--ct-signal` | #38DDFF | #0077AA | Focus, hover, selection, links |
| `--ct-arc` | #A47BFF | #6A3FE0 | Info, data, second series |
| `--ct-fault` | #FF8A3D copper | #A0400A | Errors, cuts, destructive actions |
| `--ct-fault-sock` | #4A2410 | #E0A27A | The block under a Cut key |
| `--ct-series-1` / `-2` | #1AA3CF / #9A6CF5 | #0077AA / #6A3FE0 | Chart series only |
| `--ct-aurora` | live → signal → arc | deep set | Gradient for lines only |
| `--ct-frost`, `--ct-grit` | | | Textures (section 7) |

Rules, with the reason behind each:

- **Colour fills nothing.** Surfaces are ground, panel, well, socket or the key face.
  The aurora colours appear as 1–2px lines, vias, fills of *traces*, chart lines, and
  the curtain. A filled green button or a cyan card would turn current into paint and
  the whole idea collapses.
- **Words stay ink.** Text uses `--ct-ink` or `--ct-ink-2`. The one exception is copper,
  which may write its own fault message. Status is carried by a via or an edge beside
  the word, so state is never colour alone.
- **Copper means fault, and nothing else is warm.** If a warm colour appears anywhere
  else, people will read it as an error.
- **Black is black.** Night ground is #000000, never #0B0B0B or #111.
- **Contrast is part of the palette:** ink ≥16:1, ink-2 ≥6.3:1, every interactive
  edge and aurora line ≥3:1, in both modes. Don't put `--ct-ink-2` text on `--ct-well`.

## 4. Type

Two families, each with a fixed job.

- **Anybody** (display), always wide: `font-stretch` 112–150%. Weight 700–900. For
  titles, headings, labels, key words, numbers that matter. The width is the
  personality, so never set Anybody at 100% width.
- **Martian Mono** (body and data): everything read at length, every changing number,
  code. Weight 400.

Load both from Google Fonts:
`https://fonts.googleapis.com/css2?family=Anybody:wdth,wght@50..150,100..900&family=Martian+Mono:wdth,wght@75..112.5,100..800&display=swap`

Scale (px): **144** title · **72** display · **48** section · **36** readout · **24** panel
· **16** interface · **14** body and label · **12** caption. Use the classes in
`cold-trace.css` (`.ct-title`, `.ct-display`, `.ct-section`, `.ct-readout`,
`.ct-panel-title`, `.ct-ui`, `.ct-label`, `.ct-body`, `.ct-cap`).

- Sentence case everywhere except the page title.
- Body lines ≤65 characters.
- Numbers that update use `font-variant-numeric: tabular-nums` (`.ct-num`).
- Don't emphasise one word of a headline in another colour or italic.
- Don't put small all-caps labels above every heading. A block heading is a via and the
  words (`.ct-h`), nothing else.

## 5. Shape

- **Chamfer, never round.** Cut the **top-left and bottom-right** corners at 45° ("pin
  one" sits top left). Sizes: `--ct-cut-s` 6px (checks, thumbs, tags), `--ct-cut-m` 10px
  (keys, fields, toasts, tiles), `--ct-cut-l` 16px (panels, screens, the lever). Use
  `.ct-frame` (with `--s` or `--l`) for outlined chamfered boxes; it draws the edge and
  the fill as two clipped layers. `border-radius` is 0 everywhere.
- **The via is the only circle.** A small ring at the end of a line, a radio, a status
  dot, a spinner. Nothing else is round: no pills, no round avatars, no round cards.
  Show an avatar as a chamfered square.
- **Lines turn at 0°, 45° or 90°** and end in a via. No curves, no other angles. This
  holds for dividers, connectors, chart lines (step or straight segments), icons and
  illustrations.
- **Line weights:** 1px trace (rest), 2px live (current: focus, progress, on), 4px bus
  (one per screen, under the title). Panels can take the layered ice edge
  (`.ct-frame--ice`): outer edge, 3px gap, fainter inner hairline.

## 6. Spacing and layout

Spacing steps, named for chip parts: **4** via · **8** pitch · **12** pin · **16** pad ·
**24** lane · **32** bus · **48** bank · **96** die. Use `--ct-*` variables, never other
values.

- Page container `.ct-wrap`: max 1360px, 40px gutter (16px on phones).
- A 12-column grid, 32px column gap, 48px row gap between blocks; 96px between page
  sections (`.ct-sec`).
- Section head: the title (`.ct-section`) and a short note on the right, then a
  `.ct-ruler` (a trace with pin ticks ending in a via).
- Lay out siblings with flex or grid and `gap`, not margins.
- Left-align text. Center only a single title or a loading message.
- Touch targets ≥44px. Everything collapses to one column at phone width; wide tables
  scroll inside `.ct-table-box`.
- Density is controlled: generous negative space around a few heavy elements (keys,
  numbers, the title), not a uniform scatter of equal cards.

## 7. Surface

- **Grit**: blue specks (night) or blue specks with white glints (day) on the ground,
  from `--ct-grit`. On the page ground only, never on panels. `.ct` applies it.
- **Frost**: a 45° lattice of hairlines (`--ct-frost`). Fills every well and socket and
  dead (disabled) keys. It signals "below the surface" or "inactive".
- **Etch**: 1px vertical lines on 4px pitch in `--ct-rule`, for die-like detail on
  illustrations. Rare.
- **Curtain**: aurora hairlines (`.ct-curtain` with `data-ct-curtain`, drawn by
  cold-trace.js). Hero sections and full loading screens only, never behind running
  text. It's the one slow, ambient animation.
- **No shadows, no glows, no blur.** Depth is a solid block (the socket) offset below
  the face. Elevation for menus and dialogs is a frame with the ice edge on panel
  colour, not a shadow.

## 8. Motion

Motion is how the system feels heavy and electric. It's fast and eased, and it never steps.

| Name | Curve | Time | Use |
|---|---|---|---|
| Throw | `--ct-drop` | 110ms down | A key drops its full travel and lands hard |
| Release | `--ct-spring` | 220ms | It springs back past its mark |
| Spark | `--ct-arrive` | 80–280ms | Flash where current lands (socket, slot) |
| Pulse | `--ct-current` | 420ms in, 180ms out; busy 700ms/lap | Current laps an outline on hover/focus |
| Charge | `--ct-current` | 480ms | A trace fills: progress, toggles, breaker |
| Cut | `--ct-arrive` | 220ms | A line opens and turns copper: errors |
| Orbit | `--ct-current` | 900ms/turn | Unknown wait; eases every turn |
| Curtain | ease-in-out | 9s, alternate | Ambient aurora; the one slow thing |

- **One light touch moves heavy loads.** A single click, tap, Enter or Space plays the
  whole press (`.is-thrown`, 400ms), however short the touch. Never require holding.
- A hand's action lands within 250ms; current may keep running after it.
- No linear easing, no `steps()`, no fades longer than 220ms, no bounce on landing.
  Overshoot belongs to release only.
- Entrance motion only answers an action (a toast drops in 12px). Don't animate
  sections in on scroll.
- Respect `prefers-reduced-motion` (the stylesheet cuts animations to 1ms).

## 9. Two modes

Night (dark) is the default. Daylight is a second set of role values, not an inverted
palette:

- Black moves from ground to ink; ground becomes ice and panels become snow.
- The aurora **deepens** (it doesn't flip or pale) so lines hold 3:1 on ice.
- In daylight, live, signal and arc never colour words.
- Grit gains white glints; frost turns dark blue; sockets turn glacier blue.
- Shapes, spacing, type, motion and icons are identical.

Switch with `data-theme="light"` on `<html>` (or any subtree). `ColdTrace.setTheme('dark'
| 'light' | 'system')` stores the choice. Put the before-paint snippet in `<head>` so the
page doesn't flash (see this README). Every page offers a mode switch: a `.ct-toggle`
labelled "Daylight" in the top bar.

## 10. Composing something the kit doesn't have

When a screen needs a piece the kit lacks (a modal, tabs, a menu, a chart, a date picker),
build it from these parts rather than importing another library's look:

1. **Container**: `.ct-frame` (`--ice` for floating things), panel fill, chamfer by size.
   Modals and menus: `.ct-frame--l .ct-frame--ice`, no shadow, no backdrop blur; dim the
   page with `--ct-ground` at 70% opacity.
2. **Selection and focus**: signal edge or a lit via. Selected tabs: ink word and a 2px
   signal trace under them, ending in a via. Never a filled pill.
3. **Actions**: `.ct-btn` kinds. One prime key per view; everything else ground or cut.
4. **State**: a via (`.ct-v--live|signal|arc|fault`) or a `.ct-tag`. Words stay ink.
5. **Data**: Martian Mono, tabular numbers, `.ct-table` for rows.
6. **Charts**: lines, not filled areas or bars. Bars become thick traces (2–4px) ending in
   vias. Series 1 is `--ct-series-1`, series 2 `--ct-series-2` (a validated pair; the neon
   signal and arc are too light for chart marks on black). More than two series: small
   multiples. Give the second series a secondary encoding too (dashed line or square end).
   Thresholds are dashed `--ct-line`; grid lines `--ct-rule`. Label values in ink, never
   in the series colour; always a legend for two series. Axis lines turn at 90°; smooth
   curves become stepped or straight segments. Every mark gets a hover tooltip.
7. **Motion**: pick from the table in section 8. If none fits, use `--ct-current` at
   `--ct-run`.

If you still have to invent something, check it against section 11 and the review
checklist. When unsure, choose the more restrained option.

## 11. Never

Soft shadows · glow halos · blur · rounded corners or pills · gradient-filled surfaces
or buttons · tinted near-blacks · pure white pages · pastel or neon-on-white aurora ·
linear or stepped easing · slow fades · bounce on landing · emoji · all-caps labels ·
a second warm colour · colour as the only signal · centered body text ·
equal-card grids with the same border, radius and shadow on everything.

## 12. Review checklist

Before you call a Cold Trace screen done:

- [ ] Only role tokens in component CSS; no literal colours, no Tailwind default palette.
- [ ] Night is the default and the daylight switch works; both pass contrast.
- [ ] Every box is chamfered at top-left and bottom-right; the only circles are vias.
- [ ] Colour appears only in lines, vias, traces and the curtain. Words are ink (copper
      fault messages excepted).
- [ ] Exactly one prime key per view; destructive actions are Cut keys.
- [ ] Keys respond to one touch with the full throw; focus is visible (signal).
- [ ] Anybody is wide (112–150%), Martian Mono for body and numbers; sentence case.
- [ ] Spacing uses the eight steps; sections are 96px apart.
- [ ] No shadows, glows, blur, rounded corners or emoji.
- [ ] Copy: verbs that say what happens, errors that say how to fix, no exclamation marks.
- [ ] Works at 375px wide, touch targets ≥44px, `prefers-reduced-motion` respected.

## The Eterphis logo

Eterphis pages carry the Eterphis logo (identity 2.0): an uneven square of ice ink, a custom Φ painted
inside it, and p, h and i drawn as one heavy letter cut out of the square, with a drawn lowercase
wordmark beside it. It reads Cold Trace's tokens and follows night and daylight by itself.

- Never draw it or set the wordmark in a font: use the kit's builder (`eterphisMark()`,
  `eterphisWordmark()`) or the React and Astro wrappers, and load `eterphis-mark.css` after the
  Cold Trace stylesheet.
- In a top bar the horizontal lockup (mark 40px) replaces the generic `.ct-mark`, linking home.
- The Logo component has the rules and code; the Logos asset group has the files. The full guide is the
  skill's `references/eterphis.md`.

## Iconography

24 icons on a 24-unit grid, 1.5px stroke, 0°/45°/90° only, closed shapes chamfered, at
most one via where the current enters. See the Icons asset group for the set and its README
for the drawing rules. Use them inline (`<svg class="ct-icon">`) so they take
`currentColor`; the uploaded files are drawn in firn ink for dark previews.
