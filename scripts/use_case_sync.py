#!/usr/bin/env python3
"""Bring every derived artifact of a use-case back into agreement with the project.

A use-case is one hand-written thing and a set of derived ones. The hand-written thing is
the spec plus the dbt project; every stage in the table below derives from it.
Each derived artifact has its own script, each was run by hand, and "run them all in the
right order" is exactly the instruction that gets followed nine times out of ten — the
tenth leaves an ontology asserting a model that no longer exists, which is the failure
mode an ontology is famous for.

So the stages are one command, in dependency order, and each reports what it did:

    taxonomy   ontology/conceptual-model.json      <- sources.yml + taxonomy.yml; no manifest
    columns    ontology/column-memory.json         <- the .sql on disk, parsed and cached
    annotations ontology/column-annotations.json   <- annotations.yml + the conformed columns
    ontology   connectors/*.ttl + topology/*.ttl   <- registry, manifest, lineage, annotations
    index      index.json                          <- same pass as the Turtle
    semantic   models/semantic/*.yml (MetricFlow)  <- index.json + the project's unique tests
    seeds      seeds/sample/*.csv                  <- manifest + parsed source columns
    graphify   the code graph, rebuilt             <- opt-in; must precede the merge
    graph      dbt lineage + ontology topology, merged  <- manifest
    alignment  the verdict                         <- project files + manifest
    wren       wren/ WrenAI semantic-layer project <- manifest + catalog + ontology artifacts
               ...and its joins + metric views back into the graph

**A stage that cannot run says so and does not fail.** A fresh use-case has no manifest, and
half of these need one; a checkout without sqlglot cannot parse columns. Reporting `skip`
with the reason is the difference between a gate people keep and a gate people disable, and
it is why `--check` distinguishes "would change" from "could not run".

The order is not cosmetic, and one pair of stages is destructive out of order. The index is a
projection of the ontology, and the seeds read the same parsed lineage the ontology's mappings
come from — running those out of order reports a symptom rather than a cause. But a
`graphify update` *after* the dbt merge silently deletes the entire dbt DAG: graphify has no
SQL parser, so its AST pass extracts nothing from a `.sql` file and drops the node rather
than keeping it isolated. The rebuild is therefore a stage here, sequenced ahead of the
merge, instead of a line in a runbook telling somebody to remember.

Usage:
    python3 scripts/use_case_sync.py --use-case enhanza-analytics
    python3 scripts/use_case_sync.py --all --check          # the CI gate form
    python3 scripts/use_case_sync.py --init retail-margin   # scaffold a new use-case
    python3 scripts/use_case_sync.py --use-case x --format json | rust/toon/bin/graph_to_toon
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _paths  # noqa: E402
from _paths import REPO  # noqa: E402

OK, SKIP, CHANGED, FAIL = "ok", "skip", "changed", "fail"


def use_case_dir(slug: str) -> Optional[Path]:
    """`_paths.use_case_dir` bound to this module's REPO, which tests override."""
    return _paths.use_case_dir(slug, REPO)


def all_use_cases() -> List[str]:
    """`_paths.all_use_cases` bound to this module's REPO, which tests override."""
    return _paths.all_use_cases(REPO)


@dataclass
class Stage:
    name: str
    status: str
    detail: str = ""
    changed: List[str] = field(default_factory=list)

    def as_record(self) -> Dict[str, Any]:
        return {
            "stage": self.name,
            "status": self.status,
            "detail": self.detail,
            "changed": len(self.changed),
        }


def _write(path: Path, content: str, check: bool) -> bool:
    """True when the file differs from `content`; writes it unless checking."""
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == content:
        return False
    if not check:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------------------


