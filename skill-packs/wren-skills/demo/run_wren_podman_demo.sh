#!/usr/bin/env bash
# WrenAI semantic layer end to end, inside a container, driven by podman.
#
#   podman build (Containerfile)  ->  dbt build (DuckDB)  ->  wren context build (MDL)
#   ->  governed `wren query`  ->  cross-check vs DuckDB  ->  metric view == MetricFlow
#
# Same two exact pass criteria as the host demo (run_wren_demo.sh), so the two runs are
# directly comparable and a container-only failure is visible as one.
#
# podman, not docker: rootless and daemonless, so nothing here needs a privileged daemon
# or a Docker Desktop licence. The commands are CLI-compatible with docker's, so
# substituting `docker` works — but the file is named for the tool it was verified with,
# and `Containerfile` is podman's native filename.
#
# On macOS podman runs a Linux VM (`podman machine`); this checks the machine is up and
# says how to start it rather than failing with a socket error.
#
# Exit codes:
#   0  the semantic layer produced the right numbers in the container
#   1  it did not — a real failure
#   3  podman is unavailable; nothing was proved and nothing is claimed
#
# 3 rather than 1 because of wren-rules.md rule 7: a gate that goes red on a correct
# state gets switched off within a week, taking the real failures with it. It matches
# scripts/skill_map_scan.py, which returns 3 where Node is absent.
set -euo pipefail

root="$(cd "$(dirname "$0")/../../.." && pwd)"
here="$(cd "$(dirname "$0")" && pwd)"
uc_rel="skill-packs/dbt-skills/use-cases/example-order-revenue-mart"
image="localhost/code-skills-wren-demo:0.13.2"

step() { printf '\n== %s\n' "$1"; }
skip() { printf '\nSKIP: %s\n' "$1" >&2; exit 3; }

step "0/4 podman preflight"
command -v podman >/dev/null 2>&1 || skip "no podman on PATH — https://podman.io/docs/installation"

# `podman info` is the honest probe: it round-trips to the machine on macOS and to the
# local socket on Linux, so it fails exactly when a build would.
if ! podman info >/dev/null 2>&1; then
  skip "podman is installed but not ready — run: podman machine init --now (macOS), or start the podman service (Linux)"
fi
echo "podman: $(podman --version)"
echo "host arch: $(podman info --format '{{.Host.Arch}}' 2>/dev/null || echo unknown)"

# The image compiles WrenAI's Rust core (see Containerfile for why a wheel is not an
# option here). cargo runs one rustc per core, and on a stock `podman machine` — 2 GiB —
# compiling sqlparser at opt-level=3 gets OOM-killed. The build reports
# `signal: 9, SIGKILL` against whichever crate lost, which reads like a compiler bug and
# sends you looking in the wrong place. Naming the limit up front is the whole point.
mem_bytes="$(podman info --format '{{.Host.MemTotal}}' 2>/dev/null || echo 0)"
if [[ "${mem_bytes}" =~ ^[0-9]+$ ]] && (( mem_bytes > 0 )); then
  mem_gib=$(( mem_bytes / 1024 / 1024 / 1024 ))
  echo "memory:    ${mem_gib} GiB"
  if (( mem_gib < 4 )); then
    skip "podman has ${mem_gib} GiB; building the Rust core needs ~4 GiB. Remedy:
         podman machine stop && podman machine set --memory 8192 --cpus 6 && podman machine start"
  fi
fi

step "1/4 stage the use-case somewhere podman can read"
# Two macOS constraints decide this, and staging satisfies both with one code path
# rather than an `if [[ $(uname) == Darwin ]]`:
#
#   1. podman cannot bind-mount a path under ~/Documents (or ~/Desktop, ~/Downloads).
#      Those are TCC-protected, the VM helper is not granted access, and the failure is
#      `statfs <path>: operation not permitted` — which reads like a podman bug rather
#      than a macOS privacy prompt nobody answered.
#   2. podman's statfs does not resolve symlinks, and /tmp is a symlink to /private/tmp,
#      so a literal /tmp/... mount fails with `no such file or directory` while the
#      directory plainly exists. `pwd -P` resolves it.
#
# Staging is also what makes the read-only guarantee real: the container gets a copy,
# so no bug in it can reach the working tree.
stage="$(mktemp -d)"
stage="$(cd "${stage}" && pwd -P)"
cleanup() { rm -rf "${stage}"; }
trap cleanup EXIT

cp -R "${root}/${uc_rel}" "${stage}/uc"
cp "${here}/wren_container_check.sh" "${stage}/wren_container_check.sh"
chmod +x "${stage}/wren_container_check.sh"
# The Containerfile is staged for the same TCC reason as everything else: `podman build`
# needs read access to its context directory, and a context under ~/Documents fails with
# `faccessat <path>: operation not permitted`. Staging costs nothing here because the
# image copies no repository content — the context is the one file.
mkdir -p "${stage}/ctx"
cp "${here}/Containerfile" "${stage}/ctx/Containerfile"
# Host build output is host state, not evidence about this run. Removing it here rather
# than in the container keeps the container's job to "build and verify", so an empty
# result cannot be mistaken for a passing one.
rm -rf "${stage}/uc/dbt_project/target" \
       "${stage}/uc/dbt_project/dev.duckdb" \
       "${stage}/uc/dbt_project/logs" \
       "${stage}/uc/wren/target"
echo "staged: ${stage}"

step "2/4 build the image"
podman build --quiet \
  --tag "${image}" --file "${stage}/ctx/Containerfile" "${stage}/ctx" >/dev/null
echo "image: ${image}"

step "3/4 run the semantic layer in the container"
# --rm            leave no container behind
# :ro             the stage is read-only; every write goes to the container's /work
# --network=none  after the build there is nothing left to fetch, and wren-rules.md
#                 rule 9 treats egress as something the user opts into per run. Running
#                 the tier fully offline is also the stronger claim.
#
# There is deliberately no `--workdir /work`. The Containerfile's `WORKDIR /work` already
# sets it, and passing the flag as well makes podman 5.8.5 fail with
# `workdir "/work" does not exist on container` — for a directory that demonstrably does
# exist (`podman run ... ls -ld /work` shows it, and `WorkingDir` inspects as `/work`).
# Isolated by bisecting the flags: the error appears with `--workdir` alone and with no
# volume or network options present at all.
podman run --rm \
  --network=none \
  --volume "${stage}:/stage:ro" \
  --entrypoint /bin/bash \
  "${image}" /stage/wren_container_check.sh

step "4/4 host tree unchanged"
if command -v git >/dev/null 2>&1 && git -C "${root}" rev-parse --git-dir >/dev/null 2>&1; then
  dirty="$(git -C "${root}" status --porcelain -- "${uc_rel}" | wc -l | tr -d ' ')"
  if [[ "${dirty}" != "0" ]]; then
    echo "FAIL: the run modified the host tree (${dirty} path(s))" >&2
    git -C "${root}" status --porcelain -- "${uc_rel}" >&2
    exit 1
  fi
  echo "clean: the working tree is untouched"
fi

printf '\nWrenAI podman demo: PASS\n'
