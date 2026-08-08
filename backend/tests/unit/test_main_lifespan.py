import asyncio
from collections.abc import Mapping
import json
from types import TracebackType

import httpx
import pytest

from backend import main
from backend.gateways.openai_json_transport import (
    OpenAIJSONTransportLifecycleError,
)
from backend.gateways.planning_provider import PlanningProviderGateway
from backend.gateways.chapter_outline_provider import (
    ChapterOutlineProviderGateway,
)
from backend.routers import chapter_outlines, planning
from backend.runtime import draft_operation_tasks
from backend.runtime.draft_operation_tasks import DraftOperationTaskRegistry
from backend.schema_version import SchemaMismatch
from backend.tests.support.fakes import FakeAsyncContext


class FakePlanningProviderGateway:
    def __init__(self, events):
        self.events = events

    async def start(self):
        self.events.append("provider-start")

    async def aclose(self):
        self.events.append("provider-close")


class FakeDraftOperationTaskRegistry:
    def __init__(self, events=None):
        self.events = events

    async def start(self):
        if self.events is not None:
            self.events.append("draft-registry-start")

    async def aclose(self):
        if self.events is not None:
            self.events.append("draft-registry-close")


def _assert_no_sensitive_error_graph(
    error: BaseException,
    sentinels: tuple[str, ...],
) -> None:
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


async def _next_loop_turn():
    reached = asyncio.Event()
    asyncio.get_running_loop().call_soon(reached.set)
    await asyncio.wait_for(reached.wait(), timeout=1)


def install_lifespan_fakes(monkeypatch, verify_error=None):
    events = []
    main.app.state.draft_operation_shutdown_transfer = None
    main.app.state.market_scheduler_shutdown_transfer = None
    session = object()
    context = FakeAsyncContext(session, events)

    async def fake_verify(actual_session):
        assert actual_session is session
        events.append("verify")
        if verify_error is not None:
            raise verify_error

    async def fake_close_pool():
        events.append("close")

    class FakeRuntime:
        def start(self):
            events.append("scheduler-start")

        async def stop(self):
            events.append("scheduler-stop")

    def fake_build_runtime():
        events.append("scheduler-build")
        return FakeRuntime()

    monkeypatch.setattr(main, "connection", lambda: context)
    monkeypatch.setattr(main, "verify_schema_version", fake_verify)
    monkeypatch.setattr(main, "close_pool", fake_close_pool)
    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        fake_build_runtime,
    )
    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        FakePlanningProviderGateway(events),
        raising=False,
    )
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        FakeDraftOperationTaskRegistry(),
    )
    return events


def test_planning_generation_service_uses_the_exposed_gateway_handle():
    assert (
        planning.get_planning_generation_service()._gateway
        is planning.planning_provider_gateway
    )


def test_outline_generation_service_uses_the_exposed_gateway_handle():
    assert (
        chapter_outlines.get_chapter_outline_generation_service()._gateway
        is chapter_outlines.chapter_outline_provider_gateway
    )


@pytest.mark.asyncio
async def test_lifespan_starts_planning_then_outline_and_closes_in_reverse(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)

    class NamedGateway(FakePlanningProviderGateway):
        def __init__(self, actual_events, name):
            super().__init__(actual_events)
            self.name = name

        async def start(self):
            self.events.append(f"{self.name}-start")

        async def aclose(self):
            self.events.append(f"{self.name}-close")

    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        NamedGateway(events, "planning"),
    )
    monkeypatch.setattr(
        main.chapter_outlines,
        "chapter_outline_provider_gateway",
        NamedGateway(events, "outline"),
        raising=False,
    )
    context = main.lifespan(main.app)

    await context.__aenter__()
    await context.__aexit__(None, None, None)

    assert [
        event
        for event in events
        if event.endswith(("-start", "-close"))
    ] == [
        "scheduler-start",
        "planning-start",
        "outline-start",
        "outline-close",
        "planning-close",
    ]


@pytest.mark.asyncio
async def test_outline_start_failure_rolls_back_both_gateways_before_pool(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    startup_error = RuntimeError("outline startup failed")

    class PlanningGateway(FakePlanningProviderGateway):
        async def start(self):
            events.append("planning-start")

        async def aclose(self):
            events.append("planning-close")

    class OutlineGateway(FakePlanningProviderGateway):
        async def start(self):
            events.append("outline-start")
            raise startup_error

        async def aclose(self):
            events.append("outline-close")

    monkeypatch.setattr(
        main.planning, "planning_provider_gateway", PlanningGateway(events)
    )
    monkeypatch.setattr(
        main.chapter_outlines,
        "chapter_outline_provider_gateway",
        OutlineGateway(events),
        raising=False,
    )

    with pytest.raises(RuntimeError) as caught:
        await main.lifespan(main.app).__aenter__()

    assert caught.value is startup_error
    assert events[-5:] == [
        "outline-start",
        "outline-close",
        "planning-close",
        "scheduler-stop",
        "close",
    ]


@pytest.mark.asyncio
async def test_lifespan_restarts_the_outline_gateway_with_a_new_client(
    monkeypatch,
):
    install_lifespan_fakes(monkeypatch)
    gateway = ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500, request=request)
        )
    )
    monkeypatch.setattr(
        main.chapter_outlines,
        "chapter_outline_provider_gateway",
        gateway,
        raising=False,
    )

    first_context = main.lifespan(main.app)
    await first_context.__aenter__()
    first_client = gateway._resource._client
    assert first_client is not None
    await first_context.__aexit__(None, None, None)

    second_context = main.lifespan(main.app)
    await second_context.__aenter__()
    second_client = gateway._resource._client
    assert second_client is not None
    assert second_client is not first_client
    assert first_client.is_closed is True
    await second_context.__aexit__(None, None, None)
    assert second_client.is_closed is True