def stage_ontology(use_case: Path, slug: str, manifest: Optional[Path], check: bool) -> List[Stage]:
    """Ontology and index together — one generator pass produces both, so they cannot drift."""
    catalogue = use_case / "ontology" / "connectors.yml"
    if not catalogue.exists():
        reason = "no ontology/connectors.yml — run --init to scaffold one"
        return [Stage("ontology", SKIP, reason), Stage("index", SKIP, reason)]

    import ontology_generator as og

    result = og.generate(slug, str(manifest) if manifest else None, use_case=use_case)
    lineage_ok = bool(result["lineage"].get("available"))

    changed: Dict[str, List[str]] = {"ontology": [], "index": []}
    refused: Dict[str, List[str]] = {"ontology": [], "index": []}
    for path, content in result["files"].items():
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing == content:
            continue
        which = "index" if path.suffix == ".json" else "ontology"
        marker = '"source_column"' if which == "index" else "conn:hasMapping"
        if existing and marker in existing and marker not in content:
            refused[which].append(path.name)
            continue
        changed[which].append(str(path.relative_to(REPO)))
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    problems = list(result["problems"])
    if result["unclassified"]:
        problems.append(
            f"{len(result['unclassified'])} concept(s) with no core class: "
            f"{', '.join(result['unclassified'][:5])} — add them to ontology.yml"
        )

    counts = (
        f"{len([s for s in result['specs'] if s.status == 'implemented'])} implemented, "
        f"{len([s for s in result['specs'] if s.status != 'implemented'])} planned"
    )
    details = {
        "ontology": counts,
        "index": "MCP projection: connectors, concepts, models, mappings, gaps",
    }

    def build(which: str) -> Stage:
        # A refusal is reported on the stage that was refused. Attaching it only to
        # `ontology` left `index` reporting `ok` for a file that had just been declined —
        # the reading a consumer would take as "the projection is current".
        if refused[which]:
            return Stage(
                which, FAIL,
                f"refused to rewrite {len(refused[which])} file(s) that would lose their "
                f"column mappings ({result['lineage'].get('reason', 'lineage unavailable')})",
                changed[which],
            )
        if which == "ontology" and problems:
            return Stage(which, FAIL, "; ".join(problems), changed[which])
        detail = details[which]
        if not lineage_ok:
            detail += f"; no column mappings ({result['lineage'].get('reason', 'unavailable')})"
        return Stage(which, CHANGED if changed[which] else OK, detail, changed[which])

    return [build("ontology"), build("index")]


def stage_taxonomy(use_case: Path, slug: str, check: bool) -> Stage:
    """`ontology/conceptual-model.json` — what the project should build, from the raw layer.

    First, and the only stage that takes no manifest: its inputs are `sources.yml` and the
    hand-authored `ontology/taxonomy.yml`, both of which exist before a single model does.
    That is the whole point of it — rule 6 wants the conceptual model to precede the
    physical one, and every other stage here can only describe a project that already
    exists.

    Skips rather than fails in the two states that are correct-but-incomplete: no raw layer
    yet, and a raw layer nobody has mapped. Every use-case is in the second state the day
    this lands, and a gate that goes red on it gets switched off within a week.
    """
    if not (use_case / "ontology" / "taxonomy.yml").exists():
        return Stage("taxonomy", SKIP, "no ontology/taxonomy.yml — run raw_taxonomy.py --propose")
    cmd = [sys.executable, str(REPO / "scripts/raw_taxonomy.py"),
           "--use-case", slug, "--format", "json"]
    if check:
        cmd.append("--check")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=600)
    payload = _first_json_line(proc.stdout)
    if payload is None:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        return Stage("taxonomy", FAIL, tail[-1] if tail else f"exit {proc.returncode}")
    if payload.get("status") == "skip":
        return Stage("taxonomy", SKIP, str(payload.get("reason", "")))
    changed = [payload["artifact"]] if payload.get("changed") else []
    if payload.get("problems"):
        return Stage("taxonomy", FAIL, "; ".join(payload["problems"][:3]), changed)
    detail = (
        f"{payload.get('entities', 0)} entities from "
        f"{payload.get('raw_tables_mapped', 0)} of "
        f"{payload.get('raw_tables_declared', 0)} raw table(s), "
        f"{payload.get('gaps', 0)} concept(s) with no source"
    )
    return Stage("taxonomy", CHANGED if changed else OK, detail, changed)


