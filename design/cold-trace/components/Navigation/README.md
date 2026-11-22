The top bar with its Daylight switch, and the side nav for app screens.

## Top bar and mode switch
```html
<header class="topbar">  <!-- layout is yours: flex, wrap, gap 24px, 16px block padding, 1px --ct-rule bottom border -->
  <a class="ct-mark" href="/">Project name</a>
  <nav class="ct-nav" aria-label="Main">
    <a href="/docs" aria-current="page">Docs</a>
    <a href="/pricing">Pricing</a>
  </nav>
  <div class="ct-switch-row">
    <button class="ct-toggle" type="button" role="switch" aria-checked="false"
            aria-labelledby="mode-label" id="mode-switch">
      <span class="ct-toggle__body"><span class="ct-toggle__trace"></span><span class="ct-toggle__thumb"></span></span>
    </button>
    <span id="mode-label" class="ct-label">Daylight</span>
  </div>
</header>
<script>
  const sw = document.getElementById('mode-switch');
  sw.setAttribute('aria-checked', String(document.documentElement.dataset.theme === 'light'));
  sw.addEventListener('click', () => {
    const light = sw.getAttribute('aria-checked') !== 'true';
    sw.setAttribute('aria-checked', String(light));
    ColdTrace.setTheme(light ? 'light' : 'dark');
  });
</script>
```

## Side nav
```html
<nav class="ct-sidenav" aria-label="Workspace">
  <a href="/overview" aria-current="page"><svg class="ct-icon" aria-hidden="true"><use href="#ct-i-home"/></svg>Overview</a>
  <a href="/settings"><svg class="ct-icon" aria-hidden="true"><use href="#ct-i-settings"/></svg>Settings</a>
</nav>
```

The current page gets ink words, a 2px signal trace on the left and a lit via in its icon.
