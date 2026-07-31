#!/usr/bin/env bash
# UserPromptSubmit hook: assert the TOON context pipeline on every prompt.
#
# stdout from a UserPromptSubmit hook is injected into the model's context, so
# this line is the per-prompt guarantee that the pipeline is in force. It is
# kept to a single sentence on purpose — the injection cost repeats every
# prompt, and the heavy lifting (auto-piping graphify calls) is done by the
# PreToolUse hook scripts/hooks/toon_graphify_pipe.py, which pipes through the
# Rust serializer rust/toon/bin/graph_to_toon (built by scripts/build_toon_rs.sh).
echo "[toon-pipeline] Graphify→TOON→LLM→JSON is active: bare graphify query/path/explain calls are auto-piped through the Rust serializer rust/toon/bin/graph_to_toon (build once: ./scripts/build_toon_rs.sh); serialize uniform record lists carried forward in context as TOON; emit machine-facing structured output as JSON (graph_to_toon --decode converts TOON→JSON)."
