from __future__ import annotations

import asyncio
import importlib
import json
from urllib.parse import quote

import httpx
import pytest

from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.tests.unit.test_chapter_outline_prompt import _manifest
from backend.tests.unit.test_provider_response_secret_scanning import (
    _assert_no_sensitive_error_graph,
)


def _gateway_module():
    try:
        return importlib.import_module(
            "backend.gateways.chapter_outline_provider"
        )
    except ModuleNotFoundError:
        pytest.fail("chapter outline Provider gateway is missing")


def _provider() -> dict[str, object]:
    return {
        "id": "provider-1",
        "provider_type": "openai-compatible",
        "base_url": "https://provider.example/v1",
        "api_key": "PRIVATE_API_KEY_SENTINEL",
        "temperature": 0.25,
        "max_output_tokens": 8_192,
    }


def _ref(node) -> dict[str, object]:
    return {
        "id": node.id,
        "revision": node.revision,
        "contentHash": node.content_hash,
    }


def _outline_payload(manifest=None) -> dict[str, object]:
    manifest = manifest or _manifest()
    return {
        "schemaVersion": "chapter-outline-draft-v1",
        "volumeRef": _ref(manifest.volume),
        "storyBlockRef": _ref(manifest.story_block),
        "stageRefs": [_ref(node) for node in manifest.allowed_stages],
        "sceneTaskRefs": [
            _ref(node) for node in manifest.allowed_scene_tasks
        ],
        "chapterGoal": "Find a safe path through the blockade.",
        "expectedCharacters": ["Shen Yan", "Lu Zhao"],
        "continuation": ["Continue the trapped-at-the-gate situation."],
        "plannedTasks": ["Observe the guard change.", "Test the culvert."],
        "scenes": ["Night reconnaissance.", "A costly test of trust."],
        "forbiddenEarlyEvents": ["Do not reveal the traitor."],
    }


def _response(
    payload: object,
    *,
    request: httpx.Request,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(payload, ensure_ascii=False)
                    }
                }
            ]
        },
        request=request,
    )


async def _generate_once(gateway, **kwargs):
    await gateway.start()
    try:
        return await gateway.generate(**kwargs)
    finally:
        await gateway.aclose()


def test_concrete_gateway_satisfies_the_public_outline_provider_protocol():
    module = _gateway_module()

    assert isinstance(
        module.ChapterOutlineProviderGateway(
            transport=httpx.MockTransport(
                lambda request: _response(
                    _outline_payload(),
                    request=request,
                )
            )
        ),
        module.ChapterOutlineProvider,
    )


@pytest.mark.asyncio
async def test_gateway_makes_one_bounded_structured_call_and_returns_domain_value(
    caplog,
    monkeypatch,
):
    module = _gateway_module()
    manifest = _manifest()
    requests: list[httpx.Request] = []
    parse_calls = 0
    original_validate = EditableChapterOutlineContent.model_validate

    def counted_validate(value, *, strict):
        nonlocal parse_calls
        parse_calls += 1
        return original_validate(value, strict=strict)

    monkeypatch.setattr(
        EditableChapterOutlineContent,
        "model_validate",
        counted_validate,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(_outline_payload(manifest), request=request)

    gateway = module.ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    result = await _generate_once(
        gateway,
        provider=_provider(),
        model_name="outline-model",
        manifest=manifest,
    )

    assert type(result) is EditableChapterOutlineContent
    assert result.chapter_goal == "Find a safe path through the blockade."
    assert parse_calls == 1
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://provider.example/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer PRIVATE_API_KEY_SENTINEL"
    body = json.loads(request.content)
    assert body["model"] == "outline-model"
    assert body["temperature"] == 0.25
    assert body["max_tokens"] == 8_192
    assert body["response_format"] == {"type": "json_object"}
    assert body["stream"] is False
    assert caplog.text == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ("provider", "model"))
async def test_gateway_rejects_non_planning_binding_identity_before_call(
    drift,
    caplog,
):
    module = _gateway_module()
    requests = []
    provider = _provider()
    model_name = "outline-model"
    if drift == "provider":
        provider["id"] = "provider-2"
    else:
        model_name = "different-model"

    gateway = module.ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: requests.append(request)
            or _response(_outline_payload(), request=request)
        )
    )
    with pytest.raises(module.ChapterOutlineProviderError) as caught:
        await _generate_once(
            gateway,
            provider=provider,
            model_name=model_name,
            manifest=_manifest(),
        )

    assert requests == []
    assert type(caught.value) is module.ChapterOutlineProviderError
    assert str(caught.value) == "Chapter outline provider failed"
    assert caplog.text == ""


