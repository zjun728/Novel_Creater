import ast
from pathlib import Path


source = Path("backend/routers/ai_proxy.py").read_text(encoding="utf-8")
tree = ast.parse(source)


def has_function(name: str) -> bool:
    return any(isinstance(node, ast.FunctionDef) and node.name == name for node in tree.body)


assert has_function("is_retryable_upstream_status"), "AI proxy must classify retryable upstream status codes"
assert has_function("build_ai_proxy_error_detail"), "AI proxy must return structured error details"

for marker in [
    "providerId",
    "modelName",
    "taskId",
    "taskKey",
    "upstreamStatus",
    "upstreamBodyHead",
    "upstreamBodyTail",
    "requestId",
    "timestamp",
    "retryable",
]:
    assert marker in source, f"structured proxy errors must include {marker}"

assert "status in (502, 503, 504)" in source or "{502, 503, 504}" in source, (
    "502/503/504 upstream failures must be retryable"
)
assert "httpx.TimeoutException" in source, "timeouts must be reported as retryable proxy errors"
assert "api_key" in source and "[REDACTED]" in source, "proxy diagnostics must redact API keys"

print("AI proxy retryable error contract passed")
