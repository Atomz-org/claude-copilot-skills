#!/usr/bin/env python3
"""Check that a connector's dbt models line up with the connectors already in the project.

`scripts/new_connector.py` *applies* this project's conventions when it scaffolds. Nothing
verified them afterwards, so a hand-written connector, a hand-edited scaffold, or a model
added months later drifted silently. Every defect this script checks for was found in
enhanza-analytics by running it:

  * `models/fortnox/fortnox_bi/schema.yml` used the dbt 1.10 `arguments:` nesting under
    `relationships` while the project pins `<2.0.0` and ships 1.9. One file, 95 tests, and
    `dbt parse` failed for the whole project — no connector could be added until it was
    fixed, and the error named a test, not the syntax.
  * 38 aliases were claimed by more than one model, because `model_alias()` strips the
    connector prefix and no `+schema` was ever declared. dbt refused to parse with more
    than a narrow subset of connectors enabled.
  * `tests/test_orders_mart.sql` referenced a model renamed to `orders_mart_scaffold`.

The conventions are not restated here. `new_connector.detect()` learns them from the
connectors already on disk, and this script imports it, so the generator and the checker
cannot disagree about what the convention is.

Truth comes from the manifest when one is available — `alias` and `schema` are resolved
there by dbt itself, and re-simulating `model_alias()` in Python would be a second
implementation that drifts. Checks that need no manifest (naming, ref/source discipline,
test syntax) run either way, so this is useful in a CI job with no warehouse and no parse.

Usage:
    # every connector in the default use-case
    python3 scripts/connector_alignment_check.py

    # one connector, with manifest-backed alias and schema checks
    python3 scripts/connector_alignment_check.py --connector shopify \\
        --manifest skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project/target/manifest.json

    # the CI gate form
    python3 scripts/connector_alignment_check.py --manifest <path> --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from new_connector import Conventions, detect, find_use_case  # noqa: E402

from _paths import REPO  # noqa: E402

ERROR, WARN = "error", "warn"

# What each check means, stated once. In text mode this is the per-finding sentence; in
# JSON/TOON mode it is emitted once in a `checks` table and the findings carry only the
# subject. 28 findings of one kind cost one template plus 28 names rather than 28 sentences
# — which is the whole reason a uniform record list is worth serializing as TOON.
CHECK_DETAIL: Dict[str, str] = {
    "hardcoded-source": "no source(), ref(), or project macro — invisible to lineage (rule 13)",
    "naming": "matches neither the project's staging nor its adapter model shape",
    "test-syntax": "generic test uses dbt >=1.10 `arguments:` nesting under a lower pin — dbt parse fails project-wide",
    "no-schema-yml": "no schema.yml in any of the connector's directories",
    "undocumented-model": "model has no schema.yml entry",
    "no-enable-var": "no `is_<source>_enabled` default in dbt_project.yml vars",
    "no-source-block": "no `- name: <source>` block in any sources.yml (rule 13)",
    "no-freshness": "source block declares no loaded_at_field/freshness (rule 14)",
    "alias-collision": "several models resolve to one relation in one schema — dbt cannot build both",
    "undeclared-schema": "model directory has no `+schema`; it shares target.schema with every other undeclared directory",
    "unregistered-connector": "staging models with no registry entry — nothing downstream will union them",
    "adapter-column-drift": "adapter omits columns the other adapters for this concept supply — the UNION only breaks when two sources are enabled at once",
    "undeclared-source-column": "staging reads a column its source does not declare — a typo, or a dependency nothing in the repo records",
}

# `arguments:` nesting under a generic test is dbt >= 1.10. A project pinned below that
# parses every other file and fails on this one, naming the test rather than the syntax.
DBT_110_TEST_SYNTAX = re.compile(r"^\s*arguments:\s*$", re.MULTILINE)

# Layer names that appear in `tags` and must not be mistaken for a connector name.
LAYER_TAGS = {
    "staging", "bi", "mart", "flat", "reports", "demo", "app", "unified", "scaffold", "logic",
}


@dataclass
class Finding:
    severity: str
    connector: str
    check: str
    message: str
    where: str = ""
    subject: str = ""

    def render(self) -> str:
        loc = f"\n      {self.where}" if self.where else ""
        return f"  [{self.severity:<5}] {self.check}: {self.message}{loc}"

    def as_record(self) -> Dict[str, str]:
        """The row form: no message, because `checks` carries it once for the whole run."""
        return {
            "severity": self.severity,
            "connector": self.connector,
            "check": self.check,
            "subject": self.subject or self.connector,
            "where": self.where,
        }


# ---------------------------------------------------------------------------------------
# Manifest-backed checks
# ---------------------------------------------------------------------------------------


def load_manifest(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"manifest not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _node_belongs_to(node: Dict[str, Any], connector: str) -> bool:
    """Whether a manifest node is one of `connector`'s models.

    Tags are the project's own declaration and win. The path and the name are fallbacks for
    a model whose tags were never set — which is exactly the sloppily-added model this check
    is meant to catch, so relying on tags alone would miss it.
    """
    if connector in (node.get("tags") or []):
        return True
    path = node.get("original_file_path", "")
    if f"/{connector}/" in path or path.startswith(f"models/{connector}/"):
        return True
    name = node.get("name", "")
    return name.startswith(f"{connector}_")


def check_alias_collisions(
    manifest: Dict[str, Any], connector: Optional[str] = None
) -> List[Finding]:
    """Two models resolving to the same relation in the same schema.

    Only an intra-schema collision is a defect. `fortnox_bi_dim_accounts` and
    `tripletex_bi_dim_accounts` both aliasing to `dim_accounts` is the intended design —
    the dataset separates them. The same alias twice in one dataset is what dbt refuses to
    build, and it is exactly what a new connector introduces when its models land in a
    directory that already owns that concept.

    Every model in the manifest is compared, always. `connector` narrows only which
    collisions are *reported* — those with at least one model belonging to it — so a scoped
    run still sees the whole project and does not bury the new connector's own collision
    under the project's pre-existing drift.
    """
    out: List[Finding] = []
    claims: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for uid, node in manifest.get("nodes", {}).items():
        if node.get("resource_type") not in ("model", "snapshot", "seed"):
            continue
        config = node.get("config", {}) or {}
        alias = node.get("alias") or node.get("name")
        schema = config.get("schema") or node.get("schema")
        claims.setdefault((str(schema), str(alias)), []).append(node)

    for (schema, alias), nodes in sorted(claims.items()):
        if len(nodes) < 2:
            continue
        if connector and not any(_node_belongs_to(n, connector) for n in nodes):
            continue
        paths = sorted(n.get("original_file_path", n.get("name", "?")) for n in nodes)
        owner = connector or _connector_of_node(nodes[0]) or "(project)"
        out.append(
            Finding(
                ERROR,
                owner,
                "alias-collision",
                f"{len(nodes)} models resolve to `{schema}.{alias}` — dbt cannot build both",
                "\n      ".join(paths),
                subject=f"{schema}.{alias}",
            )
        )
    return out


def check_undeclared_schema(
    manifest: Dict[str, Any], conv: Conventions, connector: Optional[str] = None
) -> List[Finding]:
    """Model directories whose models fall back to `target.schema`.

    A directory with no `+schema` shares a dataset with every other such directory, so its
    aliases compete with theirs. It parses today only while no two of them claim the same
    concept — the next connector is what breaks it.
    """
    out: List[Finding] = []
    project_yml = (conv.project / "dbt_project.yml").read_text(encoding="utf-8")
    default_schema_dirs: Dict[str, List[str]] = {}
    for node in manifest.get("nodes", {}).values():
        if node.get("resource_type") != "model":
            continue
        config = node.get("config", {}) or {}
        if config.get("schema"):
            continue
        if connector and not _node_belongs_to(node, connector):
            continue
        rel = node.get("original_file_path", "")
        directory = str(Path(rel).parent)
        default_schema_dirs.setdefault(directory, []).append(node.get("name", "?"))

    for directory, models in sorted(default_schema_dirs.items()):
        # The scaffold placeholders sit directly in models/ on purpose and are excluded
        # from a real build by tag; they are not a connector's concern.
        if directory in ("models", "."):
            continue
        out.append(
            Finding(
                WARN,
                "(project)",
                "undeclared-schema",
                f"{len(models)} model(s) in {directory} have no `+schema`; they share "
                f"target.schema with every other undeclared directory",
                f"add a `+schema:` entry for {directory} in dbt_project.yml",
                subject=directory,
            )
        )
    return out


def check_adapter_column_drift(
    manifest: Dict[str, Any], connector: Optional[str] = None
) -> List[Finding]:
    """Adapters for one ERP concept that disagree about their columns.

    `erp_union()` stacks one `<source>_erp_bi_<concept>` adapter per enabled source. A new
    connector whose adapter omits a column the others carry, or adds one they lack, produces
    a union that is only wrong when *both* sources are enabled — so the connector's own
    `dbt build --select tag:<connector>` passes, and the failure waits for a tenant who has
    two connectors on. Nothing else in this repository catches that before a warehouse does.

    Needs `sqlglot` to read the adapters' output columns out of their SQL. Without it this
    returns nothing rather than guessing, and the caller reports the check as skipped.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import dbt_column_lineage as lineage_mod
    except ImportError:  # pragma: no cover - the module ships beside this one
        return []
    if lineage_mod.sqlglot is None:
        return []

    from _manifest import Manifest  # local import: only this check needs it

    man = Manifest(manifest)
    lineage = lineage_mod.build_lineage(man)
    by_concept = lineage_mod.adapter_column_sets(man, lineage)

    out: List[Finding] = []
    for concept, sources in sorted(by_concept.items()):
        if len(sources) < 2:
            continue
        if connector and connector not in sources:
            continue
        # The shared contract is what every adapter already agrees on. A column present in
        # most but not all is the drift; a column unique to one source is usually deliberate
        # enrichment, so only the missing side is an error.
        counts: Dict[str, int] = {}
        for cols in sources.values():
            for col in cols:
                counts[col] = counts.get(col, 0) + 1
        majority = {c for c, n in counts.items() if n > len(sources) / 2}

        shared_by_others: Dict[str, Set[str]] = {
            s: set().union(*(c for k, c in sources.items() if k != s)) if len(sources) > 1 else set()
            for s in sources
        }

        for source, cols in sorted(sources.items()):
            if connector and source != connector:
                continue
            missing = sorted(majority - cols)
            if not missing:
                continue
            # A column only this source has, while it lacks one everybody else has, is
            # almost always the same column under a different name — `visma_economic` calls
            # it `isActive` where five others call it `Active`. Naming the suspect turns a
            # "you are missing a column" report into a one-line fix.
            unique = sorted(cols - shared_by_others[source])
            hint = (
                f"; it has {', '.join(unique[:3])} that no other adapter does — "
                f"likely the same column under a different name"
                if unique else ""
            )
            out.append(
                Finding(
                    ERROR,
                    source,
                    "adapter-column-drift",
                    f"`{source}_erp_bi_{concept}` is missing {len(missing)} column(s) that "
                    f"{len(sources) - 1} other adapter(s) supply: {', '.join(missing[:6])}"
                    + (f" (+{len(missing) - 6} more)" if len(missing) > 6 else "")
                    + hint,
                    f"models/staging/{source}/{source}_erp_bi_{concept}.sql",
                    subject=f"{source}_erp_bi_{concept}",
                )
            )
    return out


