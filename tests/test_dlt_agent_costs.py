"""Tests for scripts/dlt_agent_costs.py — the agent-costs blueprint on OSS dlt.

The blueprint this implements is a dltHub Platform product whose page publishes no
code, so there is no upstream behaviour to compare against. What is pinned here is
the set of decisions that make a cost report trustworthy, each of which is easy to
get wrong in a way that still produces a confident-looking number:

1. **An unpriced model is null, never zero.** Zero sums. A dashboard fed zeros
   reports a model as free rather than as unmeasured, and nobody checks a number
   that looks fine.
2. **Cache reads are priced apart from input.** They dominate token volume on real
   traces and cost a fraction of fresh input; folding them together overstates spend
   by roughly an order of magnitude.
3. **A rate card must cite its source** (analytics rule 5). The arithmetic works
   identically with invented prices, so the citation is the only thing standing
   between a demo and a wrong invoice.
4. **The grain is one row per assistant turn.** A session-level row cannot attribute
   a mid-session model switch, which is the normal case.

`dlt` is optional here, exactly as sqlglot is in `test_dbt_column_lineage.py`: the
pricing and reader tests run everywhere, and only the end-to-end load skips.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import dlt_agent_costs as ac  # noqa: E402

USE_CASE = REPO / "skill-packs/dlt-skills/use-cases/agent-costs-demo"
RATE_CARD = USE_CASE / "pricing/rate-card.json"

needs_dlt = pytest.mark.skipif(ac.dlt is None, reason="dlt not installed (optional)")
needs_demo = pytest.mark.skipif(not RATE_CARD.is_file(), reason="demo use-case not on this branch")


# --- pricing ---------------------------------------------------------------------------

@needs_demo
def test_an_unpriced_model_is_none_not_zero() -> None:
    card = ac.RateCard.load(RATE_CARD)
    tokens = {"input": 1000, "output": 1000, "cache_creation": 0, "cache_read": 0}
    assert card.price("demo-large", tokens) is not None
    assert card.price("model-nobody-declared", tokens) is None, (
        "an unpriced model must not price as 0.0 — zero sums into a total and reads as free"
    )


@needs_demo
def test_cache_reads_are_priced_apart_from_fresh_input() -> None:
    """The distinction the blueprint's 'margin, not just cost' claim rests on."""
    card = ac.RateCard.load(RATE_CARD)
    n = 1_000_000
    fresh = card.price("demo-large", {"input": n, "output": 0, "cache_creation": 0, "cache_read": 0})
    cached = card.price("demo-large", {"input": 0, "output": 0, "cache_creation": 0, "cache_read": n})
    assert fresh is not None and cached is not None
    assert cached < fresh, "cache reads must be cheaper than fresh input or the model is wrong"


def test_a_rate_card_without_a_source_is_refused(tmp_path: Path) -> None:
    """Rule 5. The arithmetic is identical with invented prices, so the citation is
    the only check a reader has."""
    path = tmp_path / "rate-card.json"
    path.write_text(json.dumps({"models": {"m": dict.fromkeys(ac.TOKEN_KINDS, 1.0)}}))
    with pytest.raises(SystemExit):
        ac.RateCard.load(path)


def test_a_rate_card_missing_a_token_kind_is_refused(tmp_path: Path) -> None:
    """A partial rate silently prices some tokens at nothing."""
    path = tmp_path / "rate-card.json"
    path.write_text(json.dumps({"source": "test", "models": {"m": {"input": 1.0}}}))
    with pytest.raises(SystemExit):
        ac.RateCard.load(path)


# --- the reader ------------------------------------------------------------------------

@needs_demo
def test_only_assistant_turns_with_usage_become_events() -> None:
    """Every other line in a transcript is conversation state. Counting them would
    inflate turn counts, and `iterations` inside usage restates the same totals."""
    traces = sorted((USE_CASE / "pipelines").glob("*.jsonl"))
    assert traces, "the demo use-case ships no traces"
    rows = ac.collect(traces, "claude-code")
    assert rows, "no usage events read"
    assert all(r["agent"] == "claude-code" for r in rows)
    assert all(r.get("turn_id") for r in rows), "every event needs a turn id — the grain"
    assert {r["session_id"] for r in rows} == {"sess-alpha", "sess-beta"}


@needs_demo
def test_the_demo_carries_an_unpriced_model_on_purpose() -> None:
    """A fixture where everything prices cannot demonstrate the abstain path, which is
    the behaviour most likely to be quietly removed."""
    rows = ac.collect(sorted((USE_CASE / "pipelines").glob("*.jsonl")), "claude-code")
    _, unpriced = ac.price_rows(rows, ac.RateCard.load(RATE_CARD))
    assert unpriced >= 1


# --- end to end -------------------------------------------------------------------------

@needs_dlt
@needs_demo
def test_the_pipeline_loads_and_the_marts_answer(tmp_path: Path) -> None:
    """The whole point: OSS dlt, a local DuckDB, and three marts — no Platform."""
    rows = ac.collect(sorted((USE_CASE / "pipelines").glob("*.jsonl")), "claude-code")
    card = ac.RateCard.load(RATE_CARD)
    rows, _ = ac.price_rows(rows, card)
    dest = tmp_path / "warehouse.duckdb"
    ac.run_pipeline(rows, card, name="agent_costs_test", dataset="agent_costs",
                    destination="duckdb", dest_path=dest)
    assert dest.is_file()

    marts = ac.query_marts(dest, "agent_costs")
    assert set(marts) == {"by_model", "by_session", "by_branch"}
    by_model = {r["model"]: r for r in marts["by_model"]}
    assert "unpriced-model" in by_model
    assert by_model["unpriced-model"]["cost"] is None, "an unpriced model must not total to 0"
    assert by_model["demo-large"]["cost"] > 0

    total_turns = sum(r["turns"] for r in marts["by_session"])
    assert total_turns == len(rows), "the marts must account for every event exactly once"


@needs_dlt
@needs_demo
def test_dlt_itself_recorded_the_load(tmp_path: Path) -> None:
    """`_dlt_loads` is written by dlt, not by this module. Its presence is what
    distinguishes a real pipeline run from a script that wrote a DuckDB file."""
    duckdb = pytest.importorskip("duckdb")
    rows, _ = ac.price_rows(
        ac.collect(sorted((USE_CASE / "pipelines").glob("*.jsonl")), "claude-code"),
        ac.RateCard.load(RATE_CARD),
    )
    dest = tmp_path / "warehouse.duckdb"
    ac.run_pipeline(rows, ac.RateCard.load(RATE_CARD), name="agent_costs_state",
                    dataset="agent_costs", destination="duckdb", dest_path=dest)
    con = duckdb.connect(str(dest), read_only=True)
    try:
        tables = {r[0] for r in con.execute(
            "select table_name from information_schema.tables where table_schema='agent_costs'"
        ).fetchall()}
        assert {"_dlt_loads", "_dlt_version", "usage_events", "model_pricing"} <= tables
    finally:
        con.close()


# --- what the demo may not claim ---------------------------------------------------------

@needs_demo
def test_the_demo_rate_card_is_declared_synthetic() -> None:
    """These prices are made up, and a reader who mistakes them for a vendor's list
    gets a confident wrong invoice. The word has to be in the file, not in a README
    nobody opens — it is loaded into `model_pricing` beside every row it priced."""
    source = json.loads(RATE_CARD.read_text(encoding="utf-8"))["source"]
    assert "SYNTHETIC" in source
