A switch for settings that apply the moment they change.

```html
<div class="ct-switch-row">
  <button class="ct-toggle" type="button" role="switch" aria-checked="true" aria-labelledby="l-alerts" data-ct-switch>
    <span class="ct-toggle__body"><span class="ct-toggle__trace"></span><span class="ct-toggle__thumb"></span></span>
  </button>
  <span id="l-alerts">Email me when a build fails</span>
</div>
```

Settings that apply immediately use a toggle; choices that wait for "Save" use checks.
