The Eterphis logo (identity 2.0): the mark, the drawn wordmark and their lockups, built by the kit's builder and never drawn by hand.

## The mark

The word phi, painted. An uneven square of ice ink sits low and left in its box; a custom Φ is painted
inside it a few shades off; p, h and i are drawn as one heavy letter, leaning right and **cut out** of
the square (a mask: the page shows through), whose tall stroke breaks out of the top as a spike. Ice
square at night, near-black by day.

## Using it

The Claude Code skill (`cold-trace/`) carries the logo as code. Read its `references/eterphis.md`
before placing the logo; never redraw it or set the wordmark in a font.

```tsx
import { EterphisMark, EterphisWordmark, EterphisLockup } from './cold-trace/EterphisMark';

<header className="topbar"><EterphisLockup href="/" /> …</header>   {/* mark 40px + wordmark */}
<EterphisMark size={320} motion="charge" key={replays} />            {/* hero, plays once */}
<EterphisMark size={96} motion="live" title="Loading" />             {/* loader */}
<EterphisWordmark height={20} />
```

Plain HTML or any template: `eterphisMark({ size, motion, mono, title, id })` and
`eterphisWordmark({ height })` from `assets/eterphis/eterphis-mark.ts` return SVG strings. Load
`eterphis-mark.css` after `cold-trace.css`: it sets the mark's colours per mode, the motion and the
lockups (`.eph-lockup--h`, `.eph-lockup--v` with `--eph-size`).

## Rules

- The drawing follows the size: full at 56px and up, small at 24 to 55px, tiny below 24px (minimum 16px).
- Clear space: a quarter of the mark's size on every side. Centre the box, never nudge the drawing.
- Charge once on arrival (hero, splash, logo click); Live only for waits over a second; nothing in top bars.
- Pass no colours; never fill the cut-out, tint it, outline it, or add a glow, shadow or colour behind it.
  Over photos or colour, put it on a chamfered ground tile.
- Mono (one ink) for print; it drops the Φ and never animates.
- One accessible name: `title="Eterphis"` alone, `title={null}` inside a lockup or a link that names it.
