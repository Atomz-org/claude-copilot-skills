#!/usr/bin/env python3
"""Scaffold a new source-system connector inside an existing use-case's dbt project.

Backs the `/new-connector` command. Takes a connector name, a use-case slug, and the raw
tables the connector exposes; writes the staging models, the source-aligned layer, and any
unified-layer adapters, following the conventions **already in use** in that project.

The conventions are detected, not assumed. The script reads an existing connector in the
target project and copies its file naming, directory layout, and registry shape. Two
use-cases with different layouts therefore get different output from the same command, and
a project with no connectors yet falls back to the dbt-labs staging convention.

It deliberately does NOT edit sources.yml, the connector registry, or dbt_project.yml. Those
are the connector's contract; a reviewer should see them arrive as a hand-written diff, not
as generated text. It prints them instead. Existing files are never overwritten.

Everything written is a stub carrying [NEEDS INPUT] where a real column list belongs — this
saves the typing, not the modeling.

Usage:
    python3 scripts/new_connector.py shopify \\
        --use-case enhanza-analytics \\
        --tables customers,orders,products \\
        --unified-concepts dim_customers,fact_orders \\
        --currency USD

    # inspect what would be written, and the conventions detected, without writing
    python3 scripts/new_connector.py shopify --use-case enhanza-analytics \\
        --tables customers --dry-run

See .claude/skills/connector-onboarding/SKILL.md for the full procedure.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Entity prefixes mark where a model's *name* starts and its *layer* ends, so
# `fortnox_bi_dim_customers` yields the infix `_bi_` rather than `_bi_dim_`. Only genuine
# entity tokens belong here: `flat_` and `reports_` look similar but are layer names in at
# least one real project, and listing them would collapse those infixes to `_`.
ENTITY_PREFIXES = ("dim_", "fact_", "stg_", "int_", "agg_", "brg_", "mart_")


# ---------------------------------------------------------------------------------------
# Detected conventions
# ---------------------------------------------------------------------------------------


@dataclass
class Conventions:
    """How this particular dbt project names and places a connector's models."""

    use_case: Path
    project: Path
    models: Path
    reference: str | None = None  # existing connector the patterns were learned from
    source_suffix: str = "_api"
    model_prefix: str = ""  # |stg_|shopify__customers
    staging_infix: str = "_bi_"  # fortnox|_bi_|dim_customers|_staging
    staging_suffix: str = "_staging"
    adapter_infix: str | None = None  # fortnox|_erp_bi_|dim_customers
    bi_dir_suffix: str | None = None  # models/fortnox|_bi|/
    sources_yml: Path | None = None
    registry_macro: Path | None = None
    registry_key: str = "all_available_sources"
    has_auto_config: bool = False
    enable_var: str = "is_{source}_enabled"
    notes: list[str] = field(default_factory=list)

    def staging_model(self, source: str, model: str) -> str:
        return f"{self.model_prefix}{source}{self.staging_infix}{model}{self.staging_suffix}"

    def bi_model(self, source: str, model: str) -> str:
        return f"{source}{self.staging_infix}{model}"

    def adapter_model(self, source: str, concept: str) -> str:
        return f"{source}{self.adapter_infix}{concept}"

    def var_for(self, source: str) -> str:
        return self.enable_var.format(source=source)


def _infix_of(remainder: str) -> str:
    """The layer infix of one filename, with everything up to the connector name stripped.

    `_bi_dim_customers` -> `_bi_`, `_erp_bi_fact_orders` -> `_erp_bi_`, `__order_lines` ->
    `__`. A doubled underscore is the dbt-labs separator and is the whole infix by itself;
    otherwise cut at the first entity prefix, and with no entity prefix present keep only
    the first token so `_flat_incoming_goods` yields `_flat_`.
    """
    inner = remainder.lstrip("_")
    underscores = remainder[: len(remainder) - len(inner)]
    if len(underscores) >= 2:
        return underscores
    cuts = [inner.find(e) for e in ENTITY_PREFIXES]
    cuts = [c for c in cuts if c > 0]
    if cuts:
        return underscores + inner[: min(cuts)]
    if "_" in inner:
        return f"{underscores}{inner.split('_', 1)[0]}_"
    return underscores


