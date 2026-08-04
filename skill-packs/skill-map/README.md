# skill-map pack

Maps this repository's **own AI harness** — every skill, command, and agent — as
one graph, and reports what is structurally wrong with it: name collisions, dead
references, reserved-name shadowing, invalid frontmatter, and token weight per
node.

Upstream project: [skill-map](https://github.com/PackMaaan/skill-map) by
Crystian, MIT licensed. This pack is a **wrapper**, not a fork or a vendored
copy — see [Integration shape](#integration-shape).

## No LLM

skill-map upstream ships a deterministic scanner *and* an optional probabilistic
layer that queues LLM jobs. **Only the scanner is wired in here.** No model call,
no API key, offline once the CLI is resolved.

That is enforced rather than promised: every invocation goes through an allowlist
in `scripts/skill_map_scan.py` that rejects the four probabilistic verb families
(`jobs`, `agent`, `findings`, `refresh`), and `tests/test_skill_map_pack.py`
fails if one is ever added.

## Run it

```bash
python scripts/skill_map_scan.py --summary                # counts + collisions
python scripts/skill_map_scan.py --json /tmp/scan.json    # full ScanResult
python scripts/skill_map_scan.py --check --max-errors 0   # CI gate form
```

Exit codes: `0` clean · `1` over the structural-error budget · `2` runner defect
· `3` no CLI available.

The wrapper resolves the CLI as `SKILL_MAP_BIN` → `sm` on `PATH` →
`npx -y @skill-map/cli@0.99.1`. Node ≥ 24 is required by upstream. When none
resolve it exits `3` and callers record a `skip`; a check never goes red because
a machine has no Node.

## Integration shape

Upstream is a 2300-file Node/TypeScript monorepo. Vendoring it or carrying it as
a submodule would put a second toolchain, its dependency tree, and its release
cadence inside a repository that is itself consumed as a submodule. So this pack
carries only:

| | |
|---|---|
| Skill | `.claude/skills/harness-mapping/SKILL.md` + `references/` |
| Command | `.claude/commands/skill-map.md` (`/skill-map`) |
| Rules | `.claude/rules/skill-map-rules.md` |
| Runner | `scripts/skill_map_scan.py` (repository root, shared) |

The skill is `harness-mapping`, not `skill-map`: a skill and a command sharing a
name shadow each other and the command loses. `tests/test_new_connector.py` pins
that rule repository-wide.

The CLI itself is fetched from npm at the pinned version. Upgrades are a
one-line, reviewable diff.

## In CI

`.github/workflows/pr-decision-diagram.yml` runs the scan as a merge gate and
nests a **Harness** subgraph inside the PR's Mermaid impact diagram when a PR
touches `.claude/**` or `skill-packs/**`. The gate reports; it does not block.

## Activate

```bash
./scripts/activate_skill_stack.sh skill-map
```

Layers the shared `github-skills` base, then this pack, into `.claude/`. This
pack ships no `agents/`, which activation tolerates.

## Reading the output

Two things decide whether your reading is correct, both covered in
[references/findings.md](.claude/skills/harness-mapping/references/findings.md):

- **Every finding is doubled** — pack and activated mirror are both scanned.
- **Fix the pack, never the mirror** — `.claude/` is generated.

Known-and-accepted findings (the `senior-analytics-engineer` alias collision,
`/review` shadowing, agent `tools`-as-string warnings) are listed there too, so
they are not re-reported as new every run.