def _connector_of_node(node: Dict[str, Any]) -> Optional[str]:
    for tag in node.get("tags", []) or []:
        if tag not in LAYER_TAGS:
            return tag
    return None


# ---------------------------------------------------------------------------------------
# File-backed checks (no manifest, no warehouse)
# ---------------------------------------------------------------------------------------


def _package_dir(conv: Conventions, connector: str) -> Optional[Path]:
    """The connector's dbt package directory, when the project uses the split layout.

    Two layouts are first-class: the monolith keeps a connector under
    `models/staging/<connector>` (+ sibling `<connector>_bi/` dirs); the package layout
    gives it `packages/<connector>/` with its own dbt_project.yml and models tree. The
    checker reads whichever the connector actually has, so the same gate holds before,
    during, and after a migration — a gate that only works on one layout goes silent
    exactly when the moves happen, which is when drift is most likely.
    """
    pkg = conv.project / "packages" / connector
    return pkg if (pkg / "dbt_project.yml").exists() else None


def _staging_dir(conv: Conventions, connector: str) -> Path:
    pkg = _package_dir(conv, connector)
    if pkg is not None:
        return pkg / "models" / "staging"
    return conv.models / "staging" / connector


def staging_dirs(conv: Conventions) -> List[str]:
    names: Set[str] = set()
    staging = conv.models / "staging"
    if staging.is_dir():
        names |= {
            d.name for d in staging.iterdir() if d.is_dir() and any(d.glob("*.sql"))
        }
    packages = conv.project / "packages"
    if packages.is_dir():
        names |= {
            d.name
            for d in packages.iterdir()
            if (d / "dbt_project.yml").exists() and any((d / "models").rglob("*.sql"))
        }
    return sorted(names)


