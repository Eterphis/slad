Rows of data with rule lines, second-ink headers and tabular numbers.

## Table
```html
<div class="ct-table-box ct-bar">
  <table class="ct-table">
    <thead><tr><th scope="col">Project</th><th scope="col">Status</th><th scope="col" class="ct-num">Builds</th></tr></thead>
    <tbody>
      <tr><th scope="row">North wall</th><td><span class="ct-tag ct-tag--live"><i class="ct-v ct-v--live"></i>Live</span></td><td class="ct-num">128</td></tr>
    </tbody>
  </table>
</div>
```

## Scroll box
Any scrolling container gets `.ct-bar` (1px trace track, chamfered ink thumb, signal on
hover). Give it `tabindex="0"` and `role="region"` with an `aria-label` when it holds content
a keyboard user must reach.