@pytest.mark.asyncio
async def test_lifespan_drains_outline_before_closing_planning_and_pool(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)

    class DrainingOutline(FakePlanningProviderGateway):
        def __init__(self, actual_events):
            super().__init__(actual_events)
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def aclose(self):
            events.append("outline-close-start")
            self.started.set()
            await self.release.wait()
            events.append("outline-close-complete")

    outline = DrainingOutline(events)
    monkeypatch.setattr(
        main.chapter_outlines,
        "chapter_outline_provider_gateway",
        outline,
        raising=False,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(outline.started.wait(), timeout=1)
        assert "provider-close" not in events
        assert "close" not in events
    finally:
        outline.release.set()
        await asyncio.wait_for(shutdown, timeout=1)

    assert events[-5:] == [
        "outline-close-start",
        "outline-close-complete",
        "provider-close",
        "scheduler-stop",
        "close",
    ]


@pytest.mark.asyncio
async def test_outline_close_failure_is_sanitized_and_planning_still_closes(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    secret = "OUTLINE_CLOSE_SECRET"

    class FailingOutline(FakePlanningProviderGateway):
        async def aclose(self):
            events.append("outline-close")
            raise RuntimeError(secret)

    monkeypatch.setattr(
        main.chapter_outlines,
        "chapter_outline_provider_gateway",
        FailingOutline(events),
        raising=False,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(OpenAIJSONTransportLifecycleError) as caught:
        await context.__aexit__(None, None, None)

    assert caught.value.args == ("OpenAI JSON transport lifecycle failed",)
    assert events[-4:] == [
        "outline-close",
        "provider-close",
        "scheduler-stop",
        "close",
    ]
    _assert_no_sensitive_error_graph(caught.value, (secret,))


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (1, 2, 4))
async def test_repeated_cancellation_cannot_interrupt_outline_then_planning_cleanup(
    monkeypatch,
    cancel_count,
):
    events = install_lifespan_fakes(monkeypatch)

    class BlockingOutline(FakePlanningProviderGateway):
        def __init__(self, actual_events):
            super().__init__(actual_events)
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def aclose(self):
            events.append("outline-close-start")
            self.started.set()
            await self.release.wait()
            events.append("outline-close-complete")

    outline = BlockingOutline(events)
    monkeypatch.setattr(
        main.chapter_outlines,
        "chapter_outline_provider_gateway",
        outline,
        raising=False,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(outline.started.wait(), timeout=1)
        for _ in range(cancel_count):
            shutdown.cancel()
            await _next_loop_turn()
        assert shutdown.done() is False
        assert "provider-close" not in events
    finally:
        outline.release.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(shutdown, timeout=1)
    assert events[-5:] == [
        "outline-close-start",
        "outline-close-complete",
        "provider-close",
        "scheduler-stop",
        "close",
    ]
    assert shutdown.cancelling() == cancel_count


@pytest.mark.asyncio
async def test_lifespan_verifies_once_before_yield_and_closes_after_success(monkeypatch):
    events = install_lifespan_fakes(monkeypatch)
    context = main.lifespan(main.app)

    await context.__aenter__()
    events.append("app-yielded")

    assert events == [
        "connection-enter",
        "verify",
        "connection-exit",
        "scheduler-build",
        "scheduler-start",
        "provider-start",
        "app-yielded",
    ]

    await context.__aexit__(None, None, None)
    assert events == [
        "connection-enter",
        "verify",
        "connection-exit",
        "scheduler-build",
        "scheduler-start",
        "provider-start",
        "app-yielded",
        "provider-close",
        "scheduler-stop",
        "close",
    ]


@pytest.mark.asyncio
async def test_lifespan_does_not_yield_or_swallow_schema_mismatch(monkeypatch):
    mismatch = SchemaMismatch("wrong schema")
    events = install_lifespan_fakes(monkeypatch, verify_error=mismatch)
    context = main.lifespan(main.app)

    with pytest.raises(SchemaMismatch) as raised:
        await context.__aenter__()

    assert raised.value is mismatch
    assert events == [
        "connection-enter",
        "verify",
        "connection-exit",
        "close",
    ]


@pytest.mark.asyncio
async def test_lifespan_closes_pool_when_yielded_application_fails(monkeypatch):
    events = install_lifespan_fakes(monkeypatch)
    context = main.lifespan(main.app)
    await context.__aenter__()
    app_error = RuntimeError("application failed")

    suppressed = await context.__aexit__(
        RuntimeError, app_error, app_error.__traceback__
    )

    assert suppressed is False
    assert events == [
        "connection-enter",
        "verify",
        "connection-exit",
        "scheduler-build",
        "scheduler-start",
        "provider-start",
        "provider-close",
        "scheduler-stop",
        "close",
    ]


@pytest.mark.asyncio
async def test_lifespan_aggregates_scheduler_and_pool_cleanup_failures(monkeypatch):
    events = install_lifespan_fakes(monkeypatch)
    scheduler_error = RuntimeError("synthetic scheduler cleanup")
    pool_error = RuntimeError("synthetic pool cleanup")

    class FailingRuntime:
        def start(self):
            events.append("scheduler-start")

        async def stop(self):
            events.append("scheduler-stop")
            raise scheduler_error

    monkeypatch.setattr(main, "build_market_scheduler_runtime", FailingRuntime)

    async def failing_close_pool():
        events.append("close")
        raise pool_error

    monkeypatch.setattr(main, "close_pool", failing_close_pool)
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup) as aggregated:
        await context.__aexit__(None, None, None)

    assert aggregated.value.exceptions == (scheduler_error, pool_error)
    assert events[-2:] == ["scheduler-stop", "close"]


@pytest.mark.asyncio
async def test_lifespan_preserves_application_error_with_all_cleanup_failures(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    application_error = RuntimeError("synthetic application failure")
    provider_secret = "PROVIDER_CLOSE_AGGREGATION_SECRET"
    scheduler_error = RuntimeError("synthetic scheduler cleanup")
    pool_error = RuntimeError("synthetic pool cleanup")

    class FailingGateway(FakePlanningProviderGateway):
        async def aclose(self):
            events.append("provider-close")
            raise RuntimeError(provider_secret)

    class FailingRuntime:
        def start(self):
            events.append("scheduler-start")

        async def stop(self):
            events.append("scheduler-stop")
            raise scheduler_error

    monkeypatch.setattr(main, "build_market_scheduler_runtime", FailingRuntime)

    async def failing_close_pool():
        events.append("close")
        raise pool_error

    monkeypatch.setattr(main, "close_pool", failing_close_pool)
    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        FailingGateway(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup) as aggregated:
        await context.__aexit__(
            RuntimeError,
            application_error,
            application_error.__traceback__,
        )

    provider_error = aggregated.value.exceptions[1]
    assert aggregated.value.exceptions == (
        application_error,
        provider_error,
        scheduler_error,
        pool_error,
    )
    assert isinstance(
        provider_error,
        OpenAIJSONTransportLifecycleError,
    )
    assert provider_error.args == (
        "OpenAI JSON transport lifecycle failed",
    )
    assert events[-3:] == ["provider-close", "scheduler-stop", "close"]
    _assert_no_sensitive_error_graph(
        aggregated.value,
        (provider_secret,),
    )


@pytest.mark.asyncio
async def test_lifespan_restarts_the_production_gateway_with_a_new_client(
    monkeypatch,
):
    install_lifespan_fakes(monkeypatch)
    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500, request=request)
        )
    )
    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        gateway,
    )

    first_context = main.lifespan(main.app)
    await first_context.__aenter__()
    first_client = gateway._resource._client
    assert first_client is not None
    await first_context.__aexit__(None, None, None)

    second_context = main.lifespan(main.app)
    await second_context.__aenter__()
    second_client = gateway._resource._client
    assert second_client is not None
    assert second_client is not first_client
    assert first_client.is_closed is True
    await second_context.__aexit__(None, None, None)
    assert second_client.is_closed is True


