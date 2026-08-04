# Makefile for graphify operations
# ================================
#
# This Makefile provides shortcuts for common graphify workflows in this repository,
# including initialization, updates, and querying. It respects the project's
# specific two-stage graph generation process to ensure dbt lineage is correctly merged.
#
# Run from repository root: `make -f scripts/Makefile <target>`

# Variables
# ---------
# Use `make -f scripts/Makefile <target> USE_CASE=your-case` to override
USE_CASE ?= enhanza-analytics
# Use `make -f scripts/Makefile query q="your question"`
q ?= "how does activation work"
# Extra flags for `init`, e.g. REBUILD_FLAGS="--code-only" or "--cold"
REBUILD_FLAGS ?=
# Use `make -f scripts/Makefile path from="start" to="end"`
from ?= "GraphManager"
to ?= "toon-serializer"

# Tools and Paths
# ---------------
ROOT_DIR := $(shell pwd)
PYTHON := $(ROOT_DIR)/.venv/bin/python3
GRAPHIFY := $(shell command -v graphify)
TOON_SERIALIZER := $(ROOT_DIR)/rust/toon/bin/graph_to_toon
SYNC_SCRIPT := $(ROOT_DIR)/scripts/use_case_sync.py
DBT_REFRESH_SCRIPT := $(ROOT_DIR)/skill-packs/dbt-skills/use-cases/$(USE_CASE)/artifacts/refresh.sh

.PHONY: all help build clean init update sync query path

all: help

help:
	@echo "Makefile for managing the graphify graph."
	@echo ""
	@echo "Usage: make -f scripts/Makefile <target> [VAR=value]"
	@echo ""
	@echo "Targets:"
	@echo "  help          Show this help message."
	@echo "  build         Build the Rust TOON serializer dependency."
	@echo "  init          Rebuild the entire graph from scratch (clean, build, sync)."
	@echo "  update        Update the code graph and merge dbt lineage (recommended)."
	@echo "  sync          Sync dbt lineage into the existing graph without a code rebuild."
	@echo "  query         Run 'graphify query'. Use 'q=\"...\"'."
	@echo "  path          Run 'graphify path'. Use 'from=\"...\" to=\"...\"'."
	@echo "  clean         Remove the graphify-out/ directory."
	@echo ""
	@echo "Variables:"
	@echo "  USE_CASE      The dbt use-case to sync (default: enhanza-analytics)."
	@echo "  q             The query for 'make query'."
	@echo "  from, to      The start and end nodes for 'make path'."

# Build dependencies
# ------------------
build: $(TOON_SERIALIZER)

$(TOON_SERIALIZER): $(ROOT_DIR)/rust/toon/graph_to_toon.rs
	@echo "--> Building TOON serializer..."
	@$(ROOT_DIR)/scripts/build_toon_rs.sh

# Graph lifecycle
# ---------------
# `init` no longer depends on `clean`. It used to, and `clean` is `rm -rf
# graphify-out` — so the graph was destroyed before anything verified a rebuild
# could succeed. It could not (no LLM API key), and the repository was left with
# no graph at all. scripts/graphify_rebuild.sh checks every precondition first,
# moves the old graph aside instead of deleting it, verifies the new one, and
# restores the old one on any failure or interrupt.
init: build
	@echo "--> Initializing graph from scratch for use-case: $(USE_CASE)"
	@$(ROOT_DIR)/scripts/graphify_rebuild.sh --use-case $(USE_CASE) $(REBUILD_FLAGS)
	@echo "--> Graph initialized successfully."

update: build
	@echo "--> Updating code graph and syncing dbt lineage for use-case: $(USE_CASE)..."
	@$(PYTHON) $(SYNC_SCRIPT) --use-case $(USE_CASE) --graphify-update
	@echo "--> Graph updated successfully."

sync:
	@echo "--> Syncing dbt lineage into existing graph for use-case: $(USE_CASE)..."
	@$(PYTHON) $(SYNC_SCRIPT) --use-case $(USE_CASE)
	@echo "--> dbt lineage synced."

clean:
	@echo "--> Removing graphify-out/ directory..."
	@rm -rf $(ROOT_DIR)/graphify-out

# Graph queries
# -------------
query: build
	@echo "--> Running graphify query: $(q)"
	@if [ -z "$(GRAPHIFY)" ]; then echo "ERROR: graphify command not found. Please install it."; exit 1; fi
	@$(GRAPHIFY) query "$(q)" | $(TOON_SERIALIZER) --passthrough

path: build
	@echo "--> Running graphify path from '$(from)' to '$(to)'"
	@if [ -z "$(GRAPHIFY)" ]; then echo "ERROR: graphify command not found. Please install it."; exit 1; fi
	@$(GRAPHIFY) path "$(from)" "$(to)" | $(TOON_SERIALIZER) --passthrough