#!/usr/bin/env bash
set -euo pipefail

payload="$(cat)"
cmd="$(printf '%s' "$payload" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"

if [[ -z "${cmd}" ]]; then
  exit 0
fi

is_blocked="false"

if [[ "$cmd" =~ ^git[[:space:]]+push ]]; then
  is_blocked="true"
fi
if [[ "$cmd" =~ ^git[[:space:]]+reset[[:space:]]+--hard ]]; then
  is_blocked="true"
fi
if [[ "$cmd" =~ ^git[[:space:]]+clean[[:space:]]+-f(d)? ]]; then
  is_blocked="true"
fi
if [[ "$cmd" =~ ^git[[:space:]]+branch[[:space:]]+-D ]]; then
  is_blocked="true"
fi
if [[ "$cmd" =~ ^git[[:space:]]+checkout[[:space:]]+\. ]]; then
  is_blocked="true"
fi
if [[ "$cmd" =~ ^git[[:space:]]+restore[[:space:]]+\. ]]; then
  is_blocked="true"
fi

if [[ "$is_blocked" == "true" ]]; then
  echo "BLOCKED: dangerous git command is not allowed by repository guardrails: $cmd" >&2
  exit 2
fi

exit 0