def registry_connectors(conv: Conventions) -> Optional[List[str]]:
    """The connectors the project itself declares, parsed out of the registry macro.

    Not every staging subdirectory is a connector. `staging/erp` holds the *unified* layer
    — models that union the other connectors' adapters — so checking it as a source system
    reports a missing `sources:` block that is correct by design, plus a naming complaint
    against every one of its 27 models. The registry is the project's own answer to "which
    connectors exist", so it is what decides.

    A text parse, deliberately: the alternative is booting dbt, which needs a profile CI
    does not have. Mirrors `tests/test_enhanza_connector_registry.py`.
    """
    if not conv.registry_macro or not conv.registry_macro.exists():
        return None
    text = conv.registry_macro.read_text(encoding="utf-8")
    marker = f"'{conv.registry_key}': {{"
    if marker not in text:
        return None
    body = text[text.index(marker) + len(marker):]
    depth = 1
    for i, ch in enumerate(body):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                body = body[:i]
                break
    return sorted(set(re.findall(r"^\s*'([a-z_0-9]+)':\s*\{$", body, re.MULTILINE)))


def unified_layer_dirs(conv: Conventions) -> Set[str]:
    """Staging subdirectories the project tags as the unified layer rather than a source."""
    text = (conv.project / "dbt_project.yml").read_text(encoding="utf-8")
    out: Set[str] = set()
    current: Optional[str] = None
    for line in text.splitlines():
        # 4 spaces when the layer sits directly under the project key (models/erp in the
        # package layout), 6 when nested under a staging: block (the monolith). Both are
        # the same declaration.
        heading = re.match(r"^ {4,6}([a-z_0-9]+):\s*$", line)
        if heading:
            current = heading.group(1)
            continue
        if current and "+tags:" in line and "unified" in line:
            out.add(current)
            current = None
    return out