def stage_columns(use_case: Path, slug: str, manifest: Optional[Path], check: bool) -> Stage:
    """`ontology/column-memory.json` — the column contract, its bindings, and its drift.

    Sequenced ahead of `ontology` because `annotations` sits between them: the annotations
    are keyed on the conformed columns this stage derives, and the ontology projects the
    annotations. Running it after `ontology` — where it used to sit, on the softer ground
    that it shares the `ontology.yml` namespace and the `property_for` rules — would make
    every ontology describe the previous generation's columns. It is a separate stage
    rather than part of
    `ontology` for one reason: it is the only stage that reads the `.sql` files on disk
    rather than the manifest, so it is the only one that can be *right* when the manifest is
    stale — and reporting that separately is the point.
    """
    if not manifest:
        return Stage("columns", SKIP, "no manifest — run artifacts/refresh.sh")

    import dbt_column_memory as ccm

    project_root = ccm.project_root_of(use_case, manifest)
    man = ccm.Manifest.load(str(manifest))
    cache = ccm.LineageCache(ccm.CACHE_DIR / f"{slug}.json")
    store = ccm.build_store(man, project_root, slug, use_case, cache=cache)

    path = ccm.artifact_path(use_case)

    # A project with no unified layer has no adapter to disagree with anything, so it has no
    # column contract. Writing an empty one would create an `ontology/` directory the
    # use-case never asked for and put a file there that asserts nothing — and every later
    # `--check` would then be comparing two empty files and reporting `ok`. Skipping says
    # what is true. An artifact that already exists is still regenerated, because an existing
    # store going empty is a regression rather than a non-event.
    if not store.contracts and not store.bindings and not path.exists():
        return Stage("columns", SKIP, "no unified adapters — nothing to contract")

    # The refusal is decided *before* anything is written, and against the file as it was.
    # Deciding it afterwards inspects this run's own output: with a warm .dbt-column-cache the
    # bindings survive the rewrite and the guard fires correctly, but on a cold cache — CI, a
    # fresh clone, exactly where this matters — the bindings-free file is already on disk, the
    # marker it looks for is gone with them, and the guard waves through the damage it exists
    # to prevent. Same refusal shape as `ontology`; only the ordering was wrong.
    had_bindings = (
        path.exists() and '"source_column"' in path.read_text(encoding="utf-8")
    )
    if not store.provenance["sqlglot"] and had_bindings:
        return Stage(
            "columns", FAIL,
            "refused to rewrite column-memory.json without its bindings "
            "(sqlglot not installed — pip install -r .github/requirements/ci.txt)",
        )

    changed = [str(path.relative_to(REPO))] if _write(path, ccm.serialise(store), check) else []

    fresh = store.provenance["freshness"]
    detail = (
        f"{len(store.contracts)} concept contracts, {len(store.bindings)} source bindings, "
        f"{len(store.drift)} drift finding(s)"
    )
    if not store.provenance["sqlglot"]:
        detail += "; no source bindings (sqlglot not installed)"
    if fresh["changed"] or fresh["untracked_sql"]:
        detail += (
            f"; {fresh['changed']} model(s) re-read from disk, "
            f"{fresh['untracked_sql']} untracked .sql — the manifest is behind the project"
        )
    return Stage("columns", CHANGED if changed else OK, detail, changed)


def stage_annotations(use_case: Path, slug: str, check: bool) -> Stage:
    """`ontology/column-annotations.json` — what each conformed column *means*.

    Between `columns` and `ontology`, because it is keyed on the conformed columns the
    first produces and projected into the Turtle and `index.json` the second writes. That
    projection is the whole reason it is a stage: an annotation nothing carries forward
    reaches neither BI nor an MCP client, which are the two consumers that need it.

    Its input is hand-authored and usually absent, so absence skips with the remedy named
    — the same call `taxonomy` makes, for the same reason. Additivity and PII cannot be
    derived from a schema, and a stage that failed until somebody wrote them would be
    switched off long before they were written.
    """
    if not (use_case / "ontology" / "annotations.yml").exists():
        return Stage("annotations", SKIP,
                     "no ontology/annotations.yml — run column_annotations.py "
                     "--propose --evidenced-only")
    cmd = [sys.executable, str(REPO / "scripts/column_annotations.py"),
           "--use-case", slug, "--format", "json"]
    if check:
        cmd.append("--check")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=600)
    payload = _first_json_line(proc.stdout)
    if payload is None:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        return Stage("annotations", FAIL, tail[-1] if tail else f"exit {proc.returncode}")
    if payload.get("status") == "skip":
        return Stage("annotations", SKIP, str(payload.get("reason", "")))
    changed = [payload["artifact"]] if payload.get("changed") else []
    if payload.get("problems"):
        return Stage("annotations", FAIL, "; ".join(payload["problems"][:3]), changed)
    detail = (
        f"{payload.get('annotated', 0)} of {payload.get('conformed_columns', 0)} "
        f"conformed column(s) annotated, {payload.get('pii_columns', 0)} carrying PII"
    )
    return Stage("annotations", CHANGED if changed else OK, detail, changed)


