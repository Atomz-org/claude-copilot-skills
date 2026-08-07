"""Tests for the no-`select *` gate and the cited column deriver.

These two exist to make an explicit column contract reachable without inventing one, so
the properties worth pinning are the ones separating "derived from a citable schema" from
"plausible":

1. **The gate distinguishes a star that reaches the output from one that does not.**
   Rule 27 names `with source as (select * from ref())` as the house import-CTE style, so
   a gate that flagged it would argue with the rules it enforces.
2. **The baseline may only shrink.** A baseline that can grow is a mute button.
3. **A derived column carries a citation or is absent.** There is no "probably has an
   email field" path.
4. **Two ingestion tools are never merged into one contract.** Fivetran's `property_email`
   and dlt's `email` are the same field under two loaders; a table declaring both matches
   no warehouse and fails every staging model that correctly reads one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import expand_star_models as esm  # noqa: E402
import no_star_check as ns  # noqa: E402
import source_schema_derive as ssd  # noqa: E402

ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"

needs_enhanza = pytest.mark.skipif(
    not (ENHANZA / "dbt_project").exists(), reason="enhanza-analytics not on this branch",
)


# ---------------------------------------------------------------------------------------
# The gate: which stars matter
# ---------------------------------------------------------------------------------------


def _verdicts(sql: str):
    return [f.verdict for f in ns.classify(sql, "m.sql")]


def test_a_star_in_an_import_cte_is_not_a_finding() -> None:
    """Rule 27 names this form; the outer select does the enumerating."""
    sql = "with source as (select * from {{ ref('x') }})\nselect a, b from source"
    assert _verdicts(sql) == [ns.STAR_IN_IMPORT_CTE]


def test_a_star_in_the_output_select_is_a_finding() -> None:
    assert _verdicts("select * from {{ ref('x') }}") == [ns.STAR_IN_OUTPUT]


def test_a_star_beside_a_macro_still_reaches_the_output() -> None:
    """`select *, {{ add_erp_fields(...) }}` — the adapter shape. The model's schema is
    still whatever upstream carries."""
    sql = "select *, {{ add_erp_fields(columns=['OrgId']) }}\nfrom {{ ref('x') }}"
    assert _verdicts(sql) == [ns.STAR_IN_OUTPUT]


def test_a_star_split_across_lines_is_found() -> None:
    """The house formatting for these models puts the star on its own line."""
    assert _verdicts("select\n  *\nfrom {{ ref('x') }}") == [ns.STAR_IN_OUTPUT]


def test_count_star_is_not_a_star() -> None:
    assert _verdicts("select count(*) as n from {{ ref('x') }}") == []


def test_jinja_parentheses_do_not_shift_the_depth() -> None:
    """`{{ source('a','b') }}` contributes parens no SQL parser sees.

    Counting them would read the outermost select as nested and silently pass every
    staging model — the exact models this gate exists for.
    """
    assert _verdicts("select * from {{ source('a', 'b') }}") == [ns.STAR_IN_OUTPUT]


def test_a_star_inside_a_comment_is_not_a_finding() -> None:
    sql = "-- select * from old_table\nselect a from {{ ref('x') }}"
    assert _verdicts(sql) == []


def test_dbt_utils_star_is_reported_but_never_failed() -> None:
    """It expands to an explicit list, so the SQL that runs is enumerated — but the list
    comes from upstream, which is a choice worth seeing."""
    verdicts = _verdicts("select {{ dbt_utils.star(from=ref('x')) }} from {{ ref('x') }}")
    assert ns.MACRO_STAR in verdicts
    assert ns.STAR_IN_OUTPUT not in verdicts


def test_snapshots_and_tests_are_out_of_scope() -> None:
    """Rule 24 requires snapshotting the raw source; a snapshot that enumerated columns
    would quietly stop capturing a new one, which is the history it exists to keep."""
    for excluded in ("snapshots", "tests", "macros", "analyses"):
        assert excluded in ns.EXCLUDED_DIRS


# ---------------------------------------------------------------------------------------
# The gate: the baseline only shrinks
# ---------------------------------------------------------------------------------------


def _project(tmp_path: Path, models: dict) -> Path:
    use_case = tmp_path / "uc"
    (use_case / "dbt_project" / "models").mkdir(parents=True)
    for name, sql in models.items():
        (use_case / "dbt_project" / "models" / name).write_text(sql, encoding="utf-8")
    return use_case


def test_a_new_star_cannot_be_added_to_the_baseline(tmp_path: Path, monkeypatch) -> None:
    """The whole mechanism. A baseline that grows silences the gate that wrote it."""
    use_case = _project(tmp_path, {"a.sql": "select * from {{ ref('x') }}"})
    monkeypatch.setattr(ns, "REPO", tmp_path)
    monkeypatch.setattr(ns._paths, "REPO", tmp_path, raising=False)
    monkeypatch.setattr(ns, "use_case_dir", lambda slug: use_case)

    first = ns.report("uc", check=False, update=True)          # bootstrap
    assert first["status"] in ("changed", "ok")
    assert first.get("bootstrapped") is True

    (use_case / "dbt_project/models/b.sql").write_text(
        "select * from {{ ref('y') }}", encoding="utf-8")
    second = ns.report("uc", check=False, update=True)
    assert second["status"] == "fail"
    assert "may only" in second["reason"]


def test_a_fixed_model_leaves_the_baseline(tmp_path: Path, monkeypatch) -> None:
    use_case = _project(tmp_path, {"a.sql": "select * from {{ ref('x') }}"})
    monkeypatch.setattr(ns, "REPO", tmp_path)
    monkeypatch.setattr(ns._paths, "REPO", tmp_path, raising=False)
    monkeypatch.setattr(ns, "use_case_dir", lambda slug: use_case)
    ns.report("uc", check=False, update=True)

    (use_case / "dbt_project/models/a.sql").write_text(
        "select a, b from {{ ref('x') }}", encoding="utf-8")
    result = ns.report("uc", check=False, update=True)
    assert result["removed_from_baseline"] == ["models/a.sql"]
    baseline = json.loads((use_case / "artifacts/star-baseline.json").read_text())
    assert baseline["models"] == []


@needs_enhanza
def test_the_committed_baseline_is_current() -> None:
    """A stale baseline hides a star that has already landed."""
    result = ns.report("enhanza-analytics", check=True, update=False)
    assert result["status"] == "ok", result.get("reason")


# ---------------------------------------------------------------------------------------
# The deriver: a citation or nothing
# ---------------------------------------------------------------------------------------


def test_singular_and_plural_match_but_a_prefix_does_not() -> None:
    """`deal_pipelines` normalises to `deal_pipeline`, which starts with `deal`.

    A prefix rule matched it to dlt's `deal` object on the first real run and gave the
    pipeline table `amount`, `closedate` and `dealname` — deal properties attributed to a
    pipeline. An honest miss costs a lookup; a wrong match generates the tests that
    enforce it.
    """
    tables = {"company": [], "deal": []}
    assert ssd.match_table("companies", tables)[0] == "company"
    assert ssd.match_table("deal", tables)[0] == "deal"
    assert ssd.match_table("deal_pipelines", tables) is None


def test_a_vendor_load_column_is_never_declared_as_ours() -> None:
    """`_fivetran_synced` is the reference connector's bookkeeping. This project lands
    `_dlt_id`; declaring the other would fail every staging model for not reading a
    column that will never exist."""
    for name in ("_fivetran_synced", "_fivetran_deleted", "_airbyte_ab_id"):
        assert ssd.VENDOR_LOAD_COLUMNS.match(name), name
    for name in ("_dlt_id", "id", "property_name"):
        assert not ssd.VENDOR_LOAD_COLUMNS.match(name), name


def test_a_doc_reference_description_is_dropped() -> None:
    """Fivetran describes columns with `{{ doc(...) }}` against blocks in *their* package.
    Carried across, `dbt parse` fails outright — found by promoting them and running it."""
    assert ssd.DOC_REFERENCE.search("{{ doc('_fivetran_synced') }}")
    assert not ssd.DOC_REFERENCE.search("The ID of the company.")


def test_every_reference_declares_the_loader_whose_names_it_lands() -> None:
    """Without it the two conventions merge and the contract matches no warehouse."""
    for connector, refs in ssd.REFERENCES.items():
        assert refs, connector
        for ref in refs:
            assert ref.loader, f"{connector}: {ref.cite} declares no loader"
            assert ref.kind in ssd.PARSERS, f"{connector}: no parser for {ref.kind}"


def test_dlt_outranks_fivetran_here_because_this_repository_loads_with_dlt() -> None:
    ranks = {r.loader: r.rank for r in ssd.REFERENCES["hubspot"]}
    assert ranks["dlt"] < ranks["fivetran"]


def test_the_fivetran_parser_reads_tables_and_columns() -> None:
    text = (
        "sources:\n"
        "  - name: hubspot\n"
        "    tables:\n"
        "      - name: company\n"
        "        columns:\n"
        "          - name: id\n"
        "            description: The ID of the company.\n"
        "          - name: domain\n"
        "      - name: deal\n"
        "        columns:\n"
        "          - name: deal_id\n"
    )
    tables = ssd.parse_fivetran_src_yml(text)
    assert [c["name"] for c in tables["company"]] == ["id", "domain"]
    assert tables["company"][0]["description"] == "The ID of the company."
    assert [c["name"] for c in tables["deal"]] == ["deal_id"]


# ---------------------------------------------------------------------------------------
# Block scalars: the description is the body, not the indicator
# ---------------------------------------------------------------------------------------
#
# `description: >` read with a plain `(.+?)` captures `>` and leaves the body unread, so
# the column's whole description became one punctuation mark. Measured on the committed
# reference before this: **41 of 468 Fivetran columns**, 34 `>` and 7 `|`.


def _columns(body: str):
    return ssd.parse_fivetran_src_yml(
        "sources:\n  - name: s\n    tables:\n      - name: t\n        columns:\n" + body)["t"]


def test_a_folded_block_scalar_becomes_its_text_not_a_chevron() -> None:
    col = _columns(
        "          - name: c\n"
        "            description: >\n"
        "              List of mappings representing contact IDs\n"
        "              that have been merged into the contact.\n"
    )[0]
    assert col["description"] == (
        "List of mappings representing contact IDs that have been merged into the contact.")


def test_a_literal_block_scalar_keeps_the_lines_the_vendor_wrote_apart() -> None:
    """This file's `|` bodies are one sentence per line — "If event type is SOCIAL, it is
    ..." — and folding them would join statements about different cases into one."""
    col = _columns(
        "          - name: c\n"
        "            description: |\n"
        "              If the type is PUBLISHING_TASK, it is one of BLOG_POST, EMAIL.\n"
        "              If the type is SOCIAL, it is one of twitter, facebook.\n"
    )[0]
    assert col["description"].splitlines() == [
        "If the type is PUBLISHING_TASK, it is one of BLOG_POST, EMAIL.",
        "If the type is SOCIAL, it is one of twitter, facebook.",
    ]