@pytest.mark.asyncio
async def test_gateway_scans_prompt_for_runtime_secret_before_provider_call(
    caplog,
):
    module = _gateway_module()
    requests = []
    manifest = _manifest(
        author_instructions="Repeat PRIVATE_API_KEY_SENTINEL in the answer."
    )

    gateway = module.ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: requests.append(request)
            or _response(_outline_payload(), request=request)
        )
    )
    with pytest.raises(module.ChapterOutlineProviderError) as caught:
        await _generate_once(
            gateway,
            provider=_provider(),
            model_name="outline-model",
            manifest=manifest,
        )

    assert requests == []
    exposed = repr(caught.value) + caplog.text
    assert str(caught.value) == "Chapter outline provider failed"
    assert "PRIVATE_API_KEY_SENTINEL" not in exposed


@pytest.mark.asyncio
async def test_gateway_scans_raw_response_before_json_or_structured_parse(
    monkeypatch,
    caplog,
):
    module = _gateway_module()
    raw_secret = quote(str(_provider()["base_url"]), safe="")

    def fail_json_parse(_value):
        pytest.fail("secret-bearing raw response reached JSON parsing")

    shared = importlib.import_module(
        "backend.gateways.openai_json_transport"
    )
    monkeypatch.setattr(shared.json, "loads", fail_json_parse)
    gateway = module.ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=f'{{"echo":"{raw_secret}"}}'.encode(),
                request=request,
            )
        )
    )

    with pytest.raises(module.ChapterOutlineProviderError) as caught:
        await _generate_once(
            gateway,
            provider=_provider(),
            model_name="outline-model",
            manifest=_manifest(),
        )

    assert str(caught.value) == "Chapter outline provider failed"
    exposed = repr(caught.value) + caplog.text
    assert raw_secret not in exposed
    assert "PRIVATE_API_KEY_SENTINEL" not in exposed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: {**value, "providerExtra": "RAW_OUTPUT_SENTINEL"},
        lambda value: {
            **value,
            "stageRefs": [
                {**value["stageRefs"][0], "id": "invented-stage-id"}
            ],
        },
        lambda value: {
            **value,
            "sceneTaskRefs": list(reversed(value["sceneTaskRefs"])),
        },
    ),
)
async def test_gateway_rejects_extra_or_non_exact_allowed_refs_without_logging(
    mutate,
    caplog,
):
    module = _gateway_module()
    payload = mutate(_outline_payload())

    gateway = module.ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: _response(payload, request=request)
        )
    )
    with pytest.raises(module.ChapterOutlineProviderError) as caught:
        await _generate_once(
            gateway,
            provider=_provider(),
            model_name="outline-model",
            manifest=_manifest(),
        )

    assert str(caught.value) == "Chapter outline provider failed"
    exposed = repr(caught.value) + caplog.text
    assert "RAW_OUTPUT_SENTINEL" not in exposed
    assert "invented-stage-id" not in exposed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_body",
    (
        b"RAW_RESPONSE_SENTINEL",
        b'{"choices":[],"raw":"RAW_RESPONSE_SENTINEL"}',
        b'{"choices":[{"message":{"content":"[]"}}]}',
    ),
)
async def test_gateway_maps_malformed_response_to_fixed_safe_category(
    raw_body,
    caplog,
):
    module = _gateway_module()
    gateway = module.ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=raw_body,
                request=request,
            )
        )
    )

    with pytest.raises(module.ChapterOutlineProviderError) as caught:
        await _generate_once(
            gateway,
            provider=_provider(),
            model_name="outline-model",
            manifest=_manifest(),
        )

    assert type(caught.value) is module.ChapterOutlineProviderError
    assert str(caught.value) == "Chapter outline provider failed"
    exposed = repr(caught.value) + caplog.text
    assert "RAW_RESPONSE_SENTINEL" not in exposed
    assert "PRIVATE_API_KEY_SENTINEL" not in exposed


