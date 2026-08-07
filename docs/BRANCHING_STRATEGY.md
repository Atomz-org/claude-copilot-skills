# Branching strategy

One trunk, short-lived stacks, no long-lived branches of any kind.

This repository delivers two things that arrive **ad hoc and in parallel**: connectors and
dashboards/reports, for many clients. That shape decides the strategy. What follows is the
whole contract; `docs/WAY_OF_WORKING.md` covers commit and review discipline.

## Why not a branch per client

Tempting, and wrong here. This repository commits **generated artifacts** —
`ontology/index.json`, `column-memory.json`, the graphify fragment, sample seeds, the Wren
projection, and the whole activation mirror (`.claude/`, `references/`, `templates/`). Every
one is regenerated wholesale by a script. Two branches that both regenerate the same file
always collide, and hand-merging them is meaningless because the generator is the authority
on the content.

A long-lived client branch turns that from an occasional merge into a permanent tax: the
longer it lives, the more regenerations diverge, and the artifacts silently describe a
project state that no longer exists. So client isolation comes from **paths**, not branches
— every client's work lives under `skill-packs/<pack>/use-cases/<slug>/` — and every branch
is measured in days.

## Lanes

| Lane | Touches | Blast radius |
|---|---|---|
| **platform** | `scripts/`, `skill-packs/*/.claude/`, `src/`, rules, CI | every client |
| **client** | `skill-packs/<pack>/use-cases/<slug>/` | one client |

A change that spans both is two stacks, platform first. A platform change that a client
delivery depends on is the bottom layer of that client's stack, never a side branch.

## Branch grammar

```
<type>/<TICKET>-<lane>-<topic>-<NN>-<layer>
```

- `<type>` — Conventional Commit type; the existing gate requires it
- `<TICKET>` — `ENG-42`, `ACME-42`; `no-ticket` is allowed but discouraged for client work
- `<lane>` — `platform`, or the client code lowercased (`acme`)
- `<NN>` — zero-padded layer ordinal, so `git branch --list` sorts into stack order
- `<layer>` — the layer's job, from the recipes below

```
feat/ACME-42-acme-fortnox-01-connector
feat/ACME-42-acme-fortnox-02-semantic
feat/ACME-42-acme-fortnox-03-dashboards
feat/ACME-42-acme-fortnox-04-hardening

feat/PLAT-51-platform-wren-cubes-01-foundation
```

This grammar is not new: `.github/ISSUE_TEMPLATE/stacked_delivery_plan.yml` already emits
exactly these names, plus the merge order and one-click PR links with the bases already
chained. Open the planning issue and copy — nothing to migrate.

`scripts/stack_lint.py` parses the same grammar and is gate 8 of `./scripts/check.sh`.

## What makes GitHub render a stack

**Each PR's base branch is the head branch of the PR below it.** The bottom targets `main`.
That is the entire mechanism — there is no separate "stack" object to create, and a PR
opened against `main` by mistake is simply not in the stack.

This is exactly why PRs #36 and #37 did not appear stacked: both were opened with
`base: main`, so GitHub had two independent PRs and nothing to chain.

Merging is **bottom-up**. Merging a middle layer auto-rebases and retargets the layers
above it; merging the top merges everything below in one operation.

## Layer recipes

Four layers maximum. If a delivery needs more, it is two deliveries.

**Client connector** — `01-connector` → `02-semantic` → `03-dashboards` → `04-hardening`

| Layer | Contains | Reviewer asks |
|---|---|---|
| `01-connector` | `sources.yml` column contract, staging, adapter models | are the raw column names right? |
| `02-semantic` | marts, metrics, semantic models, tests | is the grain and the metric definition right? |
| `03-dashboards` | Wren cubes/knowledge, the dashboard or report | does it answer the question asked? |
| `04-hardening` | **every regenerated artifact**, docs, final gates | is the committed state current? |

**Client dashboard only** — `01-semantic` → `02-dashboards` → `03-hardening`.

**Platform** — `01-foundation` → `02-semantic` → `03-dashboards` → `04-hardening`, dropping
layers that do not apply.

### The one rule that makes stacks work here

**Generated artifacts are regenerated in exactly one layer — the top one.** Lower layers
carry hand-written source only.

If every layer ran `use_case_sync.py`, each layer would rewrite the same artifact files and
collide with its own siblings — a stack that fights itself. Concentrating regeneration in
the final layer keeps every lower diff small and genuinely reviewable, and leaves exactly
one place where the artifact-currency gate has to pass.

Artifacts that must be regenerated in the top layer:

```bash
python3 scripts/use_case_sync.py --use-case <slug>          # ontology, columns, seeds, graph, wren
./scripts/activate_skill_stack.sh dbt-skills wren-skills lightdash-skills    # only if a pack asset changed
./scripts/check.sh                                          # the seven gates
```

## Running a stack

