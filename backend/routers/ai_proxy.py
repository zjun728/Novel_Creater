"""Backend AI proxy.

Browser code sends provider/task identifiers only. API keys and provider base
URLs are resolved here from local provider_profiles.
"""
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import httpx
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import StreamingResponse

from database import fetchone


router = APIRouter(tags=["ai-proxy"])

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
AI_PROXY_TIMEOUT = httpx.Timeout(1200.0, connect=30.0)
RETRYABLE_UPSTREAM_STATUS_CODES = {502, 503, 504}

MODEL_BINDING_FIELDS = [
    "writing_model_id",
    "brainstorm_model_id",
    "outline_model_id",
    "audit_model_id",
    "summary_model_id",
    "extraction_model_id",
    "market_model_id",
    "polish_model_id",
]

CAMEL_TO_SNAKE_BINDING = {
    "writingModelId": "writing_model_id",
    "brainstormModelId": "brainstorm_model_id",
    "outlineModelId": "outline_model_id",
    "auditModelId": "audit_model_id",
    "summaryModelId": "summary_model_id",
    "extractionModelId": "extraction_model_id",
    "marketModelId": "market_model_id",
    "polishModelId": "polish_model_id",
}

TASK_BINDING_HINTS = [
    ("audit_model_id", ("audit", "review", "审稿", "校验")),
    ("polish_model_id", ("polish", "rewrite", "revision", "correction", "finalize", "finalization", "定稿", "润色", "纠偏")),
    ("outline_model_id", ("outline", "beat", "planning", "volume", "story_block", "block", "小纲", "大纲", "分卷")),
    ("summary_model_id", ("summary", "summarize", "memory", "记忆", "摘要")),
    ("extraction_model_id", ("extract", "extraction", "setting", "设定", "抽取")),
    ("market_model_id", ("market", "选题", "市场")),
    ("brainstorm_model_id", ("brainstorm", "seed", "bible", "创意", "种子", "圣经")),
    ("writing_model_id", ("write", "writing", "chapter", "draft", "generation", "正文", "续写")),
]


def now_ms() -> int:
    return int(time.time() * 1000)


