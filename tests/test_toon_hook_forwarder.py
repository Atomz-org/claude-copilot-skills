import json
import os
import stat
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FORWARDER = REPO_ROOT / "scripts" / "hooks" / "toon_graphify_pipe.py"


def _run_forwarder(payload: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(FORWARDER)],
        input=json.dumps(payload).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=run_env,
        check=False,
    )


def test_forwarder_references_copilot_hook_path():
    text = FORWARDER.read_text(encoding="utf-8")
    assert ".copilot" in text
    assert "toon_graphify_pipe.py" in text
    assert "COPILOT_TOON_HOOK" in text


def test_forwarder_passes_through_to_target(tmp_path: Path):
    target = tmp_path / "hook.py"
    target.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, sys",
                "payload = json.load(sys.stdin)",
                "command = payload.get('tool_input', {}).get('command', '')",
                "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'allow', 'updatedInput': {'command': command + ' | forwarded'}}}))",
            ]
        ),
        encoding="utf-8",
    )
    target.chmod(target.stat().st_mode | stat.S_IXUSR)

    payload = {"tool_name": "Bash", "tool_input": {"command": "graphify query \"x\""}}
    result = _run_forwarder(payload, env={"COPILOT_TOON_HOOK": str(target)})

    assert result.returncode == 0
    output = json.loads(result.stdout.decode("utf-8"))
    updated = output["hookSpecificOutput"]["updatedInput"]["command"]
    assert updated.endswith("| forwarded")


def test_forwarder_noop_when_target_missing():
    payload = {"tool_name": "Bash", "tool_input": {"command": "graphify query \"x\""}}
    result = _run_forwarder(payload, env={"COPILOT_TOON_HOOK": "/tmp/definitely-missing-hook.py"})

    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""