```bash
gh extension install github/gh-stack      # once

git fetch origin                          # always branch from fresh main
gh stack init feat/ACME-42-acme-fortnox-01-connector
# ... commit layer 1 ...
gh stack add feat/ACME-42-acme-fortnox-02-semantic
# ... commit layer 2 ...
gh stack submit                           # pushes all branches, opens the chained PRs
```

Day to day:

| Command | Use |
|---|---|
| `gh stack view` | see the stack and each layer's PR status |
| `gh stack up` / `down` / `top` / `bottom` | move between layers |
| `gh stack sync` | pull remote state after a layer merges |
| `gh stack rebase` | after trunk moves under you |
| `gh stack modify` | insert, reorder, or drop a layer |
| `gh stack link` | chain PRs that already exist but were opened against `main` |
| `gh stack merge` | land the stack |

`gh stack link` is the repair tool: if you opened layers against `main` by mistake — the
#36/#37 failure — link them instead of recreating them.

Agents cannot push here: `.claude/hooks/block-dangerous-git.sh` blocks every `git push`,
and `gh stack submit` pushes. An agent prepares the branches and commits; a human submits.

## The rebase trap — read this before your first `gh stack rebase`

The `generated` merge driver is `merge.generated.driver true`, which means "leave `%A`
alone". Under `git merge`, `%A` is your branch, so your regenerated artifact wins. **Under
`git rebase`, the roles invert**: rebase replays your commits onto upstream, so `%A` is
*upstream* and the driver silently keeps upstream's artifact and drops yours.

Measured, not theorized:

| Operation | Which side survives |
|---|---|
| `git merge <trunk>` | yours — correct |
| `git rebase <trunk>` | **upstream's — your regeneration is discarded** |

**This is a local hazard only, and the distinction matters.** A merge driver is per-clone
git config — git cannot version one — so GitHub's servers do not have it. When GitHub
auto-retargets a layer after the one below it merges, there is no `generated` driver in
play: a genuine collision surfaces as a *conflict on the PR*, which is visible and safe.
The silent wrong-side pick happens only where the driver exists, which is your machine:
`gh stack rebase`, `git rebase`, `git pull --rebase`.

Stacks rebase locally often enough that this is the normal path, not an edge case.

It does fail loudly in the end — the artifact-currency gate
(`use_case_sync.py --all --check`) goes red because the artifacts no longer match the
sources — but the message points at staleness, not at the rebase that caused it.

**The rule:** after any rebase that touched a generated path, regenerate before pushing.

```bash
gh stack rebase
python3 scripts/use_case_sync.py --use-case <slug>   # in the top layer
```

This is the same doctrine `.gitattributes` already states — correctness comes from
regenerating, never from the merge — extended to the operation stacks depend on.

## CI cost, and why layers are capped at four

The suite runs on every push to every branch, and `gh stack submit` pushes every layer at
once. Three workflows (`ci.yml`, `ci-lite.yml`, `ci-quality-gate.yml`) declare no
`concurrency` group, so nothing is cancelled: a four-layer stack multiplies an already
multi-run PR pipeline by four.

That is the real reason for the four-layer cap and for preferring one more commit over one
more layer. If a stack needs a fifth layer, it is two deliveries.

## Concurrency across clients

Two clients in flight at once is the normal case, and nothing about it is special:

- Their source files do not overlap — different `use-cases/<slug>/` trees.
- Their generated artifacts do overlap, and `.gitattributes` routes those through the
  `generated` merge driver (keep one side, then regenerate). `.gitignore` merges by union.
  `scripts/setup_git_merge_drivers.sh` registers both, and activation runs it.
- Whoever merges second re-runs `use_case_sync.py` in their `04-hardening` layer. That is
  the whole conflict procedure.

The `PR Auto Update` workflow keeps stack **bottoms** current with `main` — it selects
`--base main`, so it deliberately leaves upper layers alone and lets GitHub's auto-rebase
own them. Do not widen that selector.

## Rules

1. Never commit to `main`; never open a PR from a branch that is not in the grammar.
2. Branch from fresh `origin/main` — `git fetch origin` immediately before starting.
3. One deliverable, one stack, at most four layers.
4. Generated artifacts regenerate in the top layer only.
5. Merge bottom-up. Never merge a layer whose parent is still open.
6. Regenerate after any rebase that touched a generated path — the merge driver keeps the
   wrong side under rebase.
7. One change lands from one checkout — this remote is cloned more than once
   (`code-skills` and `claude-copilot-skills`), and starting the same work in both produces
   add/add conflicts between near-identical files.
8. A stack that stops being reviewable in a week is too big; split it.
9. **Close a stalled stack rather than letting it age.** Depth is capped at four layers;
   age is capped at two weeks. A stack whose bottom layer has been open longer than that
   gets landed as-is or closed — the upper layers can be reopened from fresh `main` later.

Rule 9 exists because a stalled stack quietly becomes the thing this whole strategy rejects.
`PR Auto Update` keeps the bottom layer merge-clean with `main`, which hides the drift: the
branch stays green while its *intent* ages out from under it. Depth caps do not help — a
two-layer stack stranded for six weeks is a long-lived branch wearing a stack's clothes.