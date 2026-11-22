The key: a chamfered face over a frosted socket that drops its full travel under one light touch.

```html
<button class="ct-btn" type="button"><span class="ct-btn__face">Save changes</span></button>
<button class="ct-btn ct-btn--ground" type="button"><span class="ct-btn__face">Cancel</span></button>
<button class="ct-btn ct-btn--cut" type="button"><span class="ct-btn__face">Delete project</span></button>
<a class="ct-btn ct-btn--lever" href="/start"><span class="ct-btn__face">Start the trial</span></a>
<button class="ct-btn ct-btn--sm ct-btn--ground" type="button"><span class="ct-btn__face">Edit</span></button>
<button class="ct-btn ct-btn--icon ct-btn--ground" type="button" aria-label="Search">
  <span class="ct-btn__face"><svg class="ct-icon" aria-hidden="true"><use href="#ct-i-search"/></svg></span>
</button>
```

| Kind | Class | Use |
|---|---|---|
| Prime | `.ct-btn` | The one main action in a view: key-coloured face |
| Ground | `.ct-btn--ground` | Every other action: panel face, ink edge and word |
| Cut | `.ct-btn--cut` | Destructive or fault actions only: copper |
| Lever | `.ct-btn--lever` | The single biggest action on a page (hero CTA): 20px travel |
| Small | `.ct-btn--sm` | Dense UI, table rows: 8px travel |
| Icon | `.ct-btn--icon` | Icon-only; always `aria-label` |

States: hover/focus charge the edge in one lap and stay lit; one touch throws the press
(`cold-trace.js`); busy = `aria-busy="true"` (current keeps lapping; change the word to
"Saving"); disabled = `disabled` (sunk and frosted). Group keys in `.ct-btns`. Put the prime
key last in a row of actions (reading order ends on the commitment).