def _model_files(conv: Conventions, connector: str) -> List[Path]:
    """Every .sql file that belongs to a connector, across all its layers."""
    pkg = _package_dir(conv, connector)
    if pkg is not None:
        return sorted((pkg / "models").rglob("*.sql"))
    files: List[Path] = []
    staging = conv.models / "staging" / connector
    if staging.is_dir():
        files.extend(sorted(staging.glob("*.sql")))
    for sibling in sorted(conv.models.iterdir()):
        if not sibling.is_dir() or sibling.name == "staging":
            continue
        if sibling.name == connector or sibling.name.startswith(f"{connector}_"):
            files.extend(sorted(sibling.rglob("*.sql")))
    return files


def check_source_columns(
    manifest: Dict[str, Any], connector: Optional[str] = None
) -> List[Finding]:
    """Staging reading a column its source does not declare.

    Adding a connector has exactly one input nobody can derive: the raw table's column list.
    Every other column in the project is a rename of it. Where a source declares `columns:`,
    that list is a **contract** — a statement of what this project depends on — and a staging
    model reading outside it is one of two defects, both silent today:

      * a typo or a stale column name, which fails only when the warehouse is reached;
      * an undeclared dependency, which means an upstream field can be removed with nothing
        in the repository recording that we were reading it.

    Bootstrap the contracts with
    `dbt_column_memory.py --use-case <slug> --emit-source-columns --write`.

    **A source with no declared columns is skipped, not failed.** Most of a project will have
    no contract the day this check lands, and a gate that goes red on a correct state gets
    switched off inside a week — taking the real failures with it. This becomes meaningful
    per source table as each one gains a contract, which is also the order somebody would
    adopt it in.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import dbt_column_lineage as lineage_mod
    except ImportError:  # pragma: no cover - the module ships beside this one
        return []
    if lineage_mod.sqlglot is None:
        return []

    from _manifest import Manifest  # local import: only the manifest checks need it

    man = Manifest(manifest)
    declared: Dict[str, Tuple[str, str, Set[str]]] = {}
    for node in man.sources.values():
        columns = node.get("columns") or {}
        if not columns:
            continue
        joined = f"{node.get('source_name', '')}{lineage_mod.SOURCE_SEP}{node.get('name', '')}"
        declared[joined] = (
            node.get("source_name", ""),
            node.get("name", ""),
            {str(c) for c in columns},
        )
    if not declared:
        return []

    lineage = lineage_mod.build_lineage(man)
    model_names = {
        n.get("name") for n in man.nodes.values() if n.get("resource_type") == "model"
    }
    connector_of = {
        n.get("name"): (n.get("tags") or [None])[0] for n in man.nodes.values()
    }

    # `{model: {joined_source: {columns it reads}}}` — one finding per model per source,
    # never one per column, or a renamed source table would produce forty identical rows.
    undeclared: Dict[Tuple[str, str], Set[str]] = {}
    for edge in lineage["edges"]:
        if edge.upstream_model in model_names or not edge.upstream_column:
            continue
        if edge.upstream_column in ("*", "(macro)"):
            continue
        # Symmetric with the emitter: an unqualified reference with several tables in scope
        # binds to each of them, and exactly one is right. That binding is too weak to write
        # a contract from, so it is also too weak to fail one with — blaming `accounts` for
        # a bare `Amount` that five tables could own is the same guess in the other
        # direction. Both sides read `ambiguous` off the same edge.
        if edge.ambiguous:
            continue
        entry = declared.get(edge.upstream_model)
        if entry is None:
            continue
        if edge.upstream_column in entry[2]:
            continue
        undeclared.setdefault((edge.model, edge.upstream_model), set()).add(
            edge.upstream_column
        )

    out: List[Finding] = []
    for (model, joined), columns in sorted(undeclared.items()):
        source, table, _ = declared[joined]
        owner = next(
            (c for c in (connector_of.get(model),) if c and c not in LAYER_TAGS),
            model.split("_")[0],
        )
        if connector and owner != connector:
            continue
        out.append(
            Finding(
                ERROR,
                owner,
                "undeclared-source-column",
                f"`{model}` reads {len(columns)} column(s) that `{source}.{table}` does not "
                f"declare: {', '.join(sorted(columns)[:6])}"
                + (f" (+{len(columns) - 6} more)" if len(columns) > 6 else "")
                + " — add them to the source's `columns:` or fix the reference",
                subject=model,
            )
        )
    return out


def check_dependency_discipline(files: Iterable[Path], connector: str, conv: Conventions) -> List[Finding]:
    """Every model reaches its data through `source()`, `ref()`, or a project macro.

    Rule 13. A hardcoded `database.schema.table` is invisible to lineage, to `--select`,
    and to state comparison, and it is the one defect that makes a model unrepresentable in
    the graph no matter how the graph is built.
    """
    out: List[Finding] = []
    macro_call = re.compile(r"\{\{-?\s*([a-z_][a-z0-9_]*)\s*\(")
    # Root macros plus package-local ones; dbt_packages/ (the installed symlinks) is
    # deliberately not globbed — it would double-count everything under packages/.
    known_macros = {m.stem for m in conv.project.glob("macros/**/*.sql")}
    known_macros |= {m.stem for m in conv.project.glob("packages/*/macros/**/*.sql")}
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        if "{{ ref(" in text or "{{ref(" in text or "{{ source(" in text or "{{source(" in text:
            continue
        # A model whose body is a project macro (erp_union, auto_config) reaches its data
        # through that macro's own ref() calls.
        if any(name in known_macros for name in macro_call.findall(text)):
            continue
        out.append(
            Finding(
                ERROR,
                connector,
                "hardcoded-source",
                "no source(), ref(), or project macro — this model is invisible to lineage",
                _rel(f),
                subject=f.stem,
            )
        )
    return out


def check_naming(files: Iterable[Path], connector: str, conv: Conventions) -> List[Finding]:
    """Staging model names follow the shape the project's other connectors use."""
    out: List[Finding] = []
    staging_dir = _staging_dir(conv, connector)
    for f in files:
        if f.parent != staging_dir:
            continue
        name = f.stem
        if connector not in name:
            out.append(
                Finding(
                    WARN,
                    connector,
                    "naming",
                    f"`{name}` does not contain the connector name; "
                    f"every other connector's staging models do",
                    _rel(f),
                    subject=name,
                )
            )
            continue
        # Match the whole shape the project uses, not just its tail. Testing
        # `endswith(staging_suffix)` is vacuous where the convention carries the connector in
        # a *prefix* — `stg_shopify__orders` has no suffix at all, so every model in a
        # prefix-style project failed a check it was already satisfying.
        if _matches_staging(name, connector, conv) or (
            conv.adapter_infix and conv.adapter_infix in name
        ):
            continue
        example = conv.staging_model(connector, "<table>")
        adapter = (
            f" nor an adapter (`{conv.adapter_model(connector, '<concept>')}`)"
            if conv.adapter_infix
            else ""
        )
        out.append(
            Finding(
                WARN,
                connector,
                "naming",
                f"`{name}` is not a staging model (`{example}`){adapter}",
                _rel(f),
                subject=name,
            )
        )
    return out


