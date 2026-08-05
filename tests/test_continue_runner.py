from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_continue_runner_uses_safe_pid_handling_and_repo_venv_mlx_server():
    script = (REPO_ROOT / ".continue/continue2.sh").read_text(encoding="utf-8")

    assert 'ENV_FILES=(' in script
    assert 'load_env_overrides "${ENV_FILES[@]}"' in script
    assert 'set -a' in script
    assert 'UPSTREAM_HOST="${UPSTREAM_HOST:-127.0.0.1}"' in script
    assert 'MLX_BIN="${MLX_BIN:-$VENV_DIR/bin/mlx_lm.server}"' in script
    assert 'MLX_HOST="${MLX_HOST:-$UPSTREAM_HOST}"' in script
    assert "local -a pids" in script
    assert "kill -9 -- \"${pids[@]}\"" in script
    assert 'curl -sS --max-time 3 "http://$UPSTREAM_HOST:$UPSTREAM_PORT/v1/models"' in script
    assert 'nohup env PATH="$VENV_DIR/bin:$PATH" sh -lc "$MLX_CMD"' in script
    assert 'AUTO_START_MLX=1' in script
    assert 'chat_smoke_output="$(mktemp /tmp/local_prompt_router_chat.XXXXXX)"' in script


def test_local_prompt_router_retries_after_upstream_restart():
    router = (REPO_ROOT / ".continue/local_prompt_router.rs").read_text(encoding="utf-8")

    assert "fn kill_upstream_listener(cfg: &Cfg)" in router
    assert "fn restart_mlx(cfg: &Cfg)" in router
    assert "fn forward_with_recovery(cfg: &Cfg, target_path: &str, body: &[u8])" in router
    assert 'match forward_with_recovery(&cfg, &cfg.upstream_chat_path, body.as_bytes())' in router
    assert 'match forward_with_recovery(&cfg, &cfg.upstream_completions_path, body.as_bytes())' in router


def test_continue_makefile_exposes_environment_overrides():
    makefile = (REPO_ROOT / ".continue/Makefile").read_text(encoding="utf-8")

    assert "UPSTREAM_HOST ?= 127.0.0.1" in makefile
    assert "UPSTREAM_PORT ?= 8080" in makefile
    assert "LOCAL_MODEL ?= mlx-community/Qwen3.5-4B-MLX-8bit" in makefile
    assert "MLX_BIN ?= /Users/sswaminathan/Documents/claude-data-skills/code-skills/.venv/bin/mlx_lm.server" in makefile
    assert "MLX_HOST ?= $(UPSTREAM_HOST)" in makefile
    assert "MLX_CMD ?= $(MLX_BIN) --model $(LOCAL_MODEL) --host $(MLX_HOST) --port $(UPSTREAM_PORT)" in makefile
    assert "Optional overrides: export LOCAL_MODEL=... or write .continue/.env.local" in makefile


def test_continue_env_example_documents_supported_overrides():
    env_example = (REPO_ROOT / ".continue/.env.example").read_text(encoding="utf-8")

    assert "Copy this file to .continue/.env.local" in env_example
    assert "ROUTER_PORT=4000" in env_example
    assert "UPSTREAM_HOST=127.0.0.1" in env_example
    assert "UPSTREAM_PORT=8080" in env_example
    assert "LOCAL_MODEL=mlx-community/Qwen3.5-4B-MLX-8bit" in env_example
    assert "MLX_BIN=/Users/sswaminathan/Documents/claude-data-skills/code-skills/.venv/bin/mlx_lm.server" in env_example
    assert 'MLX_CMD="$MLX_BIN --model $LOCAL_MODEL --host $MLX_HOST --port $UPSTREAM_PORT"' in env_example
    assert "CLINE_HARD_INPUT_TOKENS=36000" in env_example