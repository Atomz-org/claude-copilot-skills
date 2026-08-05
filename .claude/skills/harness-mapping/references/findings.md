# Reading skill-map findings in this repository

## Before you read counts: everything is doubled

This repository keeps each pack asset in two places on purpose — the pack under
`skill-packs/<pack>/.claude/` and the mirror `scripts/activate_skill_stack.sh`
materialises into `.claude/`. skill-map scans both trees, so a single defect is
reported twice.

Two consequences:

- Halve the raw counts before judging severity.
- Fix the **pack** copy. An edit to the mirror is reverted by the next
  activation, and the finding comes straight back.

A finding that appears in only *one* of the two trees is itself interesting: it
means the pack and its mirror have drifted, which is what the CI activation-drift
gate exists to catch.

## The analyzers

### `name-collision` — error, act on it

Two nodes declare the same name. Which one a harness loads is undefined, so this
is a real defect rather than a style issue.

The known instance here is `senior-analytics-engineer`, which exists as both an
agent and a skill. That one is **deliberate** — `CLAUDE.md` documents the skill
as the compatibility alias for `dbt-skill` and the agent as a distinct
delegating role. It is a documented exception, not a bug to fix.

Any *new* collision should be treated as a defect in the change that introduced
it.

### `frontmatter-parse-error` — warn, but act on it anyway

The frontmatter is not valid YAML. Ranked above its severity because the failure
mode is silent: a strict parser drops the entry entirely, so the skill simply
stops existing for some consumers while continuing to work in others.

The usual cause is an unquoted `: ` inside a plain scalar:

```yaml
description: Shared operations foundation for all packs: git, CI, review   # invalid
description: "Shared operations foundation for all packs: git, CI, review" # fixed
```

Quote any description containing a colon-space, or a `#`, or a leading `[`/`{`.

### `reference-broken` — error, triage before fixing

A Markdown link or reference whose target is not in the graph or on disk. The
highest-volume analyzer here, and the noisiest, because it cannot distinguish a
dead link from a path *written about* in prose. The `../../references/<name>.md`
form quoted in `CLAUDE.md` is documentation of the mirroring convention, not a
broken link — and writing it out concretely here would itself be reported,
which is the analyzer's limitation in one line.

Triage:

- Target is a real path that moved or was deleted → fix it.
- Target is an example, placeholder, or template variable inside prose → ignore.
- Target is under `graphify-out/` → ignore; that tree is generated and gitignored.

`tests/test_docs_links.py` already enforces the strict version of this rule for
relative links in tracked Markdown. Where the two disagree, the test is
authoritative — it knows about the pack/mirror duality and this analyzer does not.

### `name-reserved` — warn, know about it

The name resolves to a Claude Code runtime built-in, which shadows it. `/review`
is the live example: this repository ships `.claude/commands/review.md` and
`.claude/commands/infra/review.md`, and the built-in `/review` wins.

Not automatically a bug — a repository may deliberately keep a command that is
only ever invoked by full path or by an agent. But if you wrote a `/command` and
it "does nothing", check here first.

### `frontmatter-invalid` — warn, low priority

Frontmatter parses as YAML but fails schema validation for its kind. Most
instances here are `/tools must be array` on agents that write `tools` as a
comma-separated string. Claude Code accepts that form; skill-map validates
against the stricter schema. Harmless unless you are targeting another harness,
which is exactly what the pack's portability targets claim to support.

### `link-self-loop` — warn, usually intentional

A skill or command references itself. In this repository the instances are a
skill documenting its own invocation, which is fine. Worth a look only if a
skill genuinely dispatches to itself at runtime.

## Node kinds

`markdown` dominates the node count because every documentation file counts as a
node. Only `skill`, `command`, and `agent` are harness entry points; a large
`markdown` count is not a problem in itself.

## Token weight

Each node carries a token weight from a `cl100k_base` tokenizer. Useful for
finding the skill that quietly costs the most to load. Treat it as a relative
signal — the tokenizer is not the one every model uses, so compare nodes against
each other rather than against a context-window budget.
