#!/usr/bin/env python3
"""
Local-only prompt router for Continue/OpenAI-compatible clients.

Behavior:
- Accepts POST /v1/chat/completions
- Trims oversized tool/history content
- Enforces local budget limits
- Forwards only to local MLX endpoint
- Never routes to cloud
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Local MLX endpoint
LOCAL_OPENAI_URL = os.getenv(
    "LOCAL_OPENAI_URL",
    "http://127.0.0.1:8080/v1/chat/completions",
)
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "mlx-community/Qwen3.5-4B-MLX-8bit")
LOCAL_TIMEOUT_SECONDS = float(os.getenv("LOCAL_TIMEOUT_SECONDS", "25"))

# Budgets tuned for 16 GB M1
PREFERRED_INPUT_TOKENS = int(os.getenv("PREFERRED_INPUT_TOKENS", "8000"))
HARD_INPUT_TOKENS = int(os.getenv("HARD_INPUT_TOKENS", "12000"))
PREFERRED_REQUEST_BYTES = int(os.getenv("PREFERRED_REQUEST_BYTES", "750000"))
HARD_REQUEST_BYTES = int(os.getenv("HARD_REQUEST_BYTES", "1000000"))
MAX_TOOL_CHARS_PER_MESSAGE = int(os.getenv("MAX_TOOL_CHARS_PER_MESSAGE", "4000"))
MAX_MESSAGES_BEFORE_SUMMARY = int(os.getenv("MAX_MESSAGES_BEFORE_SUMMARY", "10"))
MAX_LOCAL_OUTPUT_TOKENS = int(os.getenv("MAX_LOCAL_OUTPUT_TOKENS", "768"))
DISABLE_STREAM_OVER_TOKENS = int(os.getenv("DISABLE_STREAM_OVER_TOKENS", "6000"))

ROUTER_HOST = os.getenv("ROUTER_HOST", "127.0.0.1")
ROUTER_PORT = int(os.getenv("ROUTER_PORT", "4000"))


def estimate_tokens(text: str) -> int:
    # Rough estimate (works fine for guarding budgets)
    if not text:
        return 0
    return max(1, len(text) // 4)


def compact_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    head = text[:half]
    tail = text[-half:]
    removed = len(text) - len(head) - len(tail)
    return f"{head}\n\n[... trimmed {removed} chars ...]\n\n{tail}"


def normalize_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # OpenAI multimodal style content array
        try:
            return json.dumps(content, ensure_ascii=False)
        except Exception:
            return str(content)
    return str(content)


def summarize_old_messages(messages):
    if len(messages) <= MAX_MESSAGES_BEFORE_SUMMARY:
        return messages

    keep_tail = messages[-MAX_MESSAGES_BEFORE_SUMMARY:]
    older = messages[:-MAX_MESSAGES_BEFORE_SUMMARY]

    lines = []
    for msg in older[-20:]:
        role = msg.get("role", "unknown")
        content = normalize_content(msg.get("content", ""))
        content = content.replace("\n", " ").strip()
        content = compact_text(content, 240)
        lines.append(f"- {role}: {content}")

    summary_message = {
        "role": "system",
        "content": "Compressed prior conversation context:\n" + "\n".join(lines),
    }
    return [summary_message] + keep_tail


def budget_messages(messages):
    budgeted = []
    for msg in messages:
        clone = dict(msg)
        content = normalize_content(clone.get("content", ""))

        # Trim tool output aggressively
        if clone.get("role") == "tool":
            content = compact_text(content, MAX_TOOL_CHARS_PER_MESSAGE)

        clone["content"] = content
        budgeted.append(clone)

    budgeted = summarize_old_messages(budgeted)
    input_tokens = sum(estimate_tokens(m.get("content", "")) for m in budgeted)
    return budgeted, input_tokens


def make_error(status_code: int, error: str, message: str, extra=None):
    payload = {"error": error, "message": message}
    if extra:
        payload.update(extra)
    body = json.dumps(payload).encode("utf-8")
    return status_code, body


def forward_to_local(payload):
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        LOCAL_OPENAI_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=LOCAL_TIMEOUT_SECONDS) as resp:
        body = resp.read()
        return resp.getcode(), body


class LocalPromptRouter(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"not_found","message":"Use /v1/chat/completions"}')
            return

        try:
            raw_len = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(raw_len)
            request_payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            self._respond(*make_error(400, "bad_request", "Invalid JSON payload"))
            return

        messages = request_payload.get("messages", [])
        budgeted_messages, input_tokens = budget_messages(messages)

        routed = dict(request_payload)
        routed["messages"] = budgeted_messages
        routed["model"] = LOCAL_MODEL
        routed["max_tokens"] = min(
            int(request_payload.get("max_tokens", MAX_LOCAL_OUTPUT_TOKENS)),
            MAX_LOCAL_OUTPUT_TOKENS,
        )

        # Large local inputs are more stable with non-streaming
        if input_tokens > DISABLE_STREAM_OVER_TOKENS:
            routed["stream"] = False

        encoded = json.dumps(routed).encode("utf-8")
        req_bytes = len(encoded)

        # Hard local-only limits
        if req_bytes > HARD_REQUEST_BYTES:
            self._respond(
                *make_error(
                    413,
                    "local_budget_exceeded",
                    "Request too large for local budget. Narrow to 1-3 files or one concept and retry.",
                    {
                        "request_bytes": req_bytes,
                        "hard_request_bytes": HARD_REQUEST_BYTES,
                        "estimated_input_tokens": input_tokens,
                    },
                )
            )
            return

        if input_tokens > HARD_INPUT_TOKENS:
            self._respond(
                *make_error(
                    413,
                    "local_budget_exceeded",
                    "Estimated input tokens exceed local hard limit. Narrow scope and retry.",
                    {
                        "estimated_input_tokens": input_tokens,
                        "hard_input_tokens": HARD_INPUT_TOKENS,
                        "request_bytes": req_bytes,
                    },
                )
            )
            return

        try:
            status, body = forward_to_local(routed)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Route", "local")
            self.send_header("X-Model", LOCAL_MODEL)
            self.send_header("X-Estimated-Input-Tokens", str(input_tokens))
            self.send_header("X-Request-Bytes", str(req_bytes))
            if input_tokens > PREFERRED_INPUT_TOKENS:
                self.send_header("X-Budget-Warning", "input_tokens_over_preferred")
            if req_bytes > PREFERRED_REQUEST_BYTES:
                self.send_header("X-Budget-Warning-Bytes", "request_bytes_over_preferred")
            self.end_headers()
            self.wfile.write(body)
        except (HTTPError, URLError, TimeoutError, OSError):
            self._respond(
                *make_error(
                    429,
                    "local_temporarily_unavailable",
                    "Local model failed or timed out. Narrow scope and retry (cloud fallback disabled).",
                    {
                        "estimated_input_tokens": input_tokens,
                        "request_bytes": req_bytes,
                    },
                )
            )

    def _respond(self, status_code, body):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Keep console noise down
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer((ROUTER_HOST, ROUTER_PORT), LocalPromptRouter)
    print(f"Local prompt router listening on http://{ROUTER_HOST}:{ROUTER_PORT}")
    print(f"Forwarding to local endpoint: {LOCAL_OPENAI_URL}")
    print(f"Local model: {LOCAL_MODEL}")
    server.serve_forever()