@pytest.mark.asyncio
async def test_lifespan_start_failure_prevents_serving_and_always_closes(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    startup_error = RuntimeError("synthetic provider startup")

    class StartFailingGateway(FakePlanningProviderGateway):
        async def start(self):
            self.events.append("provider-start")
            raise startup_error

    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        StartFailingGateway(events),
    )
    context = main.lifespan(main.app)

    with pytest.raises(RuntimeError) as raised:
        await context.__aenter__()

    assert raised.value is startup_error
    assert "app-yielded" not in events
    assert events[-3:] == ["provider-close", "scheduler-stop", "close"]


@pytest.mark.asyncio
async def test_lifespan_waits_for_provider_calls_to_drain_before_pool_close(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)

    class DrainingGateway(FakePlanningProviderGateway):
        def __init__(self, actual_events):
            super().__init__(actual_events)
            self.close_started = asyncio.Event()
            self.active_call_released = asyncio.Event()
            self.close_completed = asyncio.Event()

        async def aclose(self):
            self.events.append("provider-close-start")
            self.close_started.set()
            await self.active_call_released.wait()
            self.events.append("provider-close-complete")
            self.close_completed.set()

    gateway = DrainingGateway(events)
    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        gateway,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(gateway.close_started.wait(), timeout=1)
        assert shutdown.done() is False
        assert "close" not in events
    finally:
        gateway.active_call_released.set()
        await asyncio.wait_for(shutdown, timeout=1)

    assert gateway.close_completed.is_set()
    assert events[-4:] == [
        "provider-close-start",
        "provider-close-complete",
        "scheduler-stop",
        "close",
    ]