def _matches_staging(name: str, connector: str, conv: Conventions) -> bool:
    """Does `name` have a shape this project's staging layers actually use?

    Two shapes are accepted. The exact `staging_model()` shape covers the convention the
    scaffolder learned (`fortnox_bi_dim_customers_staging`, or prefix-style
    `stg_shopify__orders`). The second generalises the *layer infix*: enhanza builds
    `fortnox_flat_*_staging` and `fortnox_reports_*_staging` beside the `_bi_` layer, and a
    check that recognises only the busiest layer reported 21 correct models the day it
    learned to read shapes precisely. The layer vocabulary is `LAYER_TAGS` — the same set
    the registry parser uses — so a new layer is added once, not twice.

    Deliberately not accepted: a layer infix with no staging suffix where the convention has
    one (`fortnox_base_v2_invoices`). That is the documented open naming finding, and
    loosening the shape until it disappears would be deleting the finding, not resolving it.
    """
    pattern = re.escape(conv.staging_model(connector, "\x00")).replace("\x00", r".+")
    if re.fullmatch(pattern, name) is not None:
        return True
    if conv.staging_suffix and name.endswith(conv.staging_suffix):
        layers = "|".join(sorted(LAYER_TAGS))
        generalised = (
            re.escape(conv.model_prefix)
            + re.escape(connector)
            + f"_(?:{layers})_.+"
            + re.escape(conv.staging_suffix)
        )
        return re.fullmatch(generalised, name) is not None
    return False