@pytest.mark.asyncio
async def test_gateway_rejects_oversized_or_http_error_responses_safely(caplog):
    module = _gateway_module()
    responses = (
        lambda request: httpx.Response(
            200,
            headers={
                "content-length": str(module.MAX_PROVIDER_RESPONSE_BYTES + 1)
            },
            request=request,
        ),
        lambda request: httpx.Response(
            503,
            text="RAW_HTTP_SENTINEL",
            request=request,
        ),
    )

    for response in responses:
        gateway = module.ChapterOutlineProviderGateway(
            transport=httpx.MockTransport(response)
        )
        with pytest.raises(module.ChapterOutlineProviderError) as caught:
            await _generate_once(
                gateway,
                provider=_provider(),
                model_name="outline-model",
                manifest=_manifest(),
            )
        assert str(caught.value) == "Chapter outline provider failed"

    assert "RAW_HTTP_SENTINEL" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ("transport", "http", "json", "envelope", "domain"),
)
async def test_safe_error_releases_all_sensitive_exception_references(
    failure,
    caplog,
):
    module = _gateway_module()
    manifest = _manifest(
        author_instructions="AUTHOR_INSTRUCTION_SENTINEL"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "transport":
            raise httpx.ConnectError(
                "REMOTE_FAILURE_SENTINEL",
                request=request,
            )
        if failure == "http":
            return httpx.Response(
                503,
                content=b"RAW_HTTP_BODY_SENTINEL",
                request=request,
            )
        if failure == "json":
            return httpx.Response(
                200,
                content=b'{"RAW_RESPONSE_SENTINEL":',
                request=request,
            )
        if failure == "envelope":
            return httpx.Response(
                200,
                json={
                    "choices": [],
                    "raw": "DECODED_ENVELOPE_SENTINEL",
                },
                request=request,
            )
        payload = {
            **_outline_payload(manifest),
            "providerExtra": "DECODED_VALUE_SENTINEL",
        }
        return _response(payload, request=request)

    gateway = module.ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    with pytest.raises(module.ChapterOutlineProviderError) as caught:
        await _generate_once(
            gateway,
            provider=_provider(),
            model_name="outline-model",
            manifest=manifest,
        )

    _assert_no_sensitive_error_graph(
        caught.value,
        (
            "PRIVATE_API_KEY_SENTINEL",
            "AUTHOR_INSTRUCTION_SENTINEL",
            "REMOTE_FAILURE_SENTINEL",
            "RAW_HTTP_BODY_SENTINEL",
            "RAW_RESPONSE_SENTINEL",
            "DECODED_ENVELOPE_SENTINEL",
            "DECODED_VALUE_SENTINEL",
            "Authorization",
        ),
    )
    assert caplog.text == ""


@pytest.mark.asyncio
async def test_gateway_uses_the_shared_bounded_json_transport(monkeypatch):
    module = _gateway_module()
    try:
        shared = importlib.import_module(
            "backend.gateways.openai_json_transport"
        )
    except ModuleNotFoundError:
        pytest.fail("shared OpenAI JSON transport is missing")
    instances = []

    class RecordingResource:
        def __init__(
            self,
            *,
            transport,
            timeout_seconds,
            response_byte_limit,
        ):
            self.transport = transport
            self.timeout_seconds = timeout_seconds
            self.response_byte_limit = response_byte_limit
            self.start_calls = 0
            self.close_calls = 0
            self.requests = []
            instances.append(self)

        async def start(self):
            self.start_calls += 1

        async def aclose(self):
            self.close_calls += 1

        async def request(self, **kwargs):
            self.requests.append(kwargs)
            return shared.OpenAIJSONTransportResult(
                succeeded=True,
                value=_outline_payload(),
            )

    monkeypatch.setattr(module, "OpenAIJSONTransport", RecordingResource)
    borrowed = httpx.MockTransport(
        lambda request: _response(_outline_payload(), request=request)
    )
    gateway = module.ChapterOutlineProviderGateway(transport=borrowed)
    await gateway.start()
    result = await gateway.generate(
        provider=_provider(),
        model_name="outline-model",
        manifest=_manifest(),
    )
    second = await gateway.generate(
        provider=_provider(),
        model_name="outline-model",
        manifest=_manifest(),
    )
    await gateway.aclose()

    assert type(result) is EditableChapterOutlineContent
    assert type(second) is EditableChapterOutlineContent
    assert len(instances) == 1
    resource = instances[0]
    assert resource.transport is borrowed
    assert resource.timeout_seconds == module.PROVIDER_TIMEOUT_SECONDS
    assert resource.response_byte_limit == module.MAX_PROVIDER_RESPONSE_BYTES
    assert resource.start_calls == 1
    assert resource.close_calls == 1
    assert len(resource.requests) == 2
    assert resource.requests[0]["provider"] == _provider()
    assert resource.requests[0]["model_name"] == "outline-model"
    assert [item["role"] for item in resource.requests[0]["messages"]] == [
        "system",
        "user",
    ]


class _CloseAwareOutlineTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.calls = 0
        self.close_calls = 0

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        self.calls += 1
        return _response(_outline_payload(), request=request)

    async def aclose(self) -> None:
        self.close_calls += 1


@pytest.mark.asyncio
async def test_outline_gateway_reuses_one_borrowed_transport_lifecycle_and_restarts():
    transport = _CloseAwareOutlineTransport()
    gateway = _gateway_module().ChapterOutlineProviderGateway(
        transport=transport
    )

    await gateway.start()
    first, second = await asyncio.gather(
        gateway.generate(
            provider=_provider(),
            model_name="outline-model",
            manifest=_manifest(),
        ),
        gateway.generate(
            provider=_provider(),
            model_name="outline-model",
            manifest=_manifest(),
        ),
    )
    await gateway.aclose()
    await gateway.start()
    third = await gateway.generate(
        provider=_provider(),
        model_name="outline-model",
        manifest=_manifest(),
    )
    await gateway.aclose()

    assert type(first) is EditableChapterOutlineContent
    assert type(second) is EditableChapterOutlineContent
    assert type(third) is EditableChapterOutlineContent
    assert transport.calls == 3
    assert transport.close_calls == 0


class _OutlineDrainGateStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes):
        self._content = content
        self.read_started = asyncio.Event()
        self.read_release = asyncio.Event()
        self.close_calls = 0

    async def __aiter__(self):
        self.read_started.set()
        await self.read_release.wait()
        yield self._content

    async def aclose(self) -> None:
        self.close_calls += 1
        self._content = b""


