# .continue

Local Continue runtime assets for this repository.

This folder configures and runs a local-only AI workflow:

- Continue client points to a local OpenAI-compatible endpoint.
- Local router enforces request/token/size budgets.
- MLX model server is used as the upstream model backend.
- Cloud fallback is intentionally disabled.

## What each file does

- `config.json`: Router policy and hard limits (`local_only`, token/byte budgets, error behavior).
- `config.yaml`: Continue client model profile and workflow system message.
- `continue2.sh`: Main local runtime launcher. Starts/restarts MLX and router, then runs smoke checks.
- `continue.sh`: Patches `~/.continue/config.json|yaml` to local-only routing at `http://127.0.0.1:4000/v1`.
- `Makefile`: Main operational entrypoints for setup, run, health checks, and stop.
- `local_prompt_router.rs`: Rust router source compiled and launched by `continue2.sh`.
- `rollback_continue.sh`: Restore/rollback helper for previous config state.

## Prerequisites

- Repository virtual environment at `.venv` with `mlx_lm.server` available.
- `rustc` installed to compile `local_prompt_router.rs`.
- Continue extension installed in VS Code.

## Commands

Run from this folder or repo root with `make -C .continue <target>`.

### Core targets

- `make setup`
  - Prints available run helpers and environment override hints.

- `make run`
  - Starts local router with normal budgets.
  - Uses `continue2.sh` to:
    - kill stale listeners,
    - ensure MLX upstream is running,
    - compile `local_prompt_router.rs`,
    - start router in background,
    - validate `/health` and `/v1/chat/completions`.

- `make run-cline`
  - Starts local router with larger request/token budgets tuned for Cline payload sizes.

- `make health`
  - Calls router health endpoint:
    - `http://127.0.0.1:${ROUTER_PORT:-4000}/health`

- `make test`
  - Sends a minimal chat completion request through the local router.

- `make stop`
  - Force-stops process bound to `ROUTER_PORT`.

## Useful environment overrides

You can export these before `make run` or place them in `.continue/.env.local`:

- `ROUTER_PORT` (default `4000`)
- `UPSTREAM_HOST` (default `127.0.0.1`)
- `UPSTREAM_PORT` (default `8080`)
- `LOCAL_MODEL` (default `mlx-community/Qwen3.5-4B-MLX-8bit`)
- `MLX_BIN` (default `.venv/bin/mlx_lm.server`)
- `HARD_REQUEST_BYTES`, `HARD_INPUT_TOKENS`, `DISABLE_STREAM_OVER_TOKENS`

Example:

```bash
cd .continue
export LOCAL_MODEL="mlx-community/Qwen3.5-4B-MLX-8bit"
make run
```

## Common workflow

```bash
cd .continue
make run
make health
make test
```

If you update `config.yaml` or `config.json`, restart Continue chat so changes are picked up.