def test_a_blank_line_inside_a_folded_block_is_a_paragraph_break() -> None:
    col = _columns(
        "          - name: c\n"
        "            description: >\n"
        "              Any errors that happened.\n"
        "\n"
        "              NOTE: this field is deprecated.\n"
    )[0]
    assert col["description"] == "Any errors that happened.\nNOTE: this field is deprecated."


def test_a_chomping_indicator_is_not_mistaken_for_the_description() -> None:
    col = _columns(
        "          - name: c\n            description: >-\n              Some text.\n")[0]
    assert col["description"] == "Some text."


def test_a_block_body_does_not_leak_into_the_next_column() -> None:
    """A block scalar has no terminator; the first less-indented line ends it, and that
    line still has to be processed as itself."""
    cols = _columns(
        "          - name: a\n"
        "            description: |\n"
        "              First.\n"
        "          - name: b\n"
        "            description: Second.\n"
    )
    assert [c["name"] for c in cols] == ["a", "b"]
    assert cols[0]["description"] == "First." and cols[1]["description"] == "Second."


def test_a_block_running_to_the_end_of_the_file_still_closes() -> None:
    """Nothing follows it, so nothing triggers the flush — it has to happen on the way
    out."""
    col = _columns(
        "          - name: c\n            description: >\n              Last line of file.")[0]
    assert col["description"] == "Last line of file."


