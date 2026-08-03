"""Tests for the use-case sync driver.

The driver exists because five derived artifacts were five commands that had to be run in the
right order, and "run all five" is the instruction that gets followed nine times out of ten.
So the properties worth pinning are about its *reporting*, not its arithmetic:

1. **A stage that cannot run skips, and says why.** A fresh use-case has no manifest and half
   the stages need one. If missing inputs failed, the gate would go red on correct states and
   be switched off within a week — taking the real failures with it.
2. **`--check` writes nothing.** A CI gate that mutates the tree it is checking is not a gate.
3. **`--init` invents nothing.** The scaffold produces an empty catalogue and empty reference
   data, because a row in `connectors.yml` is a claim that a source system exists (rule 5).
4. **A broken stage does not hide the others.** One failing generator must not abort the run
   before the four stages that would have reported real state.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import use_case_sync as sync  # noqa: E402

SCRIPT = REPO / "scripts/use_case_sync.py"
ENHANZA = REPO / "skill-packs/dbt-skills/use-cases/enhanza-analytics"

needs_enhanza = pytest.mark.skipif(
    not ENHANZA.exists(), reason="enhanza-analytics not on this branch"
)
needs_manifest = pytest.mark.skipif(
    not (ENHANZA / "dbt_project/target/manifest.json").exists(),
    reason="no parsed manifest; run artifacts/refresh.sh",
)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=900, cwd=REPO,
    )


def _payload(proc: subprocess.CompletedProcess) -> dict:
    return json.loads(proc.stdout)


def _stages(result: dict) -> dict[str, dict]:
    return {s["stage"]: s for s in result["stages"]}


# ---------------------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------------------


def test_every_use_case_directory_is_discovered() -> None:
    found = set(sync.all_use_cases())
    on_disk = {
        p.name for p in REPO.glob("skill-packs/*/use-cases/*")
        if p.is_dir() and not p.name.startswith(".")
    }
    assert found == on_disk


def test_an_unknown_use_case_reports_rather_than_crashes() -> None:
    result = sync.sync("no-such-use-case", check=True, manifest_arg=None)
    assert not result["ok"]
    assert _stages(result)["resolve"]["status"] == sync.FAIL


# ---------------------------------------------------------------------------------------
# Missing inputs skip; they do not fail
# ---------------------------------------------------------------------------------------


def test_a_use_case_without_a_catalogue_skips_the_ontology_stage(tmp_path: Path) -> None:
    stages = sync.stage_ontology(tmp_path, "toy", manifest=None, check=True)
    assert [s.status for s in stages] == [sync.SKIP, sync.SKIP]
    assert "connectors.yml" in stages[0].detail
    assert "--init" in stages[0].detail, "a skip must name the way out of it"


def test_seeds_skip_without_a_manifest(tmp_path: Path) -> None:
    stage = sync.stage_seeds(tmp_path, "toy", manifest=None, check=True)
    assert stage.status == sync.SKIP and "manifest" in stage.detail


def test_seeds_skip_without_reference_data(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    stage = sync.stage_seeds(tmp_path, "toy", manifest=manifest, check=True)
    assert stage.status == sync.SKIP and "reference" in stage.detail


def test_graph_skips_without_a_manifest(tmp_path: Path) -> None:
    stage = sync.stage_graph(tmp_path, manifest=None, check=True)
    assert stage.status == sync.SKIP


def test_alignment_skips_without_a_dbt_project(tmp_path: Path) -> None:
    stage = sync.stage_alignment(tmp_path, "toy", manifest=None)
    assert stage.status == sync.SKIP


def test_a_failing_stage_does_not_abort_the_others(monkeypatch, tmp_path: Path) -> None:
    """One broken generator must not cost the four reports that would have been correct."""
    def explode(*_args, **_kwargs):
        raise RuntimeError("generator is broken")

    monkeypatch.setattr(sync, "stage_ontology", explode)
    result = sync.sync("enhanza-analytics", check=True, manifest_arg=str(tmp_path / "nope.json"))
    stages = _stages(result)
    assert stages["ontology"]["status"] == sync.FAIL
    assert "generator is broken" in stages["ontology"]["detail"]
    assert {"spec", "seeds", "graph", "alignment"} <= set(stages)


def test_a_refused_downgrade_fails_the_stage_that_was_refused(monkeypatch, tmp_path: Path) -> None:
    """Regenerating without sqlglot yields the same classes with none of the mappings.

    The guard declines to write, which is right — but attaching the refusal only to the
    `ontology` stage left `index` reporting `ok` for a file that had just been declined. A
    consumer reads that as "the projection is current", which is the exact belief the guard
    exists to prevent.
    """
    ontology = tmp_path / "ontology"
    (ontology / "connectors").mkdir(parents=True)
    (ontology / "connectors.yml").write_text("connectors: []\n", encoding="utf-8")
    ttl = ontology / "connectors" / "acme.ttl"
    ttl.write_text("acme:Customer conn:hasMapping acme:x .\n", encoding="utf-8")
    index = ontology / "index.json"
    index.write_text('{"mappings": [{"source_column": "CustomerNumber"}]}\n', encoding="utf-8")

    import ontology_generator as og

    monkeypatch.setattr(sync, "REPO", tmp_path)
    monkeypatch.setattr(og, "generate", lambda *a, **k: {
        "specs": [], "files": {ttl: "acme:Customer a owl:Class .\n", index: '{"mappings": []}\n'},
        "problems": [], "unclassified": [],
        "lineage": {"available": False, "reason": "sqlglot not installed"},
    })
    stages = sync.stage_ontology(tmp_path, "toy", manifest=None, check=False)
    assert [s.status for s in stages] == [sync.FAIL, sync.FAIL], [s.detail for s in stages]
    assert all("column mappings" in s.detail for s in stages)
    assert "conn:hasMapping" in ttl.read_text(encoding="utf-8"), "refused file was written"
    assert "CustomerNumber" in index.read_text(encoding="utf-8"), "refused file was written"


def test_columns_refuses_before_it_writes_rather_than_after(monkeypatch, tmp_path: Path) -> None:
    """The same guard on `columns`, pinned to the ordering that makes it mean anything.

    It has to read the artifact as it was, not the artifact it just wrote. With a warm
    `.dbt-column-cache` the bindings survive a parser-less rebuild, so the marker the guard
    looks for is still on disk and it fires — which is why this passed by hand. On a cold
    cache, which is CI and every fresh clone, the rewrite lands first and takes the bindings
    with it; the guard then inspects its own output, finds no marker, and reports `changed`
    over the exact downgrade it exists to stop. So the fixture below is a cold one.
    """
    import dbt_column_memory as ccm

    artifact = tmp_path / "ontology" / "column-memory.json"
    artifact.parent.mkdir(parents=True)
    original = '{"bindings": [{"source_column": "CustomerNumber"}]}\n'
    artifact.write_text(original, encoding="utf-8")

    class _Store:
        contracts: dict = {}
        bindings: dict = {}
        drift: list = []
        provenance = {"sqlglot": None, "freshness": {"changed": 0, "untracked_sql": 0}}

    class _Manifest:
        @staticmethod
        def load(_path):
            return object()

    monkeypatch.setattr(sync, "REPO", tmp_path)
    monkeypatch.setattr(ccm, "Manifest", _Manifest)
    monkeypatch.setattr(ccm, "project_root_of", lambda *a, **k: tmp_path)
    monkeypatch.setattr(ccm, "LineageCache", lambda *a, **k: None)
    monkeypatch.setattr(ccm, "build_store", lambda *a, **k: _Store())
    monkeypatch.setattr(ccm, "artifact_path", lambda *a, **k: artifact)
    monkeypatch.setattr(ccm, "serialise", lambda _store: '{"bindings": []}\n')

    stage = sync.stage_columns(
        tmp_path, "toy", manifest=tmp_path / "manifest.json", check=False
    )

    assert stage.status == sync.FAIL, stage.detail
    assert artifact.read_text(encoding="utf-8") == original, "refused file was written"


# ---------------------------------------------------------------------------------------
# Stage order — the one pair that is destructive out of order
# ---------------------------------------------------------------------------------------


def test_the_graph_rebuild_runs_before_the_dbt_merge(monkeypatch) -> None:
    """`graphify update` after the merge deletes the whole dbt DAG.

    graphify has no SQL parser: its AST pass extracts zero symbols from a `.sql` file and
    drops the node rather than keeping it at degree 0. Rebuilding after a merge therefore
    removes all 359 models and their 1288 edges, and the graph still looks populated because
    the source nodes have no file to be re-extracted from. Measured while building this: 366
    model nodes in the right order, 0 in the wrong one.

    Sequencing beats documenting, and this test is what keeps the sequence.
    """
    order: list[str] = []
    monkeypatch.setattr(sync, "stage_graphify_update",
                        lambda check: order.append("graphify") or sync.Stage("graphify", sync.OK))
    monkeypatch.setattr(sync, "stage_graph",
                        lambda uc, m, c: order.append("graph") or sync.Stage("graph", sync.OK))
    monkeypatch.setattr(sync, "stage_ontology", lambda *a, **k: [])
    monkeypatch.setattr(sync, "stage_seeds", lambda *a, **k: sync.Stage("seeds", sync.SKIP))
    monkeypatch.setattr(sync, "stage_alignment", lambda *a, **k: sync.Stage("alignment", sync.SKIP))

    sync.sync("enhanza-analytics", check=False, manifest_arg=None, graphify_update=True)
    assert order == ["graphify", "graph"], order


def test_the_rebuild_is_opt_in_and_skipped_under_check(monkeypatch) -> None:
    """A gate must not rebuild the artifact it is inspecting."""
    assert sync.stage_graphify_update(check=True).status == sync.SKIP

    called: list[str] = []
    monkeypatch.setattr(sync, "stage_graphify_update",
                        lambda check: called.append("x") or sync.Stage("graphify", sync.OK))
    monkeypatch.setattr(sync, "stage_ontology", lambda *a, **k: [])
    monkeypatch.setattr(sync, "stage_seeds", lambda *a, **k: sync.Stage("seeds", sync.SKIP))
    monkeypatch.setattr(sync, "stage_graph", lambda *a, **k: sync.Stage("graph", sync.SKIP))
    monkeypatch.setattr(sync, "stage_alignment", lambda *a, **k: sync.Stage("alignment", sync.SKIP))
    sync.sync("enhanza-analytics", check=False, manifest_arg=None)
    assert called == [], "the rebuild must not run unless asked for"


def test_all_rebuilds_once_for_the_repository(monkeypatch) -> None:
    """One rebuild per use-case would drop the lineage the previous one just merged."""
    calls: list[bool] = []
    monkeypatch.setattr(
        sync, "sync",
        lambda slug, check, manifest, only=None, graphify_update=False: (
            calls.append(graphify_update) or {"use_case": slug, "stages": [],
                                              "changed_total": 0, "ok": True}
        ),
    )
    monkeypatch.setattr(sync, "all_use_cases", lambda: ["a", "b", "c"])
    sync.main(["--all", "--graphify-update", "--format", "json"])
    assert calls == [True, False, False], calls


# ---------------------------------------------------------------------------------------
# The emitter's trailing merge line
# ---------------------------------------------------------------------------------------


def test_json_is_read_from_the_first_line_not_the_whole_stream() -> None:
    """`--merge` appends graphify's own `merged: N nodes` line after the JSON payload.

    Parsing the whole stream fails on that second line — and only on a real merge, never on
    the `--dry-run` a `--check` performs. It would have passed every gate and broken on write.
    """
    stream = '{"models": 359, "edges": 1288}\nmerged: 3061 nodes, 5221 edges\n'
    assert sync._first_json_line(stream) == {"models": 359, "edges": 1288}
    assert sync._first_json_line("no json here\n") is None


# ---------------------------------------------------------------------------------------
# --init invents nothing
# ---------------------------------------------------------------------------------------


def test_init_writes_nothing_under_check() -> None:
    proc = _run(["--init", "scratch-use-case-that-should-not-exist", "--check"])
    assert not (REPO / "skill-packs/dbt-skills/use-cases/scratch-use-case-that-should-not-exist").exists()
    assert "scaffold" in proc.stdout


def test_init_scaffolds_three_files_and_refuses_without_a_spec(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sync, "REPO", tmp_path)
    stages = sync.scaffold("retail-margin", "dbt-skills", check=False)
    root = tmp_path / "skill-packs/dbt-skills/use-cases/retail-margin"
    assert (root / "ontology/connectors.yml").exists()
    assert (root / "ontology/ontology.yml").exists()
    assert (root / "ontology/reference/README.md").exists()
    # Rule 1: derived artifacts do not precede the spec that justifies them.
    assert [s.status for s in stages if s.name == "spec"] == [sync.FAIL]


def test_a_scaffolded_catalogue_names_no_connectors(monkeypatch, tmp_path: Path) -> None:
    """Rule 5. A row here claims a source system exists; the generator will not claim it."""
    monkeypatch.setattr(sync, "REPO", tmp_path)
    sync.scaffold("retail-margin", "dbt-skills", check=False)
    text = (tmp_path / "skill-packs/dbt-skills/use-cases/retail-margin"
            / "ontology/connectors.yml").read_text(encoding="utf-8")
    sys.path.insert(0, str(REPO / "scripts"))
    import _miniyaml

    assert _miniyaml.load(text)["connectors"] == []


def test_a_scaffolded_namespace_is_pinned_to_the_slug(monkeypatch, tmp_path: Path) -> None:
    """Not derived at read time: renaming the directory must not reissue every IRI."""
    monkeypatch.setattr(sync, "REPO", tmp_path)
    sync.scaffold("retail-margin", "dbt-skills", check=False)
    import _miniyaml

    ontology = (tmp_path / "skill-packs/dbt-skills/use-cases/retail-margin" / "ontology")
    config = _miniyaml.load((ontology / "ontology.yml").read_text(encoding="utf-8"))
    assert config["namespace"] == "https://w3id.org/retail-margin/"


def test_a_scaffolded_use_case_syncs_cleanly(monkeypatch, tmp_path: Path) -> None:
    """The whole point: --init leaves a state that --check calls current, not broken."""
    monkeypatch.setattr(sync, "REPO", tmp_path)
    root = tmp_path / "skill-packs/dbt-skills/use-cases/retail-margin"
    sync.scaffold("retail-margin", "dbt-skills", check=False)
    (root / "use-case-spec.md").write_text("# spec\n", encoding="utf-8")

    stages = sync.stage_ontology(root, "retail-margin", manifest=None, check=True)
    # An empty catalogue is a legitimate state; it generates a topology with no concepts.
    assert all(s.status in (sync.OK, sync.CHANGED) for s in stages), [s.detail for s in stages]


# ---------------------------------------------------------------------------------------
# The real project
# ---------------------------------------------------------------------------------------


@needs_enhanza
@needs_manifest
def test_check_writes_nothing_and_reports_current(tmp_path: Path) -> None:
    before = {
        p: p.stat().st_mtime
        for p in (ENHANZA / "ontology").rglob("*")
        if p.is_file()
    }
    proc = _run(["--use-case", "enhanza-analytics", "--check", "--format", "json",
                 "--stage", "ontology"])
    result = _payload(proc)["use_cases"][0]
    after = {p: p.stat().st_mtime for p in (ENHANZA / "ontology").rglob("*") if p.is_file()}
    assert before == after, "--check mutated the tree it was checking"
    assert result["changed_total"] == 0, (
        f"committed ontology is stale: {result['changed_files']} — run "
        f"scripts/use_case_sync.py --use-case enhanza-analytics"
    )


@needs_enhanza
@needs_manifest
def test_sync_is_idempotent() -> None:
    """Running it twice changes nothing the second time, or a diff means nothing."""
    _run(["--use-case", "enhanza-analytics", "--stage", "ontology", "--stage", "seeds"])
    proc = _run(["--use-case", "enhanza-analytics", "--stage", "ontology", "--stage", "seeds",
                 "--format", "json"])
    assert _payload(proc)["use_cases"][0]["changed_total"] == 0


@needs_enhanza
def test_every_use_case_reports_every_stage() -> None:
    """A silently-absent stage reads as a pass. Each one reports, even when it skips."""
    proc = _run(["--all", "--check", "--format", "json", "--stage", "ontology"])
    for result in _payload(proc)["use_cases"]:
        names = {s["stage"] for s in result["stages"]}
        assert {"spec", "ontology", "index"} <= names, (result["use_case"], names)