def stage_semantic(use_case: Path, slug: str, manifest: Optional[Path], check: bool) -> Stage:
    """`models/semantic/` — the MetricFlow layer the annotations support.

    After `ontology`, because it reads `index.json`'s `column_semantics`; before `wren`,
    because the Wren stage compiles each MetricFlow metric into an MDL view and can only
    compile the metrics the manifest holds. That second dependency is the one worth
    stating: this stage writes into the dbt project, so the manifest is stale the moment it
    changes anything, and the metrics reach the serving tier only after the next parse.
    Reporting `changed` with the remedy named beats silently enriching from the previous
    generation — the same reason `wren` is sequenced last.
    """
    if not manifest:
        return Stage("semantic", SKIP, "no manifest — run artifacts/refresh.sh")
    cmd = [sys.executable, str(REPO / "scripts/ontology_to_semantic.py"),
           "--use-case", slug, "--manifest", str(manifest), "--format", "json"]
    cmd.append("--check" if check else "--write")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=600)
    payload = _first_json_line(proc.stdout)
    if payload is None:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        return Stage("semantic", FAIL, tail[-1] if tail else f"exit {proc.returncode}")
    if payload.get("status") == "skip":
        return Stage("semantic", SKIP, str(payload.get("reason", "")))

    changed = payload.get("changed") or []
    refused = payload.get("refused") or {}
    detail = (
        f"{payload.get('semantic_models', 0)} semantic model(s), "
        f"{payload.get('entities', 0)} entities, {payload.get('dimensions', 0)} dimensions, "
        f"{payload.get('metrics', 0)} metric(s)"
    )
    blocked = refused.get("no-unique-test", 0)
    if blocked:
        detail += f"; {blocked} concept(s) blocked on a `unique` test (rule 21)"
    if changed:
        detail += "; manifest now stale for `wren` — run artifacts/refresh.sh"
    return Stage("semantic", CHANGED if changed else OK, detail, changed)


def stage_seeds(use_case: Path, slug: str, manifest: Optional[Path], check: bool) -> Stage:
    if not manifest:
        return Stage("seeds", SKIP, "no manifest — run artifacts/refresh.sh")
    if not (use_case / "ontology" / "reference").exists():
        return Stage("seeds", SKIP, "no ontology/reference — nothing to draw values from")

    import dbt_seed_generator as seeder
    from _manifest import Manifest

    man = Manifest.load(str(manifest))
    ref = seeder.Reference(use_case / "ontology" / "reference")
    seeds = seeder.build_seeds(man, ref, None)
    if not seeds:
        return Stage("seeds", SKIP, "no source columns resolved — sqlglot not installed")

    out_dir = use_case / "dbt_project" / "seeds" / "sample"
    changed = [
        str((out_dir / name).relative_to(REPO))
        for name, text in sorted(seeds.items())
        if _write(out_dir / name, text, check)
    ]
    csvs = sum(1 for n in seeds if n.endswith(".csv"))
    return Stage(
        "seeds", CHANGED if changed else OK,
        f"{csvs} source tables at {seeder.ROWS_PER_TABLE} rows, wired by properties.yml",
        changed,
    )