def test_the_committed_reference_holds_no_bare_block_indicators() -> None:
    """The regression guard on real data: 41 of 468 before, 0 after."""
    path = ssd.CACHE_DIR / "hubspot.json"
    if not path.exists():
        pytest.skip("hubspot reference cache not refreshed on this branch")
    cache = json.loads(path.read_text(encoding="utf-8"))
    offenders = [
        f"{table}.{column['name']}"
        for source in cache["sources"]
        for table, columns in (source.get("tables") or {}).items()
        for column in columns
        if (column.get("description") or "").strip() in {"|", ">", "|-", ">-", "|+", ">+"}
    ]
    assert not offenders, f"block-scalar indicator stored as a description: {offenders[:5]}"


def test_the_dlt_parser_reads_the_default_property_tuples() -> None:
    text = (
        'DEFAULT_COMPANY_PROPS = (\n    "createdate",\n    "domain",\n)\n'
        'DEFAULT_DEAL_PROPS: List[str] = ["amount", "dealname"]\n'
    )
    parsed = ssd.parse_dlt_settings(text)
    assert [c["name"] for c in parsed["company"]] == ["createdate", "domain"]
    assert [c["name"] for c in parsed["deal"]] == ["amount", "dealname"]


@needs_enhanza
def test_the_committed_reference_cache_carries_its_citations() -> None:
    """A cached schema with no citation is a recollection with a filename."""
    path = ssd.CACHE_DIR / "hubspot.json"
    if not path.exists():
        pytest.skip("hubspot reference cache not refreshed on this branch")
    cache = json.loads(path.read_text(encoding="utf-8"))
    assert cache["sources"], "cache holds no sources"
    for source in cache["sources"]:
        assert source["cite"] and source["url"].startswith("https://")
        assert source["loader"] and isinstance(source["rank"], int)


