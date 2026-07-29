import pytest


@pytest.mark.xfail(reason="Deliberate quality-gate demo case", strict=False)
def test_ci_quality_gate_should_fail_for_demo() -> None:
    assert False, "Deliberate failure to validate CI quality gate behavior"
