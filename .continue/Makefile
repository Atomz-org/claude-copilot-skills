SHELL := /bin/zsh

# Local router defaults for regular usage.
# The Rust router reads these values from environment variables at startup.
ROUTER_PORT ?= 4000
HARD_REQUEST_BYTES ?= 3000000
HARD_INPUT_TOKENS ?= 24000
DISABLE_STREAM_OVER_TOKENS ?= 10000
UPSTREAM_HOST ?= 127.0.0.1
UPSTREAM_PORT ?= 8080
LOCAL_MODEL ?= mlx-community/Qwen3.5-4B-MLX-8bit
MLX_BIN ?= /Users/sswaminathan/Documents/claude-data-skills/code-skills/.venv/bin/mlx_lm.server
MLX_HOST ?= $(UPSTREAM_HOST)
MLX_CMD ?= $(MLX_BIN) --model $(LOCAL_MODEL) --host $(MLX_HOST) --port $(UPSTREAM_PORT)

# Cline tends to send larger contexts/tool transcripts than lightweight chat clients.
# These values are intentionally higher than defaults to reduce 413 local_budget_exceeded errors.
CLINE_HARD_REQUEST_BYTES ?= 5000000
CLINE_HARD_INPUT_TOKENS ?= 36000
CLINE_DISABLE_STREAM_OVER_TOKENS ?= 14000

.PHONY: setup run run-cline health test stop

setup:
	# Print the available local run entrypoint and override mechanism. No process changes happen here.
	echo "Continue local run helpers are available. Use: make run"
	echo "Optional overrides: export LOCAL_MODEL=... or write .continue/.env.local"

run:
	# Start the local router using normal limits.
	# continue2.sh handles: kill existing listener, rebuild router, start background process,
	# and perform health/chat smoke checks.
	ROUTER_PORT=$(ROUTER_PORT) \
	UPSTREAM_HOST=$(UPSTREAM_HOST) \
	UPSTREAM_PORT=$(UPSTREAM_PORT) \
	HARD_REQUEST_BYTES=$(HARD_REQUEST_BYTES) \
	HARD_INPUT_TOKENS=$(HARD_INPUT_TOKENS) \
	DISABLE_STREAM_OVER_TOKENS=$(DISABLE_STREAM_OVER_TOKENS) \
	LOCAL_MODEL=$(LOCAL_MODEL) \
	MLX_BIN=$(MLX_BIN) \
	MLX_HOST=$(MLX_HOST) \
	MLX_CMD='$(MLX_CMD)' \
	zsh continue2.sh

run-cline:
	# Start the local router with Cline-specific higher budgets.
	# Use this target when Cline reports empty/unparsable responses caused by upstream truncation
	# or frequent 413 local_budget_exceeded from large request payloads.
	ROUTER_PORT=$(ROUTER_PORT) \
	UPSTREAM_HOST=$(UPSTREAM_HOST) \
	UPSTREAM_PORT=$(UPSTREAM_PORT) \
	HARD_REQUEST_BYTES=$(CLINE_HARD_REQUEST_BYTES) \
	HARD_INPUT_TOKENS=$(CLINE_HARD_INPUT_TOKENS) \
	DISABLE_STREAM_OVER_TOKENS=$(CLINE_DISABLE_STREAM_OVER_TOKENS) \
	LOCAL_MODEL=$(LOCAL_MODEL) \
	MLX_BIN=$(MLX_BIN) \
	MLX_HOST=$(MLX_HOST) \
	MLX_CMD='$(MLX_CMD)' \
	zsh continue2.sh

health:
	# Probe the router health endpoint. Expected: HTTP 200 with JSON status payload.
	curl -i -sS http://127.0.0.1:$(ROUTER_PORT)/health

test:
	# Send a minimal OpenAI-compatible chat request through the router.
	# This validates that request parsing, routing, and model forwarding are functioning.
	curl -i -sS http://127.0.0.1:4000/v1/chat/completions \
	  -H "Content-Type: application/json" \
	  -d '{"messages":[{"role":"user","content":"Reply exactly: OK"}],"stream":false,"max_tokens":16}' | head -n 40

stop:
	# Force-stop any process listening on the router port.
	# Useful when a previous run left a stale listener or a rebuild needs a clean port.
	PORT=$(ROUTER_PORT); PID=$$(lsof -ti tcp:$$PORT || true); if [ -n "$$PID" ]; then kill -9 $$PID; fi