def stage_graphify_update(check: bool) -> Stage:
    """`graphify update .` — and it must run *before* the dbt merge, never after.

    graphify has no SQL parser, so its AST pass extracts zero symbols from a `.sql` file and
    drops the node entirely rather than keeping it at degree 0. A rebuild after the merge
    therefore removes all 359 dbt models and their 1288 edges, leaving only the source nodes
    (which have no file on disk to be re-extracted from) — a graph that still looks populated
    and has lost the entire dbt DAG. Measured: 3061 nodes with lineage, 3453 without it.

    Sequencing it here is the fix. A doc that says "run them in this order" is a footgun with
    a warning label on it.
    """
    if check:
        return Stage("graphify", SKIP, "not run under --check")
    graph = REPO / "graphify-out" / "graph.json"
    if not graph.exists():
        return Stage("graphify", SKIP, "no graphify-out/graph.json — run /graphify first")
    proc = subprocess.run(
        ["graphify", "update", "."], capture_output=True, text=True, cwd=REPO, timeout=1800,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        return Stage("graphify", FAIL, tail[-1] if tail else f"exit {proc.returncode}")
    rebuilt = next(
        (ln.split("Rebuilt:")[1].strip() for ln in proc.stdout.splitlines() if "Rebuilt:" in ln),
        "rebuilt",
    )
    return Stage("graphify", OK, rebuilt)


def stage_graph(use_case: Path, manifest: Optional[Path], check: bool,
                with_column_lineage: bool = False) -> Stage:
    if not manifest:
        return Stage("graph", SKIP, "no manifest — run artifacts/refresh.sh")
    if not (REPO / "graphify-out" / "graph.json").exists():
        return Stage("graph", SKIP, "no graphify-out/graph.json — run /graphify first")

    cmd = [
        sys.executable, str(REPO / "scripts/dbt_manifest_to_graphify.py"),
        "--manifest", str(manifest), "--format", "json",
        "--dry-run" if check else "--merge",
    ]
    # Opt-in, because it roughly doubles the graph (3058 -> 6382 nodes here): worth it to
    # trace a column across layers, useless if you only ever ask about models.
    if with_column_lineage:
        cmd.append("--with-columns")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=600)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        return Stage("graph", FAIL, tail[-1] if tail else f"exit {proc.returncode}")
    # The emitter prints its JSON payload first, then `--merge` appends graphify's own
    # `merged: N nodes` line. Parsing the whole stream would fail on that second line, which
    # is exactly the case a merge produces and a dry run does not — so it would have passed
    # every --check run and broken only when writing.
    payload = _first_json_line(proc.stdout)
    if payload is None:
        return Stage("graph", FAIL, "emitter produced no JSON")
    merged = next(
        (ln for ln in proc.stdout.splitlines() if ln.startswith("merged:")), ""
    )
    detail = (
        f"{payload.get('models', 0)} models, {payload.get('edges', 0)} edges "
        f"at {payload.get('coverage_pct', 0)}% manifest coverage"
    )

    # The ontology topology rides the same stage because it obeys the same ordering rule
    # (rebuild before merge, never update after) — a second stage would be a second place
    # to state that rule. A dry run stops at the dbt emitter's verdict: the topology
    # fragment has no dry form, and mutating the graph under --check is not checking.
    topology = ""
    catalogue = use_case / "ontology" / "connectors.yml"
    if not check and catalogue.exists():
        oproc = subprocess.run(
            [sys.executable, str(REPO / "scripts/ontology_generator.py"),
             "--use-case", use_case.name, "--manifest", str(manifest), "--merge-graphify"],
            capture_output=True, text=True, cwd=REPO, timeout=600,
        )
        if oproc.returncode != 0:
            tail = (oproc.stderr or oproc.stdout).strip().splitlines()
            return Stage(
                "graph", FAIL,
                f"ontology topology: {tail[-1] if tail else f'exit {oproc.returncode}'}",
            )
        topology = next(
            (ln for ln in oproc.stdout.splitlines() if ln.startswith("fragment:")), ""
        ).split(" -> ")[0].replace("fragment:", "topology:")

    parts = [detail] + [p for p in (merged, topology) if p]
    return Stage("graph", OK, "; ".join(parts))


def _first_json_line(stream: str) -> Optional[Dict[str, Any]]:
    for line in stream.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def stage_alignment(use_case: Path, slug: str, manifest: Optional[Path]) -> Stage:
    if not (use_case / "dbt_project").exists():
        return Stage("alignment", SKIP, "no dbt_project yet")

    cmd = [
        sys.executable, str(REPO / "scripts/connector_alignment_check.py"),
        "--use-case", slug, "--format", "json",
    ]
    if manifest:
        cmd += ["--manifest", str(manifest)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=600)
    payload = _first_json_line(proc.stdout)
    if payload is None:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        return Stage("alignment", FAIL, tail[-1] if tail else "checker produced no JSON")

    errors, warnings = payload.get("errors", 0), payload.get("warnings", 0)
    skipped = payload.get("skipped_checks") or []
    note = f"; {len(skipped)} check(s) skipped" if skipped else ""
    if errors:
        kinds = sorted({
            f.get("check", "?") for f in payload.get("findings", [])
            if f.get("severity") == "error"
        })
        return Stage("alignment", FAIL, f"{errors} error(s): {', '.join(kinds[:6])}{note}")
    # Warnings are surfaced, never fatal. The checker uses them for judgement calls — a
    # naming departure, an undocumented model — and a gate that blocks on those gets turned
    # off, taking the errors with it.
    return Stage("alignment", OK, f"no errors, {warnings} warning(s){note}")


