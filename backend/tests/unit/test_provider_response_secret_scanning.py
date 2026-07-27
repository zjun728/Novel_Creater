from __future__ import annotations

import asyncio
from collections.abc import Mapping
import importlib
import json
from types import TracebackType
from urllib.parse import quote

import httpx
import pytest


_TEST_TIMEOUT_SECONDS = 2.0


async def _bounded(awaitable):
    return await asyncio.wait_for(
        awaitable,
        timeout=_TEST_TIMEOUT_SECONDS,
    )


async def _cancel_and_reap(task: asyncio.Task) -> None:
    if not task.done():
        task.cancel()
    try:
        await _bounded(task)
    except BaseException:
        pass


async def _next_loop_turn() -> None:
    ready = asyncio.Event()
    asyncio.get_running_loop().call_soon(ready.set)
    await _bounded(ready.wait())


async def _wait_until(predicate) -> None:
    async with asyncio.timeout(_TEST_TIMEOUT_SECONDS):
        while not predicate():
            await _next_loop_turn()


def _scanner(name):
    module = importlib.import_module("backend.security.provider_secrets")
    scanner = getattr(module, name, None)
    if scanner is None:
        pytest.fail(f"shared Provider response scanner is missing: {name}")
    return scanner


def _assert_no_sensitive_error_graph(
    error: BaseException,
    sentinels: tuple[str, ...],
) -> None:
    """Inspect every recoverable production error reference for secrets."""

    pending: list[tuple[object, int]] = [(error, 0)]
    seen: set[int] = set()
    evidence: list[str] = []
    while pending:
        value, depth = pending.pop()
        if value is None or depth > 24 or id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, str):
            evidence.append(value)
            continue
        if isinstance(value, bytes):
            evidence.append(value.decode("utf-8", errors="replace"))
            continue
        if isinstance(value, BaseException):
            evidence.extend((type(value).__name__, str(value)))
            pending.extend(
                (
                    (value.args, depth + 1),
                    (value.__cause__, depth + 1),
                    (value.__context__, depth + 1),
                    (value.__traceback__, depth + 1),
                    (vars(value), depth + 1),
                )
            )
            if isinstance(value, json.JSONDecodeError):
                pending.append((value.doc, depth + 1))
            if isinstance(value, httpx.HTTPError):
                try:
                    pending.append((value.request, depth + 1))
                except RuntimeError:
                    pass
                pending.append((getattr(value, "response", None), depth + 1))
            continue
        if isinstance(value, TracebackType):
            filename = value.tb_frame.f_code.co_filename.replace("\\", "/")
            if "/backend/tests/" not in filename:
                pending.append((value.tb_frame.f_locals, depth + 1))
            pending.append((value.tb_next, depth + 1))
            continue
        if isinstance(value, httpx.Request):
            pending.extend(
                (
                    (dict(value.headers), depth + 1),
                    (value.content, depth + 1),
                    (str(value.url), depth + 1),
                )
            )
            continue
        if isinstance(value, httpx.Response):
            pending.extend(
                (
                    (dict(value.headers), depth + 1),
                    (value.content, depth + 1),
                    (value.request, depth + 1),
                )
            )
            continue
        if isinstance(value, Mapping):
            pending.extend((item, depth + 1) for item in value.items())
            continue
        if isinstance(value, (list, tuple, set, frozenset)):
            pending.extend((item, depth + 1) for item in value)
            continue
        module_name = type(value).__module__
        if module_name.startswith(("backend.", "httpx.")):
            try:
                pending.append((vars(value), depth + 1))
            except TypeError:
                pass

    joined = "\n".join(evidence)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert all(sentinel not in joined for sentinel in sentinels)


def test_provider_response_text_validation_requires_str_nonblank_strict_utf8():
    validate = _scanner("validate_provider_response_text")
    valid = "  星河😀中文  "

    assert validate(valid) == valid
    assert validate(valid, strip=True) == "星河😀中文"
    for invalid in ({}, [], "", " \r\n", "\ud800", "\udfff"):
        with pytest.raises(ValueError, match="provider response text is invalid"):
            validate(invalid)


@pytest.mark.parametrize(
    ("value", "secrets"),
    (
        ("\ud800", ("long-secret",)),
        ("ordinary response", ("\udfff-long-secret",)),
    ),
)
def test_raw_response_scanner_never_leaks_unicode_errors(value, secrets):
    scanner = _scanner("provider_response_text_contains_secret")

    with pytest.raises(ValueError) as exc_info:
        scanner(value, secrets)

    assert type(exc_info.value) is ValueError
    assert str(exc_info.value) == "provider response text is invalid"


