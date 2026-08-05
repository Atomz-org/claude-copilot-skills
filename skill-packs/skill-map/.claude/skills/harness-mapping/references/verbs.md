# Driving the `sm` CLI directly

`scripts/skill_map_scan.py` is the supported path and the one CI uses. Reach for
the CLI directly only for interactive exploration, and stay inside the
deterministic verbs below — the allowlist in
[determinism.md](determinism.md) is what keeps this repository LLM-free, and
bypassing the wrapper bypasses it.

## Invocation

```bash
# preferred: an installed CLI
npm i -g @skill-map/cli
sm <verb>

# or without installing (pin the version — analyzers decide the findings)
npx -y @skill-map/cli@0.99.1 <verb>
```

Always set these for a scripted run:

```bash
SKILL_MAP_TELEMETRY=0 SM_NO_UPDATE_CHECK=1 NO_COLOR=1 sm scan --json
```

## Verbs worth knowing

| Verb | What it gives you |
|---|---|
| `sm init` | Provisions `.skill-map/` (SQLite DB + settings) and runs a first scan. Idempotent. |
| `sm scan` | Re-walks the roots and refreshes the graph. `--json` emits the full ScanResult. |
| `sm check` | Prints current issues from the DB. Faster than `scan --json` when the scan is already fresh. |
| `sm list` | Tabular node listing. |
| `sm show <node>` | One node's detail: weight, frontmatter, links, issues. |
| `sm orphans` | Nodes nothing references — the deletion-candidate list. |
| `sm graph` | Renders the whole graph through a named formatter. |
| `sm export` | Filtered export. |
| `sm doctor` | DB integrity, pending migrations, plugin status. |
| `sm version` | CLI / spec / runtime / db-schema version matrix. |

## Exit codes

`sm scan` and `sm init` exit **non-zero when they find content issues**, which
is the normal state of any real repository. Do not treat their exit code as a
failure signal — `scripts/skill_map_scan.py` deliberately ignores it and keys
off whether stdout parsed as JSON instead.

## Capturing `--json` output

Redirect to a file rather than piping:

```bash
sm scan --json > scan.json     # correct
sm scan --json | jq .          # truncates on a large repository
```

The CLI is a Node program, and Node's stdout is asynchronous on a pipe: a
process that exits before the buffer drains loses everything past the OS pipe
capacity (64 KiB). This repository's ScanResult is several hundred KiB, so a
pipe silently truncates it mid-token. The wrapper handles this by writing to a
temp file; if you invoke the CLI by hand, redirect.

## ScanResult shape

```
schemaVersion, scannedAt, roots, providers, tokenizer
nodes[]   id, kind (skill|command|agent|markdown), label, tokens, frontmatter
links[]   source, target, kind
issues[]  analyzerId, severity (error|warn|info), nodeIds[], message, data
stats     filesWalked, nodesCount, linksCount, issuesCount, durationMs
```

`issues[].analyzerId` is the field to group by — there is no `type` field, which
is the natural thing to reach for and the natural thing to get wrong.

## Do not run

`sm jobs *`, `sm agent *`, `sm findings *`, `sm refresh`. These are the
probabilistic layer. See [determinism.md](determinism.md).

`sm serve`, `sm watch`, and `sm tutorial` are interactive or long-running and
have no place in a scripted check. `sm tutorial` additionally writes into
`.claude/skills/`, which in this repository is a generated path — it would be
destroyed by the next activation and would dirty the tree in the meantime.