def stage_wren(use_case: Path, slug: str, manifest: Optional[Path], check: bool) -> Stage:
    """`wren/` — the WrenAI semantic-layer projection: native dbt import plus enrichment.

    The heavy lifting is a subprocess because the emitter needs the `wren` CLI, and CLI
    resolution (env, PATH, .venv-wren) plus every skip decision lives in one place there.
    The emitter reports `skip` in its payload rather than by exit code, so a runner without
    wrenai — or a use-case without a catalog.json — stays green with the reason on record.
    """
    cmd = [
        sys.executable, str(REPO / "scripts/wren_context_sync.py"),
        "--use-case", slug, "--format", "json",
    ]
    if manifest:
        cmd += ["--manifest", str(manifest)]
    if check:
        cmd += ["--check"]
    # 1800, not 600: the emitter budgets 300s per wren call and makes four. An outer
    # timeout below that sum SIGKILLs the child inside the run_results sanitizer window,
    # which a finally clause cannot survive.
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=1800)
    payload = _first_json_line(proc.stdout)
    if payload is None:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        return Stage("wren", FAIL, tail[-1] if tail else f"exit {proc.returncode}")

    if payload["status"] == "skip":
        return Stage("wren", SKIP, payload.get("reason", "unavailable"))

    changed = [
        str((use_case / "wren" / rel).relative_to(REPO))
        for rel in payload.get("changed", []) + payload.get("deleted", [])
    ]
    without = payload.get("models_without_columns", 0)
    coverage = f" ({without} dropped: no column info)" if without else ""
    detail = (
        f"{payload.get('models', 0)} models{coverage}, "
        f"{payload.get('relationships', 0)} "
        f"relationships, {payload.get('views', 0)} metric views, "
        f"{payload.get('knowledge_files', 0)} knowledge files, "
        f"{payload.get('validate_warnings', 0)} validate warning(s)"
    )
    stale = payload.get("stale", [])
    if stale:
        detail += f"; {len(stale)} hand-authored file(s) left alone"

    # The loop closes here: the joins and metric views the serving tier holds go back into
    # the code graph an agent orients with. Inside this stage rather than beside it because
    # the never-update-after rule binds it to the same ordering as every other merge, and
    # `graphify` is already sequenced ahead of it. A dry run stops before the merge —
    # mutating the graph under --check is not checking.
    if not check:
        merged = _merge_wren_into_graph(slug, manifest)
        if merged:
            detail += f"; {merged}"
    return Stage("wren", CHANGED if changed else OK, detail, changed)


def _merge_wren_into_graph(slug: str, manifest: Optional[Path]) -> str:
    """`wren_context_sync.py --merge-graphify`, reported rather than raised.

    A graph that cannot be merged into is not a reason to fail the wren stage: the wren
    project is written and correct either way, and the graph is rebuildable in one command.
    """
    if not (REPO / "graphify-out" / "graph.json").exists():
        return ""
    cmd = [sys.executable, str(REPO / "scripts/wren_context_sync.py"),
           "--use-case", slug, "--merge-graphify", "--format", "json"]
    if manifest:
        cmd += ["--manifest", str(manifest)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=600)
    payload = _first_json_line(proc.stdout)
    if proc.returncode != 0 or payload is None or payload.get("status") == "skip":
        return "graph merge skipped"
    dropped = payload.get("dropped_total", 0)
    note = f", {dropped} dropped" if dropped else ""
    return (f"graph +{payload.get('nodes', 0)} metric node(s) "
            f"+{payload.get('edges', 0)} edge(s){note}")


# ---------------------------------------------------------------------------------------
# Scaffolding a new use-case
# ---------------------------------------------------------------------------------------

CONNECTORS_YML_STUB = """\
# Connector catalogue
# ===================
#
# Every source system this use-case reads, or intends to. This is the extension point: a
# connector starts as a row here, and its ontology extension, its place in the topology, and
# its coverage gaps are all generated from it.
#
# `status` is the honest part:
#
#   implemented  the connector has models in the warehouse. Its extension is generated from
#                the registry, the manifest, and the parsed column lineage, and every class
#                in it names a dbt model that exists.
#
#   planned      the connector is named and its kind is known, and nothing else is. No source
#                tables, no columns, no mappings are written for it, because none are known
#                here — see rule 5. `expected_concepts` records intended scope and is not a
#                claim that the connector supplies them.
#
# Empty to start. Adding an invented connector to make this file look populated is the exact
# thing the generator refuses to do on your behalf.

connectors: []
"""

