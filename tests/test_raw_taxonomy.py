"""Tests for building the taxonomy and conceptual model from the raw layer.

This script runs *before* any dbt model exists, which removes the safety net every other
ontology artifact here has: there is no manifest to check a claim against, so nothing
downstream will notice if the model is wrong. Three failure modes follow from that, and
each has a test that reproduces it rather than describes it:

1. **Inventing an attribute.** The whole artifact is a description of a warehouse nobody has
   built yet, so an attribute that traces to no declared source column is indistinguishable
   from one that does — until somebody writes the SQL and finds the column missing.
2. **Silence about the grain.** Rule 4 wants one sentence before any SQL. A schema cannot
   supply it, so the only options are to demand it or to let it be absent, and absent is how
   a measure ends up double-counting while every test passes.
3. **Overwriting a decision with a guess.** `--propose` matches names. A rerun that
   clobbered a curated `taxonomy.yml` would make the guess authoritative over the judgement.

The fixture below is a small two-source raw layer rather than a mock, so the pipeline is
exercised end to end: sources.yml -> propose -> taxonomy -> conceptual model -> plan.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import raw_taxonomy as rt  # noqa: E402

SCRIPT = REPO / "scripts" / "raw_taxonomy.py"
ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"

SOURCES_A = """version: 2

sources:
  - name: acme_api
    schema: acme_{{ var('uid') }}
    tables:
      - name: customers
        columns:
          - name: CustomerNumber
          - name: Name
          - name: Email
      - name: invoices
        columns:
          - name: invoiceNumber
          - name: CustomerNumber
          - name: Total
      - name: _dlt_loads
        columns:
          - name: load_id
"""

SOURCES_B = """version: 2

sources:
  - name: other_api
    schema: other_{{ var('uid') }}
    tables:
      - name: customers
        columns:
          - name: CustomerNumber
          - name: Name
          - name: Country