@pytest.mark.asyncio
async def test_lifespan_sanitizes_provider_close_failure(monkeypatch):
    events = install_lifespan_fakes(monkeypatch)
    api_key = "PRIVATE_API_KEY_SENTINEL"
    base_url = "https://provider.example/v1"
    prompt = "PROMPT_SENTINEL"
    raw_response = "RAW_RESPONSE_SENTINEL"
    request = httpx.Request(
        "POST",
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        content=prompt,
    )
    response = httpx.Response(
        500,
        request=request,
        content=raw_response,
    )

    class CloseFailingGateway(FakePlanningProviderGateway):
        async def aclose(self):
            self.events.append("provider-close")
            raise httpx.HTTPStatusError(
                f"{api_key} {base_url} {prompt} {raw_response}",
                request=request,
                response=response,
            )

    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        CloseFailingGateway(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(OpenAIJSONTransportLifecycleError) as caught:
        await context.__aexit__(None, None, None)

    assert caught.value.args == ("OpenAI JSON transport lifecycle failed",)
    assert events[-3:] == ["provider-close", "scheduler-stop", "close"]
    _assert_no_sensitive_error_graph(
        caught.value,
        (api_key, base_url, prompt, raw_response, "Authorization"),
    )


@pytest.mark.asyncio
async def test_lifespan_keeps_application_failure_primary_when_provider_close_fails(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    application_error = RuntimeError("synthetic application failure")
    close_secret = "PROVIDER_CLOSE_SECRET_SENTINEL"

    class CloseFailingGateway(FakePlanningProviderGateway):
        async def aclose(self):
            self.events.append("provider-close")
            raise RuntimeError(close_secret)

    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        CloseFailingGateway(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup) as caught:
        await context.__aexit__(
            RuntimeError,
            application_error,
            application_error.__traceback__,
        )

    assert caught.value.exceptions[0] is application_error
    lifecycle_error = caught.value.exceptions[1]
    assert isinstance(
        lifecycle_error,
        OpenAIJSONTransportLifecycleError,
    )
    assert lifecycle_error.args == (
        "OpenAI JSON transport lifecycle failed",
    )
    _assert_no_sensitive_error_graph(caught.value, (close_secret,))


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (1, 2, 4))
async def test_lifespan_repeated_cancellation_cannot_interrupt_provider_cleanup(
    monkeypatch,
    cancel_count,
):
    events = install_lifespan_fakes(monkeypatch)
    cleanup_secret = "PROVIDER_CLEANUP_SECRET_SENTINEL"

    class BlockingGateway(FakePlanningProviderGateway):
        def __init__(self, actual_events):
            super().__init__(actual_events)
            self.close_started = asyncio.Event()
            self.close_release = asyncio.Event()
            self.close_completed = asyncio.Event()

        async def aclose(self):
            sensitive_cleanup_local = cleanup_secret
            self.events.append("provider-close-start")
            self.close_started.set()
            await self.close_release.wait()
            assert sensitive_cleanup_local == cleanup_secret
            self.events.append("provider-close-complete")
            self.close_completed.set()

    gateway = BlockingGateway(events)
    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        gateway,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(gateway.close_started.wait(), timeout=1)
        shutdown.cancel()
        await _next_loop_turn()
        for _ in range(cancel_count - 1):
            shutdown.cancel()
        await _next_loop_turn()
        assert shutdown.done() is False
        assert gateway.close_completed.is_set() is False
        assert "close" not in events
    finally:
        gateway.close_release.set()

    with pytest.raises(asyncio.CancelledError) as caught:
        await asyncio.wait_for(shutdown, timeout=1)

    assert gateway.close_completed.is_set()
    assert events[-4:] == [
        "provider-close-start",
        "provider-close-complete",
        "scheduler-stop",
        "close",
    ]
    assert caught.value.args == ()
    assert shutdown.cancelling() == cancel_count
    _assert_no_sensitive_error_graph(caught.value, (cleanup_secret,))


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (1, 2, 4))
async def test_lifespan_repeated_cancellation_cannot_interrupt_pool_close(
    monkeypatch,
    cancel_count,
):
    events = install_lifespan_fakes(monkeypatch)
    cleanup_secret = "POOL_CLEANUP_SECRET_SENTINEL"
    close_started = asyncio.Event()
    close_release = asyncio.Event()
    close_completed = asyncio.Event()

    async def blocking_close_pool():
        sensitive_cleanup_local = cleanup_secret
        events.append("pool-close-start")
        close_started.set()
        try:
            await close_release.wait()
        finally:
            events.append("pool-close-finally")
        assert sensitive_cleanup_local == cleanup_secret
        events.append("pool-close-complete")
        close_completed.set()

    monkeypatch.setattr(main, "close_pool", blocking_close_pool)
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(close_started.wait(), timeout=1)
        shutdown.cancel()
        await _next_loop_turn()
        for _ in range(cancel_count - 1):
            shutdown.cancel()
        await _next_loop_turn()
        assert shutdown.done() is False
        assert close_completed.is_set() is False
    finally:
        close_release.set()

    with pytest.raises(asyncio.CancelledError) as caught:
        await asyncio.wait_for(shutdown, timeout=1)

    assert close_completed.is_set()
    assert events[-3:] == [
        "pool-close-start",
        "pool-close-finally",
        "pool-close-complete",
    ]
    assert caught.value.args == ()
    assert shutdown.cancelling() == cancel_count
    _assert_no_sensitive_error_graph(caught.value, (cleanup_secret,))


@pytest.mark.asyncio
async def test_lifespan_transfers_stalled_cleanup_before_pool_close(
    monkeypatch,
):
    from backend.runtime.market_scheduler import MarketSchedulerRuntime

    events = install_lifespan_fakes(monkeypatch)

    class UnresponsiveScheduler:
        enabled = True
        next_run_at = None

        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.cleaned = asyncio.Event()

        async def run_once(self):
            self.started.set()
            try:
                while not self.release.is_set():
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        asyncio.current_task().uncancel()
            finally:
                events.append("scheduler-cleaned")
                self.cleaned.set()

    scheduler = UnresponsiveScheduler()
    runtime = MarketSchedulerRuntime(
        scheduler,
        poll_interval_seconds=60,
        shutdown_timeout_seconds=0.02,
    )
    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        lambda: runtime,
    )

    async def ordered_close_pool():
        events.append("close-after-cleaned" if scheduler.cleaned.is_set() else "close-early")

    monkeypatch.setattr(main, "close_pool", ordered_close_pool)
    context = main.lifespan(main.app)
    await context.__aenter__()
    await asyncio.wait_for(scheduler.started.wait(), timeout=1)
    started = asyncio.get_running_loop().time()

    with pytest.raises(TimeoutError):
        await context.__aexit__(None, None, None)

    elapsed = asyncio.get_running_loop().time() - started
    before_release = tuple(events)
    transfer = getattr(
        main.app.state,
        "market_scheduler_shutdown_transfer",
        None,
    )
    scheduler.release.set()
    if transfer is None:
        await asyncio.wait_for(scheduler.cleaned.wait(), timeout=1)
    else:
        await asyncio.wait_for(transfer, timeout=1)

    assert elapsed < 0.5
    assert "close-early" not in before_release
    assert "close-after-cleaned" not in before_release
    assert transfer is not None
    assert events[-2:] == ["scheduler-cleaned", "close-after-cleaned"]


