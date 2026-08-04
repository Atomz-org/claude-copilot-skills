#!/bin/zsh

set -euo pipefail

REPO_ROOT="/Users/sswaminathan/Documents/claude-data-skills/code-skills"
CONTINUE_DIR="$REPO_ROOT/.continue"
VENV_DIR="$REPO_ROOT/.venv"
ENV_FILES=(
  "$CONTINUE_DIR/.env"
  "$CONTINUE_DIR/.env.local"
)

load_env_overrides() {
  local env_file

  for env_file in "$@"; do
    if [ -f "$env_file" ]; then
      set -a
      . "$env_file"
      set +a
    fi
  done
}

load_env_overrides "${ENV_FILES[@]}"

ROUTER_PORT="${ROUTER_PORT:-4000}"
UPSTREAM_HOST="${UPSTREAM_HOST:-127.0.0.1}"
UPSTREAM_PORT="${UPSTREAM_PORT:-8080}"
ROUTER_LOG="/tmp/local_prompt_router_rust.log"
MLX_LOG="/tmp/mlx_lm_server.log"
LOCAL_MODEL="${LOCAL_MODEL:-mlx-community/Qwen3.5-4B-MLX-8bit}"
MLX_BIN="${MLX_BIN:-$VENV_DIR/bin/mlx_lm.server}"
MLX_HOST="${MLX_HOST:-$UPSTREAM_HOST}"
MLX_CMD="${MLX_CMD:-$MLX_BIN --model $LOCAL_MODEL --host $MLX_HOST --port $UPSTREAM_PORT}"

export ROUTER_PORT UPSTREAM_HOST UPSTREAM_PORT LOCAL_MODEL MLX_CMD MLX_BIN MLX_HOST

kill_port_listeners() {
  local port="$1"
  local -a pids

  pids=($(lsof -ti "tcp:$port" 2>/dev/null))
  if (( ${#pids[@]} == 0 )); then
    return
  fi

  kill -9 -- "${pids[@]}"
}

start_mlx_server() {
  if [ ! -x "$MLX_BIN" ]; then
    echo "Missing MLX server entrypoint at $MLX_BIN" >&2
    exit 1
  fi

  if curl -sS --max-time 3 "http://$UPSTREAM_HOST:$UPSTREAM_PORT/v1/models" >/dev/null 2>&1; then
    return
  fi

  kill_port_listeners "$UPSTREAM_PORT"
  nohup env PATH="$VENV_DIR/bin:$PATH" sh -lc "$MLX_CMD" > "$MLX_LOG" 2>&1 &

  local attempt
  for attempt in {1..60}; do
    if curl -sS --max-time 3 "http://$UPSTREAM_HOST:$UPSTREAM_PORT/v1/models" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done

  echo "MLX upstream did not become ready on port $UPSTREAM_PORT" >&2
  tail -n 40 "$MLX_LOG" 2>/dev/null || true
  exit 1
}

# 1) Go to your .continue folder
cd "$CONTINUE_DIR"

# 2) Start or recover the MLX upstream before the router smoke tests.
start_mlx_server

# 3) Kill anything on the router port.
kill_port_listeners "$ROUTER_PORT"

# 4) Rebuild router (explicit temp dir avoids rust temp-dir issues)
mkdir -p /tmp/rust-tmp
TMPDIR=/tmp/rust-tmp rustc local_prompt_router.rs -O -o local_prompt_router

# 5) Start router in background and capture logs
nohup env AUTO_START_MLX=1 PATH="$VENV_DIR/bin:$PATH" ./local_prompt_router > "$ROUTER_LOG" 2>&1 &
sleep 1

# 6) Verify listener
lsof -nP -iTCP:"$ROUTER_PORT" -sTCP:LISTEN

# 7) Verify health (must be JSON, not HTML 501)
curl -i -sS "http://127.0.0.1:$ROUTER_PORT/health"

# 8) Verify chat endpoint
chat_smoke_output="$(mktemp /tmp/local_prompt_router_chat.XXXXXX)"
curl -i -sS "http://127.0.0.1:$ROUTER_PORT/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Reply exactly: OK"}],"stream":false,"max_tokens":16}' \
  > "$chat_smoke_output"
head -n 40 "$chat_smoke_output"