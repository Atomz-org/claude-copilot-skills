---
name: architecture-page
description: "Author or revise a hand-drawn system-architecture page under public/ — inline SVG diagrams, figures pinned to committed artifacts, dual-theme CSS, and no external requests. Use when creating an architecture or explainer page, when updating public/code-skills-architecture.html, when tests/test_architecture_diagram.py fails, when a number on the page has gone stale, or when asked to draw or diagram how the system fits together."
---

# Architecture page

Backs the `/architecture` command. The page is
`public/code-skills-architecture.html`: the three-lane data flow from raw sources to a
served semantic layer, the derivation stages with what each one refuses to do, the layers
underneath, and the deployment surface.

Paths below are written repository-relative rather than as links, because this file is
copied verbatim into `.claude/skills/` and no single relative path resolves from both
locations.

**There is no generator and there should not be one.** Every artifact in this repository
is derived — `column-memory.json`, `index.json`, the graphify fragment — and a renderer
over any of them produces a graph of everything, which is the thing nobody reads. The page
is an argument about how the system fits together, and the ordering, the omissions, and
the sentence under each box are the whole value. `scripts/pr_decision_diagram.py` already
demonstrated the other direction: its layer-stack section was deleted for being identical
on every PR.

A hand-authored page rots, so exactly one mechanism holds it, and it is a test rather than
a lint:

> **Every figure derived from a committed artifact carries `data-metric` and is checked
> against that artifact. Every figure that needs a rebuild is left unpinned, and the footer
> names the command that re-derives it.**

Both halves matter. Pin a rebuild-derived figure — the test count, the graph size — and the
gate goes red because somebody added a test, which is how a gate gets switched off.

## The workflow

1. **Read the test before the page.** `tests/test_architecture_diagram.py` is the
   specification: 12 tests covering staleness, SVG geometry, accessibility, theming, and
   how the docs site serves it. Its `METRICS` dict is the closed set of pinnable keys.
2. **Establish the numbers first.** Never type a figure you have not read out of an
   artifact — analytics rule 5 applies to a diagram exactly as it applies to a model.
   The key-to-artifact table is in [references/pinning.md](references/pinning.md).
3. **Draw in inline SVG, by hand, to the geometry contract.** Fixed `viewBox`, boxes on a
   column pitch, labels measured rather than eyeballed. The contract and the reason each
   rule exists are in [references/svg-contract.md](references/svg-contract.md).
4. **Write the prose around the diagram, not under it.** A box named `column memory` says
   nothing; the sentence next to it — *"`raw_code` is a snapshot from the last `dbt parse`,
   so a model whose file has moved is re-parsed from disk"* — is what a reader came for.
   Prefer the refusal to the feature: what a stage declines to do is what distinguishes it.
5. **Run the gate.**

   ```bash
   python -m pytest -q tests/test_architecture_diagram.py
   ```

6. **Serve it.** `public/` is the static-asset root, so `public/x.html` serves at `/x.html`.
   A new page needs its `<iframe src>` in `docs/index.mdx` to match, and a
   `<meta name="description">` of at least 40 characters. An iframe `src` and a file path
   that disagree render an empty frame and no error.

## The four refusals

Each one was a defect first, and each is now a test.

- **No external request.** The page is also published as a Claude artifact, under a CSP
  that blocks every host. A webfont `<link>`, a CDN stylesheet, or a remote image loads
  fine on a laptop and fails silently there. Inline the CSS, use system font stacks, embed
  any image as a `data:` URI. `@import` is banned for the same reason.
- **Both themes, and the toggle wins.** `@media (prefers-color-scheme: dark)` alone ignores
  the viewer's explicit choice, because the toggle stamps `data-theme` on the root. Define
  the media query, then `:root[data-theme="dark"]` and `:root[data-theme="light"]` **after**
  it, so the override has the cascade.
- **Colour is never the only encoding.** Contrast against the light surface WARNs below
  3:1, and that warning is only dischargeable with visible text — so every box carries a
  `t-title` label and the page carries a `<ul class="legend">`. The test counts titles
  against boxes.
- **Every headline figure is pinned.** The stat strip is the part a reader trusts without
  checking, so nothing in it may be an unpinned snapshot. `test_the_headline_figures_are_all_pinned`
  rejects a `<b>` in `.stats` with no `data-metric`.

## Changing an existing page

Three failure modes, in the order they actually occur:

| Symptom | Cause | Fix |
|---|---|---|
| `the page is stale — connectors: page says 19, artifacts say 20` | an artifact moved under the page | edit the number; do not touch the test |
| `data-metric='x' has no resolver in this test` | a new key was invented | add the resolver to `METRICS`, or drop the attribute and unpin the figure |
| `'…' overflows its box` / `boxes at (…) overlap` | a label grew or a box moved | widen the box or shorten the label — SVG neither wraps nor clips |

When the *architecture* changes rather than the numbers, redraw the affected lane and
re-run the gate. Adding a box means adding its `t-title`, or the colour-encoding test fails.

## A second page

`public/decision-path.html` is the same shape under `tests/test_decision_path_page.py`.
A new page in `public/` gets its own test file rather than an extension of either — the
pinned-metric resolvers are page-specific, and one file asserting two pages fails ambiguously.
