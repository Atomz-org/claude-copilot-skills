#!/usr/bin/env python3
"""Agent cost attribution on **OSS dlt** — the `agent-costs` blueprint, unbundled.

dltHub publishes `agent-costs` as a dltHub Platform product. Its page states the
behaviour and nothing else: no schema, no code, no file names, no CLI. So this is
not a port. It is the same problem solved against `dlt` + DuckDB, and every design
decision below is one the blueprint page leaves open.

What it does: read coding-agent session traces, load them through a dlt pipeline
into a warehouse, price them against a **declared** rate card, and project three
marts — by model, by session, by branch.

    python3 scripts/dlt_agent_costs.py --use-case agent-costs-demo --run
    python3 scripts/dlt_agent_costs.py --use-case agent-costs-demo --report
    python3 scripts/dlt_agent_costs.py --source claude-code --project <slug> --run

Four rules decide whether the output can be trusted, and each is this repository's
existing doctrine applied to a new pipeline:

- **A price is declared, never recalled** (analytics rule 5). Model prices change,
  they differ per contract, and a plausible-looking rate produces a plausible-looking
  invoice that is wrong. `pricing/rate-card.json` is a hand-owned input; a model with
  no entry is priced `null` and *counted*, never silently zeroed. `--report` states
  the unpriced share on every run, because a cost report that quietly omits a model
  is worse than one that admits it.
- **Cache reads are a separate rate.** The whole claim of the blueprint is margin
  rather than raw spend, and on these traces cache-read tokens dominate volume while
  costing a fraction of fresh input. Folding them into `input_tokens` overstates cost
  by an order of magnitude. They are loaded as their own column and priced separately.
- **The trace is the grain** (analytics rule 4). One row per assistant turn per
  session — `one row per agent response`. A session-level row cannot attribute a model
  switch mid-session, which is the normal case here.
- **Nothing leaves the machine.** DuckDB by default, no network destination, matching
  the blueprint's own "runs entirely in your own data warehouse" claim.

`dlt` is an optional dependency, the same shape as sqlglot in `dbt_column_lineage.py`
and rdflib in `ontology_generator.py`: absent, this module still imports and its
readers and pricing still work, and only `--run` declines.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _paths import REPO, require_use_case_dir  # noqa: E402

try:  # optional, the same shape as sqlglot in dbt_column_lineage.py
    import dlt
except ImportError:  # pragma: no cover - exercised by the no-dlt path
    dlt = None  # type: ignore[assignment]

TOKEN_KINDS = ("input", "output", "cache_creation", "cache_read")


def die(message: str, code: int = 2) -> "NoReturn":  # type: ignore[valid-type]
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


# --- the rate card ---------------------------------------------------------------------


@dataclass
class RateCard:
    """Prices per million tokens, keyed by model.

    `source` is mandatory and unused by the arithmetic — it exists so a reader can
    check the number against the page it came from. A rate card with no citation is
    the invented-number failure mode rule 5 exists to stop, and it is invisible in
    the output precisely because the arithmetic still works.
    """

    rates: dict[str, dict[str, float]] = field(default_factory=dict)
    source: str = ""

    @classmethod
    def load(cls, path: Path) -> "RateCard":
        doc = json.loads(path.read_text(encoding="utf-8"))
        source = (doc.get("source") or "").strip()
        if not source:
            die(f"{path} declares no `source`. A rate nobody can check is not a rate.")
        rates: dict[str, dict[str, float]] = {}
        for model, entry in (doc.get("models") or {}).items():
            missing = [k for k in TOKEN_KINDS if k not in entry]
            if missing:
                die(f"{path}: model {model!r} is missing rate(s) {missing}")
            rates[model] = {k: float(entry[k]) for k in TOKEN_KINDS}
        return cls(rates=rates, source=source)

    def price(self, model: str, tokens: dict[str, int]) -> Optional[float]:
        """Cost in currency units, or None when this model has no declared rate.

        None rather than 0.0 deliberately: zero is a number a dashboard will happily
        sum, and an unpriced model would then read as a free one.
        """
        rate = self.rates.get(model)
        if rate is None:
            return None
        return sum(tokens.get(k, 0) / 1_000_000 * rate[k] for k in TOKEN_KINDS)


# --- readers ---------------------------------------------------------------------------


def read_claude_code(path: Path) -> Iterator[dict[str, Any]]:
    """One row per assistant turn from a Claude Code `.jsonl` session transcript.

    Only `type == "assistant"` turns carry `message.usage`; every other line is
    conversation state. `iterations` inside usage is a per-request breakdown of the
    same totals, so summing it would double-count the turn.
    """
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("type") != "assistant":
            continue
        message = row.get("message") or {}
        usage = message.get("usage") or {}
        if not usage:
            continue
        yield {
            "agent": "claude-code",
            "session_id": row.get("sessionId"),
            "turn_id": message.get("id") or row.get("requestId"),
            "occurred_at": row.get("timestamp"),
            "model": message.get("model"),
            "effort": row.get("effort"),
            "project": Path(row.get("cwd") or "").name or None,
            "git_branch": row.get("gitBranch") or None,
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_creation_tokens": int(usage.get("cache_creation_input_tokens") or 0),
            "cache_read_tokens": int(usage.get("cache_read_input_tokens") or 0),
            "service_tier": usage.get("service_tier"),
        }


def read_generic_jsonl(path: Path, agent: str) -> Iterator[dict[str, Any]]:
    """Cursor and Codex export flat usage rows rather than a conversation transcript.

    Their exact keys move between versions — the blueprint's own pitch is "adapting as
    formats change" — so this maps a small declared alias set and drops nothing
    silently: an unmapped row still loads, with null tokens, and shows up as unpriced.
    """
    alias = {
        "prompt_tokens": "input_tokens",
        "completion_tokens": "output_tokens",
        "cached_tokens": "cache_read_tokens",
        "timestamp": "occurred_at",
        "ts": "occurred_at",
        "session": "session_id",
    }
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        row = {alias.get(k, k): v for k, v in raw.items()}
        row.setdefault("agent", agent)
        for kind in ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens"):
            row[kind] = int(row.get(kind) or 0)
        yield row


READERS = {"claude-code": read_claude_code, "cursor": read_generic_jsonl, "codex": read_generic_jsonl}


def collect(paths: Iterable[Path], agent: str) -> list[dict[str, Any]]:
    reader = READERS.get(agent)
    if reader is None:
        die(f"unknown agent {agent!r}; known: {', '.join(sorted(READERS))}")
    rows: list[dict[str, Any]] = []
    for path in paths:
        if agent == "claude-code":
            rows.extend(read_claude_code(path))
        else:
            rows.extend(read_generic_jsonl(path, agent))
    return rows


def price_rows(rows: list[dict[str, Any]], card: RateCard) -> tuple[list[dict[str, Any]], int]:
    """Attach `cost` to every row; return the rows and how many went unpriced."""
    unpriced = 0
    for row in rows:
        tokens = {
            "input": row.get("input_tokens", 0),
            "output": row.get("output_tokens", 0),
            "cache_creation": row.get("cache_creation_tokens", 0),
            "cache_read": row.get("cache_read_tokens", 0),
        }
        cost = card.price(row.get("model") or "", tokens)
        row["cost"] = cost
        row["priced"] = cost is not None
        if cost is None:
            unpriced += 1
    return rows, unpriced


# --- the dlt pipeline -------------------------------------------------------------------


def build_pipeline(name: str, dataset: str, destination: str, dest_path: Optional[Path]):
    if dlt is None:
        die("dlt is not installed. `pip install 'dlt[duckdb]'` — it is an optional dependency.")
    kwargs: dict[str, Any] = {"pipeline_name": name, "dataset_name": dataset}
    if destination == "duckdb" and dest_path is not None:
        kwargs["destination"] = dlt.destinations.duckdb(str(dest_path))
    else:
        kwargs["destination"] = destination
    return dlt.pipeline(**kwargs)


def run_pipeline(rows: list[dict[str, Any]], card: RateCard, *, name: str, dataset: str,
                 destination: str, dest_path: Optional[Path]) -> dict[str, Any]:
    """Load usage events and the rate card that priced them, in one pipeline run.

    The rate card is loaded as a table rather than left on disk so that a warehouse
    query can answer "which rates produced this number" without the repository — the
    same reason `provenance` exists in the ontology index.
    """
    pipeline = build_pipeline(name, dataset, destination, dest_path)

    @dlt.resource(name="usage_events", write_disposition="replace")
    def usage_events():
        yield from rows

    @dlt.resource(name="model_pricing", write_disposition="replace")
    def model_pricing():
        for model, rate in card.rates.items():
            yield {"model": model, "source": card.source,
                   **{f"{k}_per_mtok": v for k, v in rate.items()}}

    info = pipeline.run([usage_events(), model_pricing()])
    return {"pipeline": name, "dataset": dataset, "rows": len(rows), "load_info": str(info)}


# --- marts ------------------------------------------------------------------------------

MARTS = {
    "by_model": """
        select model,
               count(*)                      as turns,
               sum(input_tokens)             as input_tokens,
               sum(output_tokens)            as output_tokens,
               sum(cache_read_tokens)        as cache_read_tokens,
               sum(cost)                     as cost,
               sum(case when priced then 0 else 1 end) as unpriced_turns
        from usage_events group by model order by cost desc nulls last
    """,
    "by_session": """
        select session_id, min(occurred_at) as started_at, count(*) as turns, sum(cost) as cost
        from usage_events group by session_id order by cost desc nulls last
    """,
    "by_branch": """
        select coalesce(git_branch, '(none)') as git_branch,
               count(*) as turns, sum(cost) as cost
        from usage_events group by git_branch order by cost desc nulls last
    """,
}


def query_marts(dest_path: Path, dataset: str) -> dict[str, list[dict[str, Any]]]:
    import duckdb

    con = duckdb.connect(str(dest_path), read_only=True)
    try:
        con.execute(f"set search_path='{dataset}'")
        out = {}
        for mart, sql in MARTS.items():
            cur = con.execute(sql)
            cols = [d[0] for d in cur.description]
            out[mart] = [dict(zip(cols, r)) for r in cur.fetchall()]
        return out
    finally:
        con.close()


# --- CLI ---------------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--use-case", help="use-case slug under skill-packs/dlt-skills/use-cases/")
    ap.add_argument("--traces", type=Path, nargs="*", help="explicit trace files")
    ap.add_argument("--source", default="claude-code", choices=sorted(READERS))
    ap.add_argument("--rate-card", type=Path)
    ap.add_argument("--destination", default="duckdb")
    ap.add_argument("--run", action="store_true", help="execute the dlt pipeline")
    ap.add_argument("--report", action="store_true", help="print the marts")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    args = ap.parse_args(argv)

    if args.use_case:
        base = require_use_case_dir(args.use_case, REPO)
        traces = sorted((base / "pipelines").glob("*.jsonl"))
        rate_card = args.rate_card or base / "pricing/rate-card.json"
        dest_path = base / "warehouse.duckdb"
    else:
        traces = list(args.traces or [])
        rate_card = args.rate_card or REPO / "skill-packs/dlt-skills/pricing/rate-card.json"
        dest_path = Path("warehouse.duckdb")

    if not traces:
        die("no trace files found — pass --traces or use a use-case with pipelines/*.jsonl")
    if not rate_card.is_file():
        die(f"no rate card at {rate_card}. Declare prices; this tool will not guess them.")

    card = RateCard.load(rate_card)
    rows, unpriced = price_rows(collect(traces, args.source), card)
    dataset = "agent_costs"

    payload: dict[str, Any] = {
        "traces": [str(p) for p in traces],
        "events": len(rows),
        "unpriced_events": unpriced,
        "rate_card_source": card.source,
        "models_priced": sorted(card.rates),
    }

    if args.run:
        payload["run"] = run_pipeline(rows, card, name="agent_costs", dataset=dataset,
                                      destination=args.destination, dest_path=dest_path)
    if args.report:
        if not dest_path.is_file():
            die(f"no warehouse at {dest_path} — run with --run first")
        payload["marts"] = query_marts(dest_path, dataset)

    if args.format == "json":
        print(json.dumps(payload, indent=2, default=str))
        return 0

    print(f"traces      {len(traces)} file(s), {len(rows)} usage event(s)")
    print(f"rate card   {card.source}")
    print(f"priced      {len(rows) - unpriced}/{len(rows)}"
          + (f"  — {unpriced} event(s) have no declared rate" if unpriced else ""))
    if args.run:
        print(f"loaded      {payload['run']['rows']} row(s) -> {dest_path}")
    for mart, table in (payload.get("marts") or {}).items():
        print(f"\n[{mart}]")
        for row in table[:10]:
            cost = row.get("cost")
            shown = "unpriced" if cost is None else f"{cost:.4f}"
            first = next(iter(row.values()))
            print(f"  {str(first)[:44]:46s} turns={row.get('turns','-'):>5}  cost={shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
