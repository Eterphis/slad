A status message on a snow or black panel; the edge and via carry the state.

```html
<div class="ct-frame ct-frame--ice ct-toast ct-toast--live is-new" role="status">
  <i class="ct-v ct-v--live"></i>
  <div class="ct-toast__text">
    <p class="ct-toast__t">Changes saved</p>
    <p class="ct-toast__b">Your settings apply to every page now.</p>
  </div>
</div>
```

Kinds: `--live` (done), `--arc` (info, holding), `--fault` (error; add
`<span class="ct-cutline" aria-hidden="true"><i></i><i></i></span>` inside the text for the cut).
Fault toasts use `role="alert"`. `.is-new` drops it in 12px on arrival.
