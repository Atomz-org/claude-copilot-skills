#!/usr/bin/env python3
"""Build a slice of a BigQuery dbt project locally, on DuckDB, from the sample seeds.

The problem this solves: enhanza-analytics targets BigQuery, and its SQL says so —
`float64` casts, double-quoted string literals, `json_extract_scalar`, lateral `unnest`.
The local profile is DuckDB, which parses none of that. So "does the union contract
actually execute" was only answerable in a warehouse, and the alignment checker could
prove column *sets* matched while nothing ever ran the UNION.

The expert pattern is transpilation at the execution boundary, with dbt kept for
everything it owns:

    dbt seed      loads the sample CSVs (dialect-free — dbt generates the inserts)
    dbt compile   renders jinja, resolves ref()/source(), inlines ephemeral models
    sqlglot       transpiles each compiled SELECT, BigQuery -> DuckDB
    duckdb        executes, materialises, and runs the attached data tests

sqlglot is already this repository's column-lineage engine, and DuckDB is already the
local profile; the runner adds no new dependency. What it deliberately does NOT do is
rewrite any model: the project stays BigQuery SQL, and the transpiler owns the dialect
gap the same way it does in CI tools built on the same idea.

Scope is stated, not implied. Models whose inputs are JSON payloads cannot run from the
sample seeds — a placeholder string is not a JSON document — so the sample selection is
the union concepts whose full path is JSON-free (six of them; see the seeds README). The
runner fails loudly on anything else rather than pretending coverage.

Usage:
    python3 scripts/dbt_sample_build.py                       # dim_articles, 3 connectors
    python3 scripts/dbt_sample_build.py --select erp_bi_dim_company \\
        --connectors seventime,visma_eaccounting,fortnox
    python3 scripts/dbt_sample_build.py --format json         # machine-facing
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _manifest import Manifest, die  # noqa: E402

from _paths import REPO  # noqa: E402

try:
    import sqlglot
except ImportError:  # pragma: no cover - optional, same shape as dbt_column_lineage
    sqlglot = None

try:
    import duckdb
except ImportError:  # pragma: no cover - optional
    duckdb = None

DEFAULT_SELECT = "erp_bi_dim_articles"
DEFAULT_CONNECTORS = "seventime,visma_eaccounting,shopify"
TARGET = "demo"
UID = "demo"


def find_dbt() -> Optional[str]:
    candidate = os.environ.get("DBT_BIN") or str(REPO / ".venv-dbt/bin/dbt")
    if Path(candidate).exists():
        return candidate
    from shutil import which

    return which("dbt")


# The runner's own artifact directory. NOT `target/`: the canonical manifest there is
# parsed with every connector enabled (artifacts/refresh.sh), and this runner compiles with
# one tenant's flags — letting it write `target/manifest.json` replaces the full manifest
# with a partial one, which then silently poisons every downstream consumer (the seed
# generator regenerated 30 of 99 seeds from it before this was isolated).
TARGET_PATH = "target-sample"


def run_dbt(dbt: str, project: Path, args: List[str], dbt_vars: Dict[str, Any]) -> None:
    cmd = [dbt, *args, "--profiles-dir", ".", "--target", TARGET,
           "--vars", json.dumps(dbt_vars)]
    env = {**os.environ, "DBT_TARGET_PATH": TARGET_PATH}
    proc = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=900,
                          env=env)
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
        die(f"dbt {args[0]} failed:\n{tail}")


def ancestors(man: Manifest, uid: str, seen: Optional[Set[str]] = None) -> Set[str]:
    seen = seen if seen is not None else set()
    for dep in man.nodes.get(uid, {}).get("depends_on", {}).get("nodes", []):
        if dep not in seen:
            seen.add(dep)
            if dep in man.nodes:
                ancestors(man, dep, seen)
    return seen


def topo(man: Manifest, uids: List[str]) -> List[str]:
    ordered: List[str] = []
    marked: Set[str] = set()

    def visit(uid: str) -> None:
        if uid in marked:
            return
        marked.add(uid)
        for dep in man.nodes.get(uid, {}).get("depends_on", {}).get("nodes", []):
            if dep in set(uids):
                visit(dep)
        ordered.append(uid)

    for uid in uids:
        visit(uid)
    return ordered


def compiled_sql(man: Manifest, uid: str, project: Path) -> Optional[str]:
    node = man.nodes[uid]
    code = node.get("compiled_code")
    if code:
        return code
    path = node.get("compiled_path")
    if path and (project / path).exists():
        return (project / path).read_text(encoding="utf-8")
    return None


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Sample build: dbt compile + sqlglot + DuckDB.")
    p.add_argument("--use-case", default="enhanza-analytics")
    p.add_argument("--select", default=DEFAULT_SELECT, help="terminal model to build")
    p.add_argument("--connectors", default=DEFAULT_CONNECTORS,
                   help="comma-separated connectors to enable")
    p.add_argument("--keep-db", action="store_true", help="do not delete the DuckDB file first")
    p.add_argument("--format", choices=("text", "json"), default="text")
    args = p.parse_args(argv)

    # Missing toolchain is a skip (exit 3), not a failure — the skill-map rule.
    dbt = find_dbt()
    missing = [name for name, present in
               [("dbt", dbt), ("sqlglot", sqlglot), ("duckdb", duckdb)] if not present]
    if missing:
        print(f"SKIP: sample build needs {', '.join(missing)} — not installed", file=sys.stderr)
        return 3

    matches = [q for q in REPO.glob(f"skill-packs/*/use-cases/{args.use_case}") if q.is_dir()]
    if not matches:
        die(f"no use-case '{args.use_case}'")
    project = matches[0] / "dbt_project"
    seeds_dir = project / "seeds" / "sample"
    if not any(seeds_dir.glob("*.csv")):
        die(f"no sample seeds under {seeds_dir.relative_to(REPO)} — run "
            f"scripts/use_case_sync.py --use-case {args.use_case} first")

    connectors = [c.strip() for c in args.connectors.split(",") if c.strip()]
    # is_erp_enabled gates the entire unified layer (any_source_enabled, the logic models,
    # erp_bi itself) and defaults to false. The union contract IS the thing under test.
    dbt_vars: Dict[str, Any] = {
        "uid": UID,
        "is_erp_enabled": True,
        **{f"is_{c}_enabled": True for c in connectors},
    }

    db_path = project / "enhanza_sample.duckdb"
    if not args.keep_db and db_path.exists():
        db_path.unlink()  # fresh build every run, so a pass never means "leftover state"

    # 1. Install local packages, then compile the selection: jinja rendered, refs
    #    resolved, ephemeral models inlined. deps is cheap when nothing changed.
    if (project / "packages.yml").exists():
        run_dbt(dbt, project, ["deps"], dbt_vars)
    run_dbt(dbt, project, ["compile", "--select", f"+{args.select}"], dbt_vars)
    man = Manifest.load(str(project / TARGET_PATH / "manifest.json"))
    terminal = next((uid for uid, n in man.nodes.items()
                     if n.get("resource_type") == "model" and n.get("name") == args.select), None)
    if not terminal:
        die(f"model '{args.select}' not in the manifest — is it enabled for {connectors}?")

    lineage = [terminal] + [u for u in ancestors(man, terminal) if u in man.nodes]
    models = [u for u in topo(man, lineage)
              if man.nodes[u].get("resource_type") == "model"
              and man.nodes[u].get("config", {}).get("materialized") != "ephemeral"]
    models.append(terminal)  # ephemeral terminal is materialised as a view here
    models = list(dict.fromkeys(models))

    # 2. Seed only the source tables this lineage reads.
    sources = {u for u in ancestors(man, terminal) if u in man.sources}
    seed_names = sorted(
        f"{man.sources[u].get('source_name')}__{man.sources[u].get('name')}" for u in sources
    )
    absent = [s for s in seed_names if not (seeds_dir / f"{s}.csv").exists()]
    if absent:
        die(f"lineage needs source seeds that do not exist: {absent}")
    run_dbt(dbt, project, ["seed", "--select", *seed_names], dbt_vars)

    # 3. Transpile and execute, in dependency order.
    con = duckdb.connect(str(db_path))
    built: List[Dict[str, str]] = []
    for uid in models:
        node = man.nodes[uid]
        sql = compiled_sql(man, uid, project)
        if not sql:
            return _fail(args, built, f"{node['name']}: no compiled SQL")
        try:
            ducked = sqlglot.transpile(sql, read="bigquery", write="duckdb")[0]
        except Exception as exc:  # noqa: BLE001 - report which model, then stop
            return _fail(args, built, f"{node['name']}: transpile failed: {exc}")
        schema = node.get("schema") or TARGET
        alias = node.get("alias") or node["name"]
        kind = "table" if node.get("config", {}).get("materialized") == "table" else "view"
        try:
            con.execute(f'create schema if not exists "{schema}"')
            con.execute(f'create or replace {kind} "{schema}"."{alias}" as {ducked}')
            rows = con.execute(f'select count(*) from "{schema}"."{alias}"').fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            return _fail(args, built, f"{node['name']}: execution failed: {exc}")
        built.append({"model": node["name"], "relation": f"{schema}.{alias}", "rows": rows})

    # 4. Run the data tests attached to what was built.
    built_uids = set(models)
    tests, failures = [], []
    for uid, node in man.nodes.items():
        if node.get("resource_type") != "test":
            continue
        deps = {d for d in node.get("depends_on", {}).get("nodes", []) if d.startswith("model.")}
        # ALL model dependencies must have been built, not any: a relationships test spans
        # child and parent, and running it with only the parent present reports a missing
        # table as a test failure.
        if not deps or not deps <= built_uids:
            continue
        sql = compiled_sql(man, uid, project)
        if not sql:
            continue
        try:
            ducked = sqlglot.transpile(sql, read="bigquery", write="duckdb")[0]
            bad = con.execute(f"select count(*) from ({ducked}) q").fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            failures.append({"test": node["name"], "error": str(exc)})
            continue
        tests.append({"test": node["name"], "failing_rows": bad})
        if bad:
            failures.append({"test": node["name"], "failing_rows": bad})

    # 5. The check that needs a running database: every enabled connector actually
    #    contributes rows to the union, under one conformed column list.
    terminal_node = man.nodes[terminal]
    rel = f'"{terminal_node.get("schema") or TARGET}"."{terminal_node.get("alias") or args.select}"'
    per_source = dict(con.execute(
        f"select DataSource, count(*) from {rel} group by 1 order by 1"
    ).fetchall())
    con.close()

    payload = {
        "use_case": args.use_case,
        "select": args.select,
        "connectors": connectors,
        "seeded": seed_names,
        "built": built,
        "tests_run": len(tests),
        "test_failures": failures,
        "union_rows_by_source": per_source,
        "db": str(db_path.relative_to(REPO)),
        "ok": not failures and len(per_source) == len(connectors),
    }
    if len(per_source) != len(connectors):
        payload["problem"] = (
            f"{len(connectors)} connectors enabled but {len(per_source)} present in the "
            f"union — an adapter contributed nothing"
        )

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"seeded   {len(seed_names)} source table(s): {', '.join(seed_names)}")
        for b in built:
            print(f"built    {b['relation']:<44} {b['rows']:>4} rows")
        print(f"tests    {len(tests)} run, {len(failures)} failing")
        for source, n in per_source.items():
            print(f"union    {source:<44} {n:>4} rows")
        print("OK" if payload["ok"] else f"FAILED: {payload.get('problem', failures)}")
    return 0 if payload["ok"] else 1


def _fail(args: argparse.Namespace, built: List[Dict[str, str]], reason: str) -> int:
    payload = {"use_case": args.use_case, "select": args.select, "built": built,
               "ok": False, "problem": reason}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"FAILED: {reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
