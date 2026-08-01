# 1) Kill anything on 4000
PORT=4000
PID=$(lsof -ti tcp:$PORT || true)
if [ -n "$PID" ]; then
  kill -9 $PID
fi

# 2) Go to your .continue folder
cd /Users/sswaminathan/Documents/claude-data-skills/code-skills/.continue

# 3) Rebuild router (explicit temp dir avoids rust temp-dir issues)
mkdir -p /tmp/rust-tmp
TMPDIR=/tmp/rust-tmp rustc local_prompt_router.rs -O -o local_prompt_router

# 4) Start router in background and capture logs
nohup ./local_prompt_router > /tmp/local_prompt_router_rust.log 2>&1 &
sleep 1

# 5) Verify listener
lsof -nP -iTCP:4000 -sTCP:LISTEN

# 6) Verify health (must be JSON, not HTML 501)
curl -i -sS http://127.0.0.1:4000/health

# 7) Verify chat endpoint
curl -i -sS http://127.0.0.1:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Reply exactly: OK"}],"stream":false,"max_tokens":16}' | head -n 40