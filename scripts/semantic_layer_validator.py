#!/usr/bin/env python3
"""Validate dbt Core semantic models and metrics against the MetricFlow spec, offline.

`mf validate-configs` is authoritative but needs a warehouse connection and a parsed
project. This catches the structural and spec errors — missing time granularity, filters
without the entity__dimension prefix, cumulative metrics with no time spine, metrics
referencing measures that do not exist — in a second, in CI, with nothing installed.

    python scripts/semantic_layer_validator.py --path models/ --strict

This does NOT replace `mf validate-configs`. Run both: this one first because it is
fast, then MetricFlow for the warehouse-level checks.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _manifest import Colors, Manifest, header, section, severity_tag, table  # noqa: E402
from _miniyaml import MiniYamlError, load, using_pyyaml  # noqa: E402

VALID_ENTITY_TYPES = {"primary", "foreign", "unique", "natural"}
VALID_DIM_TYPES = {"time", "categorical"}
VALID_AGGS = {"sum", "min", "max", "count", "count_distinct", "average", "median",
              "percentile", "sum_boolean"}
VALID_GRANULARITIES = {"nanosecond", "microsecond", "millisecond", "second", "minute",
                       "hour", "day", "week", "month", "quarter", "year"}
VALID_METRIC_TYPES = {"simple", "ratio", "derived", "cumulative", "conversion"}

JINJA_REF = re.compile(r"\{\{\s*(Dimension|TimeDimension|Entity|Metric)\s*\(\s*['\"]([^'\"]+)")
BARE_COLUMN = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*(=|!=|<|>|in|like)", re.I)


class Issue:
    def __init__(self, severity: str, where: str, message: str, fix: str = "") -> None:
        self.severity = severity        # error | warn | info
        self.where = where
        self.message = message
        self.fix = fix

    def as_dict(self) -> Dict[str, Any]:
        return {"severity": self.severity, "where": self.where,
                "message": self.message, "fix": self.fix}


def collect_yaml(path: str) -> List[str]:
    if os.path.isfile(path):
        return [path]
    out: List[str] = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ("target", "dbt_packages", ".git", "logs")]
        for name in files:
            if name.endswith((".yml", ".yaml")):
                out.append(os.path.join(root, name))
    return sorted(out)


def validate_filter(expr: Any, where: str, issues: List[Issue]) -> None:
    exprs = expr if isinstance(expr, list) else [expr]
    for item in exprs:
        if not isinstance(item, str):
            continue
        refs = JINJA_REF.findall(item)
        if not refs:
            issues.append(Issue(
                "error", where,
                f"filter has no Jinja object: {item!r}",
                "Filters use {{ Dimension('entity__dim') }}, {{ TimeDimension(...) }}, "
                "{{ Entity(...) }}, or {{ Metric(...) }} — not raw column names.",
            ))
            continue
        for kind, name in refs:
            if kind in ("Dimension", "TimeDimension") and "__" not in name:
                issues.append(Issue(
                    "error", where,
                    f"{kind}('{name}') is missing the entity prefix",
                    "Use entity__dimension, e.g. Dimension('order__order_status'). "
                    "This is the single most common MetricFlow filter error.",
                ))


def validate_semantic_model(sm: Dict[str, Any], file: str,
                            issues: List[Issue]) -> Dict[str, Any]:
    name = sm.get("name", "<unnamed>")
    where = f"{os.path.basename(file)}:semantic_model[{name}]"
    info: Dict[str, Any] = {"name": name, "measures": set(), "entities": set(),
                            "primary_entity": None, "has_time_dim": False}

    if not sm.get("name"):
        issues.append(Issue("error", where, "semantic model has no `name`"))
    model_ref = sm.get("model")
    if not model_ref:
        issues.append(Issue("error", where, "no `model:` — a semantic model must point "
                                            "at a dbt model", "model: ref('fct_orders')"))
    elif isinstance(model_ref, str) and "ref(" not in model_ref:
        issues.append(Issue("warn", where,
                            f"model is {model_ref!r} — expected ref('...')"))
    elif isinstance(model_ref, str):
        target = re.search(r"ref\(\s*['\"]([^'\"]+)", model_ref)
        if target and target.group(1).startswith("stg_"):
            issues.append(Issue(
                "warn", where,
                f"semantic model sits on a staging model ({target.group(1)})",
                "The semantic layer describes the business; staging describes a source "
                "system. Put semantic models on marts.",
            ))

    # entities
    entities = sm.get("entities") or []
    primaries = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        ename = entity.get("name", "<unnamed>")
        info["entities"].add(ename)
        etype = entity.get("type")
        if etype not in VALID_ENTITY_TYPES:
            issues.append(Issue("error", f"{where}.entity[{ename}]",
                                f"type {etype!r} is not one of "
                                f"{sorted(VALID_ENTITY_TYPES)}"))
        if etype == "primary":
            primaries.append(ename)
    if len(primaries) > 1:
        issues.append(Issue("error", where,
                            f"more than one primary entity: {primaries}",
                            "Exactly one entity defines the model's grain."))
    info["primary_entity"] = primaries[0] if primaries else sm.get("primary_entity")
    if not info["primary_entity"]:
        issues.append(Issue(
            "error", where,
            "no primary entity",
            "Declare `type: primary` on one entity, or set `primary_entity:` at the "
            "semantic-model level. Without it, joins and grain are undefined.",
        ))

    # dimensions
    defaults = sm.get("defaults") or {}
    agg_time = defaults.get("agg_time_dimension")
    time_dims: Set[str] = set()
    for dim in sm.get("dimensions") or []:
        if not isinstance(dim, dict):
            continue
        dname = dim.get("name", "<unnamed>")
        dwhere = f"{where}.dimension[{dname}]"
        dtype = dim.get("type")
        if dtype not in VALID_DIM_TYPES:
            issues.append(Issue("error", dwhere,
                                f"type {dtype!r} is not 'time' or 'categorical'"))
        if dtype == "time":
            time_dims.add(dname)
            info["has_time_dim"] = True
            params = dim.get("type_params") or {}
            granularity = params.get("time_granularity")
            if not granularity:
                issues.append(Issue(
                    "error", dwhere,
                    "time dimension has no type_params.time_granularity",
                    "type_params: {time_granularity: day} — this is the most common "
                    "MetricFlow validation failure.",
                ))
            elif granularity not in VALID_GRANULARITIES:
                issues.append(Issue("error", dwhere,
                                    f"time_granularity {granularity!r} is not one of "
                                    f"{sorted(VALID_GRANULARITIES)}"))

    if agg_time and agg_time not in time_dims:
        issues.append(Issue(
            "error", where,
            f"defaults.agg_time_dimension is '{agg_time}' but no time dimension has "
            f"that name (found: {sorted(time_dims) or 'none'})",
        ))
    if not agg_time and time_dims:
        issues.append(Issue(
            "warn", where,
            "no defaults.agg_time_dimension",
            "Without it, `metric_time` is unavailable and metrics from different "
            "semantic models cannot align on one timeline.",
        ))

    # measures
    is_scd = any(
        ((d.get("type_params") or {}).get("validity_params"))
        for d in (sm.get("dimensions") or []) if isinstance(d, dict)
    )
    measures = sm.get("measures") or []
    for measure in measures:
        if not isinstance(measure, dict):
            continue
        mname = measure.get("name", "<unnamed>")
        info["measures"].add(mname)
        mwhere = f"{where}.measure[{mname}]"
        agg = measure.get("agg")
        if agg not in VALID_AGGS:
            issues.append(Issue("error", mwhere,
                                f"agg {agg!r} is not one of {sorted(VALID_AGGS)}"))
        if agg == "percentile":
            params = measure.get("agg_params") or {}
            if params.get("percentile") is None:
                issues.append(Issue("error", mwhere,
                                    "agg: percentile requires agg_params.percentile"))
        mtime = measure.get("agg_time_dimension") or agg_time
        if not mtime and info["has_time_dim"]:
            issues.append(Issue("warn", mwhere,
                                "no agg_time_dimension on the measure and no default"))
    if is_scd and measures:
        issues.append(Issue(
            "error", where,
            "SCD Type 2 semantic model (validity_params present) declares measures",
            "SCD2 semantic models provide point-in-time dimensions only — they hold no "
            "measures and no metrics.",
        ))

    if not measures and not is_scd:
        issues.append(Issue("info", where, "semantic model declares no measures"))

    return info


def validate_metric(metric: Dict[str, Any], file: str, measures: Set[str],
                    metric_names: Set[str], has_spine: bool,
                    issues: List[Issue]) -> None:
    name = metric.get("name", "<unnamed>")
    where = f"{os.path.basename(file)}:metric[{name}]"
    mtype = metric.get("type")
    params = metric.get("type_params") or {}

    if not metric.get("name"):
        issues.append(Issue("error", where, "metric has no `name`"))
    if mtype not in VALID_METRIC_TYPES:
        issues.append(Issue("error", where,
                            f"type {mtype!r} is not one of {sorted(VALID_METRIC_TYPES)}"))
        return
    if not metric.get("label"):
        issues.append(Issue("info", where, "no `label` — consumers see the raw name"))
    if not (metric.get("description") or "").strip():
        issues.append(Issue(
            "warn", where,
            "no description",
            "A metric without its written definition is how two dashboards start "
            "disagreeing. Record what is included and excluded.",
        ))

    if "filter" in metric:
        validate_filter(metric["filter"], f"{where}.filter", issues)

    def check_measure(ref: Any, sub: str) -> None:
        mname = ref.get("name") if isinstance(ref, dict) else ref
        if isinstance(ref, dict) and "filter" in ref:
            validate_filter(ref["filter"], f"{where}.{sub}.filter", issues)
        if mname and measures and mname not in measures:
            issues.append(Issue(
                "error", f"{where}.{sub}",
                f"references measure '{mname}' which is not defined in any semantic "
                f"model in this path",
            ))

    if mtype == "simple":
        measure = params.get("measure")
        if not measure:
            issues.append(Issue("error", where, "simple metric has no type_params.measure"))
        else:
            check_measure(measure, "measure")
            if isinstance(measure, dict) and measure.get("join_to_timespine") and not has_spine:
                issues.append(Issue("error", where,
                                    "join_to_timespine: true but no time spine model found"))

    elif mtype == "ratio":
        for side in ("numerator", "denominator"):
            ref = params.get(side)
            if not ref:
                issues.append(Issue("error", where, f"ratio metric has no {side}"))
                continue
            rname = ref.get("name") if isinstance(ref, dict) else ref
            if isinstance(ref, dict) and "filter" in ref:
                validate_filter(ref["filter"], f"{where}.{side}.filter", issues)
            if rname and metric_names and measures:
                if rname not in metric_names and rname not in measures:
                    issues.append(Issue("error", f"{where}.{side}",
                                        f"'{rname}' is neither a defined metric nor a "
                                        f"measure"))

    elif mtype == "derived":
        expr = params.get("expr")
        inputs = params.get("metrics") or []
        if not expr:
            issues.append(Issue("error", where, "derived metric has no type_params.expr"))
        if not inputs:
            issues.append(Issue("error", where, "derived metric has no type_params.metrics"))
        aliases: Set[str] = set()
        for item in inputs:
            if not isinstance(item, dict):
                continue
            iname = item.get("name")
            alias = item.get("alias") or iname
            aliases.add(str(alias))
            if iname and metric_names and iname not in metric_names:
                issues.append(Issue("error", where,
                                    f"input metric '{iname}' is not defined"))
            if item.get("offset_window") and item.get("offset_to_grain"):
                issues.append(Issue("error", where,
                                    f"input '{alias}' sets both offset_window and "
                                    f"offset_to_grain — they are alternatives"))
            if (item.get("offset_window") or item.get("offset_to_grain")) and not has_spine:
                issues.append(Issue("error", where,
                                    "uses a time offset but no time spine model found"))
            if "filter" in item:
                validate_filter(item["filter"], f"{where}.metrics[{alias}].filter", issues)
        if isinstance(expr, str):
            if "/" in expr and "nullif" not in expr.lower():
                issues.append(Issue(
                    "warn", where,
                    "expr divides without nullif — division by zero is real",
                    "(a - b) * 100.0 / nullif(b, 0)",
                ))
            for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expr):
                if token.lower() in ("nullif", "coalesce", "case", "when", "then",
                                     "else", "end", "cast", "as", "abs", "greatest",
                                     "least", "null"):
                    continue
                if aliases and token not in aliases:
                    issues.append(Issue(
                        "warn", where,
                        f"expr references '{token}' which is not an input metric or "
                        f"alias ({sorted(aliases)})",
                    ))

    elif mtype == "cumulative":
        if not params.get("measure"):
            issues.append(Issue("error", where, "cumulative metric has no type_params.measure"))
        else:
            check_measure(params["measure"], "measure")
        window = params.get("window")
        grain = params.get("grain_to_date")
        if window and grain:
            issues.append(Issue(
                "error", where,
                "window and grain_to_date are mutually exclusive",
                "Use one: `window: 28 days` for a trailing window, `grain_to_date: "
                "month` for period-to-date.",
            ))
        if not has_spine:
            issues.append(Issue(
                "error", where,
                "cumulative metric but no time spine model found in this path",
                "Add a metricflow_time_spine model with `time_spine: "
                "{standard_granularity_column: date_day}`. Cumulative metrics cannot "
                "compute without it.",
            ))
        period_agg = params.get("period_agg")
        if period_agg and period_agg not in ("first", "last", "average"):
            issues.append(Issue("error", where,
                                f"period_agg {period_agg!r} must be first, last, or average"))

    elif mtype == "conversion":
        conv = params.get("conversion_type_params") or {}
        if not conv:
            issues.append(Issue("error", where,
                                "conversion metric has no type_params.conversion_type_params"))
            return
        for required in ("entity", "base_measure", "conversion_measure"):
            if not conv.get(required):
                issues.append(Issue("error", where,
                                    f"conversion_type_params is missing '{required}'"))
        calc = conv.get("calculation", "conversion_rate")
        if calc not in ("conversion_rate", "conversions"):
            issues.append(Issue("error", where,
                                f"calculation {calc!r} must be conversion_rate or "
                                f"conversions"))
        if not conv.get("window"):
            issues.append(Issue(
                "warn", where,
                "no conversion window",
                "Without a window, any later conversion counts — usually not what the "
                "business means.",
            ))
        for key in ("base_measure", "conversion_measure"):
            if conv.get(key):
                check_measure(conv[key], key)


def find_time_spine(files: List[str], docs: Dict[str, Any]) -> bool:
    for path, doc in docs.items():
        if not isinstance(doc, dict):
            continue
        for model in doc.get("models") or []:
            if isinstance(model, dict) and model.get("time_spine"):
                return True
            # older config style
            if isinstance(model, dict):
                cfg = model.get("config") or {}
                if cfg.get("time_spine"):
                    return True
    return any("time_spine" in os.path.basename(f) for f in files)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate MetricFlow semantic models and metrics offline."
    )
    ap.add_argument("--path", default="models/",
                    help="a directory to walk, or a single YAML file")
    ap.add_argument("--manifest", help="target/manifest.json — cross-checks that "
                                       "referenced dbt models exist")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any error")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print(f"ERROR: path not found: {args.path}", file=sys.stderr)
        return 2

    files = collect_yaml(args.path)
    issues: List[Issue] = []
    docs: Dict[str, Any] = {}

    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            issues.append(Issue("warn", path, f"could not read: {exc}"))
            continue
        if not re.search(r"^\s*(semantic_models|metrics|saved_queries|time_spine):",
                         text, re.M):
            continue
        try:
            docs[path] = load(text)
        except (MiniYamlError, Exception) as exc:  # noqa: BLE001 - PyYAML raises its own
            issues.append(Issue(
                "error", path,
                f"could not parse YAML: {exc}",
                "" if using_pyyaml() else
                "The bundled minimal parser does not support anchors, aliases, or "
                "multi-document files. `pip install pyyaml` if this file needs them.",
            ))

    semantic_files = [p for p, d in docs.items()
                      if isinstance(d, dict) and (d.get("semantic_models") or d.get("metrics"))]

    header("Semantic layer validation")
    print(f"  scanned {len(files)} YAML file(s) under {args.path}")
    print(f"  {len(semantic_files)} file(s) contain semantic models or metrics")
    print(f"  YAML parser: {'PyYAML' if using_pyyaml() else 'bundled minimal parser'}")

    if not semantic_files and not issues:
        print(f"\n  {Colors.YELLOW}No semantic models or metrics found. If you expected "
              f"some, check --path.{Colors.END}")
        return 0

    all_measures: Set[str] = set()
    all_metrics: Set[str] = set()
    semantic_infos: List[Dict[str, Any]] = []
    has_spine = find_time_spine(files, docs)

    # pass 1 — semantic models, gathering measure and metric names
    for path, doc in docs.items():
        if not isinstance(doc, dict):
            continue
        for sm in doc.get("semantic_models") or []:
            if isinstance(sm, dict):
                info = validate_semantic_model(sm, path, issues)
                semantic_infos.append(info)
                all_measures |= info["measures"]
                for metric in sm.get("metrics") or []:
                    if isinstance(metric, dict) and metric.get("name"):
                        all_metrics.add(metric["name"])
        for metric in doc.get("metrics") or []:
            if isinstance(metric, dict) and metric.get("name"):
                all_metrics.add(metric["name"])

    # pass 2 — metrics, now that every name is known
    for path, doc in docs.items():
        if not isinstance(doc, dict):
            continue
        for metric in doc.get("metrics") or []:
            if isinstance(metric, dict):
                validate_metric(metric, path, all_measures, all_metrics, has_spine, issues)
        for sm in doc.get("semantic_models") or []:
            if isinstance(sm, dict):
                for metric in sm.get("metrics") or []:
                    if isinstance(metric, dict):
                        validate_metric(metric, path, all_measures, all_metrics,
                                        has_spine, issues)

    # cross-check against the manifest
    if args.manifest and os.path.exists(args.manifest):
        man = Manifest.load(args.manifest)
        model_names = {n.get("name") for n in man.models().values()}
        for path, doc in docs.items():
            if not isinstance(doc, dict):
                continue
            for sm in doc.get("semantic_models") or []:
                if not isinstance(sm, dict):
                    continue
                ref = sm.get("model")
                target = re.search(r"ref\(\s*['\"]([^'\"]+)", str(ref or ""))
                if target and target.group(1) not in model_names:
                    issues.append(Issue(
                        "error", f"{os.path.basename(path)}:semantic_model"
                                 f"[{sm.get('name')}]",
                        f"references dbt model '{target.group(1)}' which does not exist",
                    ))

    # entity join reachability
    primaries = {i["primary_entity"] for i in semantic_infos if i["primary_entity"]}
    for info in semantic_infos:
        for entity in info["entities"]:
            if entity != info["primary_entity"] and entity not in primaries:
                issues.append(Issue(
                    "warn", f"semantic_model[{info['name']}]",
                    f"foreign entity '{entity}' has no matching primary entity in any "
                    f"semantic model — cross-model queries on it will fail",
                ))

    if not has_spine:
        issues.append(Issue(
            "info", "project",
            "no time spine model found",
            "Required for cumulative metrics, offset_window, and join_to_timespine. "
            "Build one with dbt_utils.date_spine and add `time_spine:` to its YAML.",
        ))

    # ---- report
    counts = {"error": 0, "warn": 0, "info": 0}
    for issue in issues:
        counts[issue.severity] += 1

    section(f"Summary — {len(semantic_infos)} semantic model(s), "
            f"{len(all_metrics)} metric(s), {len(all_measures)} measure(s)")
    print(f"  time spine: {'found' if has_spine else Colors.YELLOW + 'not found' + Colors.END}")
    print(f"  {severity_tag('error')}  {counts['error']}")
    print(f"  {severity_tag('warn')}  {counts['warn']}")
    print(f"  {severity_tag('info')}  {counts['info']}")

    for severity in ("error", "warn", "info"):
        group = [i for i in issues if i.severity == severity]
        if not group:
            continue
        section(f"{severity.upper()} ({len(group)})")
        for issue in group:
            print(f"  {severity_tag(severity)} {issue.where}")
            print(f"        {issue.message}")
            if issue.fix:
                print(f"        {Colors.GREY}fix: {issue.fix}{Colors.END}")

    if not issues:
        print(f"\n  {Colors.GREEN}No issues found.{Colors.END}")

    section("Next")
    print("  This is a fast offline pre-check, not a replacement for MetricFlow:")
    print("    dbt parse && mf validate-configs")
    print("    mf query --metrics <m> --group-by metric_time__month --explain")
    print("  Then compare the generated SQL's output against a hand-written query you")
    print("  trust. A metric that validates and returns the wrong number is worse than")
    print("  no metric, because it carries the semantic layer's authority.")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"counts": counts, "has_time_spine": has_spine,
                       "metrics": sorted(all_metrics), "measures": sorted(all_measures),
                       "issues": [i.as_dict() for i in issues]}, fh, indent=2)
        print(f"\n  Wrote {args.json_out}")

    if args.strict and counts["error"]:
        print(f"\n{Colors.RED}--strict: {counts['error']} error(s).{Colors.END}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