class _OutlineDrainAwareTransport(httpx.AsyncBaseTransport):
    def __init__(self, stream: _OutlineDrainGateStream):
        self._stream = stream
        self.calls = 0
        self.requests: list[httpx.Request] = []
        self.close_calls = 0

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        self.calls += 1
        self.requests.append(request)
        return httpx.Response(
            200,
            stream=self._stream,
            request=request,
        )

    async def aclose(self) -> None:
        self.close_calls += 1


async def _wait_for_outline_resource_state(resource, state: str) -> None:
    async with asyncio.timeout(1):
        while resource.state != state:
            next_turn = asyncio.Event()
            asyncio.get_running_loop().call_soon(next_turn.set)
            await next_turn.wait()


async def _next_outline_event_loop_turn() -> None:
    next_turn = asyncio.Event()
    asyncio.get_running_loop().call_soon(next_turn.set)
    await asyncio.wait_for(next_turn.wait(), timeout=1)


def _outline_traceback_reaches_any(
    error: BaseException,
    targets: tuple[object, ...],
):
    target_ids = {id(target) for target in targets}
    pending = []
    traceback = error.__traceback__
    while traceback is not None:
        filename = traceback.tb_frame.f_code.co_filename.replace("\\", "/")
        if "/backend/tests/" not in filename:
            pending.extend(traceback.tb_frame.f_locals.values())
        traceback = traceback.tb_next

    seen = set()
    while pending:
        value = pending.pop()
        if value is None or id(value) in seen:
            continue
        if id(value) in target_ids:
            return True
        seen.add(id(value))
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)
        elif type(value).__module__.startswith(("backend.", "httpx.")):
            try:
                pending.extend(vars(value).values())
            except TypeError:
                pass
    return False