@needs_enhanza
def test_the_promoted_contract_carries_no_foreign_naming_convention() -> None:
    """The union bug, pinned where it would land: a table declaring both `email` and
    `property_email` matches no warehouse."""
    sources = (ENHANZA / "dbt_project/packages/hubspot/models/sources.yml")
    if not sources.exists():
        pytest.skip("hubspot package not on this branch")
    text = sources.read_text(encoding="utf-8")
    assert "property_" not in text, (
        "a Fivetran-convention column reached this project's source contract; "
        "this repository lands dlt names"
    )
    assert "_fivetran_" not in text


# ---------------------------------------------------------------------------------------
# Expansion: which file a ref() is allowed to resolve to
# ---------------------------------------------------------------------------------------
#
# `expand_star_models.resolve` reads an upstream's projection off disk to learn what a
# `select *` over it returns. A bare `rglob("<ref>.sql")` finds dbt's *compiled* copy of
# the same model as well as the source, and the first hit is filesystem order — so the
# contract this tool writes into a model depended on whether somebody had run dbt.


def _expanding_model(name: str, sql: str, path: Path):
    return esm.Model(rel=name, path=path, name=name, sql=sql, star_count=1, star_pos=0)


def _write(project: Path, rel: str, sql: str) -> Path:
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sql, encoding="utf-8")
    return path


