#!/usr/bin/env python3
"""Ontology-aligned column memory for a dbt Core project.

`scripts/dbt_column_lineage.py` answers "which upstream column fed this one" for one model
at a time, out of `manifest.json`. That is the primitive. It is not yet something an agent
can use, for three reasons, and this module exists to fix each of them:

**1. It goes stale the moment somebody edits a `.sql` file.** `raw_code` is a snapshot taken
by the last `dbt parse`. Every dbt manifest node also carries
`checksum: {name: "sha256", checksum: "<hex>"}`, and that value is *exactly*
`sha256(file_bytes.strip()).hexdigest()` — dbt's `FileHash.from_contents` strips before
hashing. Verified here against the real project: **359 of 359 models match, zero
mismatches.** So which models changed since the parse is knowable in about twenty
milliseconds, with no dbt, no warehouse, and no profile. A model whose hash moved is
re-parsed from the file on disk instead of from `raw_code`, which is what makes this current
rather than merely recent.

**2. It re-parses the whole project every time.** 223 models through sqlglot is tens of
seconds — fine for a nightly job, far too slow for something that runs when a file is saved.
Per-model results are therefore cached under `.dbt-column-cache/` keyed by the model's own
content hash, so an edit to one model re-parses one model. That is the difference between
"regenerated on change" as a design and as a sentence in a runbook.

**3. It stops after one hop.** `erp_bi_dim_articles.Active <- fortnox_erp_bi_dim_articles.Active`
is true and unhelpful; the question a connector author actually asks is which *raw API field*
becomes that conformed column, four passthrough models down the chain. `resolve_to_source()`
walks the chain to the source table, following `select *` passthroughs and union branches,
and reports every transform it crossed on the way.

What comes out is two things, deliberately kept apart:

  * `ontology/column-memory.json` — committed. The bounded, ontology-aligned view: the
    column **contract** per conformed concept, the source **bindings** behind it, and the
    **drift** between adapters. Every class and property IRI comes from
    `scripts/ontology_generator.py`; no vocabulary is invented here.
  * `.dbt-column-cache/<slug>.json` — gitignored. The per-model edge cache that makes the
    incremental rebuild possible. Same split as the graphify fragment (committed, 1.1 MB)
    versus the manifest (not committed, 3.0 MB), and for the same reason.

## Why the shape is what it is

The contract/binding split is taken from the Fabric IQ ontology format documented in
PackMaaan/Ontology-Playground (`docs/TODO-full-ontology-format.md`), which separates an
`EntityType` — the conceptual class and its properties — from a `DataBinding` that maps each
property to a physical `table` + `columnMappings` + `keyMappings`. That is precisely the
split this repository already has and had no name for: `ontology/connectors/*.ttl` asserts
the classes, and nothing asserted the column-level binding underneath them. `conn:Mapping`
in the existing Turtle is a one-hop binding for the 92 columns that happen to match a known
property rule; a contract plus a resolved binding is the same idea carried to the whole
adapter surface and to the raw source column.

The contract half is the **topology** at column granularity. `topology/concept-coverage.ttl`
says which connectors supply `dim_articles`. It cannot say that five of them call a column
`Active` and the sixth calls it `isActive` — and `erp_union()` stacks one adapter per
enabled source, so that disagreement compiles cleanly for every tenant with one connector
and breaks for the first tenant with two. Coverage is the wrong granularity to catch it.

## AgentMemory

`--remember` mirrors this to AgentMemory, and mirrors **contracts, drift, and a locator** —
not the edge set. Three constraints force that, all of them stated in `CLAUDE.md`:

  * Memory is for what the repository cannot hold. Column edges are structure, regenerable
    from the manifest in seconds, and `CLAUDE.md` says structure goes in the graph.
  * `:3111` is a single global store with **no per-request namespace**. Six thousand
    mechanical records do not sit beside the decisions; they bury them.
  * Recall is **BM25, not embeddings**. A record is findable only by its own words, so each
    one is phrased with the terms the question would use — the concept name, the connector
    key, the column name, the word "contract" or "drift".

What survives that filter is what a future session cannot cheaply re-derive: the conformed
column contract a new adapter has to match, and the drift already found. Both are capped and
the cap is reported. `--remember-bindings` adds the resolved source bindings for callers who
want them, also capped.

Usage:
    python3 scripts/dbt_column_memory.py --use-case enhanza-analytics
    python3 scripts/dbt_column_memory.py --use-case enhanza-analytics --write
    python3 scripts/dbt_column_memory.py --use-case enhanza-analytics --check    # CI gate
    python3 scripts/dbt_column_memory.py --use-case enhanza-analytics --remember
    python3 scripts/dbt_column_memory.py --use-case enhanza-analytics --concept dim_articles
    python3 scripts/dbt_column_memory.py --use-case enhanza-analytics --stale-only
    python3 scripts/dbt_column_memory.py --use-case enhanza-analytics --format json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _manifest import Manifest, die  # noqa: E402
import _paths  # noqa: E402
import dbt_column_lineage as lineage_mod  # noqa: E402
import ontology_generator as og  # noqa: E402
from _paths import REPO, default_manifest  # noqa: E402,F401


def use_case_dir(slug: str) -> Path:
    """`_paths.require_use_case_dir` bound to this module's REPO; absence exits 2."""
    return _paths.require_use_case_dir(slug, REPO)

ARTIFACT_NAME = "column-memory.json"
CACHE_DIR = REPO / ".dbt-column-cache"

# How deep to follow one column back through the model chain. enhanza-analytics' longest
# real chain is source -> staging -> bi -> erp_bi adapter -> union -> mart, which is five;
# twelve leaves room for a project that layers more without letting a cycle spin.
MAX_CHAIN = 12

# Caps. Each is reported when it bites, because a truncated list that does not say so reads
# as a complete one — the failure mode `CLAUDE.md` calls out as "a format cannot rescue an
# unbounded dump".
MAX_MEMORY_CONTRACTS = 60
MAX_MEMORY_DRIFT = 40
MAX_MEMORY_BINDINGS = 120

AGENTMEMORY_URL = os.environ.get("AGENTMEMORY_URL", "http://127.0.0.1:3111")

# The `<source>_erp_bi_<concept>` adapter naming this project uses. Read from
# connector_alignment_check's own detection where possible; this is the fallback shape.
_RE_ADAPTER = re.compile(r"^([a-z0-9_]+?)_erp_bi_(.+)$")


# =======================================================================================
# Freshness — the manifest is a registry, the .sql on disk is normative
# =======================================================================================


def file_hash(path: Path) -> str:
    """dbt's own content hash for a model file.

    `dbt.contracts.files.FileHash.from_contents` is
    `sha256(contents.encode("utf-8").strip()).hexdigest()`. The `.strip()` is easy to miss
    and is the whole difference between 359/359 matching and 61/97 matching — without it a
    trailing newline reads as an edit, every model looks changed, and the incremental
    rebuild degrades to a full one while still claiming to be incremental.
    """
    return hashlib.sha256(path.read_bytes().strip()).hexdigest()