def test_decoded_response_scanner_matches_short_secrets_only_as_exact_scalars_or_keys():
    scanner = _scanner("provider_response_value_contains_secret")

    assert scanner({"tagline": "short"}, ("short",)) is True
    assert scanner({"short": "safe"}, ("short",)) is True
    assert scanner("short", ("short",)) is True
    assert scanner({"tagline": "ordinary short prose"}, ("short",)) is False
    assert scanner({"xylophone": "safe"}, ("x",)) is False


def test_decoded_response_scanner_matches_long_secrets_as_substrings():
    scanner = _scanner("provider_response_value_contains_secret")

    assert scanner(
        {"tagline": "prefix long-secret-value suffix"},
        ("long-secret-value",),
    ) is True


def test_decoded_response_scanner_rejects_surrogate_scalars_without_codec_error():
    scanner = _scanner("provider_response_value_contains_secret")

    with pytest.raises(ValueError) as exc_info:
        scanner({"name": "\ud800"}, ("long-secret",))

    assert type(exc_info.value) is ValueError
    assert str(exc_info.value) == "provider response text is invalid"


def test_raw_response_scanner_preserves_encoded_long_secret_detection_only():
    scanner = _scanner("provider_response_text_contains_secret")
    long_secret = "https://private.example/v1"
    mixed_case_encoding = "https%3a%2F%2fprivate.example%2Fv1"

    assert scanner(
        f'{{"echo":"{quote(long_secret, safe="")}"}}',
        (long_secret,),
    ) is True
    assert scanner(
        f'{{"echo":"{mixed_case_encoding}"}}',
        (long_secret,),
    ) is True
    assert scanner('{"tagline":"ordinary x prose"}', ("x",)) is False


def test_decoded_response_scanner_fails_closed_on_excessive_structure():
    scanner = _scanner("provider_response_value_contains_secret")
    payload: object = "safe"
    for _ in range(34):
        payload = [payload]

    with pytest.raises(ValueError, match="response structure exceeds scan limits"):
        scanner(payload, ("short",), max_depth=32)


@pytest.mark.parametrize(
    "secret_path",
    (
        ("storyBlockRef", "id"),
        ("stageRefs", 0, "id"),
        ("sceneTaskRefs", 0, "contentHash"),
        ("scenes", 0),
    ),
)
def test_decoded_response_scanner_covers_complete_outline_content(
    secret_path,
):
    scanner = _scanner("provider_response_value_contains_secret")
    secret = "long-outline-provider-secret"
    payload = {
        "storyBlockRef": {"id": "block-1", "contentHash": "a" * 64},
        "stageRefs": [{"id": "stage-1", "contentHash": "b" * 64}],
        "sceneTaskRefs": [{"id": "task-1", "contentHash": "c" * 64}],
        "scenes": ["ordinary scene"],
    }
    target = payload
    for part in secret_path[:-1]:
        target = target[part]
    target[secret_path[-1]] = f"prefix {secret} suffix"

    assert scanner(payload, (secret,)) is True


