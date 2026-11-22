Checkboxes (6px-chamfered boxes with a 45° check) and radios (vias).

```html
<label class="ct-check"><input class="ct-sr" type="checkbox" checked><span class="ct-check__box" aria-hidden="true"></span><span>Keep a log</span></label>

<fieldset class="ct-fieldset">
  <legend>Region</legend>
  <label class="ct-check"><input class="ct-sr" type="radio" name="region" checked><span class="ct-radio__via" aria-hidden="true"></span><span>Europe</span></label>
  <label class="ct-check"><input class="ct-sr" type="radio" name="region"><span class="ct-radio__via" aria-hidden="true"></span><span>North America</span></label>
</fieldset>
```

The radio is a via: ring, then a signal dot when chosen. The checkbox is a 6px-chamfered box
whose check mark is two 45° lines.
