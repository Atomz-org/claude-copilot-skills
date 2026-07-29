import os
import subprocess
import sys
from pathlib import Path


def test_git_standard_allows_sync_branch_name(tmp_path):
    script = Path(__file__).resolve().parents[1] / ".claude/commands/git-standard.sh"
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "sync/branch-update"], cwd=repo_dir, check=True, capture_output=True)
    (repo_dir / "README.md").write_text("sync test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo_dir, check=True, capture_output=True)

    result = subprocess.run(
        ["bash", str(script), "chore: add sync branch test"],
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Commit message approved" in result.stdout


def test_git_standard_rejects_invalid_branch_name(tmp_path):
    script = Path(__file__).resolve().parents[1] / ".claude/commands/git-standard.sh"
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "feature/test"], cwd=repo_dir, check=True, capture_output=True)

    result = subprocess.run(
        ["bash", str(script), "feat: add test"],
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Branch name must follow" in result.stdout or "Branch name must follow" in result.stderr
