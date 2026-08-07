# The SVG contract

The diagrams are hand-written inline SVG. Nothing generates them, and nothing in a browser
tells you when one is wrong: an unclosed tag renders as much as the parser got, and a label
wider than its box silently overprints its neighbour. Both are caught by
`tests/test_architecture_diagram.py` instead.

## Structure

```html
<div class="scroller">
  <svg viewBox="0 0 1180 540" role="img" aria-labelledby="df-title df-desc">
    <title id="df-title">Data flow across the warehouse, meaning, and serving lanes</title>
    <desc id="df-desc">Raw source APIs flow through sources.yml, staging, …</desc>
    <defs>…arrowhead markers…</defs>
    <rect class="lane" x="0" y="34" width="1180" height="106" rx="6"/>
    <text class="t-lane" x="10" y="91">RAW</text>
    <g>
      <rect class="box data" x="104" y="56" width="156" height="64"/>
      <text class="t-title" x="118" y="82">Source APIs</text>
      <text class="t-sub"   x="118" y="100" data-metric="connectors">19 connectors</text>
    </g>
  </svg>
</div>
```

Required, each by a named test:

- `role="img"` plus a `<title>` and a `<desc>` as **direct children**. They are the only
  thing a screen reader gets out of a hand-drawn diagram, and `aria-labelledby` points at
  their ids.
- Well-formed XML. The test parses each block with `ElementTree`, so an unclosed tag or a
  bare `&` fails rather than half-rendering.
- `.scroller` as the wrapper. `svg { width: 100%; min-width: 940px; height: auto }` means
  a narrow viewport scrolls the diagram instead of scrolling the page body sideways.

## Geometry

`viewBox="0 0 1180 <height>"` for every diagram, so both scale identically and boxes can
share a column pitch. Lane bands are `rect class="lane"` — full width, `height="106"` — and
are **exempt** from the overlap test, which only looks at rects whose class contains `box`.

| | |
|---|---|
| Box | `rect class="box <role>"`, `height="64"`, `width` 156 or 192 |
| Role | one of `data` `proc` `mean` `out` — the four palette roles, plus `.t-gate` ink for refusals |
| Text origin | `x = box.x + 14` |
| Baselines | title `box.y + 26`, first sub `+44`, second sub `+58` |

**No two boxes may overlap**, in any pair, in either diagram. This is a whole-rect
intersection test, not a nearest-neighbour one, so a box nudged into a different lane is
caught.

## Label budgets, because SVG does not wrap

`<text>` neither wraps nor clips. The test measures each label as
`len(text) × font-size × 0.601` — the monospace advance ratio — and fails it if the result
runs past the box's right edge minus 4px, or past the viewBox width minus 4px.

Usable width is `box.width − 18`. Round **down**:

| Class | Size | 156-wide box | 192-wide box |
|---|---|---|---|
| `t-title` | 12px | 19 chars | 24 chars |
| `t-sub` | 10.5px | 21 chars | 27 chars |
| `t-num` | 11px | 20 chars | 26 chars |

Count characters, not bytes: `·` and `…` are one each, and both are used freely.

Two escapes exist and are load-bearing:

- `text-anchor="end"` is handled — the label is measured leftward from `x`.
- A `<text>` carrying a `transform` is **skipped**. Rotated lane labels cannot be measured
  this way, so they are exempt by construction rather than by exception.

Only the classes in the table are measured. A `<text>` with no class, or an unlisted one,
passes unchecked — which is a hole, not a feature. Use the listed classes.

## Colour is never the only encoding

The palette is four semantic roles — data `#4299e1`, processing `#ed8936`, meaning
`#9f7aea`, output `#48bb78` — validated for colour-vision separation and contrast in both
themes. The dark surface needed orange and green re-stepped (`#cf7220`, `#41a874`): the
band is L 0.48–0.67 there, and a naive flip fails it.

Contrast against the light surface WARNs below 3:1, and that warning is only dischargeable
with visible text. So:

- **Every box carries a `t-title`.** `test_colour_is_never_the_only_encoding` counts
  `t-title` elements against `box` rects and fails when titles are fewer.
- **The page carries a `<ul class="legend">`** naming each role in words.

Adding a box without its title is the common way to break this, and the failure message is
a count, not a location — so add the two together.

## Themes

```css
@media (prefers-color-scheme: dark) { :root { … } }
:root[data-theme="dark"]  { … }
:root[data-theme="light"] { … }
```

In that order. The viewer's toggle stamps `data-theme` on the root element, so a page that
styles only the media query ignores the toggle in one direction — dark-preferring OS, light
toggle, unreadable page. The test asserts the explicit overrides appear **after** the media
query, because equal-specificity rules are resolved by source order.

Every SVG fill and stroke goes through a CSS custom property for the same reason. A colour
written directly onto a `rect` is invisible to both theme mechanisms.

## Self-containment

No `src` or `href` to any external host, and no `@import`. The page is published as a Claude
artifact under a CSP that blocks every host, so a webfont link, a CDN stylesheet, or a remote
image loads correctly on a laptop and fails there with no error on the page.

Fonts are system stacks (`Charter, "Bitstream Charter", "Iowan Old Style", Georgia, …` for
display; `ui-monospace, SFMono-Regular, …` for the diagram labels). The monospace stack is
not cosmetic — the label-overflow measurement assumes a monospace advance, so a proportional
diagram font makes every budget above wrong.