@pytest.mark.asyncio
async def test_lifespan_cancellation_during_stop_defers_pool_close(
    monkeypatch,
):
    from backend.runtime.market_scheduler import MarketSchedulerRuntime

    events = install_lifespan_fakes(monkeypatch)

    class UnresponsiveScheduler:
        enabled = True
        next_run_at = None

        def __init__(self):
            self.started = asyncio.Event()
            self.cancel_seen = asyncio.Event()
            self.release = asyncio.Event()
            self.cleaned = asyncio.Event()

        async def run_once(self):
            self.started.set()
            try:
                while not self.release.is_set():
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        self.cancel_seen.set()
                        asyncio.current_task().uncancel()
            finally:
                events.append("scheduler-cleaned")
                self.cleaned.set()

    scheduler = UnresponsiveScheduler()
    runtime = MarketSchedulerRuntime(
        scheduler,
        poll_interval_seconds=60,
        shutdown_timeout_seconds=1,
    )
    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        lambda: runtime,
    )

    async def ordered_close_pool():
        events.append("close-after-cleaned" if scheduler.cleaned.is_set() else "close-early")

    monkeypatch.setattr(main, "close_pool", ordered_close_pool)
    context = main.lifespan(main.app)
    await context.__aenter__()
    await asyncio.wait_for(scheduler.started.wait(), timeout=1)
    shutdown = asyncio.create_task(
        context.__aexit__(None, None, None)
    )
    await asyncio.wait_for(scheduler.cancel_seen.wait(), timeout=1)

    shutdown.cancel()
    with pytest.raises(asyncio.CancelledError):
        await shutdown

    before_release = tuple(events)
    transfer = getattr(
        main.app.state,
        "market_scheduler_shutdown_transfer",
        None,
    )
    scheduler.release.set()
    if transfer is None:
        await asyncio.wait_for(scheduler.cleaned.wait(), timeout=1)
    else:
        await asyncio.wait_for(transfer, timeout=1)

    assert "close-early" not in before_release
    assert "close-after-cleaned" not in before_release
    assert transfer is not None
    assert events[-2:] == ["scheduler-cleaned", "close-after-cleaned"]


