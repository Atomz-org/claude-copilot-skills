"""Pins for scripts/dbt_column_memory.py.

The module makes four claims that are each easy to get subtly wrong and impossible to notice
from the output, so each has a test that fails on the specific mistake rather than on a
general smell:

1. **Freshness.** dbt's `FileHash.from_contents` strips before hashing. Miss the strip and
   every model with a trailing newline reads as edited: the incremental rebuild degrades to
   a full one while still reporting cache hits, and `--check` never goes green.
2. **Currency.** A model edited since the last `dbt parse` must be read from disk, not from
   the manifest's `raw_code`. Reading `raw_code` produces lineage for the *previous* version
   of the file — confidently wrong, and everything downstream still renders.
3. **The chain.** Most of this project's adapters are `select *, {{ macro }} from ref(...)`,
   which declares no named column at all. A resolver that reads named projections only
   reports those models as empty and silently drops the concepts most likely to drift.
4. **Boundedness.** AgentMemory is one global BM25 corpus. The memory writer must never emit
   the edge set, and its caps must actually bind.

Everything runs against a synthetic manifest built in a tmp_path, so the suite needs no dbt,
no warehouse, and no committed fixture to drift.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import dbt_column_memory as ccm  # noqa: E402
from _manifest import Manifest  # noqa: E402

sqlglot_required = pytest.mark.skipif(
    ccm.lineage_mod.sqlglot is None, reason="sqlglot not installed"
)


# ---------------------------------------------------------------------------------------
# a synthetic dbt project
# ---------------------------------------------------------------------------------------


def dbt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8").strip()).hexdigest()


def model(name: str, sql: str, *, package: str, path: str, depends: list[str] | None = None):
    return {
        "resource_type": "model",
        "name": name,
        "package_name": package,
        "original_file_path": path,
        "raw_code": sql,
        "checksum": {"name": "sha256", "checksum": dbt_hash(sql)},
        "depends_on": {"nodes": depends or []},
        "tags": [],
    }


ADAPTER_SQL = """
select
    Id as ArticleId,
    Name as ArticleName,
    Active
from {{ ref('%(conn)s_bi_dim_articles') }}
"""

STAGING_SQL = """
select
    id as Id,
    name as Name,
    active as Active
from {{ source('%(conn)s_api', 'articles') }}
"""

# The shape that broke the first draft: no named projection at all.
STAR_ADAPTER_SQL = """
select *, {{ add_erp_fields(columns=['AccountId']) }}
from {{ ref('%(conn)s_bi_dim_accounts') }}
"""

ACCOUNTS_STAGING_SQL = """
select
    account_id as AccountId,
    account_name as AccountName