@pytest.mark.asyncio
async def test_outline_close_drains_active_generate_and_rejects_late_generate(
):
    manifest = _manifest()
    prepared = _response(
        _outline_payload(manifest),
        request=httpx.Request(
            "POST",
            "https://provider.example/v1/chat/completions",
        ),
    )
    stream = _OutlineDrainGateStream(prepared.content)
    transport = _OutlineDrainAwareTransport(stream)
    module = _gateway_module()
    gateway = module.ChapterOutlineProviderGateway(transport=transport)
    resource = gateway._resource
    generate_task = None
    close_task = None
    late_task = None
    lock_held = False
    close_entered = asyncio.Event()

    async def close_gateway() -> None:
        close_entered.set()
        await gateway.aclose()

    await asyncio.wait_for(gateway.start(), timeout=1)
    try:
        generate_task = asyncio.create_task(
            gateway.generate(
                provider=_provider(),
                model_name="outline-model",
                manifest=manifest,
            )
        )
        await asyncio.wait_for(stream.read_started.wait(), timeout=1)

        await asyncio.wait_for(resource._lock.acquire(), timeout=1)
        lock_held = True
        close_task = asyncio.create_task(close_gateway())
        await asyncio.wait_for(close_entered.wait(), timeout=1)
        late_task = asyncio.create_task(
            gateway.generate(
                provider=_provider(),
                model_name="outline-model",
                manifest=manifest,
            )
        )
        resource._lock.release()
        lock_held = False

        with pytest.raises(module.ChapterOutlineProviderError) as caught:
            await asyncio.wait_for(late_task, timeout=1)
        assert str(caught.value) == "Chapter outline provider failed"
        assert transport.calls == 1
        assert resource.state == "draining"
        assert close_task.done() is False

        stream.read_release.set()
        result = await asyncio.wait_for(generate_task, timeout=1)
        assert type(result) is EditableChapterOutlineContent
        await asyncio.wait_for(close_task, timeout=1)

        assert stream.close_calls == 1
        assert transport.close_calls == 0
        assert resource.active_calls == 0
        assert resource.cleanup_task_count == 0
        assert resource.state == "closed"
        assert resource._start_task is None
        assert resource._close_task is None
        assert generate_task.done() is True
        assert late_task.done() is True
        assert close_task.done() is True
    finally:
        if lock_held:
            resource._lock.release()
        stream.read_release.set()
        for task in (generate_task, late_task, close_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=1)
                except BaseException:
                    pass
        await asyncio.wait_for(gateway.aclose(), timeout=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (1, 2, 4))
async def test_outline_cancelled_late_start_has_clean_traceback_and_keeps_close(
    cancel_count,
):
    prompt_sentinel = "LATE_START_PROMPT_SENTINEL"
    manifest = _manifest(author_instructions=prompt_sentinel)
    prepared = _response(
        _outline_payload(manifest),
        request=httpx.Request(
            "POST",
            "https://provider.example/v1/chat/completions",
        ),
    )
    stream = _OutlineDrainGateStream(prepared.content)
    transport = _OutlineDrainAwareTransport(stream)
    module = _gateway_module()
    gateway = module.ChapterOutlineProviderGateway(transport=transport)
    resource = gateway._resource
    generate_task = None
    close_task = None
    start_task = None

    await asyncio.wait_for(gateway.start(), timeout=1)
    try:
        generate_task = asyncio.create_task(
            gateway.generate(
                provider=_provider(),
                model_name="outline-model",
                manifest=manifest,
            )
        )
        await asyncio.wait_for(stream.read_started.wait(), timeout=1)
        assert transport.calls == 1
        request = transport.requests[0]
        assert prompt_sentinel in request.content.decode("utf-8")

        close_task = asyncio.create_task(gateway.aclose())
        await _wait_for_outline_resource_state(resource, "draining")
        shared_close = resource._close_task
        assert shared_close is not None
        assert shared_close.done() is False

        start_task = asyncio.create_task(gateway.start())
        await _next_outline_event_loop_turn()
        assert start_task.done() is False
        for _ in range(cancel_count):
            start_task.cancel()

        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(start_task, timeout=1)

        assert caught.value.args == ()
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert start_task.cancelling() == cancel_count
        assert _outline_traceback_reaches_any(
            caught.value,
            (gateway, resource, transport, request),
        ) is False
        _assert_no_sensitive_error_graph(
            caught.value,
            (
                "PRIVATE_API_KEY_SENTINEL",
                "https://provider.example/v1",
                prompt_sentinel,
                "authorization",
            ),
        )
        assert resource._close_task is shared_close
        assert shared_close.cancelled() is False
        assert shared_close.done() is False

        stream.read_release.set()
        result = await asyncio.wait_for(generate_task, timeout=1)
        assert type(result) is EditableChapterOutlineContent
        await asyncio.wait_for(close_task, timeout=1)

        assert stream.close_calls == 1
        assert transport.calls == 1
        assert transport.close_calls == 0
        assert resource.state == "closed"
        assert resource.active_calls == 0
        assert resource.cleanup_task_count == 0
        assert resource._close_task is None
        assert shared_close.done() is True
        assert shared_close.cancelled() is False
    finally:
        stream.read_release.set()
        for task in (generate_task, start_task, close_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=1)
                except BaseException:
                    pass
        await asyncio.wait_for(gateway.aclose(), timeout=1)