@pytest.mark.asyncio
async def test_lifespan_starts_draft_registry_after_schema_and_drains_it_first(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    registry = FakeDraftOperationTaskRegistry(events)
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    context = main.lifespan(main.app)

    await context.__aenter__()
    events.append("app-yielded")
    await context.__aexit__(None, None, None)

    assert events.index("verify") < events.index("draft-registry-start")
    assert events.index("draft-registry-start") < events.index("scheduler-build")
    assert events.index("draft-registry-start") < events.index("app-yielded")
    assert events.index("draft-registry-close") < events.index("provider-close")
    assert events.index("draft-registry-close") < events.index("scheduler-stop")
    assert events.index("draft-registry-close") < events.index("close")


@pytest.mark.asyncio
async def test_lifespan_waits_for_named_draft_registry_drain_before_other_cleanup(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)

    class BlockingRegistry(FakeDraftOperationTaskRegistry):
        def __init__(self, actual_events):
            super().__init__(actual_events)
            self.close_started = asyncio.Event()
            self.close_release = asyncio.Event()
            self.close_completed = asyncio.Event()
            self.close_task_name = None

        async def aclose(self):
            self.close_task_name = asyncio.current_task().get_name()
            events.append("draft-registry-close-start")
            self.close_started.set()
            await self.close_release.wait()
            events.append("draft-registry-close-complete")
            self.close_completed.set()

    registry = BlockingRegistry(events)
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(registry.close_started.wait(), timeout=1)
        assert "provider-close" not in events
        assert "scheduler-stop" not in events
        assert "close" not in events
    finally:
        registry.close_release.set()
        await asyncio.wait_for(shutdown, timeout=1)

    assert registry.close_completed.is_set()
    assert registry.close_task_name == "draft-operation-task-registry-close"
    assert events.index("draft-registry-close-complete") < events.index(
        "provider-close"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (1, 2, 4))
async def test_repeated_cancellation_cannot_interrupt_draft_registry_drain(
    monkeypatch,
    cancel_count,
):
    events = install_lifespan_fakes(monkeypatch)

    class BlockingRegistry(FakeDraftOperationTaskRegistry):
        def __init__(self):
            super().__init__(events)
            self.close_started = asyncio.Event()
            self.close_release = asyncio.Event()
            self.close_completed = asyncio.Event()

        async def aclose(self):
            events.append("draft-registry-close-start")
            self.close_started.set()
            await self.close_release.wait()
            events.append("draft-registry-close-complete")
            self.close_completed.set()

    registry = BlockingRegistry()
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(registry.close_started.wait(), timeout=1)
        for _ in range(cancel_count):
            shutdown.cancel()
            await _next_loop_turn()
        assert shutdown.done() is False
        assert "provider-close" not in events
        assert "close" not in events
    finally:
        registry.close_release.set()

    with pytest.raises(asyncio.CancelledError) as caught:
        await asyncio.wait_for(shutdown, timeout=1)

    assert caught.value.args == ()
    assert shutdown.cancelling() == cancel_count
    assert registry.close_completed.is_set()
    assert events.index("draft-registry-close-complete") < events.index(
        "provider-close"
    )


@pytest.mark.asyncio
async def test_draft_registry_start_failure_is_primary_and_still_closes(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    startup_error = RuntimeError("synthetic draft registry startup")

    class StartFailingRegistry(FakeDraftOperationTaskRegistry):
        async def start(self):
            events.append("draft-registry-start")
            raise startup_error

        async def aclose(self):
            events.append("draft-registry-close")

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        StartFailingRegistry(events),
    )

    with pytest.raises(RuntimeError) as caught:
        await main.lifespan(main.app).__aenter__()

    assert caught.value is startup_error
    assert "scheduler-build" not in events
    assert "provider-start" not in events
    assert events[-2:] == ["draft-registry-close", "close"]


@pytest.mark.asyncio
async def test_draft_registry_close_failure_is_fixed_and_other_cleanup_continues(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    cleanup_secret = "DRAFT_REGISTRY_CLEANUP_SECRET_SENTINEL"

    class CloseFailingRegistry(FakeDraftOperationTaskRegistry):
        async def aclose(self):
            events.append("draft-registry-close")
            raise RuntimeError(cleanup_secret)

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        CloseFailingRegistry(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(RuntimeError) as caught:
        await context.__aexit__(None, None, None)

    assert caught.value.args == (
        "Draft operation task registry lifecycle failed",
    )
    assert events[-3:] == [
        "draft-registry-close",
        "provider-close",
        "scheduler-stop",
    ]
    assert "close" not in events
    _assert_no_sensitive_error_graph(caught.value, (cleanup_secret,))


@pytest.mark.asyncio
async def test_generic_draft_failure_blocks_market_transfer_pool_callback(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)

    class CloseFailingRegistry(FakeDraftOperationTaskRegistry):
        async def aclose(self):
            events.append("draft-registry-close")
            raise RuntimeError("PRIVATE_DRAFT_CLOSE_SENTINEL")

    class CleanupTransfer:
        def __init__(self):
            self.task = None

        def start_pool_close(self, close_pool_callback):
            if self.task is None:
                self.task = asyncio.create_task(close_pool_callback())
                self.task.add_done_callback(
                    lambda task: task.exception()
                    if not task.cancelled()
                    else None
                )
            return self.task

    cleanup_transfer = CleanupTransfer()

    class TransferredRuntime:
        def start(self):
            events.append("scheduler-start")

        async def stop(self):
            events.append("scheduler-stop")
            error = TimeoutError("market scheduler shutdown timed out")
            error.cleanup_transfer = cleanup_transfer
            raise error

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        CloseFailingRegistry(events),
    )
    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        lambda: TransferredRuntime(),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup):
        await context.__aexit__(None, None, None)

    transfer_task = main.app.state.market_scheduler_shutdown_transfer
    await asyncio.gather(transfer_task, return_exceptions=True)

    assert "draft-registry-close" in events
    assert "provider-close" in events
    assert "scheduler-stop" in events
    assert "close" not in events


@pytest.mark.asyncio
async def test_draft_registry_pending_drain_transfers_pool_close_safely(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    monkeypatch.setattr(
        draft_operation_tasks,
        "_DRAFT_OPERATION_TASK_SHUTDOWN_TIMEOUT_SECONDS",
        0.01,
    )
    registry = DraftOperationTaskRegistry()
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    worker_started = asyncio.Event()
    worker_cancelled = asyncio.Event()
    worker_release = asyncio.Event()
    worker_settled = asyncio.Event()
    worker_secret = "DRAFT_WORKER_PRIVATE_SENTINEL"

    async def stubborn_worker(signal):
        sensitive_local = worker_secret
        worker_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            assert signal.is_set()
            worker_cancelled.set()
            await worker_release.wait()
        assert sensitive_local == worker_secret
        events.append("draft-worker-settled")
        worker_settled.set()

    context = main.lifespan(main.app)
    await context.__aenter__()
    registry.launch("private-operation-id", stubborn_worker)
    await worker_started.wait()
    transfer = None
    try:
        with pytest.raises(
            main.DraftOperationTaskRegistryLifecycleError
        ) as caught:
            await asyncio.wait_for(
                context.__aexit__(None, None, None),
                timeout=0.5,
            )

        transfer = main.app.state.draft_operation_shutdown_transfer
        before_release = tuple(events)
        assert caught.value.args == (
            "Draft operation task registry lifecycle failed",
        )
        assert worker_cancelled.is_set()
        assert registry.state == "closing"
        assert registry.size == 1
        assert transfer is not None
        assert not transfer.done()
        assert "close" not in before_release
        _assert_no_sensitive_error_graph(
            caught.value,
            (worker_secret, "private-operation-id"),
        )

        worker_release.set()
        await asyncio.wait_for(transfer, timeout=1)

        assert worker_settled.is_set()
        assert registry.state == "closed"
        assert registry.size == 0
        assert events.count("close") == 1
        assert events.index("draft-worker-settled") < events.index("close")
    finally:
        worker_release.set()
        transfer = getattr(
            main.app.state,
            "draft_operation_shutdown_transfer",
            transfer,
        )
        if transfer is not None:
            await asyncio.wait_for(
                asyncio.shield(transfer),
                timeout=1,
            )
        await asyncio.wait_for(worker_settled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_draft_and_market_pending_drains_share_one_ordered_pool_transfer(
    monkeypatch,
):
    from backend.runtime.market_scheduler import MarketSchedulerRuntime

    events = install_lifespan_fakes(monkeypatch)
    monkeypatch.setattr(
        draft_operation_tasks,
        "_DRAFT_OPERATION_TASK_SHUTDOWN_TIMEOUT_SECONDS",
        0.01,
    )
    registry = DraftOperationTaskRegistry()
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )

    class UnresponsiveScheduler:
        enabled = True
        next_run_at = None

        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.cleaned = asyncio.Event()

        async def run_once(self):
            self.started.set()
            try:
                while not self.release.is_set():
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        asyncio.current_task().uncancel()
            finally:
                events.append("market-drained")
                self.cleaned.set()

    scheduler = UnresponsiveScheduler()
    runtime = MarketSchedulerRuntime(
        scheduler,
        poll_interval_seconds=60,
        shutdown_timeout_seconds=0.01,
    )
    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        lambda: runtime,
    )
    draft_started = asyncio.Event()
    draft_cancelled = asyncio.Event()
    draft_release = asyncio.Event()
    draft_settled = asyncio.Event()

    async def stubborn_draft(signal):
        draft_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            assert signal.is_set()
            draft_cancelled.set()
            await draft_release.wait()
        events.append("draft-drained")
        draft_settled.set()

    context = main.lifespan(main.app)
    await context.__aenter__()
    await asyncio.wait_for(scheduler.started.wait(), timeout=1)
    registry.launch("operation", stubborn_draft)
    await draft_started.wait()
    draft_transfer = None
    market_transfer = None
    try:
        with pytest.raises(BaseExceptionGroup):
            await asyncio.wait_for(
                context.__aexit__(None, None, None),
                timeout=0.5,
            )

        draft_transfer = main.app.state.draft_operation_shutdown_transfer
        market_transfer = main.app.state.market_scheduler_shutdown_transfer
        assert draft_cancelled.is_set()
        assert draft_transfer is not None
        assert draft_transfer is market_transfer
        assert "close" not in events

        scheduler.release.set()
        await asyncio.wait_for(scheduler.cleaned.wait(), timeout=1)
        await _next_loop_turn()
        assert "close" not in events

        draft_release.set()
        await asyncio.wait_for(draft_transfer, timeout=1)

        assert draft_settled.is_set()
        assert registry.state == "closed"
        assert events.count("close") == 1
        assert events.index("market-drained") < events.index("close")
        assert events.index("draft-drained") < events.index("close")
    finally:
        scheduler.release.set()
        draft_release.set()
        final_tasks = {
            task
            for task in (
                getattr(
                    main.app.state,
                    "draft_operation_shutdown_transfer",
                    draft_transfer,
                ),
                getattr(
                    main.app.state,
                    "market_scheduler_shutdown_transfer",
                    market_transfer,
                ),
            )
            if task is not None
        }
        if final_tasks:
            await asyncio.wait_for(
                asyncio.gather(*final_tasks, return_exceptions=True),
                timeout=1,
            )
        await asyncio.wait_for(scheduler.cleaned.wait(), timeout=1)
        await asyncio.wait_for(draft_settled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_lifespan_fails_closed_while_previous_draft_transfer_is_pending(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    never = asyncio.Event()
    previous_transfer = asyncio.create_task(never.wait())
    main.app.state.draft_operation_shutdown_transfer = previous_transfer
    context = main.lifespan(main.app)
    entered = False

    try:
        with pytest.raises(
            main.DraftOperationTaskRegistryLifecycleError
        ) as caught:
            await context.__aenter__()
            entered = True

        assert caught.value.args == (
            "Draft operation task registry lifecycle failed",
        )
        assert events == []
    finally:
        if entered:
            await context.__aexit__(None, None, None)
        previous_transfer.cancel()
        await asyncio.gather(previous_transfer, return_exceptions=True)
        main.app.state.draft_operation_shutdown_transfer = None


@pytest.mark.asyncio
async def test_lifespan_fails_closed_safely_after_previous_draft_transfer_failure(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    transfer_secret = "DRAFT_TRANSFER_FAILURE_SECRET_SENTINEL"

    async def fail_transfer():
        raise RuntimeError(transfer_secret)

    previous_transfer = asyncio.create_task(fail_transfer())
    await asyncio.gather(previous_transfer, return_exceptions=True)
    main.app.state.draft_operation_shutdown_transfer = previous_transfer
    context = main.lifespan(main.app)
    entered = False

    try:
        with pytest.raises(
            main.DraftOperationTaskRegistryLifecycleError
        ) as caught:
            await context.__aenter__()
            entered = True

        assert caught.value.args == (
            "Draft operation task registry lifecycle failed",
        )
        assert events == []
        _assert_no_sensitive_error_graph(caught.value, (transfer_secret,))
    finally:
        if entered:
            await context.__aexit__(None, None, None)
        main.app.state.draft_operation_shutdown_transfer = None


@pytest.mark.asyncio
async def test_lifespan_fails_closed_before_startup_for_pending_market_transfer(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    registry = FakeDraftOperationTaskRegistry(events)
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    previous_transfer = asyncio.create_task(asyncio.Event().wait())
    main.app.state.market_scheduler_shutdown_transfer = previous_transfer
    context = main.lifespan(main.app)
    entered = False

    try:
        with pytest.raises(
            main.DraftOperationTaskRegistryLifecycleError
        ) as caught:
            await context.__aenter__()
            entered = True

        assert caught.value.args == (
            "Draft operation task registry lifecycle failed",
        )
        assert events == []
    finally:
        if entered:
            await context.__aexit__(None, None, None)
        previous_transfer.cancel()
        await asyncio.gather(previous_transfer, return_exceptions=True)
        main.app.state.market_scheduler_shutdown_transfer = None


@pytest.mark.asyncio
async def test_lifespan_fails_closed_safely_for_failed_market_transfer(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    registry = FakeDraftOperationTaskRegistry(events)
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    transfer_secret = "MARKET_TRANSFER_FAILURE_SECRET_SENTINEL"

    async def fail_transfer():
        raise RuntimeError(transfer_secret)

    previous_transfer = asyncio.create_task(fail_transfer())
    await asyncio.gather(previous_transfer, return_exceptions=True)
    main.app.state.market_scheduler_shutdown_transfer = previous_transfer
    context = main.lifespan(main.app)
    entered = False

    try:
        with pytest.raises(
            main.DraftOperationTaskRegistryLifecycleError
        ) as caught:
            await context.__aenter__()
            entered = True

        assert caught.value.args == (
            "Draft operation task registry lifecycle failed",
        )
        assert events == []
        _assert_no_sensitive_error_graph(caught.value, (transfer_secret,))
    finally:
        if entered:
            await context.__aexit__(None, None, None)
        main.app.state.market_scheduler_shutdown_transfer = None


@pytest.mark.asyncio
async def test_lifespan_allows_restart_after_successful_market_transfer(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    registry = FakeDraftOperationTaskRegistry(events)
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    previous_transfer = asyncio.create_task(asyncio.sleep(0))
    await previous_transfer
    main.app.state.market_scheduler_shutdown_transfer = previous_transfer
    context = main.lifespan(main.app)

    await context.__aenter__()
    await context.__aexit__(None, None, None)

    assert events.index("verify") < events.index("draft-registry-start")
    assert events.index("draft-registry-start") < events.index("scheduler-build")


@pytest.mark.asyncio
async def test_lifespan_deduplicates_same_successful_draft_and_market_transfer(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)

    class ClosedRegistry(FakeDraftOperationTaskRegistry):
        state = "closed"

    registry = ClosedRegistry(events)
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )

    class SuccessfulTransfer:
        def __init__(self):
            self.result_calls = 0

        def done(self):
            return True

        def cancelled(self):
            return False

        def result(self):
            self.result_calls += 1

    previous_transfer = SuccessfulTransfer()
    main.app.state.draft_operation_shutdown_transfer = previous_transfer
    main.app.state.market_scheduler_shutdown_transfer = previous_transfer
    context = main.lifespan(main.app)

    await context.__aenter__()
    await context.__aexit__(None, None, None)

    assert previous_transfer.result_calls == 1


@pytest.mark.asyncio
async def test_application_error_stays_primary_when_draft_registry_close_fails(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    application_error = RuntimeError("synthetic application failure")
    cleanup_secret = "DRAFT_REGISTRY_AGGREGATION_SECRET_SENTINEL"

    class CloseFailingRegistry(FakeDraftOperationTaskRegistry):
        async def aclose(self):
            raise RuntimeError(cleanup_secret)

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        CloseFailingRegistry(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup) as caught:
        await context.__aexit__(
            RuntimeError,
            application_error,
            application_error.__traceback__,
        )

    assert caught.value.exceptions[0] is application_error
    lifecycle_error = caught.value.exceptions[1]
    assert isinstance(
        lifecycle_error,
        main.DraftOperationTaskRegistryLifecycleError,
    )
    assert lifecycle_error.args == (
        "Draft operation task registry lifecycle failed",
    )
    _assert_no_sensitive_error_graph(caught.value, (cleanup_secret,))


@pytest.mark.asyncio
async def test_lifespan_restarts_the_same_draft_registry_cleanly(monkeypatch):
    install_lifespan_fakes(monkeypatch)
    registry = DraftOperationTaskRegistry()
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )

    for generation in (1, 2):
        context = main.lifespan(main.app)
        await context.__aenter__()
        completed = asyncio.Event()

        async def worker(_signal):
            completed.set()

        registry.launch(f"operation-{generation}", worker)
        await asyncio.wait_for(completed.wait(), timeout=1)
        await context.__aexit__(None, None, None)
        assert registry.size == 0


@pytest.mark.asyncio
async def test_lifespan_shutdown_only_cancels_task_without_business_cancel(
    monkeypatch,
):
    install_lifespan_fakes(monkeypatch)
    registry = DraftOperationTaskRegistry()
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    business_cancels = []

    async def forbidden_business_cancel(*args):
        business_cancels.append(args)

    monkeypatch.setattr(
        main.chapter_sessions._draft_operation_service,
        "cancel",
        forbidden_business_cancel,
    )
    worker_started = asyncio.Event()
    worker_cancelled = asyncio.Event()

    async def worker(_signal):
        worker_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            worker_cancelled.set()
            raise

    context = main.lifespan(main.app)
    await context.__aenter__()
    registry.launch("operation-active-at-shutdown", worker)
    await asyncio.wait_for(worker_started.wait(), timeout=1)

    await context.__aexit__(None, None, None)

    assert worker_cancelled.is_set()
    assert business_cancels == []
    assert registry.size == 0


@pytest.mark.asyncio
async def test_health_echoes_browser_owner_nonce_only_when_explicitly_injected(
    monkeypatch,
):
    monkeypatch.delenv("M2_BROWSER_RUN_NONCE", raising=False)
    assert await main.health() == {"ok": True}

    monkeypatch.setenv("M2_BROWSER_RUN_NONCE", "owned-browser-child-123")
    assert await main.health() == {
        "ok": True,
        "browserRunNonce": "owned-browser-child-123",
    }