def check_test_syntax(conv: Conventions, connector: str) -> List[Finding]:
    """Generic-test syntax that the project's pinned dbt version cannot parse."""
    out: List[Finding] = []
    project_yml = (conv.project / "dbt_project.yml").read_text(encoding="utf-8")
    match = re.search(r"require-dbt-version:\s*\[([^\]]+)\]", project_yml)
    upper = None
    if match:
        cap = re.search(r'["\']<\s*([0-9.]+)["\']', match.group(1))
        if cap:
            upper = cap.group(1)
    # `arguments:` requires >= 1.10. A ceiling below 2.0 does not guarantee 1.10 is
    # installed, so this is reported whenever the project has not explicitly floored there.
    floor = re.search(r'["\']>=\s*([0-9.]+)["\']', match.group(1)) if match else None
    floored_at_110 = bool(floor and tuple(int(x) for x in floor.group(1).split(".")[:2]) >= (1, 10))

    for yml in _connector_ymls(conv, connector):
        text = yml.read_text(encoding="utf-8")
        hits = [m for m in DBT_110_TEST_SYNTAX.finditer(text)]
        if hits and not floored_at_110:
            line = text[: hits[0].start()].count("\n") + 1
            out.append(
                Finding(
                    ERROR,
                    connector,
                    "test-syntax",
                    f"{len(hits)} generic test(s) use the dbt >=1.10 `arguments:` nesting, but "
                    f"require-dbt-version floors at {floor.group(1) if floor else '?'}"
                    + (f" (ceiling <{upper})" if upper else "")
                    + " — dbt parse fails for the whole project",
                    f"{_rel(yml)}:{line}",
                    subject=f"{_rel(yml)}:{line}",
                )
            )
    return out


def check_schema_yml(conv: Conventions, connector: str, files: List[Path]) -> List[Finding]:
    """A connector's models are described and its keys are tested."""
    out: List[Finding] = []
    ymls = _connector_ymls(conv, connector)
    if not ymls:
        out.append(
            Finding(
                ERROR,
                connector,
                "no-schema-yml",
                "no schema.yml anywhere in this connector's directories — no descriptions, "
                "no tests, nothing for the graph to read",
                _rel(_staging_dir(conv, connector)),
                subject=connector,
            )
        )
        return out

    described: Set[str] = set()
    for yml in ymls:
        described |= set(re.findall(r"^\s*-\s*name:\s*([a-zA-Z0-9_]+)\s*$", yml.read_text(encoding="utf-8"), re.MULTILINE))
    undescribed = sorted({f.stem for f in files} - described)
    if undescribed:
        shown = ", ".join(undescribed[:5])
        more = f" (+{len(undescribed) - 5} more)" if len(undescribed) > 5 else ""
        out.append(
            Finding(
                WARN,
                connector,
                "undocumented-model",
                f"{len(undescribed)}/{len(files)} models have no schema.yml entry: {shown}{more}",
                subject=",".join(undescribed[:5]),
            )
        )
    return out


ENABLE_VAR_RE = re.compile(r"^\s*(is_[a-z0-9_]+_enabled):", re.MULTILINE)


def check_enable_var(conv: Conventions, connector: str) -> List[Finding]:
    """Every connector the project gates has a declared default.

    Conditional on the project gating anything at all. Connector enable vars are how a
    multi-tenant project turns sources on per customer; a project with a single source and
    no tenancy has no use for one, and demanding it there reports a missing feature as a
    defect. What is a defect is a project that gates its *other* connectors and forgot this
    one — the var then defaults to false, the connector silently produces nothing, and the
    build is green.
    """
    project_yml = (conv.project / "dbt_project.yml").read_text(encoding="utf-8")
    var = conv.var_for(connector)
    declared = set(ENABLE_VAR_RE.findall(project_yml))
    if not declared:
        return []
    if var not in declared:
        return [
            Finding(
                ERROR,
                connector,
                "no-enable-var",
                f"`{var}` has no declared default in dbt_project.yml vars, but "
                f"{len(declared)} other connector(s) declare theirs; a --vars typo would "
                f"silently disable the connector instead of failing",
                subject=var,
            )
        ]
    return []