def package_roots(project_root: Path) -> Dict[str, Path]:
    """dbt package name -> the directory it lives in.

    `original_file_path` is relative to the *package* root, not the project root, so a
    manifest holding 359 models over 11 packages resolves to 97 real paths and 262 misses
    unless the packages are mapped first.

    The map is built by reading each candidate's own `dbt_project.yml`, never by transforming
    the directory name. enhanza-analytics has `packages/favrit/` declaring
    `name: enhanza_favrit`, so a prefix rule happens to work here — and would break on the
    first package whose directory and project name diverge, silently, by resolving to
    nothing and reporting every one of its models as deleted.
    """
    roots: Dict[str, Path] = {}
    for parent in ("packages", "dbt_packages"):
        base = project_root / parent
        if not base.is_dir():
            continue
        for candidate in sorted(base.iterdir()):
            config = candidate / "dbt_project.yml"
            if not config.is_file():
                continue
            match = re.search(
                r"^\s*name:\s*['\"]?([A-Za-z0-9_]+)", config.read_text(encoding="utf-8"), re.M
            )
            if match:
                roots.setdefault(match.group(1), candidate)
    return roots


@dataclass
class ModelFile:
    """One dbt model, its manifest record, and the file that record was taken from."""

    name: str
    unique_id: str
    package: str
    path: Optional[Path]
    manifest_hash: str
    disk_hash: Optional[str]

    @property
    def status(self) -> str:
        if self.path is None or self.disk_hash is None:
            return "missing"
        return "fresh" if self.disk_hash == self.manifest_hash else "changed"

    @property
    def content_hash(self) -> str:
        """What the cache is keyed on: whatever the current truth is."""
        return self.disk_hash or self.manifest_hash


@dataclass
class Freshness:
    models: List[ModelFile]
    untracked: List[str] = field(default_factory=list)

    def by_status(self, status: str) -> List[ModelFile]:
        return [m for m in self.models if m.status == status]

    @property
    def digest(self) -> str:
        """One hash over the whole model surface — the artifact's staleness key.

        Includes the untracked `.sql` files by path, so a *new* model that no manifest knows
        about still moves the digest. Otherwise adding a model would leave the store
        reporting itself current while missing the thing that was just added.
        """
        h = hashlib.sha256()
        for model in sorted(self.models, key=lambda m: m.unique_id):
            h.update(model.unique_id.encode())
            h.update(model.content_hash.encode())
        for path in sorted(self.untracked):
            h.update(b"untracked:")
            h.update(path.encode())
        return h.hexdigest()

    def as_record(self) -> Dict[str, Any]:
        return {
            "digest": self.digest,
            "models": len(self.models),
            "fresh": len(self.by_status("fresh")),
            "changed": len(self.by_status("changed")),
            "missing": len(self.by_status("missing")),
            "untracked_sql": len(self.untracked),
        }


def freshness(man: Manifest, project_root: Path) -> Freshness:
    """Compare every model in the manifest against the file it was parsed from."""
    roots = package_roots(project_root)
    project_name = man.project_name
    models: List[ModelFile] = []
    resolved: Set[Path] = set()

    for uid, node in man.nodes.items():
        if node.get("resource_type") != "model":
            continue
        package = node.get("package_name") or ""
        base = project_root if package == project_name else roots.get(package)
        path = (base / node["original_file_path"]) if base else None
        if path is not None and path.is_file():
            resolved.add(path.resolve())
            disk = file_hash(path)
        else:
            path, disk = (path if path and path.exists() else None), None
        models.append(
            ModelFile(
                name=node.get("name", ""),
                unique_id=uid,
                package=package,
                path=path,
                manifest_hash=(node.get("checksum") or {}).get("checksum", ""),
                disk_hash=disk,
            )
        )

    # A `.sql` on disk that no manifest node claims. Either the model is new since the last
    # parse, or it is disabled by a var — indistinguishable from here, so it is reported as
    # untracked rather than asserted to be either.
    untracked: List[str] = []
    search_roots = [project_root / "models"] + [r / "models" for r in roots.values()]
    for root in search_roots:
        if not root.is_dir():
            continue
        for sql in sorted(root.rglob("*.sql")):
            if sql.resolve() not in resolved:
                untracked.append(_rel(sql))
    return Freshness(models=models, untracked=untracked)


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


# =======================================================================================
# Per-model lineage, cached on the model's content hash
# =======================================================================================


@dataclass
class ModelLineage:
    model: str
    status: str  # parsed | macro | failed | no_parser
    edges: List[Tuple[str, str, str, str]]  # (column, upstream_model, upstream_column, kind)
    error: str = ""

    def as_record(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"status": self.status, "edges": [list(e) for e in self.edges]}
        if self.error:
            out["error"] = self.error
        return out

    @classmethod
    def from_record(cls, model: str, record: Dict[str, Any]) -> "ModelLineage":
        return cls(
            model=model,
            status=record.get("status", "failed"),
            edges=[tuple(e) for e in record.get("edges", [])],  # type: ignore[misc]
            error=record.get("error", ""),
        )


