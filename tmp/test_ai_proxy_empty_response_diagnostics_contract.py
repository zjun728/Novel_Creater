from pathlib import Path


source = Path("backend/routers/ai_proxy.py").read_text(encoding="utf-8")

assert "build_openai_response_diagnostics" in source, "AI proxy must build response diagnostics for successful empty responses"
assert "proxyDiagnostics" in source, "AI proxy must attach safe proxyDiagnostics to successful responses"

for field in [
    "backendResponseStatus",
    "responseBodyLength",
    "choicesLength",
    "messageContentLength",
    "finishReason",
    "usage",
]:
    assert field in source, f"AI proxy empty-response diagnostics must include {field}"

assert "api_key" in source and "[REDACTED]" in source, "diagnostics must preserve API-key redaction behavior"

print("AI proxy empty response diagnostics contract tests passed")