UPSTREAM = "select\n      a\n    , b\nfrom {{ source('s', 't') }}\n"


def test_a_ref_never_resolves_to_dbts_compiled_copy(tmp_path: Path) -> None:
    """Measured on enhanza-analytics: 394 of 707 stems duplicate, every duplicate a build
    artifact, and `rglob` returned the compiled copy for **6 of 6** upstream reads. Both
    `target/` trees are gitignored, so the tool answered one way on a developer machine
    and another on a fresh clone."""
    project = tmp_path / "dbt_project"
    _write(project, "models/staging/up.sql", UPSTREAM)
    _write(project, "target/compiled/pkg/models/staging/up.sql",
           "select\n      compiled_only\nfrom x\n")
    model = _expanding_model("down", "select * from {{ ref('up') }}", project / "down.sql")
    model.ref = "up"
    esm.resolve({"down": model}, {}, project)
    assert model.reason == "", model.reason
    assert model.star_columns == ["a", "b"], "read the compiled copy, not the source model"


def test_the_build_dirs_excluded_here_are_a_subset_of_the_gates(tmp_path: Path) -> None:
    """`no_star_check.EXCLUDED_DIRS` answers "where may a star live" and also drops
    `snapshots/`, which is the right answer there and the wrong one here: `ref()` to a
    snapshot is legal dbt. The subset relationship is the part that must not drift."""
    assert set(esm.BUILD_DIRS) < set(ns.EXCLUDED_DIRS)
    assert "snapshots" not in esm.BUILD_DIRS


def test_two_real_model_files_of_one_name_are_refused_not_picked(tmp_path: Path) -> None:
    """Zero today, which is what makes refusing cheap. Picking the first would rewrite a
    model against the wrong contract while reading as resolved."""
    project = tmp_path / "dbt_project"
    _write(project, "packages/a/models/up.sql", UPSTREAM)
    _write(project, "packages/b/models/up.sql", "select\n      c\nfrom x\n")
    model = _expanding_model("down", "select * from {{ ref('up') }}", project / "down.sql")
    model.ref = "up"
    esm.resolve({"down": model}, {}, project)
    assert model.star_columns is None
    assert "2 model files" in model.reason and "ambiguous" in model.reason


def test_a_ref_resolving_to_nothing_still_says_so(tmp_path: Path) -> None:
    """The pre-existing no-model reason survives the exclusion — a project whose only copy
    of a model is compiled output must not read as a naming ambiguity."""
    project = tmp_path / "dbt_project"
    _write(project, "target/compiled/pkg/models/up.sql", UPSTREAM)
    model = _expanding_model("down", "select * from {{ ref('up') }}", project / "down.sql")
    model.ref = "up"
    esm.resolve({"down": model}, {}, project)
    assert model.star_columns is None
    assert "resolves to no model file" in model.reason


# ---------------------------------------------------------------------------------------
# Expansion: the rewrite lands, or it is not called an expansion
# ---------------------------------------------------------------------------------------
#
# The detector runs on `strip_noise(sql)`; the rewrite used to re-search the raw SQL. Any
# comment or Jinja tag between `select` and `*` is whitespace in the first and unmatchable
# in the second, so `rewrite` returned the file unchanged while `run` had already recorded
# it as expanded. Measured: all 4 of this project's expandable models are that shape, so
# `--write` reported four expansions and wrote four identical files.


def _rewrite(sql: str, columns=("a", "b")):
    body = ns.strip_noise(sql)
    stars = list(esm.STAR.finditer(body))
    model = esm.Model(rel="d", path=Path("d.sql"), name="d", sql=sql,
                      star_count=len(stars),
                      star_pos=stars[0].start() if stars else -1,
                      star_columns=list(columns))
    return esm.rewrite(model)