class LineageCache:
    """Per-model lineage keyed by the model's content hash.

    Gitignored on purpose. It is derivable, it is large, and it churns on every model edit —
    the same three properties that keep `manifest.json` out of the repository while the
    graphify fragment stays in it.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: Dict[str, Dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("version") == 1:
                    self._data = payload.get("models") or {}
            except (json.JSONDecodeError, OSError):
                # A corrupt cache is a slow run, never a wrong answer: drop it and re-parse.
                self._data = {}

    def get(self, model: str, content_hash: str) -> Optional[ModelLineage]:
        record = self._data.get(f"{model}:{content_hash}")
        if record is None:
            self.misses += 1
            return None
        self.hits += 1
        return ModelLineage.from_record(model, record)

    def put(self, model: str, content_hash: str, lineage: ModelLineage) -> None:
        self._data[f"{model}:{content_hash}"] = lineage.as_record()

    def save(self, keep: Iterable[str]) -> None:
        """Write the cache, dropping entries for hashes no model carries any more."""
        live = set(keep)
        self._data = {k: v for k, v in self._data.items() if k in live}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"version": 1, "models": self._data}, sort_keys=True), encoding="utf-8"
        )


def read_current_sql(model: ModelFile, node: Dict[str, Any]) -> str:
    """The model body as it is *now*, not as the last parse saw it.

    This is the point of the whole freshness pass. A model edited since `dbt parse` has a
    `raw_code` that describes the previous version of the file, and lineage derived from it
    is confidently wrong rather than merely absent — the failure mode that is hardest to
    notice, because everything downstream still renders.
    """
    if model.status == "changed" and model.path is not None:
        try:
            return model.path.read_text(encoding="utf-8")
        except OSError:
            pass
    return node.get("raw_code") or ""


def model_lineage(
    model: ModelFile,
    node: Dict[str, Any],
    by_name: Dict[str, Dict[str, Any]],
    dialect: str,
) -> ModelLineage:
    """Lineage for one model, from whichever body is current."""
    raw = read_current_sql(model, node)
    stripped = lineage_mod.strip_jinja(raw)

    if not lineage_mod.has_literal_select(stripped):
        # Macro-only. `structural_lineage` resolves the two macros whose contract is
        # definitional and returns nothing for the rest — which is reported, not guessed.
        structural = lineage_mod.structural_lineage({**node, "raw_code": raw}, by_name)
        return ModelLineage(
            model.name,
            "macro",
            [(e.column, e.upstream_model, e.upstream_column, e.kind) for e in structural],
        )

    if lineage_mod.sqlglot is None:
        return ModelLineage(model.name, "no_parser", [], "sqlglot not installed")

    edges, error = lineage_mod.lineage_from_sql(model.name, raw, dialect)
    if error:
        return ModelLineage(model.name, "failed", [], error)
    return ModelLineage(
        model.name,
        "parsed",
        [(e.column, e.upstream_model, e.upstream_column, e.kind) for e in edges],
    )


# =======================================================================================
# Transitive resolution to the source column
# =======================================================================================


class ChainResolver:
    """Follow a conformed column back to the raw source column that produced it.

    One hop is what `dbt_column_lineage` gives and is not the question anybody asks. In this
    project a conformed column crosses four models before it reaches an API field, and three
    of those hops are `select *` passthroughs generated by `auto_config`, which carry no
    per-column edge at all — only a `("*", parent, "*", "passthrough")`. A resolver that
    followed named edges only would stop at the first passthrough and report the chain as
    ending inside the warehouse.

    Terminal means "not a model": a `ref()` chain ends at an identifier that
    `strip_jinja` produced from `{{ source(a, b) }}`, which is `a__b`. That name is in no
    model registry, and reaching it is the success condition, not a failure.
    """

    def __init__(self, lineages: Dict[str, ModelLineage], model_names: Set[str]) -> None:
        self.model_names = model_names
        self.named: Dict[Tuple[str, str], List[Tuple[str, str, str]]] = {}
        self.stars: Dict[str, List[Tuple[str, str]]] = {}
        for name, lineage in lineages.items():
            for column, up_model, up_column, kind in lineage.edges:
                if column == "*":
                    self.stars.setdefault(name, []).append((up_model, kind))
                elif column != "(macro)" and up_model:
                    self.named.setdefault((name, column), []).append((up_model, up_column, kind))
        self._memo: Dict[Tuple[str, str], List[Tuple[str, str, Tuple[str, ...]]]] = {}

    def resolve(self, model: str, column: str) -> List[Tuple[str, str, Tuple[str, ...]]]:
        """(terminal_model, terminal_column, transforms crossed) for one column."""
        return self._resolve(model, column, (), set(), 0)

    def _resolve(
        self,
        model: str,
        column: str,
        kinds: Tuple[str, ...],
        seen: Set[Tuple[str, str]],
        depth: int,
    ) -> List[Tuple[str, str, Tuple[str, ...]]]:
        key = (model, column)
        if depth >= MAX_CHAIN or key in seen:
            return [(model, column, kinds)]
        if depth == 0 and key in self._memo:
            return self._memo[key]

        seen = seen | {key}
        out: List[Tuple[str, str, Tuple[str, ...]]] = []

        for up_model, up_column, kind in self.named.get(key, []):
            if up_model in self.model_names:
                out.extend(self._resolve(up_model, up_column, kinds + (kind,), seen, depth + 1))
            else:
                out.append((up_model, up_column, kinds + (kind,)))

        if not out:
            # No named edge: the column either passes through a `select *` / union branch
            # keeping its name, or this is where the chain ends.
            for up_model, kind in self.stars.get(model, []):
                if up_model in self.model_names:
                    out.extend(self._resolve(up_model, column, kinds + (kind,), seen, depth + 1))
                else:
                    out.append((up_model, column, kinds + (kind,)))

        if not out:
            out = [(model, column, kinds)]

        result = sorted(set(out))
        if depth == 0:
            self._memo[key] = result
        return result


def classify(kinds: Sequence[str]) -> str:
    """One word for a whole chain.

    Order of precedence, strongest claim last-resort: anything unresolved poisons the chain;
    a derivation anywhere means the value was transformed; a rename anywhere means the name
    moved. Only a chain of pure passthroughs and direct hops is `direct`, and saying so is
    the only classification a reader can act on without re-reading the SQL.
    """
    kinds = list(kinds)
    if not kinds or "unresolved" in kinds:
        return "unresolved"
    if "derived" in kinds:
        return "derived"
    if "renamed" in kinds:
        return "renamed"
    if "union" in kinds:
        return "union"
    if all(k in ("passthrough", "direct") for k in kinds):
        return "direct"
    return "derived"


# =======================================================================================
# The ontology-aligned store
# =======================================================================================


@dataclass
class ColumnStore:
    slug: str
    config: Any
    freshness: Freshness
    lineages: Dict[str, ModelLineage]
    contracts: List[Dict[str, Any]]
    bindings: List[Dict[str, Any]]
    drift: List[Dict[str, Any]]
    provenance: Dict[str, Any]
    # Facts about this run, deliberately kept out of `as_artifact()`. See `build_store`.
    run: Dict[str, Any] = field(default_factory=dict)

    def as_artifact(self) -> Dict[str, Any]:
        return {
            "use_case": self.slug,
            "title": self.config.title,
            "generated_by": "scripts/dbt_column_memory.py",
            "normative_source": (
                "the .sql files on disk; manifest.json supplies the model registry only"
            ),
            "prefixes": {
                "erp": self.config.erp,
                "crm": self.config.crm,
                "conn": self.config.conn,
                "topo": self.config.topo,
            },
            "mcp_tools": [
                {
                    "tool": "column_contract",
                    "backed_by": "contracts",
                    "answers": "The columns every adapter for a conformed concept must carry.",
                },
                {
                    "tool": "resolve_source_column",
                    "backed_by": "bindings",
                    "answers": "The raw source column behind a conformed column, per connector.",
                },
                {
                    "tool": "column_drift",
                    "backed_by": "drift",
                    "answers": "Adapter columns that disagree across connectors for one concept.",
                },
            ],
            "provenance": self.provenance,
            "contracts": self.contracts,
            "bindings": self.bindings,
            "drift": self.drift,
        }


def adapter_models(man: Manifest) -> Dict[str, Dict[str, str]]:
    """`{concept: {connector: model_name}}` for every `<connector>_erp_bi_<concept>`.

    The unified layer is where conformance has to hold, and it is the only layer where two
    connectors' columns are ever stacked on top of each other. A source-aligned model has no
    peer to disagree with, so it has no contract.
    """
    out: Dict[str, Dict[str, str]] = {}
    for node in man.nodes.values():
        if node.get("resource_type") != "model":
            continue
        match = _RE_ADAPTER.match(node.get("name", ""))
        if not match:
            continue
        connector, concept = match.group(1), match.group(2)
        out.setdefault(concept, {})[connector] = node["name"]
    return out


def build_store(
    man: Manifest,
    project_root: Path,
    slug: str,
    use_case: Path,
    dialect: str = lineage_mod.DEFAULT_DIALECT,
    cache: Optional[LineageCache] = None,
) -> ColumnStore:
    """Everything, in one pass, incremental where the cache allows."""
    config = og.read_config(use_case / "ontology", slug)
    fresh = freshness(man, project_root)

    nodes_by_uid = {
        uid: node for uid, node in man.nodes.items() if node.get("resource_type") == "model"
    }
    by_name = {node["name"]: node for node in nodes_by_uid.values()}

    lineages: Dict[str, ModelLineage] = {}
    keys: List[str] = []
    reparsed = 0
    for model in fresh.models:
        node = nodes_by_uid.get(model.unique_id, {})
        key = f"{model.name}:{model.content_hash}"
        keys.append(key)
        cached = cache.get(model.name, model.content_hash) if cache else None
        if cached is not None:
            lineages[model.name] = cached
            continue
        computed = model_lineage(model, node, by_name, dialect)
        lineages[model.name] = computed
        if cache:
            cache.put(model.name, model.content_hash, computed)
        if model.status == "changed":
            reparsed += 1
    if cache:
        cache.save(keys)

    resolver = ChainResolver(lineages, set(by_name))
    adapters = adapter_models(man)

    contracts, bindings, drift = _contracts_and_bindings(
        adapters, lineages, resolver, config, man
    )

    counts = {status: 0 for status in ("parsed", "macro", "failed", "no_parser")}
    for lineage in lineages.values():
        counts[lineage.status] = counts.get(lineage.status, 0) + 1

    # Provenance carries only what the *content* determines. A cache-hit count or a manifest
    # timestamp is a fact about the run, and putting either in a committed artifact means the
    # file changes when nothing about the project did — so `--check` reports "out of date"
    # forever and the gate stops meaning anything. Measured the hard way: writing with a cold
    # cache and checking with a warm one produced a diff of two integers.
    provenance = {
        "dbt_version": man.dbt_version,
        "project": man.project_name,
        "sqlglot": getattr(lineage_mod.sqlglot, "__version__", None),
        "dialect": dialect,
        "freshness": fresh.as_record(),
        "models_parsed": counts["parsed"],
        "models_macro_only": counts["macro"],
        "models_parse_failed": counts["failed"],
        "models_no_parser": counts["no_parser"],
        "stale_models": sorted(m.name for m in fresh.by_status("changed"))[:20],
        "parse_failures": sorted(
            l.model for l in lineages.values() if l.status == "failed"
        )[:10],
    }
    run = {
        "models_reparsed_from_disk": reparsed,
        "cache_hits": cache.hits if cache else 0,
        "cache_misses": cache.misses if cache else 0,
    }

    return ColumnStore(
        slug=slug,
        config=config,
        freshness=fresh,
        lineages=lineages,
        contracts=contracts,
        bindings=bindings,
        drift=drift,
        provenance=provenance,
        run=run,
    )


@dataclass
class Declared:
    """The output columns of one model, and whether that list is the whole story."""

    columns: List[str]
    complete: bool
    reason: str = ""


class ColumnSetResolver:
    """The output columns one model declares, in the order the SQL declares them.

    Order matters and is not decoration: `erp_union()` stacks adapters positionally, so a
    column in the wrong position with a compatible type unions cleanly and transposes the
    data silently. Sorting here would throw away the only evidence of that.

    Reading the named projections alone is not enough, and the shortfall is not marginal.
    Most adapters in this project are

        select *, {{ add_erp_fields(columns=[...]) }} from {{ ref('..._staging') }}

    which declares **no named column at all** — `lineage_from_sql` emits one `*` passthrough
    edge and one `(macro)` edge, and a resolver that skipped both reported the model as
    having an empty column set. Measured here: 20 of 30 conformed concepts got a contract,
    and the 10 that did not included `dim_accounts`, which five connectors supply. A
    conformance check silent on the concepts most likely to drift is worse than none.

    So a `*` is expanded in place by resolving the upstream model's own columns, recursively,
    at the position the star occupied. Two things it deliberately will **not** do:

      * invent columns behind a macro. `{{ add_erp_fields(...) }}` expands to a list this
        parser cannot see, so the model is marked incomplete and says why.
      * invent columns behind a source. A `.sql` chain ending at `{{ source(...) }}` reaches
        a table whose schema is in the warehouse, not the repository.

    Incomplete is carried through to the contract rather than smoothed over, because a
    contract that silently omits columns reads as a complete one and gets trusted.
    """

    def __init__(self, lineages: Dict[str, ModelLineage], model_names: Set[str]) -> None:
        self.lineages = lineages
        self.model_names = model_names
        self._memo: Dict[str, Declared] = {}

    def declared(self, model: str) -> Declared:
        return self._declared(model, set(), 0)

    def _declared(self, model: str, seen: Set[str], depth: int) -> Declared:
        if model in self._memo and not seen:
            return self._memo[model]
        if depth >= MAX_CHAIN or model in seen:
            return Declared([], False, f"cycle or depth limit at {model}")

        lineage = self.lineages.get(model)
        if lineage is None:
            return Declared([], False, f"{model} is not a model in this project")

        seen = seen | {model}
        columns: List[str] = []
        complete = True
        reason = ""

        def add(name: str) -> None:
            if name not in columns:
                columns.append(name)

        for column, up_model, _up_column, _kind in lineage.edges:
            if column == "*":
                if up_model in self.model_names:
                    upstream = self._declared(up_model, seen, depth + 1)
                    for name in upstream.columns:
                        add(name)
                    if not upstream.complete:
                        complete = False
                        reason = reason or upstream.reason
                else:
                    complete = False
                    reason = reason or f"select * from source {up_model}"
            elif column == "(macro)":
                complete = False
                reason = reason or "a macro generates columns this parser cannot name"
            else:
                add(column)

        result = Declared(columns, complete, reason)
        if depth == 0:
            self._memo[model] = result
        return result


def _contracts_and_bindings(
    adapters: Dict[str, Dict[str, str]],
    lineages: Dict[str, ModelLineage],
    resolver: ChainResolver,
    config: Any,
    man: Manifest,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    contracts: List[Dict[str, Any]] = []
    bindings: List[Dict[str, Any]] = []
    drift: List[Dict[str, Any]] = []

    columns_of = ColumnSetResolver(lineages, set(lineages))

    for concept in sorted(adapters):
        suppliers = adapters[concept]
        core_class = config.concept_class.get(concept)
        declared = {
            connector: columns_of.declared(model)
            for connector, model in sorted(suppliers.items())
            if model in lineages
        }
        per_connector = {c: d.columns for c, d in declared.items() if d.columns}
        if not per_connector:
            continue
        # A connector whose column list is known to be short cannot be said to be *missing*
        # anything — the column may well be there, behind a macro this parser cannot expand.
        # Excluding it from `missing_from` is the difference between a drift report people
        # act on and one they learn to ignore.
        partial = {c for c, d in declared.items() if c in per_connector and not d.complete}

        # The contract is the union of what the adapters declare, ordered by the first
        # adapter that declares each column. A column nobody but one connector carries is
        # still in the contract — with `missing_from` naming the rest, which is the whole
        # signal.
        ordered: List[str] = []
        for columns in per_connector.values():
            for column in columns:
                if column not in ordered:
                    ordered.append(column)

        columns_out: List[Dict[str, Any]] = []
        for column in ordered:
            carried = sorted(c for c, cols in per_connector.items() if column in cols)
            missing = sorted(c for c in per_connector if c not in carried and c not in partial)
            unknown = sorted(c for c in partial if c not in carried)
            prop = og.property_for(column, core_class)
            columns_out.append(
                {
                    "column": column,
                    "property": prop,
                    "carried_by": carried,
                    "missing_from": missing,
                    "unknown_for": unknown,
                }
            )
            # Drift is a column most peers carry and at least one does not. One supplier
            # carrying a column nobody else does is a connector-specific extension, not
            # drift, so it needs two carriers before it is reported.
            #
            # `unknown_for` is reported too, as `suspected`. Suppressing it was a real bug,
            # found by onboarding a test connector: an adapter that drops a column while
            # calling `add_erp_fields(...)` is `partial`, so the dropped column lands in
            # `unknown_for` and nothing was emitted — this file said "0 drift findings" for a
            # project where `connector_alignment_check.py` was reporting an error on the same
            # adapter. Two detectors disagreeing is worse than either being wrong alone,
            # because the quiet one is the one people read.
            #
            # Still not merged into `missing_from`: the macro genuinely might generate it, and
            # a report that cannot tell "definitely absent" from "cannot see" teaches people
            # to distrust both. The label carries that distinction instead of a silence.
            if len(carried) >= 2 and (missing or unknown):
                drift.append(
                    {
                        "concept": concept,
                        "column": column,
                        "confidence": "confirmed" if missing else "suspected",
                        "carried_by": carried,
                        "missing_from": missing,
                        "unknown_for": unknown,
                        "property": prop,
                    }
                )

            for connector in carried:
                model = suppliers[connector]
                for term_model, term_column, kinds in resolver.resolve(model, column):
                    if term_model == model and term_column == column:
                        continue
                    # No `class`, `core_class`, `property`, or `dbt_model` here — every one of
                    # them is already stated once. The class IRI composes from `prefixes` plus
                    # connector and concept; the property and core class sit on the contract
                    # this binding belongs to; and the adapter model name is in that contract's
                    # `adapters` map. Repeating the first three cost 240 KB of the original
                    # 584 KB draft and the fourth another 47 KB, which is the same "declare the
                    # fields once" argument that makes TOON worth using on a uniform record set.
                    #
                    # `adapters` rather than rebuilding `f"{connector}_erp_bi_{concept}"` in
                    # the consumer: that formula is this project's convention, not a rule, and
                    # `new_connector.detect()` exists precisely because conventions differ
                    # between projects. A stated map cannot be wrong about one.
                    bindings.append(
                        {
                            "concept": concept,
                            "connector": connector,
                            "column": column,
                            "source_model": term_model,
                            "source_column": term_column,
                            "transform": classify(kinds),
                            "hops": len(kinds),
                        }
                    )

        contracts.append(
            {
                "concept": concept,
                "id": f"{config.topo}{og._local(concept)}",
                "core_class": core_class,
                "suppliers": sorted(per_connector),
                "adapters": {c: suppliers[c] for c in sorted(per_connector)},
                "supplier_count": len(per_connector),
                "column_count": len(ordered),
                "conformed": [
                    c["column"] for c in columns_out
                    if not c["missing_from"] and not c["unknown_for"]
                ],
                "partial_for": sorted(partial),
                "columns": columns_out,
            }
        )

    bindings.sort(key=lambda b: (b["concept"], b["connector"], b["column"], b["source_column"]))
    drift.sort(key=lambda d: (d["concept"], d["column"]))
    return contracts, bindings, drift


# =======================================================================================
# Source column contracts — the one input nobody writes down
# =======================================================================================


def consumed_source_columns(
    store: "ColumnStore", man: Manifest
) -> Dict[str, Dict[str, Any]]:
    """`{source_unique_id: {source, table, columns, read_by}}` — what the project consumes.

    Adding a connector has exactly one genuinely unknown input: the raw table's column list.
    Everything downstream is derivable. And that one unknown is the only thing this project
    never writes down — measured: 200 source tables declared in `sources.yml`, **zero** of
    them declaring `columns:`. The raw schema exists only inside whatever somebody hand-typed
    into a staging model, which is why adapter drift is detectable downstream but not
    preventable upstream.

    This recovers it in the only direction currently available: every lineage edge whose
    upstream is a source rather than a model names a real raw column, because sqlglot read it
    out of the SQL that selects it.

    The source name is resolved against the manifest, never by splitting on `SOURCE_SEP`.
    `strip_jinja` renders `{{ source('fortnox_api_demo', 'articles') }}` as
    `fortnox_api_demo__articles`, and a source name may itself contain `__` — splitting would
    attribute the columns to a source that does not exist and silently drop the ones that do.
    """
    by_joined: Dict[str, str] = {}
    for uid, node in man.sources.items():
        joined = f"{node.get('source_name', '')}{lineage_mod.SOURCE_SEP}{node.get('name', '')}"
        by_joined[joined] = uid

    model_names = set(store.lineages)
    out: Dict[str, Dict[str, Any]] = {}
    for model_name, lineage in store.lineages.items():
        for column, up_model, up_column, _kind in lineage.edges:
            if up_model in model_names or not up_column or up_column in ("*", "(macro)"):
                continue
            uid = by_joined.get(up_model)
            if uid is None:
                continue
            node = man.sources[uid]
            entry = out.setdefault(
                uid,
                {
                    "source": node.get("source_name", ""),
                    "table": node.get("name", ""),
                    "path": node.get("original_file_path", ""),
                    "package": node.get("package_name", ""),
                    "columns": set(),
                    "read_by": set(),
                    "declared": sorted(node.get("columns") or {}),
                },
            )
            entry["columns"].add(up_column)
            entry["read_by"].add(model_name)
    for entry in out.values():
        entry["columns"] = sorted(entry["columns"])
        entry["read_by"] = sorted(entry["read_by"])
    return out


_RE_YAML_ENTRY = re.compile(r"^(\s*)-\s+name:\s*['\"]?([A-Za-z0-9_.-]+)['\"]?\s*$")

COLUMNS_BANNER = (
    "# Columns this project consumes from this table. Derived by "
    "scripts/dbt_column_memory.py\n"
    "# from the staging SQL that reads them, so this is a statement of what we depend on "
    "and\n"
    "# not an inventory of what the API returns. Removing one upstream is a breaking change."
)


def insert_source_columns(
    text: str, wanted: Dict[Tuple[str, str], List[str]]
) -> Tuple[str, List[str]]:
    """Insert `columns:` blocks under the named tables, preserving everything else.

    `wanted` is keyed by **(source name, table name)**, not table name alone. Two of this
    project's `sources.yml` files declare three and five sources respectively, and nothing
    stops two of them from exposing a table with the same name — `customers` is the obvious
    candidate. Keying on the table alone would then write one source's column list under
    another's table, silently and plausibly. It does not collide today; it is one added table
    away from colliding, and the failure would look like a correct file.

    A line-based insertion rather than a YAML round-trip, and that is not laziness. These
    files carry Jinja in load-bearing positions —
    `schema: fortnox_api_{{ var('demo_uid', var('uid')) }}` — and a YAML library either
    rejects that or re-emits it quoted so dbt stops rendering it. A round-trip would also
    drop every comment in the file. Inserting lines touches nothing it does not add.

    A table that already declares `columns:` is left alone. The generated list bootstraps a
    contract a human then owns; overwriting a hand-authored one would make the generator the
    authority on a fact it only inferred.
    """
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    written: List[str] = []
    index = 0
    tables_indent: Optional[int] = None
    current_source = ""

    while index < len(lines):
        line = lines[index]
        out.append(line)
        index += 1

        stripped = line.rstrip("\n")
        if re.match(r"^\s*tables:\s*$", stripped):
            tables_indent = len(stripped) - len(stripped.lstrip())
            continue

        match = _RE_YAML_ENTRY.match(stripped)
        if not match:
            continue
        indent, name = match.group(1), match.group(2)

        # A source block is also `- name: <something>`. An entry inside the open `tables:`
        # block is a table; anything else at this level starts a new source, which also ends
        # the previous source's table list.
        if tables_indent is None or len(indent) <= tables_indent:
            current_source = name
            tables_indent = None
            continue
        columns = wanted.get((current_source, name))
        if not columns:
            continue

        # Everything strictly more-indented belongs to this entry. Scanning the whole body
        # rather than peeking one line ahead is what finds an existing `columns:` under an
        # entry that already carries a description, tests, or a freshness block.
        body_start = index
        while index < len(lines) and lines[index].startswith(indent + "  "):
            index += 1
        body = lines[body_start:index]
        out.extend(body)
        if any(re.match(r"^\s*columns:\s*$", ln.rstrip("\n")) for ln in body):
            continue

        pad = indent + "  "
        out += [f"{pad}{ln}\n" for ln in COLUMNS_BANNER.splitlines()]
        out.append(f"{pad}columns:\n")
        out += [f"{pad}  - name: {column}\n" for column in columns]
        written.append(name)

    return "".join(out), written


def emit_source_columns(
    store: "ColumnStore", man: Manifest, project_root: Path, write: bool
) -> Dict[str, Any]:
    """Bootstrap `columns:` into every `sources.yml` that declares a consumed table."""
    consumed = consumed_source_columns(store, man)
    roots = package_roots(project_root)
    project_name = man.project_name

    by_file: Dict[Path, Dict[Tuple[str, str], List[str]]] = {}
    skipped: List[str] = []
    for entry in consumed.values():
        if entry["declared"]:
            skipped.append(f"{entry['source']}.{entry['table']}")
            continue
        base = project_root if entry["package"] == project_name else roots.get(entry["package"])
        if base is None or not entry["path"]:
            continue
        path = base / entry["path"]
        if path.is_file():
            by_file.setdefault(path, {})[(entry["source"], entry["table"])] = entry["columns"]

    changed: List[Dict[str, Any]] = []
    for path, wanted in sorted(by_file.items()):
        original = path.read_text(encoding="utf-8")
        updated, written = insert_source_columns(original, wanted)
        if not written or updated == original:
            continue
        if write:
            path.write_text(updated, encoding="utf-8")
        by_table = {table: cols for (_source, table), cols in wanted.items()}
        changed.append(
            {
                "file": _rel(path),
                "tables": written,
                "columns": sum(len(by_table.get(t, [])) for t in written),
            }
        )

    return {
        "tables_consumed": len(consumed),
        "tables_already_declared": sorted(skipped),
        "files": changed,
        "tables_written": sum(len(c["tables"]) for c in changed),
        "columns_written": sum(c["columns"] for c in changed),
        "written": write,
    }


# =======================================================================================
# graphify — the contract as graph nodes, so orientation finds it
# =======================================================================================


def graphify_fragment(store: ColumnStore, use_case: Path) -> Dict[str, Any]:
    """An extraction fragment putting the column contract into the code graph.

    The point is not to store the contract twice. It is that `CLAUDE.md`'s Graphify-first
    rule makes `graphify query` the first move for any structural question, so an agent
    onboarding a connector runs `graphify query "dim_articles"` before it reads anything.
    If the contract is not in the graph, that query answers with a `.sql` file node and the
    agent goes on to diff adapters by hand — which is the work this module exists to remove.

    Every contract node **attaches to the real adapter model nodes** by reusing
    `dbt_manifest_to_graphify.node_id()`, the same byte-for-byte reproduction of graphify's
    own ID formula that lets the dbt merge upgrade nodes instead of duplicating them. A
    contract is therefore reachable in two hops from any model in the concept, and the
    concept is reachable from the contract.

    Emitted `EXTRACTED` at confidence 1.0 for the same reason the dbt fragment is: sqlglot
    read these column names out of the SQL. Nothing here is inferred by a model.
    """
    import dbt_manifest_to_graphify as emitter

    artifact = _rel(artifact_path(use_case))
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    minted: Set[str] = set()

    def adapter_node(model_name: str) -> Optional[str]:
        """The graph ID of an adapter model, or None when it is not on disk.

        Resolved through the freshness pass rather than by rebuilding the path: that pass
        already mapped every model to the file it came from, including the ten dbt packages
        whose `original_file_path` is package-relative.
        """
        for model in store.freshness.models:
            if model.name == model_name and model.path is not None:
                return emitter.node_id(_rel(model.path))
        return None

    def mint(node_id: str, node: Dict[str, Any]) -> str:
        if node_id not in minted:
            minted.add(node_id)
            nodes.append(node)
        return node_id

    base = re.sub(r"[^a-z0-9]+", "_", artifact.lower()).strip("_")

    for contract in store.contracts:
        concept = contract["concept"]
        slug = re.sub(r"[^a-z0-9]+", "_", concept.lower()).strip("_")
        contract_id = mint(
            f"{base}_contract_{slug}",
            {
                "id": f"{base}_contract_{slug}",
                "label": f"column contract: {concept}",
                "file_type": "code",
                "source_file": artifact,
                "source_location": None,
                "source_url": None,
                "captured_at": None,
                "author": None,
                "contributor": None,
                "dbt_resource_type": "column_contract",
                "dbt_concept": concept,
                "ontology_class": contract["core_class"],
                "ontology_id": contract["id"],
                "suppliers": ", ".join(contract["suppliers"]),
                "columns": ", ".join(c["column"] for c in contract["columns"]),
                "conformed_columns": len(contract["conformed"]),
                "column_count": contract["column_count"],
            },
        )
        for connector, adapter in sorted(contract["adapters"].items()):
            target = adapter_node(adapter)
            if not target:
                continue
            edges.append(
                {
                    "source": contract_id,
                    "target": target,
                    "relation": "constrains",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "source_file": artifact,
                    "source_location": None,
                    "weight": 1.0,
                }
            )

    for finding in store.drift:
        slug = re.sub(r"[^a-z0-9]+", "_", f"{finding['concept']}_{finding['column']}".lower())
        drift_id = mint(
            f"{base}_drift_{slug}",
            {
                "id": f"{base}_drift_{slug}",
                "label": f"column drift: {finding['concept']}.{finding['column']}",
                "file_type": "code",
                "source_file": artifact,
                "source_location": None,
                "source_url": None,
                "captured_at": None,
                "author": None,
                "contributor": None,
                "dbt_resource_type": "column_drift",
                "dbt_concept": finding["concept"],
                "dbt_column": finding["column"],
                "carried_by": ", ".join(finding["carried_by"]),
                "missing_from": ", ".join(finding["missing_from"]),
            },
        )
        # Edge to the adapters that are *missing* the column: that is where the fix goes,
        # and it is the node somebody investigating the union failure will be looking at.
        adapters = next(
            (c["adapters"] for c in store.contracts if c["concept"] == finding["concept"]), {}
        )
        for connector in finding["missing_from"]:
            target = adapter_node(adapters.get(connector, ""))
            if target:
                edges.append(
                    {
                        "source": drift_id,
                        "target": target,
                        "relation": "reports_drift_in",
                        "confidence": "EXTRACTED",
                        "confidence_score": 1.0,
                        "source_file": artifact,
                        "source_location": None,
                        "weight": 1.0,
                    }
                )

    return {
        "nodes": nodes,
        "edges": edges,
        "hyperedges": [],
        "input_tokens": 0,
        "output_tokens": 0,
    }


# =======================================================================================
# AgentMemory
# =======================================================================================


def memory_records(store: ColumnStore) -> List[Dict[str, Any]]:
    """The bounded, BM25-findable set. Not the edges.

    Every record leads with the words a future question would use — the use-case slug, the
    concept, the connector keys, the column names — because recall here is lexical and a
    record phrased in different words than the question is a record that does not exist.
    """
    out: List[Dict[str, Any]] = []
    slug = store.slug

    fresh = store.provenance["freshness"]
    out.append(
        {
            "concepts": ["column-lineage", "dbt", slug, "locator"],
            "content": (
                f"dbt column lineage for use-case {slug} is stored at "
                f"skill-packs/*/use-cases/{slug}/ontology/{ARTIFACT_NAME}, generated by "
                f"scripts/dbt_column_memory.py from the .sql files on disk. It holds the "
                f"conformed column contract per concept, the resolved source-column bindings "
                f"behind each adapter column, and adapter column drift. "
                f"{len(store.contracts)} concept contracts, {len(store.bindings)} bindings, "
                f"{len(store.drift)} drift findings over {fresh['models']} models "
                f"({store.provenance['models_parsed']} parsed with sqlglot). "
                f"Regenerate with: python3 scripts/dbt_column_memory.py --use-case {slug} --write. "
                f"Query one concept with --concept <name>. Do not re-derive it by hand."
            ),
        }
    )

    for finding in store.drift[:MAX_MEMORY_DRIFT]:
        carried = ", ".join(finding["carried_by"])
        confirmed = bool(finding["missing_from"])
        absent = ", ".join(finding["missing_from"] or finding["unknown_for"])
        qualifier = (
            f"missing from {absent}"
            if confirmed
            else f"not visible in {absent}, whose column list is generated by a macro this "
                 f"parser cannot expand — verify by hand"
        )
        out.append(
            {
                "concepts": [
                    "column-drift", "dbt", slug, finding["concept"], finding["column"],
                    finding["confidence"],
                ],
                "content": (
                    f"Adapter column drift ({finding['confidence']}) in {slug}, conformed "
                    f"concept {finding['concept']}: column {finding['column']} is carried by "
                    f"{carried} and {qualifier}. erp_union() stacks one adapter per enabled "
                    f"source, so this unions cleanly for a tenant with one connector enabled "
                    f"and breaks for the first tenant with two — the connector's own build "
                    f"passes and the failure waits. Fix the adapter, not the union."
                ),
            }
        )

    for contract in store.contracts[:MAX_MEMORY_CONTRACTS]:
        columns = ", ".join(c["column"] for c in contract["columns"])
        out.append(
            {
                "concepts": ["column-contract", "dbt", slug, contract["concept"], "new-connector"],
                "content": (
                    f"Column contract for conformed concept {contract['concept']} "
                    f"({contract['core_class'] or 'unclassified'}) in {slug}: supplied by "
                    f"{', '.join(contract['suppliers'])}. A new connector's "
                    f"<key>_erp_bi_{contract['concept']} adapter must declare these "
                    f"{contract['column_count']} columns, in this order: {columns}. "
                    f"Column order is positional in erp_union() — a column in the wrong "
                    f"position with a compatible type unions cleanly and transposes the data."
                ),
            }
        )
    return out


def binding_records(store: ColumnStore, limit: int = MAX_MEMORY_BINDINGS) -> List[Dict[str, Any]]:
    """Resolved source bindings, one record per (concept, column) across connectors."""
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for binding in store.bindings:
        grouped.setdefault((binding["concept"], binding["column"]), []).append(binding)

    out: List[Dict[str, Any]] = []
    for (concept, column), rows in sorted(grouped.items())[:limit]:
        where = "; ".join(
            f"{r['connector']} <- {r['source_model']}.{r['source_column']} ({r['transform']})"
            for r in sorted(rows, key=lambda r: r["connector"])[:12]
        )
        out.append(
            {
                "concepts": ["column-binding", "dbt", store.slug, concept, column],
                "content": (
                    f"Source binding in {store.slug} for conformed column {concept}.{column}"
                    + (f" (property {rows[0]['property']})" if rows[0].get("property") else "")
                    + f": {where}. Resolved by parsing the .sql, not from documentation."
                ),
            }
        )
    return out


def remember(records: Sequence[Dict[str, Any]], url: str = AGENTMEMORY_URL,
             timeout: float = 3.0) -> Tuple[int, str]:
    """POST each record to AgentMemory. Never raises; an absent server is not a failure.

    Same contract as `scripts/sync_context.sh` and `src/ai-core/memory-store.ts`: probe
    health first, and treat "no server" as a skip so a checkout or CI runner without
    AgentMemory behaves exactly as it did before this existed.
    """
    base = url.rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/agentmemory/health", timeout=1.0) as response:
            if response.status != 200:
                return 0, f"server at {base} is unhealthy"
    except (urllib.error.URLError, OSError, ValueError):
        return 0, f"no AgentMemory server at {base}"

    written = 0
    for record in records:
        body = json.dumps(
            {"content": record["content"], "concepts": list(record.get("concepts", []))}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{base}/agentmemory/remember",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if 200 <= response.status < 300:
                    written += 1
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return written, ""


# =======================================================================================
# Artifact IO
# =======================================================================================


def artifact_path(use_case: Path) -> Path:
    return use_case / "ontology" / ARTIFACT_NAME


def serialise(store: ColumnStore) -> str:
    return json.dumps(store.as_artifact(), indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def is_current(use_case: Path, digest: str) -> Tuple[bool, str]:
    """Whether the committed artifact matches the model surface on disk."""
    path = artifact_path(use_case)
    if not path.is_file():
        return False, "no column-memory.json yet"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"unreadable: {exc}"
    stored = ((payload.get("provenance") or {}).get("freshness") or {}).get("digest")
    if stored == digest:
        return True, "current"
    return False, "the .sql on disk has changed since this was generated"


def project_root_of(use_case: Path, manifest: Path) -> Path:
    """`_paths.project_root_of` with this module's argument order and fatal absence.

    The order is `(use_case, manifest)` here and `(manifest, use_case)` in `_paths`;
    both are kept because `tests/test_dbt_column_memory.py` monkeypatches this name
    and the callers below pass positionally.
    """
    found = _paths.project_root_of(manifest, use_case)
    if found is None:
        die(f"could not locate a dbt_project.yml above {manifest}")
        raise SystemExit(2)  # unreachable
    return found


# =======================================================================================
# CLI
# =======================================================================================


def _report(store: ColumnStore, args: argparse.Namespace) -> None:
    fresh = store.provenance["freshness"]
    print(f"use-case: {store.slug}  ({store.provenance['project']})")
    print(
        f"models:   {fresh['models']} in manifest · {fresh['fresh']} fresh · "
        f"{fresh['changed']} changed on disk · {fresh['missing']} missing · "
        f"{fresh['untracked_sql']} untracked .sql"
    )
    if store.run.get("models_reparsed_from_disk"):
        print(
            f"          {store.run['models_reparsed_from_disk']} re-parsed from disk "
            f"(the manifest's raw_code is behind the file)"
        )
    if not store.provenance["sqlglot"]:
        print("sqlglot:  NOT INSTALLED — only passthrough and union chains resolved.")
        print("          pip install -r .github/requirements/ci.txt")
    print(
        f"parsed:   {store.provenance['models_parsed']} parsed · "
        f"{store.provenance['models_macro_only']} macro-only · "
        f"{store.provenance['models_parse_failed']} parse-failed  "
        f"(cache {store.run.get('cache_hits', 0)} hit / {store.run.get('cache_misses', 0)} miss)"
    )
    print(
        f"store:    {len(store.contracts)} concept contracts · "
        f"{len(store.bindings)} source bindings · {len(store.drift)} drift findings"
    )

    if args.concept:
        contract = next((c for c in store.contracts if c["concept"] == args.concept), None)
        if contract is None:
            print(f"\nno contract for concept '{args.concept}'")
            return
        print(f"\ncontract: {contract['concept']}  ({contract['core_class'] or 'unclassified'})")
        print(f"          supplied by {', '.join(contract['suppliers'])}")
        for column in contract["columns"]:
            flag = "" if not column["missing_from"] else f"  MISSING FROM {','.join(column['missing_from'])}"
            prop = f"  [{column['property']}]" if column["property"] else ""
            print(f"  {column['column']:<40}{prop}{flag}")
        rows = [b for b in store.bindings if b["concept"] == args.concept]
        if rows:
            print(f"\n  source bindings ({len(rows)}):")
            for binding in rows[: args.limit]:
                print(
                    f"    {binding['connector']:<20} {binding['column']:<28} <- "
                    f"{binding['source_model']}.{binding['source_column']} [{binding['transform']}]"
                )
            if len(rows) > args.limit:
                print(f"    ... {len(rows) - args.limit} more (raise --limit)")
        return

    if store.drift:
        print(f"\ndrift ({len(store.drift)}):")
        for finding in store.drift[: args.limit]:
            absent = finding["missing_from"] or finding["unknown_for"]
            print(
                f"  [{finding['confidence']:<9}] {finding['concept']}.{finding['column']}: "
                f"carried by {','.join(finding['carried_by'])}, "
                f"{'missing from' if finding['missing_from'] else 'not visible in'} "
                f"{','.join(absent)}"
            )
        if len(store.drift) > args.limit:
            print(f"  ... {len(store.drift) - args.limit} more (raise --limit)")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ontology-aligned, incrementally rebuilt column lineage for a dbt project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--use-case", required=True)
    parser.add_argument("--manifest", help="override the manifest path")
    parser.add_argument("--write", action="store_true", help="write ontology/column-memory.json")
    parser.add_argument(
        "--check", action="store_true",
        help="exit 1 if the store is stale or would change; writes nothing",
    )
    parser.add_argument("--remember", action="store_true", help="mirror to AgentMemory")
    parser.add_argument(
        "--remember-bindings", action="store_true",
        help=f"also mirror resolved source bindings (capped at {MAX_MEMORY_BINDINGS})",
    )
    parser.add_argument("--concept", help="report one conformed concept's contract")
    parser.add_argument(
        "--emit-source-columns", action="store_true",
        help="bootstrap `columns:` into sources.yml from the staging SQL that reads them",
    )
    parser.add_argument(
        "--graphify-fragment", metavar="PATH",
        help="write the contract/drift graph fragment here instead of merging",
    )
    parser.add_argument(
        "--merge-graphify", action="store_true",
        help="merge the contract into graphify-out/graph.json (never run graphify update after)",
    )
    parser.add_argument(
        "--stale-only", action="store_true",
        help="report freshness only — no parsing, no sqlglot, ~20ms",
    )
    parser.add_argument("--no-cache", action="store_true", help="ignore the incremental cache")
    parser.add_argument("--dialect", default=lineage_mod.DEFAULT_DIALECT)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--memory-url", default=AGENTMEMORY_URL)
    args = parser.parse_args(argv)

    use_case = use_case_dir(args.use_case)
    manifest_path = Path(args.manifest) if args.manifest else default_manifest(use_case)
    if manifest_path is None or not manifest_path.is_file():
        message = (
            f"no manifest for '{args.use_case}'. Run "
            f"skill-packs/*/use-cases/{args.use_case}/artifacts/refresh.sh, or pass --manifest."
        )
        if args.format == "json":
            print(json.dumps({"use_case": args.use_case, "status": "skip", "reason": message}))
            return 0
        print(message, file=sys.stderr)
        return 0

    man = Manifest.load(str(manifest_path))
    project_root = project_root_of(use_case, manifest_path)

    # The cheap path: freshness needs no SQL parser and no ontology, and is what a hook runs.
    if args.stale_only:
        fresh = freshness(man, project_root)
        current, reason = is_current(use_case, fresh.digest)
        record = {
            "use_case": args.use_case,
            "current": current,
            "reason": reason,
            **fresh.as_record(),
            "changed_models": sorted(m.name for m in fresh.by_status("changed"))[:20],
        }
        if args.format == "json":
            print(json.dumps(record))
        else:
            state = "current" if current else "STALE"
            print(
                f"{args.use_case}: {state} — {record['changed']} changed, "
                f"{record['missing']} missing, {record['untracked_sql']} untracked ({reason})"
            )
        return 0 if current else 1

    cache = None if args.no_cache else LineageCache(CACHE_DIR / f"{args.use_case}.json")
    store = build_store(
        man, project_root, args.use_case, use_case, dialect=args.dialect, cache=cache
    )

    content = serialise(store)
    path = artifact_path(use_case)
    existing = path.read_text(encoding="utf-8") if path.is_file() else None
    would_change = existing != content

    if args.check:
        if args.format == "json":
            print(
                json.dumps(
                    {
                        "use_case": args.use_case,
                        "status": "changed" if would_change else "ok",
                        "artifact": _rel(path),
                        "contracts": len(store.contracts),
                        "bindings": len(store.bindings),
                        "drift": len(store.drift),
                        "freshness": store.provenance["freshness"],
                    }
                )
            )
        elif would_change:
            print(f"{_rel(path)} is out of date — run --write")
        else:
            print(f"{_rel(path)} is current")
        return 1 if would_change else 0

    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    if args.emit_source_columns:
        result = emit_source_columns(store, man, project_root, write=args.write)
        if args.format == "json":
            print(json.dumps({"use_case": args.use_case, **result}))
            return 0
        verb = "wrote" if args.write else "would write (pass --write)"
        print(
            f"source columns: {verb} {result['columns_written']} column(s) across "
            f"{result['tables_written']} table(s) in {len(result['files'])} file(s)"
        )
        for entry in result["files"]:
            print(f"  {entry['file']}: {len(entry['tables'])} tables, {entry['columns']} columns")
        if result["tables_already_declared"]:
            print(
                f"  left alone ({len(result['tables_already_declared'])} already declare "
                f"columns): {', '.join(result['tables_already_declared'][:5])}"
            )
        return 0

    merged = ""
    if args.graphify_fragment or args.merge_graphify:
        import dbt_manifest_to_graphify as emitter

        fragment = graphify_fragment(store, use_case)
        target = Path(args.graphify_fragment) if args.graphify_fragment else (
            REPO / "graphify-out" / ".graphify_column_contract.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(fragment, ensure_ascii=False), encoding="utf-8")
        merged = f"{len(fragment['nodes'])} nodes, {len(fragment['edges'])} edges -> {_rel(target)}"
        if args.merge_graphify:
            # Same ordering rule as the dbt merge, and for the same reason: graphify's AST
            # pass extracts nothing from a `.sql` file, so a `graphify update` after this
            # drops the model nodes these edges point at.
            code = emitter.merge_into_graph(target, project_root)
            if code != 0:
                print("graphify merge failed; the fragment is still on disk", file=sys.stderr)

    written = 0
    memory_note = ""
    if args.remember:
        records = memory_records(store)
        if args.remember_bindings:
            records += binding_records(store)
        written, memory_note = remember(records, url=args.memory_url)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "use_case": args.use_case,
                    "artifact": _rel(path),
                    "written": bool(args.write),
                    "contracts": len(store.contracts),
                    "bindings": len(store.bindings),
                    "drift": len(store.drift),
                    "memories_written": written,
                    "memory_note": memory_note,
                    "graphify": merged,
                    "provenance": store.provenance,
                    "run": store.run,
                }
            )
        )
        return 0

    _report(store, args)
    if args.write:
        print(f"\nwrote {_rel(path)}" + ("" if not would_change else " (changed)"))
    if merged:
        print(f"graphify:    {merged}")
    if args.remember:
        print(
            f"AgentMemory: {written} record(s) written"
            + (f" — {memory_note}" if memory_note else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