@pytest.mark.asyncio
async def test_lifecycle_close_failure_has_content_free_error_graph(monkeypatch):
    module = importlib.import_module(
        "backend.gateways.openai_json_transport"
    )
    resource_type = getattr(module, "OpenAIJSONTransport", None)
    lifecycle_error_type = getattr(
        module,
        "OpenAIJSONTransportLifecycleError",
        None,
    )
    if resource_type is None or lifecycle_error_type is None:
        pytest.fail("transport lifecycle API is missing")
    secret = (
        "PRIVATE_API_KEY_SENTINEL "
        "https://provider.example/v1 "
        "Authorization RAW_RESPONSE_SENTINEL"
    )

    class FailingClient:
        async def aclose(self):
            raise RuntimeError(secret)

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **_kwargs: FailingClient(),
    )
    resource = resource_type(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()

    with pytest.raises(lifecycle_error_type) as caught:
        await resource.aclose()

    assert str(caught.value) == "OpenAI JSON transport lifecycle failed"
    assert resource.state == "broken"
    assert resource.cleanup_task_count == 0
    _assert_no_sensitive_error_graph(
        caught.value,
        (
            "PRIVATE_API_KEY_SENTINEL",
            "https://provider.example/v1",
            "Authorization",
            "RAW_RESPONSE_SENTINEL",
        ),
    )


@pytest.mark.asyncio
async def test_start_failure_cannot_reach_borrowed_request_history(
    monkeypatch,
):
    module = importlib.import_module(
        "backend.gateways.openai_json_transport"
    )
    resource_type = getattr(module, "OpenAIJSONTransport", None)
    lifecycle_error_type = getattr(
        module,
        "OpenAIJSONTransportLifecycleError",
        None,
    )
    if resource_type is None or lifecycle_error_type is None:
        pytest.fail("transport lifecycle API is missing")

    class RecordingTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.calls = []
            self.close_calls = 0

        async def handle_async_request(self, request):
            self.calls.append(request)
            body = json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps({"answer": "ok"})
                            }
                        }
                    ]
                }
            ).encode()
            return httpx.Response(200, content=body, request=request)

        async def aclose(self):
            self.close_calls += 1

    borrowed = RecordingTransport()
    resource = resource_type(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()
    request_result = await resource.request(
        provider={
            "provider_type": "openai-compatible",
            "base_url": "https://provider.example/v1",
            "api_key": "PRIVATE_API_KEY_SENTINEL",
            "temperature": 0.4,
            "max_output_tokens": 512,
        },
        model_name="planning-model",
        messages=[
            {
                "role": "user",
                "content": "PROMPT_TRACEBACK_SENTINEL",
            }
        ],
    )
    await resource.aclose()

    assert request_result.succeeded is True
    assert len(borrowed.calls) == 1
    assert b"PROMPT_TRACEBACK_SENTINEL" in borrowed.calls[0].content
    assert borrowed.close_calls == 0

    def fail_client_construction(**_kwargs):
        raise RuntimeError("CLIENT_CONSTRUCTION_SECRET_SENTINEL")

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        fail_client_construction,
    )
    with pytest.raises(lifecycle_error_type) as caught:
        await resource.start()

    assert str(caught.value) == "OpenAI JSON transport lifecycle failed"
    assert resource.state == "broken"
    assert resource.cleanup_task_count == 0
    assert borrowed.close_calls == 0
    reachable_request_content = []
    traceback = caught.value.__traceback__
    while traceback is not None:
        filename = traceback.tb_frame.f_code.co_filename.replace("\\", "/")
        if "/backend/tests/" not in filename:
            owner = traceback.tb_frame.f_locals.get("self")
            reachable_transport = getattr(
                owner,
                "_borrowed_transport",
                None,
            )
            for request in getattr(reachable_transport, "calls", ()):
                reachable_request_content.append(request.content)
        traceback = traceback.tb_next
    assert all(
        b"PROMPT_TRACEBACK_SENTINEL" not in content
        for content in reachable_request_content
    )
    _assert_no_sensitive_error_graph(
        caught.value,
        (
            "PROMPT_TRACEBACK_SENTINEL",
            "PRIVATE_API_KEY_SENTINEL",
            "https://provider.example/v1",
            "CLIENT_CONSTRUCTION_SECRET_SENTINEL",
        ),
    )
    assert resource._borrowed_transport is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (1, 2, 4))
