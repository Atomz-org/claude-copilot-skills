"""The containerised WrenAI demo: its contract, not its execution.

`skill-packs/wren-skills/demo/run_wren_podman_demo.sh` builds an image and runs the
semantic layer inside it. Running that here would mean compiling the Rust query engine
on every `pytest` — minutes, a network, and a container runtime — so this suite pins the
parts that go wrong silently and leaves the run to the demo script:

- the image's pins cannot drift from `requirements.txt` (a container that installs
  different versions is a container that tests something else);
- an absent podman skips with exit 3 rather than failing, per wren-rules.md rule 7;
- the container is never given the working tree, so it cannot dirty it.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "skill-packs/wren-skills/demo"
CONTAINERFILE = DEMO / "Containerfile"
RUNNER = DEMO / "run_wren_podman_demo.sh"
IN_CONTAINER = DEMO / "wren_container_check.sh"
REQUIREMENTS = REPO / "requirements.txt"

# Pins that must be identical in requirements.txt and in the image.
SHARED_PINS = ("sqlglot", "wrenai", "mcp")


def test_the_three_demo_files_exist_and_are_executable() -> None:
    assert CONTAINERFILE.is_file(), "podman reads Containerfile natively; docker needs -f"
    for script in (RUNNER, IN_CONTAINER):
        assert script.is_file(), f"{script.name} missing"
        assert os.access(script, os.X_OK), f"{script.name} is not executable"


def test_both_scripts_are_valid_bash() -> None:
    for script in (RUNNER, IN_CONTAINER):
        proc = subprocess.run(
            ["bash", "-n", str(script)], capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, f"{script.name}: {proc.stderr}"


def _requirement_specs() -> dict[str, str]:
    """`{name: full spec}` for the pins requirements.txt declares."""
    specs: dict[str, str] = {}
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=\[]", line, maxsplit=1)[0].strip()
        specs[name] = line
    return specs


def test_the_image_pins_match_requirements_txt() -> None:
    """A container that resolves different versions is testing a different system.

    wrenai 0.13.2 imports `mcp.server.fastmcp`, which mcp 2.0 removed, and its extra
    declares no upper bound — so an unpinned image builds happily and dies on import.
    sqlglot's major version is load-bearing for the same reason requirements.txt gives:
    30.x renamed the `from` argument, and a resolver reading only the old key returns
    `unresolved` for every edge without erroring.
    """
    containerfile = CONTAINERFILE.read_text(encoding="utf-8")
    specs = _requirement_specs()

    for package in SHARED_PINS:
        assert package in specs, f"{package} vanished from requirements.txt"
        constraint = specs[package].split("#")[0].strip()
        assert f'"{constraint}"' in containerfile, (
            f"Containerfile must install {package} as `{constraint}`, exactly as "
            f"requirements.txt pins it"
        )


def test_the_image_installs_offline_so_a_bad_pin_fails_loudly() -> None:
    """`--no-index` is what turns an unsatisfiable pin into an error.

    Without it, a pin the builder stage failed to produce a wheel for is quietly
    resolved from PyPI instead, and the image ships a version nobody chose.
    """
    containerfile = CONTAINERFILE.read_text(encoding="utf-8")
    assert "--no-index" in containerfile
    assert "--find-links=/wheels" in containerfile


def test_the_container_never_receives_the_working_tree() -> None:
    """It gets a staged copy, mounted read-only; `dbt build` writes beside its sources."""
    runner = RUNNER.read_text(encoding="utf-8")
    assert "mktemp -d" in runner, "the use-case is staged, not mounted from the repo"
    assert ":/stage:ro" in runner, "the mount must be read-only"
    assert "--network=none" in runner, (
        "wren-rules.md rule 9 makes egress opt-in; the tier needs no network to run"
    )


def test_the_runner_skips_rather_than_fails_without_podman(tmp_path: Path) -> None:
    """wren-rules.md rule 7. A gate that goes red on a correct state gets switched off.

    The PATH is rebuilt with only what the script uses *before* the preflight — `bash`
    to run it and `dirname` to resolve the repository root — so `command -v podman`
    genuinely misses and the real branch executes. Emptying PATH outright would make the
    test fail on the missing `bash` and prove nothing about podman.
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for tool in ("bash", "dirname"):
        resolved = shutil.which(tool)
        assert resolved, f"{tool} is needed to run the script at all"
        (fake_bin / tool).symlink_to(resolved)
    assert shutil.which("podman", path=str(fake_bin)) is None

    env = dict(os.environ, PATH=str(fake_bin))
    proc = subprocess.run(
        [str(fake_bin / "bash"), str(RUNNER)], capture_output=True, text=True, env=env,
        timeout=120, check=False,
    )

    assert proc.returncode == 3, (
        f"expected the documented skip code 3, got {proc.returncode}\n{proc.stderr}"
    )
    assert "SKIP" in proc.stderr
    assert "podman" in proc.stderr.lower(), "the skip must name the missing tool"


def test_the_run_does_not_pass_workdir() -> None:
    """podman 5.8.5 rejects `--workdir /work` for a directory that exists.

    The Containerfile's `WORKDIR /work` already sets it, and adding the flag makes the
    run die with `workdir "/work" does not exist on container` — while
    `podman run ... ls -ld /work` lists the directory and `WorkingDir` inspects as
    `/work`. Isolated by bisecting the flags: it reproduces with `--workdir` alone, no
    volume and no network options involved.

    The flag is redundant, so removing it is the fix rather than a workaround. This test
    exists because re-adding it looks like an improvement.
    """
    runner = RUNNER.read_text(encoding="utf-8")
    run_invocation = runner.split("podman run", 1)[1].split("\n\n", 1)[0]
    assert "--workdir" not in run_invocation, (
        "WORKDIR in the image already sets it; the flag makes podman 5.8.5 fail"
    )
    assert "WORKDIR /work" in CONTAINERFILE.read_text(encoding="utf-8")


def test_the_preflight_checks_memory_and_names_the_remedy() -> None:
    """Peak memory is what fails this build, and it fails unrecognisably.

    The image compiles WrenAI's Rust core; cargo runs one rustc per core, and on a stock
    `podman machine` (2 GiB) compiling sqlparser at opt-level=3 is OOM-killed. What the
    build prints is `signal: 9, SIGKILL` against whichever crate lost the race, which
    reads like a compiler bug. Measured: the build ran 3.5 minutes and died there.

    Bounding cargo's jobs helps but cannot rescue 2 GiB on its own, so the runner checks
    and the Containerfile bounds — both, not either.
    """
    runner = RUNNER.read_text(encoding="utf-8")
    assert "MemTotal" in runner, "the preflight must read the machine's memory"
    assert "podman machine set --memory" in runner, "a skip must name its remedy"

    containerfile = CONTAINERFILE.read_text(encoding="utf-8")
    assert "CARGO_BUILD_JOBS" in containerfile, (
        "cargo defaults to one rustc per core; unbounded, the peak OOMs a small VM"
    )


@pytest.mark.skipif(
    shutil.which("podman") is None, reason="podman not installed"
)
def test_podman_preflight_probes_the_machine_not_just_the_binary() -> None:
    """On macOS the binary exists whether or not the VM is up.

    `podman --version` answers from the client alone, so a preflight built on it reports
    ready and the build then fails on a socket error. `podman info` round-trips.
    """
    runner = RUNNER.read_text(encoding="utf-8")
    assert "podman info" in runner
    assert "podman machine init" in runner, "the skip must name the remedy"
