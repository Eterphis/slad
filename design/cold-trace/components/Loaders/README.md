Current lapping a chip package, a routed progress trace, a sweep and an orbiting via.

## Loaders
```html
<!-- boot: current laps a chip package -->
<svg width="120" height="120" viewBox="0 0 120 120" role="img" aria-label="Loading">
  <path class="ct-svg-base" d="M24,8 H112 V96 L96,112 H8 V24 Z"/>
  <path class="ct-svg-loop" pathLength="100" d="M24,8 H112 V96 L96,112 H8 V24 Z"/>
</svg>

<!-- progress: a routed trace that fills (set stroke-dasharray: <percent> 100) -->
<svg viewBox="0 0 320 44" role="img" aria-label="Upload, 62 percent">
  <path class="ct-svg-base" d="M6,32 H96 L116,12 H204 L224,32 H314"/>
  <path class="ct-svg-fill" pathLength="100" style="stroke-dasharray: 62 100" d="M6,32 H96 L116,12 H204 L224,32 H314"/>
  <circle class="ct-svg-via" cx="6" cy="32" r="4"/><circle class="ct-svg-via" cx="314" cy="32" r="4"/>
</svg>

<!-- unknown length: swap ct-svg-fill for ct-svg-sweep. Small spinner: -->
<svg width="48" height="48" viewBox="0 0 48 48" role="img" aria-label="Waiting">
  <circle class="ct-svg-base" cx="24" cy="24" r="16"/>
  <circle class="ct-svg-spin" pathLength="100" cx="24" cy="24" r="16"/>
</svg>
```

## Loading screen
For a full-page wait over about a second. The curtain and the horizon line sit behind one snow
or black panel with one sentence and one moving trace.

```html
<div class="ct-frame ct-frame--l ct-frame--ice ct-frame--ground" style="position:relative; min-height:360px; display:grid; place-items:center; overflow:hidden">
  <div class="ct-curtain" data-ct-curtain="48" aria-hidden="true"></div>
  <span style="position:absolute; left:0; right:0; top:75.8%; height:1px; background:var(--ct-ink-2)"></span>
  <div class="ct-frame ct-frame--ice ct-panel" role="status" style="text-align:center">
    <p class="ct-panel-title">Preparing your workspace</p>
    <!-- sweep trace here -->
    <p class="ct-cap">Copying 6 of 12 files</p>
  </div>
</div>
```