class _OutlineCancellationProbeStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes, *, block_read: bool):
        self._content = content
        self._block_read = block_read
        self.read_started = asyncio.Event()
        self.read_release = asyncio.Event()
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_completed = asyncio.Event()
        self.close_calls = 0

    async def __aiter__(self):
        self.read_started.set()
        if self._block_read:
            await self.read_release.wait()
        yield self._content

    async def aclose(self) -> None:
        self.close_calls += 1
        self.close_started.set()
        await self.close_release.wait()
        self._content = b""
        self.close_completed.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_during", ("body-read", "response-close"))
async def test_outline_gateway_repeated_cancellation_waits_for_clean_response_close(
    cancel_during,
):
    manifest = _manifest(
        author_instructions=(
            "AUTHOR_INSTRUCTION_SENTINEL "
            "RAW_CANCELLATION_SENTINEL"
        )
    )
    payload = _outline_payload(manifest)
    payload["chapterGoal"] = "DECODED_CANCELLED_SENTINEL"
    prepared = _response(
        payload,
        request=httpx.Request(
            "POST",
            "https://provider.example/v1/chat/completions",
        ),
    )
    stream = _OutlineCancellationProbeStream(
        prepared.content,
        block_read=cancel_during == "body-read",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=stream,
            request=request,
        )

    gateway = _gateway_module().ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    await gateway.start()
    task = asyncio.create_task(
        gateway.generate(
            provider=_provider(),
            model_name="outline-model",
            manifest=manifest,
        )
    )
    try:
        if cancel_during == "body-read":
            await asyncio.wait_for(stream.read_started.wait(), timeout=1)
            task.cancel()
            await asyncio.wait_for(stream.close_started.wait(), timeout=1)
            task.cancel()
            task.cancel()
        else:
            await asyncio.wait_for(stream.close_started.wait(), timeout=1)
            task.cancel()
            task.cancel()
            task.cancel()

        assert task.done() is False
        stream.close_release.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, timeout=1)

        assert caught.value.args == ()
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert task.cancelling() == 3
        assert stream.close_calls == 1
        assert stream.close_completed.is_set()
        _assert_no_sensitive_error_graph(
            caught.value,
            (
                "PRIVATE_API_KEY_SENTINEL",
                "https://provider.example/v1",
                "AUTHOR_INSTRUCTION_SENTINEL",
                "RAW_CANCELLATION_SENTINEL",
                "DECODED_CANCELLED_SENTINEL",
                "authorization",
            ),
        )
    finally:
        stream.read_release.set()
        stream.close_release.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        await asyncio.wait_for(gateway.aclose(), timeout=1)


@pytest.mark.asyncio
async def test_cancellation_returns_a_fresh_secret_free_cancelled_error():
    module = _gateway_module()
    entered = asyncio.Event()
    release = asyncio.Event()
    manifest = _manifest(
        author_instructions=(
            "AUTHOR_INSTRUCTION_SENTINEL "
            "RAW_CANCELLATION_SENTINEL"
        )
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        entered.set()
        await release.wait()
        return _response(_outline_payload(manifest), request=request)

    gateway = module.ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(handler)
    )
    await gateway.start()
    task = asyncio.create_task(
        gateway.generate(
            provider=_provider(),
            model_name="outline-model",
            manifest=manifest,
        )
    )
    try:
        await entered.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError) as caught:
            await task

        assert task.cancelled() is True
        _assert_no_sensitive_error_graph(
            caught.value,
            (
                "PRIVATE_API_KEY_SENTINEL",
                "https://provider.example/v1",
                "AUTHOR_INSTRUCTION_SENTINEL",
                "RAW_CANCELLATION_SENTINEL",
                "authorization",
            ),
        )
    finally:
        release.set()
        await gateway.aclose()