def check_sources_declared(conv: Conventions, connector: str) -> List[Finding]:
    """The connector's raw tables enter through `sources:` with a freshness SLA."""
    out: List[Finding] = []
    candidates = sorted(conv.models.glob("**/*sources.yml")) + sorted(
        conv.project.glob("packages/*/models/**/*sources.yml")
    )
    text = "\n".join(f.read_text(encoding="utf-8") for f in candidates)
    if not re.search(rf"^\s*-\s*name:\s*{re.escape(connector)}\w*\s*$", text, re.MULTILINE):
        out.append(
            Finding(
                ERROR,
                connector,
                "no-source-block",
                f"no `- name: {connector}...` block in any sources.yml — rule 13",
                subject=connector,
            )
        )
        return out
    block = _source_block(text, connector)
    if block and "loaded_at_field" not in block:
        out.append(
            Finding(WARN, connector, "no-freshness", "source block has no `loaded_at_field`; freshness is an undocumented SLA", subject=connector)
        )
    elif block and "freshness" not in block:
        out.append(
            Finding(WARN, connector, "no-freshness", "source block has no `freshness:` thresholds", subject=connector)
        )
    return out


def _source_block(text: str, connector: str) -> str:
    match = re.search(rf"^(\s*)-\s*name:\s*{re.escape(connector)}\w*\s*$", text, re.MULTILINE)
    if not match:
        return ""
    indent = len(match.group(1))
    rest = text[match.end():].splitlines()
    body: List[str] = []
    for line in rest:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent and line.lstrip().startswith("- name:"):
            break
        body.append(line)
    return "\n".join(body)


def _connector_ymls(conv: Conventions, connector: str) -> List[Path]:
    pkg = _package_dir(conv, connector)
    if pkg is not None:
        out = sorted((pkg / "models").rglob("*.yml"))
        return [y for y in out if y.name != "sources.yml"]
    out = []
    staging = conv.models / "staging" / connector
    if staging.is_dir():
        out.extend(sorted(staging.glob("*.yml")))
    for sibling in sorted(conv.models.iterdir()):
        if sibling.is_dir() and (sibling.name == connector or sibling.name.startswith(f"{connector}_")):
            out.extend(sorted(sibling.rglob("*.yml")))
    return [y for y in out if y.name != "sources.yml"]


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return p.as_posix()


def _common_prefix(paths: List[str]) -> str:
    """The longest shared directory prefix, ending in `/`, or "" when there is none.

    Cut on a path separator, never mid-segment: `models/staging/erp` and
    `models/staging/erpx` share the characters `models/staging/erp` but only the directory
    `models/staging/`, and stripping the former leaves a row that reads as a relative path
    and is not one.
    """
    usable = [p for p in paths if "/" in p]
    if len(usable) < 2:
        return ""
    segments = [p.split("/")[:-1] for p in usable]
    shared: List[str] = []
    for parts in zip(*segments):
        if len(set(parts)) != 1:
            break
        shared.append(parts[0])
    return "/".join(shared) + "/" if shared else ""


# ---------------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------------


def skipped_checks(manifest_path: Optional[str]) -> List[str]:
    """Checks that could not run, so a clean report never overstates what was verified.

    Silence here is the failure mode that matters: `0 error(s)` reads as "checked and fine"
    whether the adapter-column comparison ran or was skipped for a missing parser. Naming
    the gap is the difference between a clean result and an uninformed one.
    """
    out: List[str] = []
    if not manifest_path:
        out.append("alias-collision, undeclared-schema, adapter-column-drift (need --manifest)")
        return out
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import dbt_column_lineage as lineage_mod
        if lineage_mod.sqlglot is None:
            out.append("adapter-column-drift (needs sqlglot: pip install sqlglot)")
    except ImportError:  # pragma: no cover - the module ships beside this one
        out.append("adapter-column-drift (scripts/dbt_column_lineage.py not importable)")
    return out


