cd /Users/sswaminathan/Documents/claude-data-skills/code-skills
source .venv/bin/activate

set -euo pipefail

ROUTER_API_BASE="http://127.0.0.1:4000/v1"
ROUTER_MODEL="mlx-community/Qwen3.5-4B-MLX-8bit"
CFG_DIR="$HOME/.continue"

if [ -f "$CFG_DIR/config.json" ]; then
  CFG="$CFG_DIR/config.json"
elif [ -f "$CFG_DIR/config.yaml" ]; then
  CFG="$CFG_DIR/config.yaml"
elif [ -f "$CFG_DIR/config.yml" ]; then
  CFG="$CFG_DIR/config.yml"
else
  echo "No Continue config found in $CFG_DIR (expected config.json or config.yaml/yml)."
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP="${CFG}.bak.${TS}"
cp "$CFG" "$BACKUP"
echo "Backup created: $BACKUP"
echo "Active config:  $CFG"

case "$CFG" in
  *.json)
    CFG_JSON="$CFG" ROUTER_API_BASE="$ROUTER_API_BASE" ROUTER_MODEL="$ROUTER_MODEL" python - <<'PY'
import json, os
cfg = os.environ["CFG_JSON"]
api = os.environ["ROUTER_API_BASE"]
model_name = os.environ["ROUTER_MODEL"]

with open(cfg, "r", encoding="utf-8") as f:
    data = json.load(f)

models = data.get("models")
if isinstance(models, list) and models:
    for m in models:
        if isinstance(m, dict):
            m["provider"] = m.get("provider", "openai")
            m["apiBase"] = api
            m["model"] = m.get("model", model_name)
else:
    data["models"] = [{
        "title": "Local Hybrid (Graphify+RTK+MLX)",
        "provider": "openai",
        "model": model_name,
        "apiBase": api,
        "apiKey": "local-only"
    }]

sys_msg = data.get("systemMessage", "")
guard = (
    "Workflow policy (local-only): Graphify first (1-3 files/concepts), "
    "then RTK trimmed outputs, then final local MLX answer. "
    "Never route to cloud. If scope exceeds local budget, ask to narrow."
)
if guard not in sys_msg:
    data["systemMessage"] = (sys_msg + ("\n\n" if sys_msg else "") + guard)

with open(cfg, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
print("Patched JSON config successfully.")
PY
    ;;

  *.yaml|*.yml)
    # Replace existing keys in-place (keeps file readable without requiring extra tools).
    # If keys are missing, append a minimal local-only model block.
    perl -0777 -i -pe 's{(^[ \t-]*apiBase:\s*).*$}{$1http://127.0.0.1:4000/v1}mg' "$CFG"
    perl -0777 -i -pe 's{(^[ \t-]*model:\s*).*$}{$1mlx-community/Qwen3.5-4B-MLX-8bit}mg' "$CFG"
    perl -0777 -i -pe 's{(^[ \t-]*provider:\s*).*$}{$1openai}mg' "$CFG"

    if ! grep -qE '^[[:space:]]*apiBase:[[:space:]]*http://127\.0\.0\.1:4000/v1' "$CFG"; then
      cat >> "$CFG" <<'YAML_APPEND'

models:
  - title: Local Hybrid (Graphify+RTK+MLX)
    provider: openai
    model: mlx-community/Qwen3.5-4B-MLX-8bit
    apiBase: http://127.0.0.1:4000/v1
    apiKey: local-only

systemMessage: |
  Workflow policy (local-only):
  1) Run Graphify discovery first and narrow to 1-3 files or concepts.
  2) Use RTK tools next and return structured, trimmed results only.
  3) Ask local MLX only the final focused question.
  4) Never route to cloud.
  5) If input exceeds local limits, stop and ask to narrow scope.
YAML_APPEND
      echo "Appended minimal local-only block to YAML config."
    else
      echo "Patched existing YAML keys."
    fi
    ;;
esac

echo
echo "Patched config summary:"
grep -nE 'provider:|model:|apiBase:|title|systemMessage' "$CFG" | head -n 40 || true

echo
echo "Done. Restart Continue/VS Code chat to apply changes."