---
description: Author or update a hand-drawn architecture page under public/, with every figure pinned to a committed artifact.
---

# /architecture

Runs the `architecture-page` skill over `public/code-skills-architecture.html` — or over a
new page in `public/` when the argument names one.

## Usage

```
/architecture                     # update the architecture page to current artifacts
/architecture <what changed>      # redraw the affected lane and re-pin
/architecture new <slug>          # a new public/<slug>.html plus its test
```

## Steps

1. **Read the spec, which is a test.** `tests/test_architecture_diagram.py` — 12 tests over
   staleness, SVG well-formedness, label geometry, accessibility, theming, and the docs
   embed. `METRICS` is the closed set of pinnable keys.
2. **Re-derive the numbers.** Never type a figure that was not read out of a committed
   artifact.

   ```bash
   python3 scripts/use_case_sync.py --all --check
   python -m pytest -q tests/test_architecture_diagram.py
   ```

   A `the page is stale — <key>: page says X, artifacts say Y` failure is the page's
   problem, never the test's.
3. **Edit the page.** Inline SVG on a 1180-wide `viewBox`; boxes 64 tall; every box gets a
   `t-title`; labels inside the character budget for their box width.
4. **Re-run the gate**, then the full suite if the page's markup structure changed:

   ```bash
   python -m pytest -q tests/test_architecture_diagram.py tests/test_docs_links.py
   ```

5. **A new page also needs**: its own `tests/test_<slug>_page.py`, an `<iframe src="/<slug>.html">`
   in `docs/index.mdx` matching the served path, and a `<meta name="description">` of 40+
   characters.

## Refusals

- Do not build a generator for this page. Every artifact in the repository is already
  derived; a renderer over one produces the graph of everything, which is the thing nobody
  reads.
- Do not pin a figure that needs a rebuild — a test count, a graph size. Name the command
  in the footer instead. A gate that goes red because somebody added a test gets switched
  off.
- Do not add an external font, stylesheet, or image. The page ships under a CSP that blocks
  every host.
- Do not edit `.claude/skills/architecture-page/`. It is generated; the source is
  `skill-packs/github-skills/.claude/skills/architecture-page/`, and activation reverts a
  direct edit.

## Reference

- Skill: `.claude/skills/architecture-page/SKILL.md`
- Pinned figures: `.claude/skills/architecture-page/references/pinning.md`
- SVG contract: `.claude/skills/architecture-page/references/svg-contract.md`
