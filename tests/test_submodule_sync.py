"""Tests for the pinned-submodule report and its version gate.

Ten submodules under `external/`, each pinned to a SHA committed here. The properties
worth pinning are about what the gate can and cannot claim:

1. **A pin mismatch fails.** The `external/OpenMetadata` tag, `SERVER_PIN` in the
   bridge, and the `openmetadata-ingestion` wheel are one version. Bumping one without
   the others produces a bundle that validates against schema A and is rejected by a
   server running schema B, one entity at a time, after the egress has begun.
2. **An uninitialised submodule skips; it does not fail.** That is the normal state of
   a fresh clone and of any CI job that did not pass `--recursive`. A gate that goes
   red there gets switched off within a week.
3. **A validator that read nothing does not report `ok`.** The two spec gates in
   `openmetadata_sync.py` read from submodules; absent, they must say `skip`, because
   "passed because there was nothing to check" is the failure this repository names
   everywhere else.
4. **Every submodule is shallow.** `external/OpenMetadata` is 403 MB at depth 1 and far
   more with history; dropping `shallow = true` puts that on every clone and every CI
   run with no diff that looks like the cause.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import openmetadata_sync as oms  # noqa: E402
import sync_submodules as subs  # noqa: E402

SCRIPT = REPO / "scripts/sync_submodules.py"

OPENMETADATA_SUBMODULES = {
    "external/OpenMetadata",
    "external/OpenMetadataStandards",
    "external/openmetadata-demo",
    "external/openmetadata-ai-sdk",
    "external/openmetadata-sqllineage",
    "external/openmetadata-retention",
    "external/openmetadata-dbt-action",
    "external/collate-dbt-artifacts-parser",
}

needs_standards = pytest.mark.skipif(
    not oms.OM_ONTOLOGY.exists(), reason="external/OpenMetadataStandards not initialised"
)
needs_spec = pytest.mark.skipif(
    not oms.SPEC_ROOT.exists(), reason="external/OpenMetadata not initialised"
)


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=300, cwd=REPO,
    )


# ---------------------------------------------------------------------------------------
# Declaration
# ---------------------------------------------------------------------------------------


def test_every_openmetadata_repository_is_declared_as_a_submodule() -> None:
    declared = {m.path for m in subs.read_gitmodules()}
    missing = OPENMETADATA_SUBMODULES - declared
    assert not missing, f"not declared in .gitmodules: {sorted(missing)}"


def test_every_submodule_is_shallow() -> None:
    """403 MB at depth 1; with history it is multiples of that, on every clone."""
    full = [m.path for m in subs.read_gitmodules()
            if not m.shallow and m.path in OPENMETADATA_SUBMODULES]
    assert not full, (
        f"missing `shallow = true` in .gitmodules: {full} — "
        "git config -f .gitmodules submodule.<path>.shallow true"
    )


def test_every_submodule_url_is_an_open_metadata_repository() -> None:
    """A fork would be drift with extra steps (rule 14)."""
    for module in subs.read_gitmodules():
        if module.path not in OPENMETADATA_SUBMODULES:
            continue
        assert module.url.startswith("https://github.com/open-metadata/"), (
            f"{module.path} points at {module.url}, not upstream"
        )


def test_every_submodule_records_what_reads_it() -> None:
    """A pinned repository nobody reads and nobody explains is dead weight."""
    for module in subs.read_gitmodules():
        assert module.path in subs.CONSUMERS, (
            f"{module.path} has no entry in CONSUMERS — say what reads it, or "
            "say it is reference-only"
        )


# ---------------------------------------------------------------------------------------
# The version gate
# ---------------------------------------------------------------------------------------


def test_the_server_pin_and_the_submodule_tag_agree() -> None:
    """The one gate that stops a half-finished version bump from merging."""
    payload = json.loads(_run("--format", "json").stdout)
    pins = {p["pin"]: p for p in payload["version_pins"]}
    pin = next(iter(pins.values()))
    if pin["status"] == "skip":
        pytest.skip(pin["detail"])
    assert pin["status"] == "ok", pin.get("detail")


def test_a_mismatched_pin_is_reported_as_a_failure(monkeypatch) -> None:
    """Proven by moving the declared version, not by trusting the happy path."""
    modules = {m.path: subs.inspect(m) for m in subs.read_gitmodules()}
    if not modules["external/OpenMetadata"].initialised:
        pytest.skip("external/OpenMetadata not initialised")

    broken = subs.VersionPin(
        label="probe", submodule="external/OpenMetadata",
        declared_in="scripts/openmetadata_sync.py",
        pattern=r'^INGESTION_PIN\s*=\s*f"\{SERVER_PIN\}\.(\d+)"',  # yields "0"
        release_format="{version}-release",
    )
    monkeypatch.setattr(subs, "VERSION_PINS", (broken,))
    result = subs.check_version_pins(modules)[0]
    assert result["status"] == "fail"
    assert "move together" in result["detail"]


def test_the_wheel_pin_derives_from_the_server_pin() -> None:
    """Server 1.13.3 is wheel 1.13.3.0 — one edit moves both."""
    assert oms.INGESTION_PIN.startswith(oms.SERVER_PIN + ".")
    tag = subs.VERSION_PINS[0].release_format.format(version=oms.SERVER_PIN)
    assert tag == f"{oms.SERVER_PIN}-release"


# ---------------------------------------------------------------------------------------
# Unavailable is not failed
# ---------------------------------------------------------------------------------------


def test_an_uninitialised_submodule_is_reported_and_not_failed(monkeypatch) -> None:
    """The normal state of a fresh clone. Red here means the gate gets switched off."""
    absent = subs.Submodule(path="external/does-not-exist", url="https://x/y", shallow=True)
    monkeypatch.setattr(subs, "read_gitmodules", lambda: [absent])
    monkeypatch.setattr(subs, "VERSION_PINS", ())
    payload = subs.report(check=True, do_init=False)
    assert payload["ok"] is True
    assert payload["counts"][subs.ABSENT] == 1
    assert any("--init" in n for n in payload["submodules"][0]["notes"])


def test_the_check_form_passes_on_this_checkout() -> None:
    result = _run("--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_spec_gates_skip_rather_than_pass_when_a_submodule_is_absent(
    monkeypatch, tmp_path: Path,
) -> None:
    """A validator that read nothing must not report `ok`."""
    monkeypatch.setattr(oms, "SPEC_ROOT", tmp_path / "absent")
    monkeypatch.setattr(oms, "OM_ONTOLOGY", tmp_path / "absent.ttl")

    spec = oms.check_against_pinned_spec({"lineage": {"edges": []},
                                          "glossary": {"terms": []}})
    assert spec["status"] == "skip"
    assert "submodule update --init" in spec["detail"]

    vocabulary = oms.check_vocabulary()
    assert vocabulary["status"] == "skip"
    assert "submodule update --init" in vocabulary["detail"]


# ---------------------------------------------------------------------------------------
# What the submodules are actually for
# ---------------------------------------------------------------------------------------


@needs_spec
def test_every_hardcoded_enum_member_exists_in_the_pinned_spec() -> None:
    """The reason `external/OpenMetadata` is pinned rather than read from docs.

    An invented enum member is rejected by the server on push, one entity at a time,
    after the egress has already started.
    """
    result = oms.check_against_pinned_spec({
        "lineage": {"edges": []},
        "glossary": {"terms": []},
    })
    assert result["status"] == "ok", result["problems"]


@needs_standards
def test_every_om_term_the_alignment_uses_exists_upstream() -> None:
    """The reason `external/OpenMetadataStandards` is pinned.

    Written from documentation, the alignment guessed the namespace as `.../schema/`
    (it is `.../ontology/`) and invented `om:glossaryTerm` (no such property). Neither
    was catchable without the ontology on disk.
    """
    result = oms.check_vocabulary()
    assert result["status"] == "ok", result["problems"]
    assert result["declared_terms"] > 100, "the pinned ontology looks truncated"


@needs_standards
def test_the_generated_alignment_uses_only_upstream_declared_terms() -> None:
    """The check above validates the constant; this validates the emitted file."""
    ontology = oms.OM_ONTOLOGY.read_text(encoding="utf-8")
    declared = set(re.findall(r"^om:(\w+)\s+a\s+owl:", ontology, re.M))
    for path in (REPO / "skill-packs/dbt-skills/use-cases").glob(
        "*/openmetadata/rdf/*.ttl"
    ):
        used = set(re.findall(r"\bom:(\w+)\b", path.read_text(encoding="utf-8")))
        unknown = used - declared
        assert not unknown, f"{path}: om: terms not in the pinned ontology: {sorted(unknown)}"


@needs_standards
def test_the_alignment_does_not_redeclare_upstream_terms() -> None:
    """Redeclaring a term upstream owns makes this repo an authority on it — drift."""
    for path in (REPO / "skill-packs/dbt-skills/use-cases").glob(
        "*/openmetadata/rdf/*.ttl"
    ):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^om:\w+\s+a\s+owl:", text, re.M), (
            f"{path} declares an om: term; upstream owns them"
        )


@needs_standards
def test_the_pinned_standards_repo_carries_what_the_docs_claim() -> None:
    """The claims in docs/OPENMETADATA_INTEGRATION.md about rdf/ are checkable now."""
    root = oms.STANDARDS_SUBMODULE / "rdf"
    assert (root / "ontology/openmetadata.ttl").exists()
    assert (root / "ontology/openmetadata-prov.ttl").exists()
    assert (root / "shapes/openmetadata-shapes.ttl").exists()
    assert (root / "contexts/dataAsset.jsonld").exists()


@needs_spec
def test_the_pinned_compose_file_the_deploy_runbook_names_exists() -> None:
    """The runbook stopped curling it once the submodule was pinned; keep it honest."""
    compose = (REPO / "external/OpenMetadata/docker/development"
               / "docker-compose-postgres.yml")
    assert compose.exists()
    runbook = (REPO / "skill-packs/openmetadata-skills/deploy/README.md").read_text(
        encoding="utf-8"
    )
    assert str(compose.relative_to(REPO)) in runbook