from {{ source('%(conn)s_api', 'accounts') }}
"""


@pytest.fixture
def project(tmp_path: Path):
    """A two-connector dbt project on disk, plus the manifest that describes it."""
    root = tmp_path / "use-cases" / "demo"
    dbt = root / "dbt_project"
    (dbt / "models").mkdir(parents=True)
    (dbt / "dbt_project.yml").write_text("name: demo_root\nversion: '1.0'\n", encoding="utf-8")

    nodes: dict = {}

    def place(name, sql, package, subdir):
        base = dbt if package == "demo_root" else dbt / "packages" / package.replace("demo_", "")
        target = base / "models" / subdir
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{name}.sql").write_text(sql, encoding="utf-8")
        if package != "demo_root":
            (base / "dbt_project.yml").write_text(
                f"name: {package}\nversion: '1.0'\n", encoding="utf-8"
            )
        nodes[f"model.{package}.{name}"] = model(
            name, sql, package=package, path=f"models/{subdir}/{name}.sql"
        )

    for conn in ("alpha", "beta"):
        pkg = f"demo_{conn}"
        place(f"{conn}_bi_dim_articles", STAGING_SQL % {"conn": conn}, pkg, "staging")
        place(f"{conn}_erp_bi_dim_articles", ADAPTER_SQL % {"conn": conn}, pkg, "erp")
        place(f"{conn}_bi_dim_accounts", ACCOUNTS_STAGING_SQL % {"conn": conn}, pkg, "staging")
        place(f"{conn}_erp_bi_dim_accounts", STAR_ADAPTER_SQL % {"conn": conn}, pkg, "erp")

    manifest = {
        "metadata": {"project_name": "demo_root", "dbt_version": "1.9.0"},
        "nodes": nodes,
        "sources": {},
    }
    (root / "ontology").mkdir(parents=True)
    (root / "ontology" / "ontology.yml").write_text(
        "namespace: https://example.test/demo/\n"
        "title: demo\n"
        "concept_classes:\n"
        "  dim_articles: erp:Article\n"
        "  dim_accounts: erp:Account\n",
        encoding="utf-8",
    )
    return root, dbt, Manifest(manifest, str(dbt / "target" / "manifest.json"))


def build(project, **kwargs):
    use_case, dbt, man = project
    return ccm.build_store(man, dbt, "demo", use_case, cache=kwargs.pop("cache", None), **kwargs)


# ---------------------------------------------------------------------------------------
# 1. freshness
# ---------------------------------------------------------------------------------------


def test_an_untouched_project_reports_every_model_fresh(project):
    _, dbt, man = project
    fresh = ccm.freshness(man, dbt)

    assert len(fresh.models) == 8
    assert len(fresh.by_status("fresh")) == 8
    assert fresh.by_status("changed") == []
    assert fresh.by_status("missing") == []


def test_the_hash_strips_exactly_as_dbt_does(tmp_path: Path):
    """dbt hashes `contents.encode().strip()`. Without the strip nothing ever matches."""
    path = tmp_path / "m.sql"
    path.write_text("\n\nselect 1\n\n  ", encoding="utf-8")

    assert ccm.file_hash(path) == hashlib.sha256(b"select 1").hexdigest()


def test_editing_one_model_marks_exactly_that_model_changed(project):
    _, dbt, man = project
    target = dbt / "packages" / "alpha" / "models" / "erp" / "alpha_erp_bi_dim_articles.sql"
    target.write_text(target.read_text(encoding="utf-8") + "\n-- edit\n", encoding="utf-8")

    fresh = ccm.freshness(man, dbt)
    changed = [m.name for m in fresh.by_status("changed")]

    assert changed == ["alpha_erp_bi_dim_articles"]
    assert len(fresh.by_status("fresh")) == 7


def test_trailing_whitespace_alone_is_not_a_change(project):
    """The exact false positive the strip prevents, on the real code path."""
    _, dbt, man = project
    target = dbt / "packages" / "alpha" / "models" / "erp" / "alpha_erp_bi_dim_articles.sql"
    target.write_text(target.read_text(encoding="utf-8") + "\n\n   \n", encoding="utf-8")

    assert ccm.freshness(man, dbt).by_status("changed") == []


def test_a_new_sql_file_is_untracked_and_moves_the_digest(project):
    _, dbt, man = project
    before = ccm.freshness(man, dbt).digest
    new = dbt / "packages" / "alpha" / "models" / "erp" / "alpha_erp_bi_dim_new.sql"
    new.write_text("select 1 as X\n", encoding="utf-8")

    after = ccm.freshness(man, dbt)

    assert len(after.untracked) == 1
    assert after.digest != before, "a model the manifest has never seen must still be noticed"


def test_a_deleted_file_is_missing_not_silently_fresh(project):
    _, dbt, man = project
    (dbt / "packages" / "alpha" / "models" / "erp" / "alpha_erp_bi_dim_articles.sql").unlink()

    assert [m.name for m in ccm.freshness(man, dbt).by_status("missing")] == [
        "alpha_erp_bi_dim_articles"
    ]


def test_package_roots_come_from_each_package_dbt_project_yml(project):
    """Never by transforming the directory name — `packages/alpha/` declares `demo_alpha`."""
    _, dbt, _ = project

    roots = ccm.package_roots(dbt)

    assert roots["demo_alpha"].name == "alpha"
    assert roots["demo_beta"].name == "beta"


def test_the_real_project_manifest_agrees_with_every_file_on_disk():
    """The claim the whole module rests on, checked against the real 359-model project."""
    use_case = REPO_ROOT / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
    manifest = use_case / "dbt_project/target/manifest.json"
    if not manifest.is_file():
        pytest.skip("no manifest — run artifacts/refresh.sh")

    fresh = ccm.freshness(Manifest.load(str(manifest)), use_case / "dbt_project")

    assert fresh.by_status("missing") == [], "package roots failed to resolve"
    assert len(fresh.models) > 300


# ---------------------------------------------------------------------------------------
# 2. currency — a changed model is re-read from disk
# ---------------------------------------------------------------------------------------


@sqlglot_required
def test_a_changed_model_is_parsed_from_disk_not_from_raw_code(project):
    use_case, dbt, man = project
    target = dbt / "packages" / "alpha" / "models" / "erp" / "alpha_erp_bi_dim_articles.sql"
    target.write_text(
        "select Id as ArticleId, Name as ArticleName, Active, Extra\n"
        "from {{ ref('alpha_bi_dim_articles') }}\n",
        encoding="utf-8",
    )

    store = build(project)
    columns = [
        c["column"] for c in next(
            c for c in store.contracts if c["concept"] == "dim_articles"
        )["columns"]
    ]

    assert "Extra" in columns, "the manifest's stale raw_code was used instead of the file"


@sqlglot_required
def test_an_unreadable_changed_file_falls_back_rather_than_failing(project, monkeypatch):
    """A file that vanishes mid-run degrades to the manifest, it does not abort the store."""
    _, dbt, man = project
    fresh = ccm.freshness(man, dbt)
    entry = fresh.models[0]
    object.__setattr__(entry, "disk_hash", "0" * 64)  # force `changed`

    def explode(*_args, **_kwargs):
        raise OSError("gone")

    monkeypatch.setattr(Path, "read_text", explode)
    node = man.nodes[entry.unique_id]

    assert ccm.read_current_sql(entry, node) == node["raw_code"]


# ---------------------------------------------------------------------------------------
# 3. the chain
# ---------------------------------------------------------------------------------------


@sqlglot_required
def test_a_column_resolves_through_the_chain_to_the_source_column(project):
    store = build(project)

    binding = next(
        b for b in store.bindings
        if b["connector"] == "alpha" and b["column"] == "ArticleName"
    )

    assert binding["source_model"] == "alpha_api__articles"
    assert binding["source_column"] == "name"
    assert binding["transform"] == "renamed"
    assert binding["hops"] >= 2, "a one-hop answer means the chain was not followed"


@sqlglot_required
def test_a_star_and_macro_adapter_still_gets_a_contract(project):
    """`select *, {{ macro }} from ref(...)` declares no named column.

    Before the star was expanded this reported an empty column set, and 10 of 30 conformed
    concepts — including one supplied by five connectors — had no contract at all.
    """
    store = build(project)

    contract = next(c for c in store.contracts if c["concept"] == "dim_accounts")

    assert [c["column"] for c in contract["columns"]] == ["AccountId", "AccountName"]
    assert contract["suppliers"] == ["alpha", "beta"]


@sqlglot_required
def test_a_macro_generated_column_list_marks_the_contract_partial(project):
    """Incomplete is carried through, never smoothed over."""
    store = build(project)

    contract = next(c for c in store.contracts if c["concept"] == "dim_accounts")

    assert contract["partial_for"] == ["alpha", "beta"]


@sqlglot_required
def test_the_column_order_the_sql_declares_is_preserved(project):
    """`erp_union()` stacks adapters positionally, so sorting would destroy the evidence."""
    store = build(project)

    contract = next(c for c in store.contracts if c["concept"] == "dim_articles")
    columns = [c["column"] for c in contract["columns"]]

    assert columns == ["ArticleId", "ArticleName", "Active"]
    assert columns != sorted(columns), "a sorted list cannot detect a transposed union"


def test_the_chain_resolver_terminates_on_a_cycle():
    lineages = {
        "a": ccm.ModelLineage("a", "parsed", [("X", "b", "X", "direct")]),
        "b": ccm.ModelLineage("b", "parsed", [("X", "a", "X", "direct")]),
    }
    resolver = ccm.ChainResolver(lineages, {"a", "b"})

    assert resolver.resolve("a", "X")  # returns, rather than recursing forever


def test_classify_reports_the_strongest_claim_in_the_chain():
    assert ccm.classify(["passthrough", "direct"]) == "direct"
    assert ccm.classify(["passthrough", "renamed"]) == "renamed"
    assert ccm.classify(["renamed", "derived"]) == "derived"
    assert ccm.classify(["direct", "unresolved"]) == "unresolved"
    assert ccm.classify([]) == "unresolved"


# ---------------------------------------------------------------------------------------
# drift
# ---------------------------------------------------------------------------------------


@sqlglot_required
def test_a_peer_dropping_a_column_is_reported_as_drift(project):
    """The `isActive` case from CLAUDE.md, reproduced synthetically.

    The real project currently has zero drift, so without this the detector could break and
    the suite would stay green.
    """
    _, dbt, man = project
    target = dbt / "packages" / "beta" / "models" / "erp" / "beta_erp_bi_dim_articles.sql"
    target.write_text(
        "select Id as ArticleId, Name as ArticleName\n"
        "from {{ ref('beta_bi_dim_articles') }}\n",
        encoding="utf-8",
    )
    # A third supplier, so the dropped column has the two carriers drift requires.
    gamma_dir = dbt / "packages" / "alpha" / "models" / "erp"
    (gamma_dir / "gamma_erp_bi_dim_articles.sql").write_text(
        ADAPTER_SQL % {"conn": "alpha"}, encoding="utf-8"
    )
    man.nodes["model.demo_alpha.gamma_erp_bi_dim_articles"] = model(
        "gamma_erp_bi_dim_articles",
        ADAPTER_SQL % {"conn": "alpha"},
        package="demo_alpha",
        path="models/erp/gamma_erp_bi_dim_articles.sql",
    )

    store = build(project)
    drift = [d for d in store.drift if d["column"] == "Active"]

    assert len(drift) == 1
    assert drift[0]["missing_from"] == ["beta"]
    assert sorted(drift[0]["carried_by"]) == ["alpha", "gamma"]


@sqlglot_required
def test_a_column_hidden_behind_a_macro_is_suspected_drift_not_silence(project):
    """Found by onboarding a test connector end to end, not by reading the code.

    An adapter that drops a column *and* calls `add_erp_fields(...)` is `partial`, so the
    dropped column lands in `unknown_for` rather than `missing_from`. Emitting nothing for
    that case made this module report "0 drift findings" for a project where
    `connector_alignment_check.py` was reporting an error on the same adapter — and the
    quiet detector is the one people read. It is reported as `suspected`, never merged into
    `missing_from`, because the macro genuinely might generate it.
    """
    _, dbt, man = project
    # beta drops `Active` and hides its column list behind a macro.
    target = dbt / "packages" / "beta" / "models" / "erp" / "beta_erp_bi_dim_articles.sql"
    target.write_text(
        "select Id as ArticleId, Name as ArticleName, "
        "{{ add_erp_fields(columns=['ArticleId']) }}\n"
        "from {{ ref('beta_bi_dim_articles') }}\n",
        encoding="utf-8",
    )
    gamma = ADAPTER_SQL % {"conn": "alpha"}
    (dbt / "packages" / "alpha" / "models" / "erp" / "gamma_erp_bi_dim_articles.sql").write_text(
        gamma, encoding="utf-8"
    )
    man.nodes["model.demo_alpha.gamma_erp_bi_dim_articles"] = model(
        "gamma_erp_bi_dim_articles", gamma, package="demo_alpha",
        path="models/erp/gamma_erp_bi_dim_articles.sql",
    )

    store = build(project)
    found = [d for d in store.drift if d["column"] == "Active"]

    assert len(found) == 1, "a macro-shadowed adapter silently suppressed the drift"
    assert found[0]["confidence"] == "suspected"
    assert found[0]["unknown_for"] == ["beta"]
    assert found[0]["missing_from"] == [], "a guess must not be reported as a confirmed absence"


@sqlglot_required
def test_confirmed_drift_is_labelled_as_such(project):
    _, dbt, _ = project
    target = dbt / "packages" / "beta" / "models" / "erp" / "beta_erp_bi_dim_articles.sql"
    target.write_text(
        "select Id as ArticleId, Name as ArticleName\n"
        "from {{ ref('beta_bi_dim_articles') }}\n",
        encoding="utf-8",
    )
    gamma = ADAPTER_SQL % {"conn": "alpha"}
    (dbt / "packages" / "alpha" / "models" / "erp" / "gamma_erp_bi_dim_articles.sql").write_text(
        gamma, encoding="utf-8"
    )
    _, _, man = project
    man.nodes["model.demo_alpha.gamma_erp_bi_dim_articles"] = model(
        "gamma_erp_bi_dim_articles", gamma, package="demo_alpha",
        path="models/erp/gamma_erp_bi_dim_articles.sql",
    )

    found = [d for d in build(project).drift if d["column"] == "Active"]

    assert found and found[0]["confidence"] == "confirmed"
    assert found[0]["missing_from"] == ["beta"]


@sqlglot_required
def test_a_column_only_one_connector_carries_is_an_extension_not_drift(project):
    """One carrier is a connector-specific column. Reporting it teaches people to ignore drift."""
    _, dbt, _ = project
    target = dbt / "packages" / "alpha" / "models" / "erp" / "alpha_erp_bi_dim_articles.sql"
    target.write_text(
        "select Id as ArticleId, Name as ArticleName, Active, Name as AlphaOnly\n"
        "from {{ ref('alpha_bi_dim_articles') }}\n",
        encoding="utf-8",
    )

    store = build(project)

    assert [d["column"] for d in store.drift] == []


# ---------------------------------------------------------------------------------------
# 4. the artifact and the cache
# ---------------------------------------------------------------------------------------


def test_the_artifact_is_byte_stable_across_runs(project):
    """Anything run-dependent in the artifact makes `--check` permanently red."""
    first = ccm.serialise(build(project))
    second = ccm.serialise(build(project))

    assert first == second


def test_a_cold_and_a_warm_run_produce_the_same_artifact(project, tmp_path: Path):
    """The bug that shipped in the first draft: cache counters were inside `provenance`."""
    cache_path = tmp_path / "cache.json"

    cold = ccm.serialise(build(project, cache=ccm.LineageCache(cache_path)))
    warm_cache = ccm.LineageCache(cache_path)
    warm = ccm.serialise(build(project, cache=warm_cache))

    assert warm_cache.hits > 0, "the cache was not populated"
    assert cold == warm


def test_the_cache_re_parses_only_what_changed(project, tmp_path: Path):
    use_case, dbt, man = project
    cache_path = tmp_path / "cache.json"
    build(project, cache=ccm.LineageCache(cache_path))

    target = dbt / "packages" / "alpha" / "models" / "erp" / "alpha_erp_bi_dim_articles.sql"
    target.write_text(target.read_text(encoding="utf-8") + "\n-- edit\n", encoding="utf-8")
    warm = ccm.LineageCache(cache_path)
    build(project, cache=warm)

    assert warm.misses == 1
    assert warm.hits == 7


def test_a_corrupt_cache_is_dropped_rather_than_trusted(tmp_path: Path):
    path = tmp_path / "cache.json"
    path.write_text("{not json", encoding="utf-8")

    cache = ccm.LineageCache(path)

    assert cache.get("anything", "hash") is None


def test_the_cache_drops_entries_for_hashes_no_model_carries(project, tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    cache = ccm.LineageCache(cache_path)
    build(project, cache=cache)
    cache.put("ghost", "deadbeef", ccm.ModelLineage("ghost", "parsed", []))
    cache.save(["real:hash"])

    assert "ghost:deadbeef" not in json.loads(cache_path.read_text(encoding="utf-8"))["models"]


# ---------------------------------------------------------------------------------------
# 5. AgentMemory boundedness
# ---------------------------------------------------------------------------------------


def test_memory_records_never_carry_the_edge_set(project):
    """One global BM25 corpus. Six thousand mechanical records bury the decisions in it."""
    store = build(project)

    records = ccm.memory_records(store)

    assert len(records) <= 1 + ccm.MAX_MEMORY_DRIFT + ccm.MAX_MEMORY_CONTRACTS
    assert len(records) < len(store.bindings) or not store.bindings


@sqlglot_required
def test_the_contract_cap_actually_binds(project, monkeypatch):
    store = build(project)
    store.contracts = store.contracts * 200
    monkeypatch.setattr(ccm, "MAX_MEMORY_CONTRACTS", 5)

    contracts = [r for r in ccm.memory_records(store) if "column-contract" in r["concepts"]]

    assert len(contracts) == 5


def test_every_memory_record_names_the_use_case_and_its_subject(project):
    """Recall is lexical; a record phrased in other words than the question does not exist."""
    store = build(project)

    for record in ccm.memory_records(store):
        assert "demo" in record["content"]
        assert record["concepts"], "an unconcepted record is unfindable"


def test_the_locator_record_says_how_to_regenerate(project):
    store = build(project)

    locator = ccm.memory_records(store)[0]

    assert "dbt_column_memory.py" in locator["content"]
    assert ccm.ARTIFACT_NAME in locator["content"]


def test_remember_treats_an_absent_server_as_a_skip_not_a_failure():
    written, note = ccm.remember(
        [{"content": "x", "concepts": []}], url="http://127.0.0.1:1", timeout=0.2
    )

    assert written == 0
    assert "no AgentMemory server" in note


def test_remember_posts_each_record_once_to_the_documented_endpoint(project):
    import http.server
    import threading

    seen: list[tuple[str, dict]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/agentmemory/health" else 404)
            self.end_headers()

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            seen.append((self.path, json.loads(body)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        records = ccm.memory_records(build(project))
        written, note = ccm.remember(records, url=f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()

    assert note == ""
    assert written == len(records)
    assert {path for path, _ in seen} == {"/agentmemory/remember"}
    assert all("content" in body and "concepts" in body for _, body in seen)


# ---------------------------------------------------------------------------------------
# 6. the graphify fragment
# ---------------------------------------------------------------------------------------


@sqlglot_required
def test_the_graphify_fragment_attaches_to_real_model_node_ids(project):
    """A fragment whose edges point at invented IDs adds ghosts instead of upgrading nodes."""
    use_case, _, _ = project
    store = build(project)

    fragment = ccm.graphify_fragment(store, use_case)
    node_ids = {n["id"] for n in fragment["nodes"]}
    targets = {e["target"] for e in fragment["edges"]}

    assert fragment["nodes"], "no contract nodes emitted"
    assert targets.isdisjoint(node_ids), "an edge pointed back at a contract node"
    assert all(e["confidence"] == "EXTRACTED" for e in fragment["edges"])


def test_the_real_fragment_only_points_at_nodes_the_graph_already_has():
    graph_path = REPO_ROOT / "graphify-out" / "graph.json"
    use_case = REPO_ROOT / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
    manifest = use_case / "dbt_project/target/manifest.json"
    if not graph_path.is_file() or not manifest.is_file():
        pytest.skip("no graph or no manifest in this checkout")

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    existing = {n["id"] for n in graph["nodes"]}
    store = ccm.build_store(
        Manifest.load(str(manifest)), use_case / "dbt_project", "enhanza-analytics", use_case
    )
    fragment = ccm.graphify_fragment(store, use_case)

    missing = {e["target"] for e in fragment["edges"]} - existing
    assert not missing, f"{len(missing)} edge(s) point at nodes graphify never minted"


# ---------------------------------------------------------------------------------------
# 7. the CLI contract
# ---------------------------------------------------------------------------------------


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "dbt_column_memory.py"), *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300, check=False,
    )


def test_stale_only_exits_nonzero_when_stale_and_zero_when_current():
    use_case = REPO_ROOT / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
    if not (use_case / "dbt_project/target/manifest.json").is_file():
        pytest.skip("no manifest")

    result = run_cli("--use-case", "enhanza-analytics", "--stale-only", "--format", "json")
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert result.returncode == (0 if payload["current"] else 1)


def test_a_missing_manifest_is_a_skip_not_a_failure(tmp_path: Path):
    """A gate that goes red on a correct state gets switched off within a week."""
    result = run_cli(
        "--use-case", "enhanza-analytics",
        "--manifest", str(tmp_path / "nope.json"), "--format", "json",
    )

    assert result.returncode == 0
    assert json.loads(result.stdout.strip().splitlines()[-1])["status"] == "skip"


def test_check_writes_nothing():
    use_case = REPO_ROOT / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
    artifact = ccm.artifact_path(use_case)
    if not artifact.is_file():
        pytest.skip("no committed artifact")
    before = artifact.read_bytes()

    run_cli("--use-case", "enhanza-analytics", "--check")

    assert artifact.read_bytes() == before


def test_the_committed_artifact_is_current():
    """The CI gate. `use_case_sync.py --all --check` asserts the same thing."""
    use_case = REPO_ROOT / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
    if not (use_case / "dbt_project/target/manifest.json").is_file():
        pytest.skip("no manifest")
    if ccm.lineage_mod.sqlglot is None:
        pytest.skip("sqlglot not installed — the artifact would regenerate without bindings")

    result = run_cli("--use-case", "enhanza-analytics", "--check")

    assert result.returncode == 0, (
        f"{ccm.ARTIFACT_NAME} is out of date. Run:\n"
        f"  python3 scripts/dbt_column_memory.py --use-case enhanza-analytics --write\n"
        f"{result.stdout}"
    )


# ---------------------------------------------------------------------------------------
# 8. the PostToolUse hook
# ---------------------------------------------------------------------------------------

HOOK = REPO_ROOT / "scripts" / "hooks" / "dbt_column_memory_watch.py"


def run_hook(payload: dict, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True, text=True, cwd=str(cwd or REPO_ROOT), timeout=300, check=False,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"tool_name": "Edit"},
        {"tool_name": "Edit", "tool_input": {}},
        {"tool_name": "Edit", "tool_input": {"file_path": "/nowhere/x.sql"}},
        {"tool_name": "Write", "tool_input": {"file_path": str(REPO_ROOT / "README.md")}},
        {"tool_name": "Edit", "tool_input": {"file_path": str(REPO_ROOT / "scripts/x.py")}},
    ],
    ids=["empty", "no-input", "no-path", "outside-repo", "not-dbt", "python-file"],
)
def test_the_hook_is_silent_and_zero_on_anything_it_does_not_own(payload):
    """PostToolUse runs after the edit landed. A non-zero exit cannot undo it — it can only
    break the agent's next step for an unrelated reason."""
    result = run_hook(payload)

    assert result.returncode == 0
    assert result.stdout == ""