def test_a_comment_between_select_and_star_does_not_silently_skip_the_rewrite() -> None:
    """The house staging stub, verbatim. It is the shape every expandable model here has."""
    out = _rewrite("select\n    -- RawColumnName as ColumnName\n    *\nfrom {{ ref('u') }}\n")
    assert out is not None, "returned None where the star is genuinely there"
    assert "*" not in out.split("do not hand-edit the list.\n")[-1]
    assert "-- RawColumnName as ColumnName" in out, "dropped the author's own note"


def test_select_distinct_star_keeps_its_distinct() -> None:
    """`load_models` counted `select distinct *` as a star and `STAR` did not match one —
    two regexes for one concept, disagreeing silently. Dropping the DISTINCT would change
    the model's grain, which is worse than not rewriting it at all."""
    out = _rewrite("select distinct * from {{ ref('u') }}\n")
    assert out is not None
    tail = out.split("do not hand-edit the list.\n")[-1]
    assert tail.startswith("select distinct")
    assert "*" not in tail


def test_an_uppercase_distinct_is_preserved_as_written() -> None:
    out = _rewrite("SELECT DISTINCT * from {{ ref('u') }}\n")
    assert out is not None
    tail = out.split("do not hand-edit the list.\n")[-1]
    assert tail.startswith("SELECT DISTINCT") and "*" not in tail


def test_the_star_is_replaced_where_it_was_found_not_at_the_next_match() -> None:
    """`star_pos` already names the one star that owns the output. Searching forward from
    it can only ever land somewhere else."""
    sql = "with s as (\n    select 1 as x\n)\nselect\n    *\nfrom s\n"
    out = _rewrite(sql)
    assert out is not None
    assert out.index("do not hand-edit") > out.index("with s as")


def test_a_star_that_cannot_be_placed_is_refused_not_reported_as_expanded() -> None:
    """The caller's half of the contract: `rewrite` returning None must not become a row
    in `expanded`, because a run that says the star is gone while the file still has it is
    the quiet detector disagreeing with the loud one."""
    model = esm.Model(rel="d", path=Path("d.sql"), name="d", sql="select a from t\n",
                      star_count=1, star_pos=999, star_columns=["a"])
    assert esm.rewrite(model) is None


@needs_enhanza
def test_every_expandable_model_actually_changes_when_rewritten() -> None:
    """The end-to-end guard. Before this, 4 of 4 were no-ops reported as expansions."""
    payload = esm.run("enhanza-analytics", write=False, only=None, exclude=None)
    if payload["status"] == "skip":
        pytest.skip(payload["reason"])
    assert payload["expanded"], "nothing expandable — this guard would pass vacuously"
    project = ENHANZA / "dbt_project"
    baseline = json.loads(
        (ENHANZA / "artifacts" / ns.BASELINE_NAME).read_text(encoding="utf-8"))["models"]
    models = esm.load_models(project, baseline, esm.erp_exceptions(project))
    esm.resolve(models, esm.declared_source_columns(project), project)
    for entry in payload["expanded"]:
        model = next(m for m in models.values() if m.rel == entry["model"])
        out = esm.rewrite(model)
        assert out is not None and out != model.sql, f"no-op rewrite: {model.rel}"


@needs_enhanza
def test_no_upstream_is_read_out_of_a_build_directory() -> None:
    """The regression guard on real data: 6 of 6 reads were compiled artifacts before."""
    project = ENHANZA / "dbt_project"
    read: list = []
    original = esm.output_columns_of_explicit_model
    esm.output_columns_of_explicit_model = lambda p: (read.append(p), original(p))[1]
    try:
        esm.run("enhanza-analytics", write=False, only=None, exclude=None)
    finally:
        esm.output_columns_of_explicit_model = original
    offenders = [str(p.relative_to(project)) for p in read
                 if set(p.relative_to(project).parts) & set(esm.BUILD_DIRS)]
    assert not offenders, f"upstream columns read from build output: {offenders[:5]}"
