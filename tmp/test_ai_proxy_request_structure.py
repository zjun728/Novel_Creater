import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def main():
    from routers.ai_proxy import build_openai_compatible_request

    provider = {
        "id": "provider-1",
        "name": "deepseek-v4-flash",
        "provider_type": "openai-compatible",
        "base_url": "https://api.deepseek.test/v1",
        "api_key": "SECRET_SHOULD_NOT_LEAK",
        "model": "deepseek-v4-flash",
        "max_output_tokens": 4096,
        "temperature": 0.8,
        "top_p": 0.9,
        "thinking": {"type": "disabled"},
    }
    payload = {
        "messages": [{"role": "user", "content": "hello"}],
        "maxTokens": 1234,
        "temperature": 0.25,
        "top_p": 0.7,
        "response_format": {"type": "json_object"},
        "stream": False,
        "taskName": "auditModelId/writingModelId",
    }

    request = build_openai_compatible_request(provider, payload, force_stream=False)

    assert request["url"] == "https://api.deepseek.test/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer SECRET_SHOULD_NOT_LEAK"
    assert request["body"]["model"] == "deepseek-v4-flash"
    assert request["body"]["messages"] == payload["messages"]
    assert request["body"]["max_tokens"] == 1234
    assert request["body"]["temperature"] == 0.25
    assert request["body"]["top_p"] == 0.7
    assert request["body"]["response_format"] == {"type": "json_object"}
    assert request["body"]["stream"] is False
    assert request["body"]["thinking"] == {"type": "disabled"}
    assert "api_key" not in request["body"]
    assert "apiKey" not in request["body"]

    stream_request = build_openai_compatible_request(provider, payload, force_stream=True)
    assert stream_request["body"]["stream"] is True
    assert stream_request["body"]["stream_options"] == {"include_usage": True}


if __name__ == "__main__":
    asyncio.run(main())
    print("AI_PROXY_REQUEST_STRUCTURE_OK")
