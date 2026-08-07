# Contributing

This repository is published as `Atomz-org/claude-copilot-skills`; the module itself is
named `code-skills`, and the checkout works the same under either name. Contributions are
welcome — the conventions below are the whole bar, and one command checks all of them.

## Development setup

Clone **with submodules**. `external/WrenAI` is a pinned submodule and CI resolves it, so a
plain clone leaves you with a tree CI is not testing:

```bash
git clone --recurse-submodules https://github.com/Atomz-org/claude-copilot-skills.git
cd claude-copilot-skills
python3 -m venv .venv            # Python 3.11 is what CI runs
.venv/bin/pip install -r .github/requirements/ci.txt
```

Already cloned without submodules? `git submodule update --init` repairs it.

That is the whole required setup. Three toolchains are optional, and each unlocks one
thing:

| Toolchain | Unlocks |
|---|---|
| `rustc` | the TOON serializer, built with `./scripts/build_toon_rs.sh` |
| Node | the skill-map harness scan (`python scripts/skill_map_scan.py --summary`) |
| `dbt-core` + `dbt-duckdb` | the worked examples, including `./skill-packs/wren-skills/demo/run_wren_demo.sh` |

None of them is required. Every gate that needs one reports **skipped** when it is absent
— never failed — so a laptop without Rust or Node still gets a trustworthy verdict.

## One command answers "would my change be accepted?"

```bash
./scripts/check.sh
```

It runs the same gates a pull request runs, in the same order, so a green result locally
is a green result in CI. When a gate fails it says what the gate was protecting and prints
the exact command that fixes it. It changes nothing you have not committed. Longer
explanations of each gate live in [docs/DEBUGGING.md](docs/DEBUGGING.md).

## The trap to know about before your first edit

**`.claude/`, `references/`, and `templates/` are generated.** They are rebuilt from
`skill-packs/<pack>/` by `scripts/activate_skill_stack.sh`, which runs in CI and inside
`check.sh`. An edit made directly in those directories works until the next rebuild
silently reverts it. The correct loop is:

```bash
# 1. edit the source under skill-packs/<pack>/
# 2. regenerate the mirror
./scripts/activate_skill_stack.sh dbt-skills wren-skills lightdash-skills openmetadata-skills
# 3. commit both the pack change and the regenerated copy
```

The `activation drift` gate in `check.sh` catches an edit made in the wrong place before a
reviewer has to.

## Tests

```bash
python -m pytest -q        # from the repository root
```

The suite runs in parallel when `pytest-xdist` is installed (it is in
`.github/requirements/ci.txt`) and serially when it is not — same command either way.
`CODE_SKILLS_NO_XDIST=1` forces a serial run when you are bisecting a flake.

Two expectations for new work:

- New logic gets a paired test file under `tests/`.
- Every relative markdown link must resolve to a real file —
  `tests/test_docs_links.py` enforces this, so verify a path exists before writing it
  into a document.

## Git conventions

- Never commit directly to `main` or `master`.
- Branch names take the form `<type>/<ticket>-<description>`, for example
  `fix/no-ticket-seed-collision`. Larger deliveries follow the stacked-branch grammar in
  [docs/BRANCHING_STRATEGY.md](docs/BRANCHING_STRATEGY.md).
- Commits follow Conventional Commits: `type: summary`, such as
  `docs: add contributing guide`.
- Open pull requests against `main`, and review your own diff before asking anyone else
  to. The commit and review discipline is written down in
  [docs/WAY_OF_WORKING.md](docs/WAY_OF_WORKING.md).

## Where things go

- **New use-cases** live under `skill-packs/<pack>/use-cases/<slug>/` — the owning pack's
  path, never a top-level directory.
- **New skills** need a `SKILL.md` and an intent entry in
  `.claude/commands/skills-index.md`. Both live in the pack — the index's source is
  `skill-packs/github-skills/.claude/commands/skills-index.md` — and reach the root
  mirror through activation, per the generated-path rule above. The full lifecycle rules
  are in [.claude/rules/standards.md](.claude/rules/standards.md).

## Releases

Maintainers cut releases manually through
[.github/workflows/release.yml](.github/workflows/release.yml), a `workflow_dispatch`
workflow that takes a version tag input (for example `v0.1.0`). Contributors do not need
to do anything release-related; landing on `main` is the finish line for a PR.

## First contribution?

Welcome — small, focused first PRs are genuinely appreciated, and
[docs/START_HERE.md](docs/START_HERE.md) is the guided tour of the repository. For a large
change, open an issue first so the approach can be agreed before the work is done. The
project is MIT-licensed, and contributions are accepted under the same license.

Questions and support channels are in [SUPPORT.md](SUPPORT.md), and the community
standards we hold ourselves to are in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
