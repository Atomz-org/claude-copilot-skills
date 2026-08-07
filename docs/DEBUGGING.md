# When something breaks

Start here. One command tells you whether a change is acceptable, and every failure it
prints already carries the fix.

```bash
./scripts/check.sh
```

It runs the same eight gates a pull request runs, in the same order, so a green result here
means a green result there. It changes nothing you have not committed.

```
Running the eight gates a pull request has to pass.

  ✓  branch naming            fix/no-ticket-seed-collision
  ✓  conventional commits     3 commit(s) conform
  ✗  activation drift          M .claude/skills/dbt-skill/SKILL.md
     what it means  .claude/, references/ and templates/ are copies, rebuilt from
                    skill-packs/. Editing a copy works until the next rebuild
                    silently reverts it.
     how to fix     make the same edit under skill-packs/dbt-skills/, then:
                    ./scripts/activate_skill_stack.sh dbt-skills wren-skills
```

A `—` is a gate that could not run, not a gate that failed. Rust and Node are optional here;
the checks that need them report "skipped" and the exit code stays 0.

## Setting up from nothing

```bash
python3 -m venv .venv
.venv/bin/pip install -r .github/requirements/ci.txt
./scripts/check.sh
```

That is the whole setup. `dbt` is **not** needed — the committed artifacts are what the
tooling reads, which is the reason they are committed. Install it only to run the worked
example in `skill-packs/dbt-skills/use-cases/example-order-revenue-mart/`.

## The eight gates, in plain words

| Gate | The mistake it catches |
|---|---|
| branch naming | Committing to `main`, or a branch name tooling cannot classify |
| conventional commits | A commit subject that does not start with `fix:`, `feat:`, `docs:`, … |
| activation drift | Editing a generated copy instead of the source it is copied from |
| marketplace portability | A skill pack missing the metadata another repository needs to install it |
| toon serializer build | `rust/toon/graph_to_toon.rs` no longer compiles |
| test suite | A test that used to pass no longer does |
| harness integrity | Two skills or commands answering to the same name |
| stack hygiene | A branch outside the stack grammar, or regenerated artifacts committed below the top layer of a stack |

## The three that confuse people

### "I edited a file and my change disappeared"

`.claude/`, `references/` and `templates/` are **generated**. They are rebuilt from
`skill-packs/<pack>/` every time `scripts/activate_skill_stack.sh` runs, which happens in
CI and in the check above. An edit there is overwritten with no warning.

Edit the pack, then re-run activation:

```bash
$EDITOR skill-packs/dbt-skills/.claude/skills/<name>/SKILL.md
./scripts/activate_skill_stack.sh dbt-skills wren-skills
```

Both copies must be committed. Skills link to shared files with a single relative path that
has to resolve in the pack *and* in the activated copy.

### "The tests pass on my machine and fail in CI"

Almost always an optional dependency. `sqlglot` parses SQL and is optional at runtime, so
tests that need it are written to skip rather than fail. Without it installed, the suite
goes green having skipped roughly fifty tests — including every one that exercises the SQL
parser.

```bash
.venv/bin/pip install -r .github/requirements/ci.txt   # includes sqlglot, pinned
```

`./scripts/check.sh` prints a note under the test suite line when sqlglot is missing, so
this is visible rather than inferred.

### "A number in a generated file changed and I did not touch it"

Several files in this repository are derived, not written:

| File | Rebuilt by |
|---|---|
| `ontology/column-memory.json` | `scripts/dbt_column_memory.py --write` |
| `ontology/index.json`, `ontology/*.ttl` | `scripts/use_case_sync.py` |
| `artifacts/graphify-fragment.json` | `artifacts/refresh.sh` |
| `.claude/`, `references/`, `templates/` | `scripts/activate_skill_stack.sh` |

Committing them is deliberate: it is what lets a fresh clone work with no dbt and no
warehouse. If one changes unexpectedly, something regenerated it — usually the PostToolUse
hook after a `.sql` edit, which is doing its job. Regenerate the rest and commit them
together:

```bash
python3 scripts/use_case_sync.py --use-case <slug>
```

## When the check passes but something is still wrong

```bash
.venv/bin/python -m pytest -q tests/test_docs_links.py   # every markdown link resolves
python3 scripts/use_case_sync.py --all --check           # every derived artifact is current
python3 scripts/connector_alignment_check.py --help      # convention drift in a dbt project
```

Two known-noisy signals, so you do not chase them:

- **The harness-integrity issue count is not a defect count.** Both the pack and its
  activated copy are scanned, so every finding appears twice, and broken references are
  excluded from the gate on purpose — `tests/test_docs_links.py` owns those and is stricter.
  Only name collisions and unparseable frontmatter are budgeted.
- **Two accepted warnings on enhanza-analytics**, documented in `CLAUDE.md`: the
  `fortnox_base_v2_invoices` naming finding, and eight sources with no freshness SLA. Both
  are filed as issues under `.github/issues/`. Neither is a regression.

## Where the rules actually live

| | |
|---|---|
| `CLAUDE.md` | how this repository works, and why each rule exists |
| `.claude/rules/` | the binding rules — analytics engineering, standards, skill-map |
| `docs/use-cases.md` | what a use-case directory contains |
| `.github/workflows/pr-decision-diagram.yml` | the eight gates, as CI runs them |
