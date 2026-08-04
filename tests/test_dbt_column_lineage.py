"""Tests for column-level lineage derived from dbt raw SQL.

Column lineage is the one thing here that can be confidently wrong. The model-level DAG
comes from dbt and is either right or absent; column lineage is *inferred by parsing*, so a
resolver bug does not raise — it emits a plausible edge to a column that does not exist.
Two such bugs were found while building this and both are pinned below:

  * `find_all(exp.Table)` walks the whole subtree, so for `with main as (select ... from
    src) select OrgName from main` the outer SELECT reported `src` as one of its own
    sources. Every unqualified column then resolved against `src` too, inventing
    `src.OrgName` alongside the true `src.companyName` — a confident edge to a column that
    is not there.
  * sqlglot 30 renamed the `from` argument to `from_`. Reading only the old key returned
    "no sources" for every model and turned all 5591 edges into `unresolved`, silently.

sqlglot is optional, so these skip where it is absent rather than failing — but the
Jinja-handling tests need no parser and always run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import dbt_column_lineage as lineage  # noqa: E402

SCRIPT = REPO / "scripts" / "dbt_column_lineage.py"
ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project"

needs_sqlglot = pytest.mark.skipif(
    lineage.sqlglot is None, reason="sqlglot not installed (optional dependency)"
)


# ---------------------------------------------------------------------------------------
# Jinja handling — no parser required
# ---------------------------------------------------------------------------------------


def test_ref_becomes_a_bare_identifier() -> None:
    assert "from stg_orders" in lineage.strip_jinja("select a from {{ ref('stg_orders') }}")


def test_source_becomes_a_joined_identifier() -> None:
    out = lineage.strip_jinja("select a from {{ source('shop_api', 'orders') }}")
    assert f"shop_api{lineage.SOURCE_SEP}orders" in out


def test_config_block_is_removed() -> None:
    out = lineage.strip_jinja("{{ config(materialized='view') }}\nselect a from t")
    assert out.startswith("select")


def test_statement_blocks_are_removed() -> None:
    out = lineage.strip_jinja("{% set x = 1 %}select a from t")
    assert "{%" not in out and "set x" not in out


def test_macro_calls_are_listed_in_order() -> None:
    raw = "{{ config(x=1) }}\nselect {{ add_erp_fields(columns=['a']) }} from {{ ref('t') }}"
    assert lineage.macro_calls(raw) == ["config", "add_erp_fields", "ref"]


# ---------------------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------------------


@needs_sqlglot
def test_a_plain_column_is_direct() -> None:
    edges, err = lineage.lineage_from_sql("m", "select OrgId from {{ ref('src') }}", "bigquery")
    assert err is None
    assert [(e.column, e.upstream_model, e.upstream_column, e.kind) for e in edges] == [
        ("OrgId", "src", "OrgId", "direct")
    ]


@needs_sqlglot
def test_an_aliased_column_is_renamed() -> None:
    edges, err = lineage.lineage_from_sql(
        "m", "select Name as OrgName from {{ ref('src') }}", "bigquery"
    )
    assert err is None
    assert edges[0].upstream_column == "Name"
    assert edges[0].kind == "renamed"


@needs_sqlglot
def test_an_expression_is_derived() -> None:
    edges, err = lineage.lineage_from_sql(
        "m", "select initcap(City) as City from {{ ref('src') }}", "bigquery"
    )
    assert err is None
    assert edges[0].kind == "derived"


@needs_sqlglot
def test_a_column_is_followed_through_a_cte() -> None:
    """The regression guard for the subtree-walk bug."""
    sql = """
    with main as (select companyName OrgName from {{ source('api', 'company') }})
    select OrgName from main
    """
    edges, err = lineage.lineage_from_sql("m", sql, "bigquery")
    assert err is None
    resolved = {(e.upstream_model, e.upstream_column) for e in edges}
    assert resolved == {(f"api{lineage.SOURCE_SEP}company", "companyName")}, resolved


@needs_sqlglot
def test_a_cte_base_table_is_not_a_source_of_the_outer_select() -> None:
    """The precise shape of the bug: `src.OrgName` must not be invented."""
    sql = """
    with main as (select companyName OrgName, other from {{ ref('src') }})
    select OrgName from main
    """
    edges, _ = lineage.lineage_from_sql("m", sql, "bigquery")
    assert not [e for e in edges if e.upstream_column == "OrgName"], (
        "the outer select's column name leaked onto the CTE's base table"
    )


@needs_sqlglot
def test_a_join_contributes_its_table() -> None:
    sql = "select a.x, b.y from {{ ref('ta') }} a join {{ ref('tb') }} b on a.k = b.k"
    edges, err = lineage.lineage_from_sql("m", sql, "bigquery")
    assert err is None
    assert {(e.column, e.upstream_model) for e in edges} == {("x", "ta"), ("y", "tb")}


@needs_sqlglot
def test_select_star_is_a_passthrough() -> None:
    edges, err = lineage.lineage_from_sql("m", "select * from {{ ref('src') }}", "bigquery")
    assert err is None
    assert edges[0].kind == "passthrough"
    assert edges[0].column == "*"


@needs_sqlglot
def test_union_branches_are_both_reported() -> None:
    sql = "select a from {{ ref('t1') }} union all select a from {{ ref('t2') }}"
    edges, err = lineage.lineage_from_sql("m", sql, "bigquery")
    assert err is None
    assert {e.upstream_model for e in edges} == {"t1", "t2"}
    assert {e.kind for e in edges} == {"union"}


# ---------------------------------------------------------------------------------------
# Macro substitution fallback
# ---------------------------------------------------------------------------------------


@needs_sqlglot
def test_a_macro_in_a_select_list_still_parses() -> None:
    """`{{ add_erp_fields(...) }}` expands to `, col, col` and needs its own comma."""
    sql = "select OrgId, City\n  {{ add_erp_fields(columns=['OrgId']) }}\nfrom {{ ref('t') }}"
    edges, err = lineage.lineage_from_sql("m", sql, "bigquery")
    assert err is None, err
    assert {e.column for e in edges} >= {"OrgId", "City"}


@needs_sqlglot
def test_a_macro_in_a_where_clause_still_parses() -> None:
    """`{{ fortnox_start_year_filter(...) }}` expands to `and ...`."""
    sql = "select *\nfrom {{ ref('t') }}\nwhere 1=1\n  {{ start_year_filter('a','b') }}"
    _, err = lineage.lineage_from_sql("m", sql, "bigquery")
    assert err is None, err


@needs_sqlglot
def test_unparseable_sql_is_reported_not_swallowed() -> None:
    _, err = lineage.lineage_from_sql("m", "select from from from", "bigquery")
    assert err, "a parse failure must surface, not vanish"


# ---------------------------------------------------------------------------------------
# Macro-only models
# ---------------------------------------------------------------------------------------


def test_auto_config_resolves_to_a_passthrough_from_its_staging_model() -> None:
    node = {
        "name": "fortnox_bi_dim_company",
        "raw_code": "{{ auto_config() }}",
        "depends_on": {"nodes": ["model.p.fortnox_bi_dim_company_staging"]},
    }
    by_name = {
        "fortnox_bi_dim_company_staging": {"name": "fortnox_bi_dim_company_staging"},
        "model.p.fortnox_bi_dim_company_staging": {"name": "fortnox_bi_dim_company_staging"},
    }
    edges = lineage.structural_lineage(node, by_name)
    assert len(edges) == 1
    assert edges[0].kind == "passthrough"
    assert edges[0].upstream_model == "fortnox_bi_dim_company_staging"


def test_erp_union_resolves_to_a_union_over_its_adapters() -> None:
    node = {
        "name": "erp_bi_dim_company",
        "raw_code": "{{ erp_union() }}",
        "depends_on": {"nodes": ["a", "b"]},
    }
    by_name = {"a": {"name": "fortnox_erp_bi_dim_company"}, "b": {"name": "tripletex_erp_bi_dim_company"}}
    edges = lineage.structural_lineage(node, by_name)
    assert {e.upstream_model for e in edges} == {
        "fortnox_erp_bi_dim_company", "tripletex_erp_bi_dim_company"
    }
    assert {e.kind for e in edges} == {"union"}


def test_an_unknown_macro_resolves_to_nothing_rather_than_a_guess() -> None:
    node = {"name": "m", "raw_code": "{{ something_bespoke() }}", "depends_on": {"nodes": []}}
    assert lineage.structural_lineage(node, {}) == []


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------


needs_manifest = pytest.mark.skipif(
    not (ENHANZA / "target/manifest.json").exists(),
    reason="no parsed manifest; run artifacts/refresh.sh",
)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=300
    )


@needs_manifest
def test_cli_reports_parse_coverage_honestly() -> None:
    result = _run(["--manifest", str(ENHANZA / "target/manifest.json"), "--format", "json"])
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["models"] > 0
    # Every model lands in exactly one bucket, with or without the optional parser —
    # otherwise the coverage line understates the project and reads as if the models were
    # simply absent.
    assert (
        payload["models_parsed"]
        + payload["models_macro_only"]
        + payload["models_parse_failed"]
        + payload["models_no_parser"]
    ) == payload["models"]


@needs_manifest
def test_cli_states_when_sqlglot_is_missing() -> None:
    payload = json.loads(
        _run(["--manifest", str(ENHANZA / "target/manifest.json"), "--format", "json"]).stdout
    )
    assert payload["sqlglot_available"] is (lineage.sqlglot is not None)


@needs_manifest
@needs_sqlglot
def test_lineage_records_are_uniform_for_toon() -> None:
    payload = json.loads(
        _run([
            "--manifest", str(ENHANZA / "target/manifest.json"),
            "--format", "json", "--limit", "50",
        ]).stdout
    )
    keys = {tuple(sorted(r)) for r in payload["lineage"]}
    assert len(keys) <= 1, f"ragged records would break the TOON header: {keys}"


@needs_sqlglot
def test_an_unnest_alias_is_not_read_as_a_column() -> None:
    """`unnest(...) r` binds a row; `r` is not a column of the base table.

    Before this was handled, a bare `r` inside a projection resolved against the FROM table
    and produced 32 edges into `fortnox_api__v2_invoices.r`, a column that does not exist.
    """
    sql = """
    select json_extract_scalar(r, '$.Price') as Price
    from {{ source('api', 'invoices') }}, unnest(json_extract_array(InvoiceRows)) r
    """
    edges, err = lineage.lineage_from_sql("m", sql, "bigquery")
    assert err is None, err
    assert not [e for e in edges if e.upstream_column == "r"], (
        f"row variable leaked in as a column: {[(e.column, e.upstream_column) for e in edges]}"
    )


@needs_sqlglot
def test_a_qualified_row_variable_is_not_attributed_to_the_base_table() -> None:
    sql = """
    select r.Price as Price, InvoiceNumber
    from {{ source('api', 'invoices') }}, unnest(json_extract_array(Rows)) r
    """
    edges, err = lineage.lineage_from_sql("m", sql, "bigquery")
    assert err is None, err
    resolved = {(e.column, e.upstream_model, e.upstream_column) for e in edges}
    assert ("Price", f"api{lineage.SOURCE_SEP}invoices", "Price") not in resolved
    # The genuine column alongside it still resolves.
    assert ("InvoiceNumber", f"api{lineage.SOURCE_SEP}invoices", "InvoiceNumber") in resolved


# ---------------------------------------------------------------------------------------
# Jinja block resolution
#
# Deleting `{% ... %}` tags and keeping everything between them produces text no parser
# accepts. Both shapes below were found by running this module over a real project, where
# they accounted for all five of its parse failures.
# ---------------------------------------------------------------------------------------


def test_only_the_first_branch_of_a_conditional_survives():
    """`{% if %} X {% else %} NULL {% endif %} as C` collapsed to `X NULL as C`."""
    sql = "select {% if a %} Price {% else %} NULL {% endif %} as Amount from t"

    out = lineage.resolve_jinja_blocks(sql)

    assert "Price" in out
    assert "NULL" not in out
    assert "as Amount from t" in out


def test_nested_conditionals_keep_the_right_branches():
    sql = (
        "select {% if a %}{% if b %} X {% else %} Y {% endif %}"
        "{% else %} Z {% endif %} as C from t"
    )

    out = lineage.resolve_jinja_blocks(sql)

    assert "X" in out
    assert "Y" not in out and "Z" not in out


def test_a_dropped_branch_does_not_unbalance_the_stack():
    """A nested `if` inside a dropped `else` must not pop the outer level early."""
    sql = "select A {% if a %} , B {% else %} {% if c %} , C {% endif %} {% endif %} , D from t"

    out = lineage.resolve_jinja_blocks(sql)

    assert ", B" in out
    assert ", C" not in out
    assert ", D from t" in out, "the tail after endif was lost — the stack unbalanced"


def test_a_set_block_body_is_dropped_entirely():
    """`{% set q %}...{% endset %}` assigns to a variable; it is not emitted in place."""
    sql = "{% set q %} select 1 as X from other {% endset %} select A from t"

    out = lineage.resolve_jinja_blocks(sql)

    assert "other" not in out
    assert "select A from t" in out.strip()


def test_a_one_line_set_is_not_treated_as_a_block():
    """`{% set x = 1 %}` opens no scope; treating it as one swallows the rest of the file."""
    sql = "{% set cols = ['A'] %}\nselect A from t"

    out = lineage.resolve_jinja_blocks(sql)

    assert "select A from t" in out


@needs_sqlglot
def test_a_conditional_where_clause_no_longer_breaks_the_case_statement():
    """The `categories_x_mapping` shape: an `{% if %}` wrapping `when`, leaving a bare `then`."""
    sql = (
        "select case {% if a %} when X = 1 then 'a' {% endif %} "
        "{% if b %} when X = 2 then 'b' {% endif %} end as C from t"
    )

    tree, error = lineage.parse_model_sql(sql, "bigquery")

    assert error is None, error
    assert tree is not None


# ---------------------------------------------------------------------------------------
# Macros in different syntactic positions at once
# ---------------------------------------------------------------------------------------


@needs_sqlglot
def test_macros_in_two_different_positions_still_parse():
    """One uniform substitution cannot be valid in a select list *and* after a FROM.

    `logic_bi_dim_articles` has a macro in each: all four uniform forms failed and the model
    was reported unparseable while its column list was perfectly readable.
    """
    sql = (
        "select\n  A\n  , B as Renamed\n  {{ extra_columns() }}\n"
        "from {{ ref('upstream') }}\n{{ some_filter() }}\norder by 1"
    )

    tree, error = lineage.parse_model_sql(sql, "bigquery")

    assert error is None, f"mixed-position macros still fail: {error}"
    assert tree is not None


@needs_sqlglot
def test_the_mixed_pass_is_bounded():
    """It is exponential in the macro count, so it must refuse rather than hang.

    Guarded even though it passes without sqlglot: `parse_model_sql` returns `(None, error)`
    when the parser is absent, which satisfies the assertion while proving nothing. A test
    that goes green having exercised nothing is worse than one that says it was skipped.
    """
    macros = " ".join("{{ m%d() }}" % i for i in range(lineage.MAX_MIXED_MACROS + 3))
    sql = f"select A {macros} from t"

    tree, error = lineage.parse_model_sql(sql, "bigquery")

    assert tree is not None or error is not None  # returns either way, never hangs


def test_the_real_project_has_no_parse_failures():
    """Was 5. Each was one of the two Jinja shapes above."""
    manifest = (
        REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
        "/dbt_project/target/manifest.json"
    )
    if not manifest.is_file() or lineage.sqlglot is None:
        pytest.skip("needs the manifest and sqlglot")

    import sys as _sys
    _sys.path.insert(0, str(REPO / "scripts"))
    from _manifest import Manifest

    result = lineage.build_lineage(Manifest.load(str(manifest)))

    assert result["parse_failed"] == 0, [f["model"] for f in result["failures"]]
