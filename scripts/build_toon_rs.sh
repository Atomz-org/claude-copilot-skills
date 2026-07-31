#!/usr/bin/env bash
# Build the Rust TOON serializer: rust/toon/graph_to_toon.rs -> rust/toon/bin/graph_to_toon
#
# Single-file, dependency-free: plain `rustc -O`, no cargo, no crates.io — the
# module stays buildable offline by submodule consumers. The binary is
# gitignored; the PreToolUse hook (scripts/hooks/toon_graphify_pipe.py) prefers
# it when present and falls back to the Python serializer when it is not.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
src="${root}/rust/toon/graph_to_toon.rs"
out_dir="${root}/rust/toon/bin"

if ! command -v rustc >/dev/null 2>&1; then
  echo "build_toon_rs: rustc not found — the Python serializer remains the runtime" >&2
  exit 1
fi

mkdir -p "${out_dir}"
rustc --edition 2021 -O -o "${out_dir}/graph_to_toon" "${src}"
echo "built ${out_dir}/graph_to_toon ($(rustc --version | cut -d' ' -f2))"
