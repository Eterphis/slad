A text field whose outline charges with aurora on focus and cuts open in copper on a fault.

```html
<div class="ct-field">
  <label class="ct-field__label" for="f-depth">Cable depth</label>
  <span class="ct-input is-fault">
    <input id="f-depth" type="text" inputmode="numeric" value="1600" aria-invalid="true" aria-describedby="f-depth-msg">
    <span class="ct-input__unit">m</span>
  </span>
  <p class="ct-field__msg is-fault" id="f-depth-msg">Too deep. The fjord ends at 1,308 m, so enter that or less.</p>
</div>
```

- Rest: wire edge, panel fill. Hover: second-ink edge. Focus: the edge fills with aurora.
- Fault: `.is-fault` on `.ct-input` and `.ct-field__msg`, `aria-invalid="true"`. The edge
  turns copper and a gap opens in the bottom line. The message says what's wrong and the fix.
- Hint text sits in `.ct-field__msg` without `.is-fault`; keep the line so the layout doesn't jump.
- `<select>` and `<textarea>` go inside `.ct-input` the same way. A leading icon:
  `<svg class="ct-icon">` before the input.
- Stack fields in `.ct-fields` (24px apart).