ONTOLOGY_YML_STUB = """\
# Ontology settings for this use-case
# ===================================

# The IRI root every generated class, property, and individual hangs off. Pinned here rather
# than derived from the slug, so renaming the directory does not silently reissue every
# identifier this use-case has published.
namespace: {namespace}

title: {slug}

# Concept -> core class, merged over the shared ERP/CRM map in
# scripts/ontology_generator.py. Add an entry when this domain has a concept the shared
# vocabulary does not cover — a lease, a berth, a clinical episode. The generator reports an
# unclassified concept rather than guessing at one.
concept_classes: {{}}
"""

REFERENCE_README_STUB = """\
# Reference data

Values that generated sample data is allowed to use, and the only ones it is allowed to use.

The convention is [microsoft/Ontology-Playground](https://github.com/microsoft/Ontology-Playground/tree/main/data/reference)'s:
one source of truth for names, never invented at the point of use. It is also rule 5 —
never invent a number or a name — enforced by a file rather than by discipline.

**Empty to start.** `scripts/dbt_seed_generator.py` reads CSVs from this directory and emits
a visibly fake placeholder (`somefield_value_3`) for any column no reference file covers. A
placeholder that looks like data is worse than one that does not, so add real reference
values here rather than teaching the generator to invent plausible ones.

See `skill-packs/dbt-skills/use-cases/enhanza-analytics/ontology/reference/` for the shape:
one CSV per kind of value, every column real.
"""


def scaffold(slug: str, pack: str, check: bool) -> List[Stage]:
    """Create the derived-artifact skeleton for a use-case. Invents nothing."""
    root = REPO / "skill-packs" / pack / "use-cases" / slug
    namespace = f"https://w3id.org/{slug}/"
    files = {
        root / "ontology" / "connectors.yml": CONNECTORS_YML_STUB,
        root / "ontology" / "ontology.yml": ONTOLOGY_YML_STUB.format(
            namespace=namespace, slug=slug
        ),
        root / "ontology" / "reference" / "README.md": REFERENCE_README_STUB,
    }
    created = [str(p.relative_to(REPO)) for p, text in files.items() if _write(p, text, check)]

    spec = root / "use-case-spec.md"
    stages = [Stage("scaffold", CHANGED if created else OK,
                    f"ontology skeleton at {(root / 'ontology').relative_to(REPO)}", created)]
    if not spec.exists():
        stages.append(Stage(
            "spec", FAIL,
            f"no use-case-spec.md — write it from templates/use-case-spec.md before any "
            f"model exists (rule 1)",
        ))
    return stages


# ---------------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------------