def run(use_case_slug: str, connector: Optional[str], manifest_path: Optional[str]) -> List[Finding]:
    use_case = find_use_case(use_case_slug)
    conv = detect(use_case)
    manifest = load_manifest(manifest_path)

    dirs = staging_dirs(conv)
    registry = registry_connectors(conv)
    unified = unified_layer_dirs(conv)
    known = registry if registry is not None else dirs

    if connector and connector not in dirs:
        raise SystemExit(
            f"connector '{connector}' has no staging directory under "
            f"{_rel(conv.models / 'staging')}.\n"
            f"Known: {', '.join(known) or '(none)'}"
        )

    findings: List[Finding] = []

    # A staging directory that is neither registered nor the unified layer is the failure
    # the registry exists to prevent — it builds, it ships, and `erp_union()` never sees it.
    if registry is not None and not connector:
        for name in dirs:
            if name in registry or name in unified:
                continue
            findings.append(
                Finding(
                    ERROR,
                    name,
                    "unregistered-connector",
                    f"`{name}` has models in staging/ but no entry in "
                    f"{conv.registry_key}; nothing downstream will union it",
                    _rel(conv.registry_macro) if conv.registry_macro else "",
                    subject=name,
                )
            )

    targets = [connector] if connector else [d for d in dirs if d in known]
    for name in targets:
        files = _model_files(conv, name)
        findings += check_dependency_discipline(files, name, conv)
        findings += check_naming(files, name, conv)
        findings += check_test_syntax(conv, name)
        findings += check_schema_yml(conv, name, files)
        findings += check_enable_var(conv, name)
        findings += check_sources_declared(conv, name)

    # Cross-model checks. These compare against every model in the project, which is the
    # only way to answer "does this new connector conflict with what is already here" — a
    # question the per-connector checks above cannot reach, because they only ever look at
    # one connector's own files. They run for a scoped invocation too, narrowed to
    # collisions the named connector participates in rather than skipped outright.
    if manifest:
        findings += check_alias_collisions(manifest, connector)
        findings += check_undeclared_schema(manifest, conv, connector)
        findings += check_adapter_column_drift(manifest, connector)
        findings += check_source_columns(manifest, connector)

    return findings


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Check connector dbt models against the project's existing conventions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--use-case", default="enhanza-analytics", help="use-case slug")
    p.add_argument("--connector", help="check one connector (default: all)")
    p.add_argument("--manifest", help="manifest.json — enables alias and schema checks")
    p.add_argument("--check", action="store_true", help="exit 1 if any error-severity finding")
    p.add_argument("--warn-as-error", action="store_true", help="treat warnings as errors")
    p.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="text for humans; json for machines — pipe it through "
             "rust/toon/bin/graph_to_toon for TOON (the PreToolUse hook does this "
             "automatically for agent-run invocations)",
    )
    args = p.parse_args(argv)

    findings = run(args.use_case, args.connector, args.manifest)
    errors = sum(1 for f in findings if f.severity == ERROR)
    warns = len(findings) - errors
    failed = args.check and (errors or (args.warn_as_error and warns))

    use_case = find_use_case(args.use_case)
    conv = detect(use_case)
    registry = registry_connectors(conv)
    scope = args.connector or (
        f"{len(registry)} registered connectors" if registry is not None
        else f"{len(staging_dirs(conv))} staging directories"
    )

    if args.format == "json":
        # One uniform record list plus a `checks` lookup, so a repeated message template
        # costs once rather than once per finding. graph_to_toon turns this into a header
        # row plus one comma-separated line per finding.
        used = sorted({f.check for f in findings})
        records = [f.as_record() for f in sorted(
            findings, key=lambda x: (x.severity != ERROR, x.connector, x.check)
        )]
        # Every `where` shares the same deep prefix — 61 characters of
        # `skill-packs/.../dbt_project/` on every row. Declaring it once is the same move
        # TOON makes for field names, and on a 28-finding run it is a third of the payload.
        root = _common_prefix([r["where"] for r in records if r["where"]])
        if root:
            for record in records:
                if record["where"].startswith(root):
                    record["where"] = record["where"][len(root):]
        print(json.dumps({
            "use_case": args.use_case,
            "reference_connector": conv.reference,
            "scope": scope,
            "manifest_backed": bool(args.manifest),
            "skipped_checks": skipped_checks(args.manifest),
            "errors": errors,
            "warnings": warns,
            "root": root,
            "checks": [{"check": c, "detail": CHECK_DETAIL.get(c, "")} for c in used],
            "findings": records,
        }, ensure_ascii=False))
        return 1 if failed else 0

    print(f"use-case:    {args.use_case}")
    print(f"conventions: learned from `{conv.reference or '(none)'}`  "
          f"staging=`{conv.staging_model('<src>', '<table>')}`  "
          f"adapter=`{conv.adapter_model('<src>', '<concept>') if conv.adapter_infix else '(none)'}`")
    print(f"scope:       {scope}")
    for note in skipped_checks(args.manifest):
        print(f"skipped:     {note}")
    print()

    if not findings:
        print("No drift. Every connector matches the project's conventions.")
        return 0

    by_connector: Dict[str, List[Finding]] = {}
    for f in findings:
        by_connector.setdefault(f.connector, []).append(f)

    for name in sorted(by_connector):
        print(f"{name}")
        for f in sorted(by_connector[name], key=lambda x: (x.severity != ERROR, x.check)):
            print(f.render())
        print()

    print(f"{errors} error(s), {warns} warning(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