def _vote_infix(remainders: list[str]) -> str:
    """The most common infix across a connector's files.

    A real connector carries several naming families at once — the reference project has
    `_bi_` (50 files), `_erp_bi_` (27), `_flat_` (14), `_reports_` (6) and `_base_` (1) in
    one directory. A longest-common-prefix over all of them collapses to `_`; the majority
    family is the convention a new connector should follow.
    """
    counts: dict[str, int] = {}
    for remainder in remainders:
        infix = _infix_of(remainder)
        counts[infix] = counts.get(infix, 0) + 1
    if not counts:
        return ""
    return max(counts, key=lambda k: (counts[k], -len(k)))


def find_use_case(slug: str) -> Path:
    """Locate skill-packs/<pack>/use-cases/<slug>/ across every pack."""
    matches = sorted(REPO.glob(f"skill-packs/*/use-cases/{slug}"))
    matches = [m for m in matches if m.is_dir()]
    if not matches:
        available = sorted(
            p.name for p in REPO.glob("skill-packs/*/use-cases/*") if p.is_dir()
        )
        raise SystemExit(
            f"No use-case '{slug}' found under skill-packs/*/use-cases/.\n"
            f"Available: {', '.join(available) or '(none)'}\n"
            f"Run /new-use-case first — a connector belongs to a framed use-case."
        )
    if len(matches) > 1:
        raise SystemExit(
            f"Ambiguous use-case '{slug}', found in several packs:\n  "
            + "\n  ".join(str(m.relative_to(REPO)) for m in matches)
        )
    return matches[0]


