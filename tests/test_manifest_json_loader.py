"""Tests for the artifact JSON loader in `scripts/_manifest.py`.

`load_json` is the single chokepoint every script uses to read dbt's JSON artifacts, so
the accelerator swap underneath it has to be invisible. Two properties matter:

1. **Parser equivalence** — orjson and the standard library must return the same object
   for the same bytes. The fallback is forced explicitly rather than left to whichever
   environment the suite happens to run in, so both branches are covered on a machine
   with orjson installed and on one without.
2. **Failure behaviour is unchanged** — a missing or malformed artifact must still exit
   with the actionable message, whichever parser raised. The two parsers raise different
   exception classes; only their shared `ValueError` base is relied on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import _manifest  # noqa: E402

# Ships on the default branch, so it is safe to assert against directly — see the note
# in `test_new_connector.py` about branch-dependent use-cases.
EXAMPLE_MANIFEST = (
    REPO
    / "skill-packs"
    / "dbt-skills"
    / "use-cases"
    / "example-order-revenue-mart"
    / "artifacts"
    / "prod"
    / "manifest.json"
)

needs_orjson = pytest.mark.skipif(
    not _manifest.using_orjson(), reason="orjson is not installed in this environment"
)


@pytest.fixture
def stdlib_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the standard-library branch regardless of what is installed."""
    monkeypatch.setattr(_manifest, "_orjson", None)


# ---------------------------------------------------------------- parser selection


def test_using_orjson_matches_importability() -> None:
    try:
        import orjson  # noqa: F401
        expected = True
    except ImportError:
        expected = False
    assert _manifest.using_orjson() is expected


def test_parser_name_reports_the_active_parser() -> None:
    name = _manifest.json_parser_name()
    assert name == ("orjson" if _manifest.using_orjson() else "bundled standard-library json")


def test_fallback_is_reported_when_forced(stdlib_only: None) -> None:
    assert _manifest.using_orjson() is False
    assert _manifest.json_parser_name() == "bundled standard-library json"


# ---------------------------------------------------------------- loads()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"nodes": {}},
        {"a": [1, 2.5, True, False, None]},
        {"nested": {"deep": {"deeper": ["x"]}}},
        {"unicode": "naïve café — ✓"},
        {"big_int": 2**53 + 1},
        {"escaped": 'quote " backslash \\ newline \n tab \t'},
    ],
)
def test_loads_roundtrips_payloads(payload: dict) -> None:
    raw = json.dumps(payload).encode("utf-8")
    assert _manifest.loads(raw) == payload


def test_loads_accepts_bytes_not_just_str(stdlib_only: None) -> None:
    assert _manifest.loads(b'{"k": "v"}') == {"k": "v"}


def test_loads_raises_valueerror_on_garbage() -> None:
    with pytest.raises(ValueError):
        _manifest.loads(b"{not json")


@needs_orjson
def test_both_parsers_agree_on_the_same_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The equivalence that makes the swap safe. Only meaningful with orjson present."""
    raw = EXAMPLE_MANIFEST.read_bytes()
    with_orjson = _manifest.loads(raw)
    monkeypatch.setattr(_manifest, "_orjson", None)
    with_stdlib = _manifest.loads(raw)
    assert with_orjson == with_stdlib


# ---------------------------------------------------------------- load_json()


def test_load_json_reads_the_example_manifest() -> None:
    data = _manifest.load_json(str(EXAMPLE_MANIFEST), "manifest.json")
    assert isinstance(data, dict)
    assert data.get("nodes"), "example manifest should expose nodes"


def test_load_json_matches_a_plain_stdlib_read() -> None:
    """Guards the 'rb' + loads() rewrite against the original text-mode json.load."""
    with open(EXAMPLE_MANIFEST, "r", encoding="utf-8") as fh:
        expected = json.load(fh)
    assert _manifest.load_json(str(EXAMPLE_MANIFEST), "manifest.json") == expected


def test_load_json_works_on_the_fallback_path(stdlib_only: None) -> None:
    data = _manifest.load_json(str(EXAMPLE_MANIFEST), "manifest.json")
    assert data.get("nodes")


def test_manifest_load_still_wraps_the_artifact() -> None:
    man = _manifest.Manifest.load(str(EXAMPLE_MANIFEST))
    assert man.nodes
    assert man.path == str(EXAMPLE_MANIFEST)


def test_load_json_preserves_utf8(tmp_path: Path) -> None:
    artifact = tmp_path / "manifest.json"
    payload = {"description": "one row per café — naïve ✓"}
    artifact.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert _manifest.load_json(str(artifact))["description"] == payload["description"]


# ---------------------------------------------------------------- failure paths


def test_missing_artifact_exits_with_guidance(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    with pytest.raises(SystemExit) as exc:
        _manifest.load_json(str(tmp_path / "absent.json"), "manifest.json")
    assert exc.value.code == 2
    assert "dbt parse" in capsys.readouterr().err


@pytest.mark.parametrize("forced_fallback", [False, True])
def test_malformed_artifact_exits_with_the_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    forced_fallback: bool,
) -> None:
    """Both parsers raise distinct classes; both must land on the same message."""
    if forced_fallback:
        monkeypatch.setattr(_manifest, "_orjson", None)
    artifact = tmp_path / "manifest.json"
    artifact.write_text('{"nodes": ', encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _manifest.load_json(str(artifact), "manifest.json")

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "not valid JSON" in err
    assert str(artifact) in err


def test_empty_artifact_is_treated_as_malformed(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    artifact = tmp_path / "manifest.json"
    artifact.write_bytes(b"")
    with pytest.raises(SystemExit):
        _manifest.load_json(str(artifact), "manifest.json")
    assert "not valid JSON" in capsys.readouterr().err