async def test_cancelled_start_waiting_for_close_has_safe_traceback(
    cancel_count,
):
    module = importlib.import_module(
        "backend.gateways.openai_json_transport"
    )
    resource_type = getattr(module, "OpenAIJSONTransport", None)
    if resource_type is None:
        pytest.fail("transport lifecycle API is missing")

    response_body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"answer": "ok"})
                    }
                }
            ]
        }
    ).encode()

    class BlockingResponseStream(httpx.AsyncByteStream):
        def __init__(self):
            self.read_started = asyncio.Event()
            self.read_release = asyncio.Event()
            self.close_calls = 0

        async def __aiter__(self):
            self.read_started.set()
            await _bounded(self.read_release.wait())
            yield response_body

        async def aclose(self):
            self.close_calls += 1

    class RecordingTransport(httpx.AsyncBaseTransport):
        def __init__(self, stream):
            self.stream = stream
            self.calls = []
            self.close_calls = 0

        async def handle_async_request(self, request):
            self.calls.append(request)
            return httpx.Response(
                200,
                stream=self.stream,
                request=request,
            )

        async def aclose(self):
            self.close_calls += 1

    stream = BlockingResponseStream()
    borrowed = RecordingTransport(stream)
    resource = resource_type(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await _bounded(resource.start())
    request_task = asyncio.create_task(
        resource.request(
            provider={
                "provider_type": "openai-compatible",
                "base_url": "https://provider.example/v1",
                "api_key": "PRIVATE_API_KEY_SENTINEL",
                "temperature": 0.4,
                "max_output_tokens": 512,
            },
            model_name="planning-model",
            messages=[
                {
                    "role": "user",
                    "content": "PROMPT_CLOSE_WAIT_SENTINEL",
                }
            ],
        )
    )
    close_waiter = None
    late_start = None
    try:
        await _bounded(stream.read_started.wait())
        assert b"PROMPT_CLOSE_WAIT_SENTINEL" in borrowed.calls[0].content

        close_waiter = asyncio.create_task(resource.aclose())
        await _wait_until(
            lambda: (
                resource.state == "draining"
                and resource._close_task is not None
            )
        )
        shared_close = resource._close_task
        late_start = asyncio.create_task(resource.start())
        await _wait_until(lambda: late_start._fut_waiter is not None)

        for _ in range(cancel_count):
            late_start.cancel()
        with pytest.raises(asyncio.CancelledError) as caught:
            await _bounded(late_start)

        assert caught.value.args == ()
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert late_start.cancelling() == cancel_count
        assert shared_close.cancelled() is False
        assert shared_close.done() is False
        assert resource._close_task is shared_close

        reachable_request_content = []
        traceback = caught.value.__traceback__
        while traceback is not None:
            filename = traceback.tb_frame.f_code.co_filename.replace(
                "\\",
                "/",
            )
            if "/backend/tests/" not in filename:
                owner = traceback.tb_frame.f_locals.get("self")
                reachable_transport = getattr(
                    owner,
                    "_borrowed_transport",
                    None,
                )
                for request in getattr(reachable_transport, "calls", ()):
                    reachable_request_content.append(request.content)
            traceback = traceback.tb_next
        assert all(
            b"PROMPT_CLOSE_WAIT_SENTINEL" not in content
            for content in reachable_request_content
        )
        _assert_no_sensitive_error_graph(
            caught.value,
            (
                "PROMPT_CLOSE_WAIT_SENTINEL",
                "PRIVATE_API_KEY_SENTINEL",
                "https://provider.example/v1",
            ),
        )

        stream.read_release.set()
        request_result = await _bounded(request_task)
        await _bounded(close_waiter)
    finally:
        stream.read_release.set()
        await _cancel_and_reap(request_task)
        if late_start is not None:
            await _cancel_and_reap(late_start)
        if close_waiter is not None:
            await _cancel_and_reap(close_waiter)
        if resource.state == "open":
            await _bounded(resource.aclose())

    assert request_result.succeeded is True
    assert len(borrowed.calls) == 1
    assert borrowed.close_calls == 0
    assert stream.close_calls == 1
    assert shared_close.done() is True
    assert shared_close.cancelled() is False
    assert resource.state == "closed"
    assert resource.active_calls == 0
    assert resource.cleanup_task_count == 0
    assert resource._start_task is None
    assert resource._close_task is None


@pytest.mark.asyncio
async def test_response_close_failure_is_hidden_and_cancellation_wins():
    module = importlib.import_module(
        "backend.gateways.openai_json_transport"
    )
    resource_type = getattr(module, "OpenAIJSONTransport", None)
    if resource_type is None:
        pytest.fail("transport lifecycle API is missing")
    secret = (
        "PRIVATE_API_KEY_SENTINEL "
        "https://provider.example/v1 "
        "ordinary prompt Authorization RAW_RESPONSE_SENTINEL"
    )
    read_started = asyncio.Event()
    read_release = asyncio.Event()
    close_calls = 0

    class FailingCloseStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            read_started.set()
            await asyncio.wait_for(
                read_release.wait(),
                timeout=_TEST_TIMEOUT_SECONDS,
            )
            yield b"unreachable"

        async def aclose(self):
            nonlocal close_calls
            close_calls += 1
            raise RuntimeError(secret)

    class BorrowedTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.request = None

        async def handle_async_request(self, request):
            self.request = request
            return httpx.Response(
                200,
                stream=FailingCloseStream(),
                request=request,
            )

        async def aclose(self):
            pytest.fail("borrowed transport must not be closed")

    resource = resource_type(
        transport=BorrowedTransport(),
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()
    task = asyncio.create_task(
        resource.request(
            provider={
                "provider_type": "openai-compatible",
                "base_url": "https://provider.example/v1",
                "api_key": "PRIVATE_API_KEY_SENTINEL",
                "temperature": 0.4,
                "max_output_tokens": 512,
            },
            model_name="planning-model",
            messages=[{"role": "user", "content": "ordinary prompt"}],
        )
    )
    try:
        await asyncio.wait_for(
            read_started.wait(),
            timeout=_TEST_TIMEOUT_SECONDS,
        )
        task.cancel()

        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, timeout=_TEST_TIMEOUT_SECONDS)
    finally:
        read_release.set()
        if not task.done():
            task.cancel()
        try:
            await asyncio.wait_for(task, timeout=_TEST_TIMEOUT_SECONDS)
        except BaseException:
            pass
        await asyncio.wait_for(
            resource.aclose(),
            timeout=_TEST_TIMEOUT_SECONDS,
        )

    assert caught.value.args == ()
    assert task.cancelled() is True
    assert close_calls == 1
    assert resource.active_calls == 0
    assert resource.cleanup_task_count == 0
    _assert_no_sensitive_error_graph(
        caught.value,
        (
            "PRIVATE_API_KEY_SENTINEL",
            "https://provider.example/v1",
            "ordinary prompt",
            "Authorization",
            "RAW_RESPONSE_SENTINEL",
        ),
    )