def first_present(payload: Dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in payload and payload[name] is not None:
            return payload[name]
    return default


def parse_json_field(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def redact_sensitive_text(text: Any, secrets: Iterable[str] = ()) -> str:
    safe = "" if text is None else str(text)
    for secret in secrets:
        if secret:
            safe = safe.replace(str(secret), "[REDACTED]")
    return safe


def raw_head_tail(raw: Any, secrets: Iterable[str] = ()) -> Dict[str, str]:
    safe = redact_sensitive_text(raw, secrets)
    return {
        "rawHead": safe[:800],
        "rawTail": safe[-800:] if len(safe) > 800 else safe,
    }


def is_retryable_upstream_status(status: Optional[int]) -> bool:
    return status in RETRYABLE_UPSTREAM_STATUS_CODES


def resolve_task_key(payload: Dict[str, Any]) -> str:
    task_name = first_present(payload, "taskName", "task_name", default="")
    candidates = task_binding_candidates(task_name) if task_name else []
    return candidates[0] if candidates else ""


def safe_diagnostic(
    provider: Optional[Dict[str, Any]],
    payload: Dict[str, Any],
    started_ms: int,
    *,
    http_status: Optional[int],
    raw: Any = "",
    message: str = "",
) -> Dict[str, Any]:
    provider = provider or {}
    secrets = [provider.get("api_key"), provider.get("apiKey")]
    diagnostic = {
        "message": message,
        "providerId": provider.get("id") or first_present(payload, "providerId", "provider_id", default=""),
        "providerName": provider.get("name") or "",
        "modelName": first_present(payload, "model", default=provider.get("model") or ""),
        "taskName": first_present(payload, "taskName", "task_name", default=""),
        "httpStatus": http_status,
        "elapsedMs": max(0, now_ms() - started_ms),
    }
    diagnostic.update(raw_head_tail(raw, secrets))
    return diagnostic


def build_ai_proxy_error_detail(
    provider: Optional[Dict[str, Any]],
    payload: Dict[str, Any],
    started_ms: int,
    *,
    http_status: Optional[int],
    raw: Any = "",
    message: str = "",
    retryable: Optional[bool] = None,
    error_type: str = "",
) -> Dict[str, Any]:
    detail = safe_diagnostic(
        provider,
        payload,
        started_ms,
        http_status=http_status,
        raw=raw,
        message=message,
    )
    head_tail = raw_head_tail(raw, [provider.get("api_key"), provider.get("apiKey")] if provider else [])
    upstream_retryable = is_retryable_upstream_status(http_status)
    task_name = first_present(payload, "taskName", "task_name", default="")
    detail.update({
        "requestId": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "taskId": first_present(payload, "taskId", "task_id", "taskKey", "task_key", default=task_name),
        "taskKey": first_present(payload, "taskKey", "task_key", default=resolve_task_key(payload)),
        "upstreamStatus": http_status,
        "upstreamBodyHead": head_tail["rawHead"],
        "upstreamBodyTail": head_tail["rawTail"],
        "retryable": bool(upstream_retryable if retryable is None else retryable),
    })
    if error_type:
        detail["errorType"] = error_type
    return detail


def build_openai_response_diagnostics(response: httpx.Response, data: Any, started_ms: int) -> Dict[str, Any]:
    body_text = response.text or ""
    choices = data.get("choices") if isinstance(data, dict) else []
    choices = choices if isinstance(choices, list) else []
    first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
    content = message.get("content")
    if content is None:
        content = first_choice.get("text") or ""
    usage = data.get("usage") if isinstance(data, dict) else None
    usage = usage if isinstance(usage, dict) else None

    def usage_number(source: Any, *keys: str) -> Optional[int]:
        if not isinstance(source, dict):
            return None
        for key in keys:
            value = source.get(key)
            if isinstance(value, (int, float)):
                return int(value)
        return None

    token_details = {}
    if isinstance(usage, dict):
        token_details = (
            usage.get("completion_tokens_details")
            or usage.get("completionTokensDetails")
            or usage.get("output_tokens_details")
            or usage.get("outputTokensDetails")
            or {}
        )
        if not isinstance(token_details, dict):
            token_details = {}

    content_length = len(str(content or ""))
    return {
        "backendResponseStatus": response.status_code,
        "responseBodyLength": len(body_text),
        "choicesLength": len(choices),
        "messageContentLength": content_length,
        "contentLength": content_length,
        "finishReason": first_choice.get("finish_reason"),
        "usage": usage,
        "completionTokens": usage_number(usage, "completion_tokens", "completionTokens", "output_tokens", "outputTokens"),
        "promptTokens": usage_number(usage, "prompt_tokens", "promptTokens", "input_tokens", "inputTokens"),
        "totalTokens": usage_number(usage, "total_tokens", "totalTokens"),
        "reasoningTokens": usage_number(token_details, "reasoning_tokens", "reasoningTokens")
        or usage_number(usage, "reasoning_tokens", "reasoningTokens"),
        "elapsedMs": max(0, now_ms() - started_ms),
    }


def normalize_openai_endpoint(base_url: str) -> str:
    normalized = (base_url or DEFAULT_OPENAI_BASE_URL).rstrip("/")
    if "/chat/completions" in normalized:
        return normalized
    return f"{normalized}/chat/completions"


def normalize_response_format(payload: Dict[str, Any]) -> Any:
    response_format = first_present(payload, "response_format", "responseFormat")
    if response_format == "json":
        return {"type": "json_object"}
    if response_format:
        return response_format
    if payload.get("json") is True:
        return {"type": "json_object"}
    return None


def build_openai_compatible_request(
    provider: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    force_stream: Optional[bool] = None,
) -> Dict[str, Any]:
    stream = bool(force_stream if force_stream is not None else payload.get("stream", False))
    max_tokens = first_present(
        payload,
        "max_tokens",
        "maxTokens",
        default=provider.get("max_output_tokens") or 4096,
    )
    top_p = first_present(payload, "top_p", "topP", default=provider.get("top_p") or 0.9)
    temperature = first_present(
        payload,
        "temperature",
        default=provider.get("temperature") if provider.get("temperature") is not None else 0.8,
    )

    body = {
        "model": first_present(payload, "model", default=provider.get("model") or ""),
        "messages": payload.get("messages") or [],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": stream,
    }

    response_format = normalize_response_format(payload)
    if response_format:
        body["response_format"] = response_format

    thinking = first_present(payload, "thinking", default=parse_json_field(provider.get("thinking")))
    if thinking:
        body["thinking"] = thinking

    if stream and payload.get("includeUsage") is not False:
        body["stream_options"] = {"include_usage": True}

    return {
        "url": normalize_openai_endpoint(provider.get("base_url") or ""),
        "headers": {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.get('api_key') or ''}",
        },
        "body": body,
    }


def task_binding_candidates(task_name: str) -> List[str]:
    task_text = (task_name or "").strip()
    lowered = task_text.lower()
    candidates: List[str] = []

    for camel, snake in CAMEL_TO_SNAKE_BINDING.items():
        if camel in task_text or snake in lowered:
            candidates.append(snake)

    for field, hints in TASK_BINDING_HINTS:
        if any(hint in lowered or hint in task_text for hint in hints):
            candidates.append(field)

    candidates.append("writing_model_id")
    deduped: List[str] = []
    for field in candidates:
        if field in MODEL_BINDING_FIELDS and field not in deduped:
            deduped.append(field)
    return deduped


async def fetch_provider_by_id(provider_id: str) -> Optional[Dict[str, Any]]:
    if not provider_id:
        return None
    return await fetchone("SELECT * FROM provider_profiles WHERE id=%s", (provider_id,))


async def resolve_provider(payload: Dict[str, Any]) -> Dict[str, Any]:
    provider_id = first_present(payload, "providerId", "provider_id", default="")
    if provider_id:
        provider = await fetch_provider_by_id(provider_id)
        if not provider:
            raise HTTPException(404, detail={"message": "AI 供应商配置不存在", "providerId": provider_id})
        return provider

    project_id = first_present(payload, "projectId", "project_id", default="")
    task_name = first_present(payload, "taskName", "task_name", default="")
    if project_id and task_name:
        bindings = await fetchone("SELECT * FROM task_model_bindings WHERE project_id=%s", (project_id,))
        if not bindings:
            raise HTTPException(400, detail={"message": "当前项目未配置任务模型映射", "projectId": project_id, "taskName": task_name})

        for field in task_binding_candidates(task_name):
            provider_id = bindings.get(field)
            provider = await fetch_provider_by_id(provider_id)
            if provider:
                return provider

        raise HTTPException(
            400,
            detail={
                "message": "任务模型映射未找到可用供应商",
                "projectId": project_id,
                "taskName": task_name,
                "bindingCandidates": task_binding_candidates(task_name),
            },
        )

    model = first_present(payload, "model", default="")
    if model:
        provider = await fetchone(
            "SELECT * FROM provider_profiles WHERE model=%s ORDER BY updated_at DESC LIMIT 1",
            (model,),
        )
        if provider:
            return provider

    raise HTTPException(400, detail={"message": "AI 代理请求缺少 providerId，或缺少 projectId + taskName/model"})


def ensure_supported_provider(provider: Dict[str, Any], payload: Dict[str, Any], started_ms: int):
    provider_type = (provider.get("provider_type") or "openai-compatible").lower()
    if not provider.get("model") and not payload.get("model"):
        raise HTTPException(
            400,
            detail=safe_diagnostic(
                provider,
                payload,
                started_ms,
                http_status=400,
                raw="Provider model is empty.",
                message="供应商模型 ID 未配置",
            ),
        )
    if not provider.get("api_key"):
        raise HTTPException(
            400,
            detail=safe_diagnostic(
                provider,
                payload,
                started_ms,
                http_status=400,
                raw="Provider API key is empty.",
                message="供应商 API Key 未配置",
            ),
        )
    if provider_type == "openai-compatible":
        return
    if provider_type == "anthropic":
        raise HTTPException(
            400,
            detail=safe_diagnostic(
                provider,
                payload,
                started_ms,
                http_status=400,
                raw="Anthropic providers are not supported by backend AI proxy v1.",
                message="后端 AI 代理 v1 暂不支持 Anthropic provider，请切换 OpenAI-compatible 供应商。",
            ),
        )
    raise HTTPException(
        400,
        detail=safe_diagnostic(
            provider,
            payload,
            started_ms,
            http_status=400,
            raw=f"Unsupported provider type: {provider_type}",
            message=f"后端 AI 代理不支持 providerType={provider_type}",
        ),
    )


@router.post("/ai/chat-completions")
async def chat_completions(payload: Dict[str, Any] = Body(...)):
    started_ms = now_ms()
    provider = await resolve_provider(payload)
    ensure_supported_provider(provider, payload, started_ms)
    request = build_openai_compatible_request(provider, payload, force_stream=False)

    try:
        async with httpx.AsyncClient(timeout=AI_PROXY_TIMEOUT) as client:
            response = await client.post(request["url"], headers=request["headers"], json=request["body"])
    except httpx.RequestError as exc:
        timeout = isinstance(exc, httpx.TimeoutException)
        raise HTTPException(
            502,
            detail=build_ai_proxy_error_detail(
                provider,
                payload,
                started_ms,
                http_status=None,
                raw=str(exc),
                message="后端 AI 代理请求失败",
                retryable=timeout,
                error_type=exc.__class__.__name__,
            ),
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(
            502,
            detail=build_ai_proxy_error_detail(
                provider,
                payload,
                started_ms,
                http_status=response.status_code,
                raw=response.text,
                message="供应商返回失败",
            ),
        )

    try:
        data = response.json()
        if isinstance(data, dict):
            data["proxyDiagnostics"] = build_openai_response_diagnostics(response, data, started_ms)
        return data
    except ValueError as exc:
        raise HTTPException(
            502,
            detail=build_ai_proxy_error_detail(
                provider,
                payload,
                started_ms,
                http_status=response.status_code,
                raw=response.text,
                message="供应商返回非 JSON 响应",
                retryable=False,
                error_type=exc.__class__.__name__,
            ),
        ) from exc


@router.post("/ai/chat-completions/stream")
async def chat_completions_stream(payload: Dict[str, Any] = Body(...)):
    started_ms = now_ms()
    provider = await resolve_provider(payload)
    ensure_supported_provider(provider, payload, started_ms)
    request = build_openai_compatible_request(provider, payload, force_stream=True)
    client = httpx.AsyncClient(timeout=AI_PROXY_TIMEOUT)

    try:
        upstream_request = client.build_request("POST", request["url"], headers=request["headers"], json=request["body"])
        response = await client.send(upstream_request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        timeout = isinstance(exc, httpx.TimeoutException)
        raise HTTPException(
            502,
            detail=build_ai_proxy_error_detail(
                provider,
                payload,
                started_ms,
                http_status=None,
                raw=str(exc),
                message="后端 AI 代理流式请求失败",
                retryable=timeout,
                error_type=exc.__class__.__name__,
            ),
        ) from exc

    if response.status_code >= 400:
        raw = (await response.aread()).decode("utf-8", errors="replace")
        await response.aclose()
        await client.aclose()
        raise HTTPException(
            502,
            detail=build_ai_proxy_error_detail(
                provider,
                payload,
                started_ms,
                http_status=response.status_code,
                raw=raw,
                message="供应商返回失败",
            ),
        )

    async def iter_upstream():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        iter_upstream(),
        media_type=response.headers.get("content-type") or "text/event-stream",
    )