"""


def _tree(tmp_path: Path) -> Path:
    """A use-case with a raw layer and nothing else — the state this script is for."""
    use_case = tmp_path / "skill-packs/dbt-skills/use-cases/demo"
    models = use_case / "dbt_project/models"
    (models / "acme").mkdir(parents=True)
    (models / "other").mkdir(parents=True)
    (models / "acme/sources.yml").write_text(SOURCES_A, encoding="utf-8")
    (models / "other/sources.yml").write_text(SOURCES_B, encoding="utf-8")
    (use_case / "ontology").mkdir(parents=True)
    (use_case / "ontology/ontology.yml").write_text(
        "namespace: https://example.test/demo/\ntitle: Demo\nconcept_classes: {}\n",
        encoding="utf-8",
    )
    return use_case


def _run(tmp_path: Path, monkeypatch, args: list) -> tuple:
    monkeypatch.setattr(rt, "REPO", tmp_path)
    monkeypatch.setattr(rt._paths, "REPO", tmp_path, raising=False)
    return rt.main(args)


# ---------------------------------------------------------------------------------------
# Reading the raw layer
# ---------------------------------------------------------------------------------------


def test_the_raw_layer_reads_through_jinja_bearing_schemas(tmp_path, monkeypatch) -> None:
    """`schema: acme_{{ var('uid') }}` is load-bearing Jinja; a strict YAML parser either
    rejects it or requotes it so dbt stops rendering it."""
    monkeypatch.setattr(rt, "REPO", tmp_path)
    use_case = _tree(tmp_path)
    tables, problems = rt.read_raw_layer(use_case / "dbt_project")
    assert not problems
    assert {t.key for t in tables} == {
        "acme_api.customers", "acme_api.invoices", "acme_api._dlt_loads",
        "other_api.customers",
    }
    assert next(t for t in tables if t.key == "acme_api.customers").columns == [
        "CustomerNumber", "Email", "Name",
    ]


def test_a_table_is_keyed_by_source_and_table_never_by_table_alone() -> None:
    """Two sources.yml here declare eight sources between them; nothing stops two of them
    exposing a `customers`. Keying by table alone merges their schemas silently."""
    a = rt.RawTable("acme_api", "customers", ["CustomerNumber"])
    b = rt.RawTable("other_api", "customers", ["Country"])
    assert a.key != b.key


# ---------------------------------------------------------------------------------------
# Proposing
# ---------------------------------------------------------------------------------------


def test_a_bare_number_column_is_a_natural_key_candidate() -> None:
    """Found against the real raw layer: requiring a stem meant `accounts.Number` — the
    account number — was not a candidate, while `OrgId` and `SalaryCode` were."""
    assert rt.KEY_SHAPES[0].match("Number")
    assert rt.KEY_SHAPES[0].match("CustomerNumber")
    assert not any(s.match("Id") for s in rt.KEY_SHAPES), (
        "a bare Id identifies a row in whichever table it sits in and names no entity"
    )


def test_proposal_ranks_a_cross_source_key_above_a_single_source_one(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(rt, "REPO", tmp_path)
    use_case = _tree(tmp_path)
    tables, _ = rt.read_raw_layer(use_case / "dbt_project")
    result = rt.propose(tables, {"dim_customers": "erp:Customer"}, {})
    keys = result["natural_key_candidates"]["dim_customers"]
    assert keys[0]["column"] == "CustomerNumber"
    assert keys[0]["declared_by"] == 2 and keys[0]["of_tables"] == 2
    assert "Email" in [k["column"] for k in keys]
    assert "unconfirmed" in next(k for k in keys if k["column"] == "Email")["evidence"]


def test_pipeline_bookkeeping_is_excluded_from_proposals(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rt, "REPO", tmp_path)
    use_case = _tree(tmp_path)
    tables, _ = rt.read_raw_layer(use_case / "dbt_project")
    result = rt.propose(tables, {"dim_customers": "erp:Customer"}, {})
    assert "acme_api._dlt_loads" in result["excluded_as_noise"]


def test_an_unmatched_table_is_reported_not_guessed_at(tmp_path, monkeypatch) -> None:
    """A schema cannot know `invoices` is out of scope; saying so is the honest answer."""
    monkeypatch.setattr(rt, "REPO", tmp_path)
    use_case = _tree(tmp_path)
    tables, _ = rt.read_raw_layer(use_case / "dbt_project")
    result = rt.propose(tables, {"dim_customers": "erp:Customer"}, {})
    assert {r["table"] for r in result["unmatched_tables"]} == {"invoices"}


def test_a_confirmed_mapping_is_never_re_proposed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rt, "REPO", tmp_path)
    use_case = _tree(tmp_path)
    tables, _ = rt.read_raw_layer(use_case / "dbt_project")
    existing = {"entities": {"dim_customers": {
        "sources": [{"source": "acme_api", "table": "customers"}]
    }}}
    result = rt.propose(tables, {"dim_customers": "erp:Customer"}, existing)
    proposed = {
        f"{r['source']}.{r['table']}" for rows in result["proposed"].values() for r in rows
    }
    assert "acme_api.customers" not in proposed
    assert "other_api.customers" in proposed
    assert result["already_confirmed"] == 1


def test_propose_refuses_to_overwrite_a_curated_taxonomy(tmp_path, monkeypatch) -> None:
    """The guess must never become authoritative over the judgement."""
    use_case = _tree(tmp_path)
    curated = use_case / "ontology/taxonomy.yml"
    curated.write_text("version: 1\nentities: {}\n", encoding="utf-8")
    rc = _run(tmp_path, monkeypatch, ["--use-case", "demo", "--propose"])
    assert rc == 1
    assert curated.read_text(encoding="utf-8") == "version: 1\nentities: {}\n"


def test_the_scaffold_leaves_grain_empty_rather_than_filling_it(
    tmp_path, monkeypatch
) -> None:
    """Rule 4's sentence is the one thing this file exists to capture; a pre-filled grain
    would be the generator inventing exactly that."""
    use_case = _tree(tmp_path)
    rc = _run(tmp_path, monkeypatch, ["--use-case", "demo", "--propose"])
    assert rc == 0
    text = (use_case / "ontology/taxonomy.yml").read_text(encoding="utf-8")
    assert 'grain: ""' in text
    assert "natural_key: []" in text
    assert "#   CustomerNumber" in text, "candidates are offered as comments, not decisions"


# ---------------------------------------------------------------------------------------
# Building — rule 5 and rule 4, mechanically
# ---------------------------------------------------------------------------------------


def _curated(use_case: Path, extra: str = "") -> None:
    (use_case / "ontology/taxonomy.yml").write_text(
        "version: 1\n"
        "entities:\n"
        "  dim_customers:\n"
        "    core_class: erp:Customer\n"
        '    grain: "one row per customer per tenant"\n'
        "    natural_key:\n"
        "      - CustomerNumber\n"
        "    sources:\n"
        "      - source: acme_api\n"
        "        table: customers\n"
        "      - source: other_api\n"
        "        table: customers\n"
        + extra,
        encoding="utf-8",
    )


def test_every_attribute_traces_to_a_declared_source_column(tmp_path, monkeypatch) -> None:
    use_case = _tree(tmp_path)
    _curated(use_case)
    rc = _run(tmp_path, monkeypatch, ["--use-case", "demo"])
    assert rc == 0
    model = json.loads((use_case / "ontology/conceptual-model.json").read_text("utf-8"))
    ent = model["entities"][0]
    assert {a["name"] for a in ent["attributes"]} == {
        "CustomerNumber", "Email", "Name", "Country",
    }
    universal = {a["name"] for a in ent["attributes"] if a["universal"]}
    assert universal == {"CustomerNumber", "Name"}, (
        "a column only one source declares must be visible as exactly that, not conformed"
    )
    assert next(a for a in ent["attributes"] if a["name"] == "Country")["declared_by"] == [
        "other_api.customers"
    ]


def test_a_natural_key_no_source_declares_is_a_problem(tmp_path, monkeypatch) -> None:
    """Rule 5 in the direction that matters: the taxonomy may not name a column the raw
    layer does not have, because nothing downstream would catch it until the SQL fails."""
    use_case = _tree(tmp_path)
    _curated(use_case)
    text = (use_case / "ontology/taxonomy.yml").read_text("utf-8")
    (use_case / "ontology/taxonomy.yml").write_text(
        text.replace("- CustomerNumber", "- CustomerUuid"), encoding="utf-8"
    )
    rc = _run(tmp_path, monkeypatch, ["--use-case", "demo"])
    assert rc == 1


def test_an_entity_without_a_grain_is_reported(tmp_path, monkeypatch, capsys) -> None:
    use_case = _tree(tmp_path)
    _curated(use_case)
    text = (use_case / "ontology/taxonomy.yml").read_text("utf-8")
    (use_case / "ontology/taxonomy.yml").write_text(
        text.replace('grain: "one row per customer per tenant"', 'grain: ""'),
        encoding="utf-8",
    )
    rc = _run(tmp_path, monkeypatch, ["--use-case", "demo"])
    assert rc == 1
    assert "grain" in capsys.readouterr().out.lower()


def test_a_taxonomy_naming_an_undeclared_table_is_a_problem(
    tmp_path, monkeypatch, capsys
) -> None:
    use_case = _tree(tmp_path)
    _curated(use_case, extra=(
        "  dim_ghosts:\n"
        "    core_class: erp:Party\n"
        '    grain: "one row per ghost"\n'
        "    natural_key: []\n"
        "    sources:\n"
        "      - source: acme_api\n"
        "        table: nowhere\n"
    ))
    rc = _run(tmp_path, monkeypatch, ["--use-case", "demo"])
    assert rc == 1
    assert "nowhere" in capsys.readouterr().out


def test_a_relationship_is_proposed_only_toward_a_declared_entity(
    tmp_path, monkeypatch
) -> None:
    use_case = _tree(tmp_path)
    _curated(use_case, extra=(
        "  fact_invoices:\n"
        "    core_class: erp:Invoice\n"
        '    grain: "one row per invoice per tenant"\n'
        "    natural_key:\n"
        "      - invoiceNumber\n"
        "    sources:\n"
        "      - source: acme_api\n"
        "        table: invoices\n"
    ))
    rc = _run(tmp_path, monkeypatch, ["--use-case", "demo"])
    assert rc == 0
    model = json.loads((use_case / "ontology/conceptual-model.json").read_text("utf-8"))
    rels = model["relationships"]
    assert len(rels) == 1
    assert (rels[0]["from"], rels[0]["to"], rels[0]["via"]) == (
        "Invoice", "Customer", "CustomerNumber",
    )
    assert rels[0]["confidence"] == "proposed", "a name match is evidence, not a fact"


def test_the_artifact_carries_nothing_run_dependent(tmp_path, monkeypatch) -> None:
    """The column-memory bug, pre-empted: a timestamp or a cache counter in provenance
    makes the file change when the project has not, so `--check` is permanently red."""
    use_case = _tree(tmp_path)
    _curated(use_case)
    _run(tmp_path, monkeypatch, ["--use-case", "demo"])
    first = (use_case / "ontology/conceptual-model.json").read_bytes()
    _run(tmp_path, monkeypatch, ["--use-case", "demo"])
    assert (use_case / "ontology/conceptual-model.json").read_bytes() == first
    assert _run(tmp_path, monkeypatch, ["--use-case", "demo", "--check"]) == 0


def test_check_writes_nothing_when_the_artifact_is_stale(tmp_path, monkeypatch) -> None:
    use_case = _tree(tmp_path)
    _curated(use_case)
    artifact = use_case / "ontology/conceptual-model.json"
    artifact.write_text("{}\n", encoding="utf-8")
    rc = _run(tmp_path, monkeypatch, ["--use-case", "demo", "--check"])
    assert rc == 1
    assert artifact.read_text(encoding="utf-8") == "{}\n"


# ---------------------------------------------------------------------------------------
# Skips — a correct early state is not a failure
# ---------------------------------------------------------------------------------------


def test_a_use_case_with_no_raw_layer_skips(tmp_path, monkeypatch, capsys) -> None:
    use_case = tmp_path / "skill-packs/dbt-skills/use-cases/demo"
    (use_case / "ontology").mkdir(parents=True)
    (use_case / "dbt_project").mkdir(parents=True)
    rc = _run(tmp_path, monkeypatch, ["--use-case", "demo"])
    assert rc == 0
    assert "skip" in capsys.readouterr().out


def test_a_raw_layer_with_no_taxonomy_skips_with_the_remedy(
    tmp_path, monkeypatch, capsys
) -> None:
    """The state every use-case is in the day this lands. A gate that goes red here gets
    switched off within a week, taking the real failures with it."""
    _tree(tmp_path)
    rc = _run(tmp_path, monkeypatch, ["--use-case", "demo"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "skip" in out and "--propose" in out


# ---------------------------------------------------------------------------------------
# Closing the loop
# ---------------------------------------------------------------------------------------


def test_plan_reports_declared_entities_the_project_has_not_built(
    tmp_path, monkeypatch
) -> None:
    """The reason the model is worth writing before the SQL: the difference between what is
    declared and what exists is a work list, computed rather than remembered."""
    use_case = _tree(tmp_path)
    _curated(use_case)
    manifest = use_case / "dbt_project/target/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"nodes": {}, "sources": {}, "metadata": {}}), "utf-8")
    _run(tmp_path, monkeypatch, ["--use-case", "demo"])
    model = json.loads((use_case / "ontology/conceptual-model.json").read_text("utf-8"))
    result = rt.plan(model, manifest)
    assert result["declared"] == 1 and result["built"] == 0 and result["not_built"] == 1
    assert result["todo"][0]["grain"] == "one row per customer per tenant"

    manifest.write_text(json.dumps({
        "nodes": {"model.d.acme_bi_dim_customers": {
            "resource_type": "model", "name": "acme_bi_dim_customers",
        }},
        "sources": {}, "metadata": {},
    }), encoding="utf-8")
    after = rt.plan(model, manifest)
    assert after["built"] == 1 and after["not_built"] == 0


def test_plan_without_a_manifest_is_unavailable_not_empty(tmp_path, monkeypatch) -> None:
    """'Nothing is built' and 'we cannot tell' are different answers, and reporting the
    second as the first would put every entity on a work list that is already done."""
    use_case = _tree(tmp_path)
    _curated(use_case)
    _run(tmp_path, monkeypatch, ["--use-case", "demo"])
    model = json.loads((use_case / "ontology/conceptual-model.json").read_text("utf-8"))
    result = rt.plan(model, use_case / "dbt_project/target/manifest.json")
    assert result["available"] is False and "refresh.sh" in result["reason"]


# ---------------------------------------------------------------------------------------
# The real raw layer
# ---------------------------------------------------------------------------------------


@pytest.mark.skipif(
    not (ENHANZA / "dbt_project/models/sources.yml").exists(),
    reason="enhanza-analytics not on this branch",
)
def test_the_committed_raw_layer_reads_without_problems() -> None:
    """200 tables across 12 files, every one carrying Jinja. Parsing is the whole input."""
    tables, problems = rt.read_raw_layer(ENHANZA / "dbt_project")
    assert not problems, problems
    assert len(tables) > 150
    assert sum(len(t.columns) for t in tables) > 500


@pytest.mark.skipif(
    not (ENHANZA / "dbt_project/models/sources.yml").exists(),
    reason="enhanza-analytics not on this branch",
)
def test_proposing_against_the_real_raw_layer_finds_the_real_keys() -> None:
    """The regression guard for the key-shape fix, on the data that exposed it."""
    import ontology_generator as og

    tables, _ = rt.read_raw_layer(ENHANZA / "dbt_project")
    result = rt.propose(tables, og.CONCEPT_CLASS, {})
    keys = result["natural_key_candidates"]
    assert keys["dim_accounts"][0]["column"] == "Number"
    assert keys["dim_customers"][0]["column"] == "CustomerNumber"
    assert keys["dim_articles"][0]["column"] == "ArticleNumber"


def test_the_cli_is_stdlib_only(tmp_path) -> None:
    """Every script in scripts/ runs on a bare interpreter; this one is no exception."""
    use_case = _tree(tmp_path)
    del use_case
    result = subprocess.run(
        [sys.executable, "-S", "-c",
         f"import sys; sys.path.insert(0, {str(REPO / 'scripts')!r}); import raw_taxonomy"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_a_gap_is_a_concept_this_domain_asked_for(tmp_path, monkeypatch) -> None:
    """Found by running the pipeline on a two-entity demo: every concept in the shared
    ERP/CRM vocabulary counted as a gap, so the one that mattered sat under 56 that nobody
    requested. A concept nobody asked for is not a gap (rule 3), and an unbounded list is
    not a finding.
    """
    use_case = _tree(tmp_path)
    (use_case / "ontology/ontology.yml").write_text(
        "namespace: https://example.test/demo/\n"
        "title: Demo\n"
        "concept_classes:\n"
        "  dim_customers: erp:Customer\n"
        "  fact_subscriptions: erp:Contract\n",
        encoding="utf-8",
    )
    _curated(use_case)
    rc = _run(tmp_path, monkeypatch, ["--use-case", "demo"])
    assert rc == 0
    model = json.loads((use_case / "ontology/conceptual-model.json").read_text("utf-8"))
    assert [g["concept"] for g in model["gaps"]] == ["fact_subscriptions"], (
        "only concepts this use-case declared and has no source for"
    )
    unused = model["shared_vocabulary_unused"]
    assert unused["count"] > 10 and len(unused["sample"]) <= 10, (
        "the shared vocabulary is reported as a capped sample, never dumped"
    )
    assert "dim_customers" not in unused["sample"], "a mapped concept is not unused"