def sync(slug: str, check: bool, manifest_arg: Optional[str],
         only: Optional[List[str]] = None, graphify_update: bool = False,
         with_column_lineage: bool = False) -> Dict[str, Any]:
    use_case = use_case_dir(slug)
    if not use_case:
        return {
            "use_case": slug,
            "stages": [Stage("resolve", FAIL, "no such use-case under skill-packs/*/use-cases/").as_record()],
            "ok": False,
        }

    manifest = Path(manifest_arg) if manifest_arg else use_case / "dbt_project/target/manifest.json"
    if not manifest.exists():
        manifest = None

    stages: List[Stage] = []
    if not (use_case / "use-case-spec.md").exists():
        stages.append(Stage("spec", FAIL, "no use-case-spec.md (rule 1)"))
    else:
        stages.append(Stage("spec", OK, "use-case-spec.md present"))

    wanted = set(only) if only else None

    def run(name: str, fn) -> None:
        if wanted and name not in wanted:
            return
        try:
            produced = fn()
        except SystemExit as exc:  # die() inside a generator is a stage failure, not an abort
            stages.append(Stage(name, FAIL, str(exc) or "aborted"))
            return
        except Exception as exc:  # noqa: BLE001 - a broken stage must not hide the others
            stages.append(Stage(name, FAIL, f"{type(exc).__name__}: {exc}"))
            return
        stages.extend(produced if isinstance(produced, list) else [produced])

    # First, and manifest-free: it declares what the project should build, which the
    # manifest-derived stages below can only describe once it has been built.
    run("taxonomy", lambda: stage_taxonomy(use_case, slug, check))
    # columns -> annotations -> ontology: each reads the one before it. The ontology is
    # last of the three because it projects the annotations into the Turtle and the index.
    run("columns", lambda: stage_columns(use_case, slug, manifest, check))
    run("annotations", lambda: stage_annotations(use_case, slug, check))
    run("ontology", lambda: stage_ontology(use_case, slug, manifest, check))
    # After the index it reads, before the wren stage that compiles its metrics.
    run("semantic", lambda: stage_semantic(use_case, slug, manifest, check))
    run("seeds", lambda: stage_seeds(use_case, slug, manifest, check))
    # Order-critical: the rebuild drops every .sql node, so the merge has to follow it.
    if graphify_update:
        run("graphify", lambda: stage_graphify_update(check))
    run("graph", lambda: stage_graph(use_case, manifest, check, with_column_lineage))
    run("alignment", lambda: stage_alignment(use_case, slug, manifest))
    # Last on purpose: it projects the artifacts the earlier stages just refreshed
    # (index.json, column-memory.json) into the Wren project, so running it earlier
    # would enrich from the previous generation.
    run("wren", lambda: stage_wren(use_case, slug, manifest, check))

    changed = [c for s in stages for c in s.changed]
    failed = [s for s in stages if s.status == FAIL]
    return {
        "use_case": slug,
        "manifest": str(manifest.relative_to(REPO)) if manifest else None,
        "stages": [s.as_record() for s in stages],
        "changed_files": changed[:20],
        "changed_total": len(changed),
        "failures": [f"{s.name}: {s.detail}" for s in failed],
        "ok": not failed and not (check and changed),
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Regenerate every derived artifact of a use-case, in dependency order.",
    )
    p.add_argument("--use-case", help="slug under skill-packs/*/use-cases/")
    p.add_argument("--all", action="store_true", help="every use-case in the repository")
    p.add_argument("--init", metavar="SLUG", help="scaffold a new use-case's ontology skeleton")
    p.add_argument("--pack", default="dbt-skills", help="pack that owns a new use-case")
    p.add_argument("--manifest", help="manifest.json (default: <project>/target/manifest.json)")
    p.add_argument("--stage", action="append", metavar="STAGE",
                   choices=("taxonomy", "columns", "annotations", "ontology", "semantic",
                            "seeds",
                            "graphify", "graph", "alignment", "wren"),
                   help="run only this stage (repeatable)")
    p.add_argument("--graphify-update", action="store_true",
                   help="rebuild the code graph before merging dbt lineage into it; never "
                        "run `graphify update` after a merge, it drops every .sql node")
    p.add_argument("--with-column-lineage", action="store_true",
                   help="merge column-level lineage too; roughly doubles the graph")
    p.add_argument("--check", action="store_true",
                   help="write nothing; exit 1 if anything would change or has failed")
    p.add_argument("--format", choices=("text", "json"), default="text")
    args = p.parse_args(argv)

    if args.init:
        stages = scaffold(args.init, args.pack, args.check)
        results = [{
            "use_case": args.init,
            "stages": [s.as_record() for s in stages],
            "changed_files": [c for s in stages for c in s.changed],
            "changed_total": sum(len(s.changed) for s in stages),
            "failures": [f"{s.name}: {s.detail}" for s in stages if s.status == FAIL],
            "ok": not any(s.status == FAIL for s in stages),
        }]
    elif args.all:
        # One rebuild for the repository, not one per use-case: each would drop the dbt
        # lineage the previous use-case had just merged in.
        results = []
        for i, slug in enumerate(all_use_cases()):
            results.append(sync(slug, args.check, None, args.stage,
                                graphify_update=args.graphify_update and i == 0,
                                with_column_lineage=args.with_column_lineage))
    elif args.use_case:
        results = [sync(args.use_case, args.check, args.manifest, args.stage,
                        graphify_update=args.graphify_update,
                        with_column_lineage=args.with_column_lineage)]
    else:
        p.error("one of --use-case, --all, or --init is required")

    if args.format == "json":
        print(json.dumps({"check": args.check, "use_cases": results}, ensure_ascii=False))
    else:
        for result in results:
            print(f"\n{result['use_case']}")
            for stage in result["stages"]:
                mark = {OK: "ok  ", SKIP: "skip", CHANGED: "chg ", FAIL: "FAIL"}[stage["status"]]
                count = f" ({stage['changed']} file(s))" if stage["changed"] else ""
                print(f"  {mark} {stage['stage']:<10} {stage['detail']}{count}")
            if result["failures"]:
                print(f"  -> {len(result['failures'])} failing stage(s)")

    failed = [r for r in results if not r["ok"]]
    if args.check and any(r["changed_total"] for r in results):
        print("\nre-run without --check to regenerate", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