def detect(use_case: Path) -> Conventions:
    """Learn the project's connector conventions from the connectors already in it."""
    project = use_case / "dbt_project"
    if not (project / "dbt_project.yml").exists():
        raise SystemExit(
            f"No dbt project at {project.relative_to(REPO)}/dbt_project.yml.\n"
            f"A connector needs a project to live in."
        )

    models = project / "models"
    match = re.search(
        r'^\s*model-paths:\s*\[\s*["\']([^"\']+)["\']',
        (project / "dbt_project.yml").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match:
        models = project / match.group(1)

    conv = Conventions(use_case=use_case, project=project, models=models)

    # The registry, if this project has one.
    for macro in sorted(project.glob("macros/**/*.sql")):
        if conv.registry_key in macro.read_text(encoding="utf-8"):
            conv.registry_macro = macro
            break
    conv.has_auto_config = any(
        "macro auto_config" in m.read_text(encoding="utf-8")
        for m in project.glob("macros/**/*.sql")
    )

    # The reference connector: the staging directory with the most models. A project's
    # busiest connector is the one whose conventions are most likely to be the real ones.
    # Two layouts contribute candidates: `models/staging/<connector>/` (monolith) and
    # `packages/<connector>/models/staging/` (split) — in the second, the connector's name
    # is the *package* directory, not the staging dir's own name.
    candidates: dict[Path, int] = {}
    names: dict[Path, str] = {}
    staging_root = models / "staging"
    if staging_root.is_dir():
        for d in staging_root.iterdir():
            if d.is_dir():
                candidates[d] = len(list(d.glob("*.sql")))
                names[d] = d.name
    packages_root = project / "packages"
    if packages_root.is_dir():
        for pkg in packages_root.iterdir():
            d = pkg / "models" / "staging"
            if (pkg / "dbt_project.yml").exists() and d.is_dir():
                candidates[d] = len(list(d.glob("*.sql")))
                names[d] = pkg.name
    candidates = {d: n for d, n in candidates.items() if n}
    if not candidates:
        conv.notes.append(
            "No existing connector found — falling back to the dbt-labs staging "
            "convention (staging/<source>/stg_<source>__<table>.sql)."
        )
        conv.model_prefix = "stg_"
        conv.staging_infix = "__"
        conv.staging_suffix = ""
        conv.bi_dir_suffix = None
        conv.sources_yml = next(iter(sorted(models.glob("**/*sources.yml"))), None)
        return conv

    ref_dir = max(candidates, key=lambda d: candidates[d])
    ref = names[ref_dir]
    conv.reference = ref

    # The connector name is not always at the start: `fortnox_bi_dim_customers_staging`
    # leads with it, `stg_shopify__customers` puts it in the middle. Split each filename
    # around the connector name and vote on both halves.
    split = [(n[: n.index(ref)], n[n.index(ref) + len(ref) :]) for n in (p.stem for p in ref_dir.glob("*.sql")) if ref in n]
    if not split:
        conv.notes.append(
            f"connector directory '{ref}' has no file naming it — patterns not learned"
        )
        return conv

    prefixes: dict[str, int] = {}
    for before, _ in split:
        prefixes[before] = prefixes.get(before, 0) + 1
    conv.model_prefix = max(prefixes, key=lambda k: prefixes[k])

    staged = [after for _, after in split if after.endswith("_staging")]
    if staged:
        conv.staging_infix = _vote_infix([s[: -len("_staging")] for s in staged]) or "_"
    else:
        conv.staging_suffix = ""
        conv.staging_infix = _vote_infix([after for _, after in split]) or "_"

    # Adapter models: same directory, no _staging suffix, a longer infix than staging.
    adapters = [after for _, after in split if not after.endswith("_staging")]
    if conv.staging_suffix and adapters:
        candidate = _vote_infix(adapters)
        if candidate and candidate != conv.staging_infix and len(candidate) > len(conv.staging_infix):
            conv.adapter_infix = candidate

    # The source-aligned layer, if the project has one. Look across every connector rather
    # than only the reference: the busiest connector is usually the oldest, and in the
    # reference project it predates the `<source>_bi/` convention its successors follow.
    suffixes: dict[str, int] = {}
    for connector_dir in candidates:
        connector_name = names[connector_dir]
        # Monolith: sibling dirs beside models/staging; split: dirs beside the package's
        # own models/staging. Both express the same `<connector>_bi/` convention.
        sibling_roots = [models]
        if connector_dir.parent.name == "models":
            sibling_roots = [connector_dir.parent]
        for root in sibling_roots:
            for sibling in root.iterdir():
                if sibling.is_dir() and sibling.name.startswith(connector_name):
                    suffix = sibling.name[len(connector_name) :]
                    suffixes[suffix] = suffixes.get(suffix, 0) + 1
    non_empty = {s: n for s, n in suffixes.items() if s}
    if non_empty:
        conv.bi_dir_suffix = max(non_empty, key=lambda k: non_empty[k])
    elif suffixes:
        conv.bi_dir_suffix = ""

    # The source suffix used in sources.yml — <ref>_api vs bare <ref>. Prefer a central
    # sources.yml; some projects keep one per connector as `_<ref>__sources.yml`.
    found_files = sorted(models.glob("**/*sources.yml")) + sorted(
        project.glob("packages/*/models/**/*sources.yml")
    )
    conv.sources_yml = next(
        (f for f in found_files if f.name == "sources.yml"), next(iter(found_files), None)
    )
    for candidate_file in found_files:
        found = re.search(
            rf"^\s*-\s*name:\s*{re.escape(ref)}(\w*)\s*$",
            candidate_file.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if found:
            conv.source_suffix = found.group(1)
            conv.sources_yml = candidate_file
            break

    return conv


# ---------------------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------------------

STAGING_STUB = """\
{config_line}

-- Quarantines the raw {display} source: rename, cast, and coerce here and nowhere else.
-- Nothing downstream may reference a raw column name.
-- Enumerate every column — `select *` must not survive past this layer.
-- [NEEDS INPUT] replace the column list with the real one from {source}{suffix}.{table}

select
    -- RawColumnName as ColumnName
    *
from {{{{ source('{source}{suffix}', '{table}') }}}}
"""

ADAPTER_STUB = """\
{config_line}

-- Adapts {display} to the common unified schema so {union_model} can union it.
-- The output columns must match every other source's {concept} adapter exactly, in the
-- same order. A missing column fails the UNION ALL at compile time, which is loud; a
-- column in the wrong position with a compatible type does not fail at all — it silently
-- transposes the data. Diff this against {compare} before merging.
-- [NEEDS INPUT] replace the column list

select
    -- ColumnName
    *
from {{{{ ref('{staging_model}') }}}}
"""

BI_AUTO_STUB = "{{ auto_config() }}\n"

# The dbt package a new connector becomes in a split-layout project. Mechanism macros are
# called unqualified from these models and resolve through the ROOT project — dbt Core
# never searches sibling packages — so the package declares no macro dependencies and
# carries only what it owns: its models, its sources.yml, and any macro used solely here.
PACKAGE_PROJECT_STUB = """\
# enhanza_{source} — the {display} connector as a dbt package.
# Installed by one `- local: packages/{source}` line in the root packages.yml.
name: 'enhanza_{source}'
version: '1.0.0'
config-version: 2
require-dbt-version: [">=1.9.0", "<2.0.0"]

model-paths: ["models"]
macro-paths: ["macros"]

models:
  enhanza_{source}:
    +materialized: view
    +tags: ['{source}']
    +enabled: "{{{{ var('is_{source}_enabled', false) | as_bool }}}}"
    staging:
      +schema: {source}_staging
      +tags: ['staging']
"""

BI_PLAIN_STUB = """\
{{{{ config(materialized='view') }}}}

select *
from {{{{ ref('{staging_model}') }}}}
"""


def write(path: Path, content: str, created: list, skipped: list, dry_run: bool) -> None:
    if path.exists():
        skipped.append(path)
        return
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    created.append(path)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", value.strip().lower())


def parse_tables(raw: str) -> list[tuple[str, str]]:
    """`customers,orders=fact_orders` -> [('customers','customers'), ('orders','fact_orders')].

    The model name is never guessed from the table name. Whether `customers` becomes
    `dim_customers` is a modeling decision, so it is stated explicitly or left alone.
    """
    out = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        table, _, model = item.partition("=")
        out.append((slug(table), slug(model) if model else slug(table)))
    return out


# ---------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Scaffold a connector inside an existing use-case's dbt project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("connector", help="registry key, e.g. shopify (lowercase, underscores)")
    p.add_argument(
        "--use-case",
        required=True,
        help="use-case slug under skill-packs/*/use-cases/, e.g. enhanza-analytics",
    )
    p.add_argument(
        "--tables",
        default="",
        help="comma-separated raw tables the connector exposes. Each becomes a source "
        "table and one staging model. Use table=model to name the model explicitly, "
        "e.g. customers=dim_customers.",
    )
    p.add_argument(
        "--unified-concepts",
        default="",
        help="comma-separated concepts this connector contributes to the unified layer. "
        "Each gets an adapter model. Omit for a source-aligned-only connector.",
    )
    p.add_argument("--display-name", help="human-readable name, e.g. Shopify")
    p.add_argument(
        "--currency",
        help="ISO code for default_currency. Omit if unconfirmed — a wrong currency "
        "silently mis-values every row, a missing one is emitted as NULL.",
    )
    p.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    p.add_argument("--staging-infix", help="override the detected staging infix")
    p.add_argument("--adapter-infix", help="override the detected adapter infix")
    p.add_argument(
        "--source-suffix",
        help="override the detected sources.yml suffix, e.g. _api. Detection copies what "
        "the project already does; pass this when the project is inconsistent.",
    )
    args = p.parse_args(argv)

    source = slug(args.connector)
    if source != args.connector:
        print(f"note: using '{source}' as the connector key", file=sys.stderr)
    display = args.display_name or source.replace("_", " ").title()

    conv = detect(find_use_case(args.use_case))
    if args.staging_infix:
        conv.staging_infix = args.staging_infix
    if args.adapter_infix:
        conv.adapter_infix = args.adapter_infix
    if args.source_suffix is not None:
        conv.source_suffix = args.source_suffix

    tables = parse_tables(args.tables)
    concepts = [slug(c) for c in args.unified_concepts.split(",") if c.strip()]

    if not tables:
        p.error("--tables is required: a connector with no raw tables has nothing to stage")

    model_names = {model for _, model in tables}
    orphans = [c for c in concepts if c not in model_names]
    if orphans:
        p.error(
            f"--unified-concepts {orphans} have no matching --tables entry. Every adapter "
            f"reads its own connector's staging model, so each concept needs a table "
            f"(e.g. --tables orders={orphans[0]})."
        )

    rel = lambda path: path.relative_to(REPO)  # noqa: E731

    print(f"Connector '{source}' ({display}) -> {rel(conv.use_case)}")
    print("\nDetected conventions" + (f", from '{conv.reference}'" if conv.reference else ""))
    print(f"  staging model    {conv.staging_model(source, '<model>')}")
    if conv.adapter_infix:
        print(f"  adapter model    {conv.adapter_model(source, '<concept>')}")
    else:
        print("  adapter model    (none — project has no unified adapter layer)")
    if conv.bi_dir_suffix is not None:
        print(f"  source-aligned   {conv.models.name}/{source}{conv.bi_dir_suffix}/")
    print(f"  source name      {source}{conv.source_suffix}")
    print(f"  enable var       {conv.var_for(source)}")
    print(f"  registry         {rel(conv.registry_macro) if conv.registry_macro else '(none)'}")
    for note in conv.notes:
        print(f"  note: {note}")
    if conv.adapter_infix is None and concepts:
        print(
            f"\n  warning: --unified-concepts given but no adapter convention was detected."
            f"\n  Adapters will be written as '{source}_erp_bi_<concept>'; override with"
            f"\n  --adapter-infix if that is wrong.",
            file=sys.stderr,
        )
        conv.adapter_infix = "_erp_bi_"

    created: list[Path] = []
    skipped: list[Path] = []

    # In a package-layout project, a new connector is born as a package: its models land
    # under packages/<source>/models/ and the scaffold also writes the package's
    # dbt_project.yml. Detection keys on packages/ containing at least one dbt package —
    # the same signal the alignment checker uses — so the scaffolder and the checker
    # cannot disagree about where a connector lives.
    packages_root = conv.project / "packages"
    split_layout = packages_root.is_dir() and any(
        (d / "dbt_project.yml").exists() for d in packages_root.iterdir() if d.is_dir()
    )
    if split_layout:
        pkg_root = packages_root / source
        model_root = pkg_root / "models"
        staging_dir = model_root / "staging"
        bi_dir = (
            model_root / f"{source}{conv.bi_dir_suffix}"
            if conv.bi_dir_suffix is not None
            else None
        )
        write(
            pkg_root / "dbt_project.yml",
            PACKAGE_PROJECT_STUB.format(source=source, display=display),
            created,
            skipped,
            args.dry_run,
        )
    else:
        staging_dir = conv.models / "staging" / source
        bi_dir = (
            conv.models / f"{source}{conv.bi_dir_suffix}"
            if conv.bi_dir_suffix is not None
            else None
        )

    enable = f"var('{conv.var_for(source)}', false)"
    staging_cfg = (
        f"{{{{ config(alias=model_alias(model.name), enabled = {enable}) }}}}"
        if conv.has_auto_config
        else f"{{{{ config(enabled = {enable}) }}}}"
    )

    for table, model in tables:
        write(
            staging_dir / f"{conv.staging_model(source, model)}.sql",
            STAGING_STUB.format(
                config_line=staging_cfg,
                display=display,
                source=source,
                suffix=conv.source_suffix,
                table=table,
            ),
            created,
            skipped,
            args.dry_run,
        )
        if bi_dir is not None:
            body = (
                BI_AUTO_STUB
                if conv.has_auto_config
                else BI_PLAIN_STUB.format(staging_model=conv.staging_model(source, model))
            )
            write(bi_dir / f"{conv.bi_model(source, model)}.sql", body, created, skipped, args.dry_run)

    union_prefix = conv.adapter_infix.strip("_").split("_", 1)[0] if conv.adapter_infix else "erp"
    for concept in concepts:
        compare = (
            f"{conv.adapter_model(conv.reference, concept)}.sql"
            if conv.reference
            else "an existing adapter for the same concept"
        )
        write(
            staging_dir / f"{conv.adapter_model(source, concept)}.sql",
            ADAPTER_STUB.format(
                config_line=f"{{{{ config(materialized='ephemeral', enabled = {enable}) }}}}",
                display=display,
                concept=concept,
                union_model=f"{union_prefix}_bi_{concept}",
                compare=compare,
                staging_model=conv.staging_model(source, concept),
            ),
            created,
            skipped,
            args.dry_run,
        )

    write(
        staging_dir / "schema.yml",
        "version: 2\n\nmodels:\n"
        + "".join(
            f"  - name: {conv.staging_model(source, m)}\n"
            f"    description: '[NEEDS INPUT] one row per <entity>; staged {display} {t}.'\n"
            for t, m in tables
        ),
        created,
        skipped,
        args.dry_run,
    )
    if bi_dir is not None:
        write(
            bi_dir / "schema.yml",
            "version: 2\n\nmodels:\n"
            + "".join(
                f"  - name: {conv.bi_model(source, m)}\n"
                f"    description: '[NEEDS INPUT] one row per <entity>. State the grain, "
                f"not the model name.'\n"
                f"    columns:\n"
                f"      - name: '[NEEDS INPUT] primary key'\n"
                f"        tests: [unique, not_null]\n"
                for _, m in tables
            ),
            created,
            skipped,
            args.dry_run,
        )

    verb = "Would create" if args.dry_run else "Created"
    if created:
        print(f"\n{verb} {len(created)} file(s):")
        for f in sorted(created):
            print(f"  {rel(f)}")
    if skipped:
        print(f"\nLeft alone, already present ({len(skipped)}):")
        for f in sorted(skipped):
            print(f"  {rel(f)}")

    print(paste_blocks(conv, source, display, args.currency, tables, model_names))
    return 0


def paste_blocks(
    conv: Conventions,
    source: str,
    display: str,
    currency: str | None,
    tables: list[tuple[str, str]],
    model_names: set[str],
) -> str:
    """The three files a reviewer must see as a hand-written diff."""
    rel = lambda path: path.relative_to(REPO)  # noqa: E731
    table_lines = "\n".join(f"      - name: {t}" for t, _ in tables)

    packages_yml = conv.project / "packages.yml"
    split_layout = packages_yml.exists() and (conv.project / "packages").is_dir()
    sources_dest = (
        rel(conv.project / "packages" / source / "models" / "sources.yml")
        if split_layout
        else (rel(conv.sources_yml) if conv.sources_yml else str(rel(conv.models)) + "/sources.yml")
    )
    out = [
        "",
        "-" * 86,
        "Now paste these by hand. They are the connector's contract — a reviewer should",
        "see them as a hand-written diff, not as generated text.",
        "-" * 86,
        "",
    ]
    if split_layout:
        out += [
            f"0. {rel(packages_yml)} — install the package:",
            "",
            f"  - local: packages/{source}",
            "",
            "   Then run `dbt deps`.",
            "",
        ]
    out += [
        f"1. {sources_dest}",
        "",
        f"  - name: {source}{conv.source_suffix}",
        f"    description: '{display} raw data'",
        '    database: "{{ target.project | default(target.database) }}"',
        f"    schema: {source}{conv.source_suffix}_{{{{ var('uid') }}}}",
        "    loaded_at_field: [NEEDS INPUT]",
        "    freshness:",
        "      warn_after: {count: [NEEDS INPUT], period: hour}",
        "      error_after: {count: [NEEDS INPUT], period: hour}",
        "    tables:",
        table_lines,
        "",
    ]

    if conv.registry_macro:
        currency_line = (
            f"                'default_currency': '{currency}',"
            if currency
            else "                {#- default_currency omitted: unconfirmed. [NEEDS INPUT] -#}"
        )
        included = "\n".join(f"                    '{m}'," for m in sorted(model_names))
        out += [
            f"2. {rel(conv.registry_macro)} -> {conv.registry_key}",
            "   (alphabetically placed)",
            "",
            f"            '{source}': {{",
            f"                'name': '{display}',",
            currency_line,
            f"                'enabled': var('{conv.var_for(source)}', 'False') | as_bool,",
            "                'included_models': [",
            included.rstrip(","),
            "                ]",
            "            },",
            "",
            f"3. {rel(conv.project)}/dbt_project.yml",
            "",
            f"   under vars:                {conv.var_for(source)}: false",
            f"   under models: -> staging:  {source}:",
            f"                                +tags: ['{source}']",
        ]
        if conv.bi_dir_suffix is not None:
            out += [
                f"   and as a sibling layer:    {source}{conv.bi_dir_suffix}:",
                f"                                +tags: ['{source}', 'bi']",
            ]
    else:
        out += [
            f"2. {rel(conv.project)}/dbt_project.yml",
            "",
            f"   under vars:                {conv.var_for(source)}: false",
            f"   under models: -> staging:  {source}:",
            f"                                +tags: ['{source}']",
            "",
            "   This project has no connector registry. If connectors are going to keep",
            "   arriving, add one before the third — a per-connector `if` in every union",
            "   model is what the registry exists to prevent.",
        ]

    out += [
        "",
        "Then verify, and commit through the git skill:",
        "",
        "  python3 -m pytest tests/ -q",
        f"  cd {rel(conv.project)}",
        f"  dbt parse --vars '{{\"uid\": \"<tenant>\", \"{conv.var_for(source)}\": true}}'",
        f"  dbt build --select tag:{source} --vars '{{\"uid\": \"<tenant>\", "
        f'"{conv.var_for(source)}": true}}\'',
        "",
        f"  bash .claude/commands/infra/git-standard.sh \\",
        f'      "feat({source}): add {display} connector to {conv.use_case.name}"',
        "",
    ]
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