def test_the_hook_never_raises_on_malformed_stdin():
    result = subprocess.run(
        [sys.executable, str(HOOK)], input="not json at all",
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=60, check=False,
    )

    assert result.returncode == 0


def test_the_hook_recognises_a_dbt_model_and_leaves_others_alone():
    root = REPO_ROOT
    inside = root / "skill-packs/dbt-skills/use-cases/enhanza-analytics/dbt_project/models/x.sql"
    outside = root / "skill-packs/dbt-skills/use-cases/enhanza-analytics/ontology/x.yml"

    import importlib.util

    spec = importlib.util.spec_from_file_location("hook", HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)

    assert hook.use_case_for(inside, root) == "enhanza-analytics"
    assert hook.use_case_for(outside, root) is None, (
        "only files inside a dbt_project can change what a column means"
    )


def test_the_hook_rebuilds_the_store_when_a_model_actually_changes(tmp_path: Path):
    """The end-to-end claim: edit a .sql, and the committed artifact is current again."""
    use_case = REPO_ROOT / "skill-packs/dbt-skills/use-cases/enhanza-analytics"
    manifest = use_case / "dbt_project/target/manifest.json"
    artifact = ccm.artifact_path(use_case)
    if not manifest.is_file() or not artifact.is_file() or ccm.lineage_mod.sqlglot is None:
        pytest.skip("needs the real project, its artifact, and sqlglot")

    target = next(
        p for p in (use_case / "dbt_project/packages").rglob("*_erp_bi_*.sql")
    )
    original = target.read_bytes()
    artifact_before = artifact.read_bytes()
    try:
        target.write_bytes(original + b"\n-- hook test probe\n")
        assert run_cli("--use-case", "enhanza-analytics", "--stale-only").returncode == 1

        result = run_hook({"tool_name": "Edit", "tool_input": {"file_path": str(target)}})

        assert result.returncode == 0
        assert "[column-memory]" in result.stderr
        assert run_cli("--use-case", "enhanza-analytics", "--stale-only").returncode == 0
    finally:
        target.write_bytes(original)
        artifact.write_bytes(artifact_before)


# ---------------------------------------------------------------------------------------
# 9. source column contracts
