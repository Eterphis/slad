The chamfered, two-layer outline every panel, tile and screen is cut from.

## Frame and panel
```html
<div class="ct-frame ct-frame--ice ct-panel">…</div>       <!-- panel: 10px cut, ice edge, 24px padding -->
<div class="ct-frame ct-frame--l ct-frame--ice">…</div>    <!-- large panel or screen -->
<div class="ct-frame ct-frame--s">…</div>                  <!-- small tile -->
<div class="ct-frame ct-frame--well">…</div>               <!-- a frosted well -->
<div class="ct-frame ct-toast--live">…</div>               <!-- any role edge: set --ct-edge -->
```

Custom edge or fill: set `--ct-edge` / `--ct-fill` on the element to a **role token**
(`style="--ct-edge: var(--ct-arc)"`). The frame clips its children; give content padding.

## Section head
```html
<section class="ct-sec" aria-labelledby="s-pricing">
  <div class="ct-sec__head">
    <h2 class="ct-section" id="s-pricing">Pricing</h2>
    <p class="ct-sec__note">Billed monthly, cancel any time</p>
  </div>
  <div class="ct-ruler" aria-hidden="true"></div>
  …
</section>
```

Block heading inside a section: `<h3 class="ct-h">Keys</h3>` (draws a via before the words).
The page's one heavy line: `<div class="ct-ruler ct-ruler--bus" aria-hidden="true"></div>` under the title.
