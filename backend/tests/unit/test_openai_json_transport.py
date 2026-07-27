from __future__ import annotations

import asyncio
import importlib
import json

import httpx
import pytest

from backend.tests.unit.test_provider_response_secret_scanning import (
    _assert_no_sensitive_error_graph,
)


transport_module = importlib.import_module(
    "backend.gateways.openai_json_transport"
)
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


def _resource_type():
    resource_type = getattr(transport_module, "OpenAIJSONTransport", None)
    if resource_type is None:
        pytest.fail("OpenAIJSONTransport lifecycle resource is missing")
    return resource_type


def _provider() -> dict[str, object]:
    return {
        "provider_type": "openai-compatible",
        "base_url": "https://provider.example/v1",
        "api_key": "PRIVATE_API_KEY_SENTINEL",
        "temperature": 0.4,
        "max_output_tokens": 512,
    }


def _messages() -> list[dict[str, str]]:
    return [{"role": "user", "content": "ordinary prompt"}]


def _response_body(value: object | None = None) -> bytes:
    if value is None:
        value = {"answer": "ok"}
    return json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(value),
                    }
                }
            ]
        }
    ).encode()


class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, response_factory=None):
        self.calls: list[httpx.Request] = []
        self.close_calls = 0
        self._response_factory = response_factory

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        self.calls.append(request)
        if self._response_factory is not None:
            return self._response_factory(request)
        return httpx.Response(
            200,
            content=_response_body(),
            request=request,
        )

    async def aclose(self) -> None:
        self.close_calls += 1


class _BlockingClient:
    def __init__(self, *, close_blocks: bool = False):
        self.close_calls = 0
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_completed = asyncio.Event()
        if not close_blocks:
            self.close_release.set()

    async def aclose(self) -> None:
        self.close_calls += 1
        self.close_started.set()
        await _bounded(self.close_release.wait())
        self.close_completed.set()


class _ClientFactory:
    def __init__(self, *, close_blocks: bool = False):
        self.clients: list[_BlockingClient] = []
        self.close_blocks = close_blocks

    def __call__(self, **_kwargs):
        client = _BlockingClient(close_blocks=self.close_blocks)
        self.clients.append(client)
        return client


class _GateReadStream(httpx.AsyncByteStream):
    def __init__(self, body: bytes):
        self._body = body
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.close_calls = 0

    async def __aiter__(self):
        self.entered.set()
        await _bounded(self.release.wait())
        yield self._body

    async def aclose(self) -> None:
        self.close_calls += 1


class _BlockingCloseStream(httpx.AsyncByteStream):
    def __init__(self, *, block_body_read: bool):
        self._body = _response_body()
        self._block_body_read = block_body_read
        self.read_started = asyncio.Event()
        self.read_release = asyncio.Event()
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_completed = asyncio.Event()
        self.close_calls = 0

    async def __aiter__(self):
        self.read_started.set()
        if self._block_body_read:
            await _bounded(self.read_release.wait())
        yield self._body

    async def aclose(self) -> None:
        self.close_calls += 1
        self.close_started.set()
        await _bounded(self.close_release.wait())
        self.close_completed.set()


class _NeverIteratedStream(httpx.AsyncByteStream):
    def __init__(self):
        self.iterated = False
        self.close_calls = 0

    async def __aiter__(self):
        self.iterated = True
        yield _response_body()

    async def aclose(self) -> None:
        self.close_calls += 1


async def _request(resource, **overrides):
    arguments = {
        "provider": _provider(),
        "model_name": "planning-model",
        "messages": _messages(),
    }
    arguments.update(overrides)
    return await resource.request(**arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (1, 2, 4))
async def test_cancellation_while_waiting_for_admission_preserves_count(
    cancel_count,
):
    borrowed = _RecordingTransport()
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()
    await resource._lock.acquire()
    admission_started = asyncio.Event()
    original_admit = resource._admit

    async def observed_admit():
        admission_started.set()
        return await original_admit()

    resource._admit = observed_admit
    provider = _provider()
    messages = [
        {
            "role": "user",
            "content": "PROMPT_ADMISSION_CANCELLATION_SENTINEL",
        }
    ]

    async def capture_outcome():
        try:
            return (
                "result",
                await resource.request(
                    provider=provider,
                    model_name="planning-model",
                    messages=messages,
                ),
            )
        except asyncio.CancelledError as error:
            return "cancelled", error

    task = asyncio.create_task(capture_outcome())
    try:
        await _bounded(admission_started.wait())
        for _ in range(cancel_count):
            task.cancel()
        outcome, value = await _bounded(task)
    finally:
        resource._lock.release()
        await _cancel_and_reap(task)
        await _bounded(resource.aclose())

    if isinstance(value, BaseException):
        _assert_no_sensitive_error_graph(
            value,
            (
                "PRIVATE_API_KEY_SENTINEL",
                "https://provider.example/v1",
                "PROMPT_ADMISSION_CANCELLATION_SENTINEL",
            ),
        )
    assert outcome == "result"
    assert value is transport_module.OPENAI_JSON_TRANSPORT_CANCELLED
    assert task.cancelled() is False
    assert task.cancelling() == cancel_count
    assert borrowed.calls == []
    assert resource.active_calls == 0
    assert resource.cleanup_task_count == 0


@pytest.mark.asyncio
async def test_concurrent_start_and_close_are_idempotent(monkeypatch):
    factory = _ClientFactory(close_blocks=True)
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", factory)
    resource = _resource_type()(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )

    await _bounded(asyncio.gather(*(resource.start() for _ in range(8))))

    assert resource.state == "open"
    assert len(factory.clients) == 1

    close_tasks = [
        asyncio.create_task(resource.aclose()) for _ in range(8)
    ]
    try:
        await _bounded(factory.clients[0].close_started.wait())
        assert resource.state == "closing"
        assert factory.clients[0].close_calls == 1
        factory.clients[0].close_release.set()
        await _bounded(asyncio.gather(*close_tasks))
    finally:
        factory.clients[0].close_release.set()
        for task in close_tasks:
            await _cancel_and_reap(task)

    assert resource.state == "closed"
    assert factory.clients[0].close_calls == 1
    assert resource.cleanup_task_count == 0


@pytest.mark.asyncio
async def test_close_lifecycle_clears_its_task_at_terminal_publication(
    monkeypatch,
):
    factory = _ClientFactory()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", factory)
    resource = _resource_type()(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await _bounded(resource.start())
    terminal_published = asyncio.Event()
    close_task_release = asyncio.Event()
    original_close_lifecycle = resource._close_lifecycle

    async def gated_close_lifecycle():
        outcome = await original_close_lifecycle()
        terminal_published.set()
        await _bounded(close_task_release.wait())
        return outcome

    resource._close_lifecycle = gated_close_lifecycle
    close_waiter = asyncio.create_task(resource.aclose())
    try:
        await _bounded(terminal_published.wait())
        state_at_publication = resource.state
        stale_task_at_publication = resource._close_task
        close_waiter.cancel()
        close_task_release.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            await _bounded(close_waiter)
    finally:
        close_task_release.set()
        await _cancel_and_reap(close_waiter)
        resource._close_lifecycle = original_close_lifecycle

    await _bounded(resource.start())
    restarted_client = factory.clients[-1]
    await _bounded(resource.aclose())

    assert state_at_publication == "closed"
    assert stale_task_at_publication is None
    assert caught.value.args == ()
    assert resource._start_task is None
    assert resource._close_task is None
    assert restarted_client.close_calls == 1
    assert resource.state == "closed"


@pytest.mark.asyncio
async def test_start_lifecycle_clears_its_task_at_terminal_publication(
    monkeypatch,
):
    factory = _ClientFactory()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", factory)
    resource = _resource_type()(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    terminal_published = asyncio.Event()
    start_task_release = asyncio.Event()
    original_start_lifecycle = resource._start_lifecycle

    async def gated_start_lifecycle():
        outcome = await original_start_lifecycle()
        terminal_published.set()
        await _bounded(start_task_release.wait())
        return outcome

    resource._start_lifecycle = gated_start_lifecycle
    start_waiter = asyncio.create_task(resource.start())
    try:
        await _bounded(terminal_published.wait())
        state_at_publication = resource.state
        stale_task_at_publication = resource._start_task
        start_task_release.set()
        await _bounded(start_waiter)
    finally:
        start_task_release.set()
        await _cancel_and_reap(start_waiter)

    await _bounded(resource.aclose())

    assert state_at_publication == "open"
    assert stale_task_at_publication is None
    assert resource._start_task is None
    assert resource._close_task is None
    assert factory.clients[0].close_calls == 1


@pytest.mark.asyncio
async def test_cancelled_only_start_waiter_rolls_back_created_client(
    monkeypatch,
):
    factory = _ClientFactory()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", factory)
    resource = _resource_type()(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    start_entered = asyncio.Event()
    start_release = asyncio.Event()
    original_start_lifecycle = resource._start_lifecycle

    async def blocked_start_lifecycle():
        start_entered.set()
        await _bounded(start_release.wait())
        return await original_start_lifecycle()

    resource._start_lifecycle = blocked_start_lifecycle
    start_waiter = asyncio.create_task(resource.start())
    try:
        await _bounded(start_entered.wait())
        start_waiter.cancel()
        await _next_loop_turn()
        finished_before_release = start_waiter.done()
        start_release.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            await _bounded(start_waiter)
        await _wait_until(lambda: resource.state != "starting")
        terminal_state = resource.state
        close_calls = factory.clients[0].close_calls
        if resource.state != "closed":
            await _bounded(resource.aclose())
    finally:
        start_release.set()
        await _cancel_and_reap(start_waiter)

    assert finished_before_release is False
    assert caught.value.args == ()
    assert terminal_state == "closed"
    assert close_calls == 1
    assert resource._start_task is None
    assert resource._close_task is None
    assert resource.cleanup_task_count == 0


@pytest.mark.asyncio
async def test_late_successful_start_owns_open_generation(monkeypatch):
    factory = _ClientFactory()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", factory)
    resource = _resource_type()(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    open_published = asyncio.Event()
    lifecycle_release = asyncio.Event()
    original_start_lifecycle = resource._start_lifecycle

    async def gated_start_lifecycle():
        succeeded = await original_start_lifecycle()
        open_published.set()
        await _bounded(lifecycle_release.wait())
        return succeeded

    resource._start_lifecycle = gated_start_lifecycle
    first = asyncio.create_task(resource.start())
    try:
        await _bounded(open_published.wait())
        assert resource.state == "open"

        await _bounded(resource.start())
        first.cancel()
        await _next_loop_turn()
        lifecycle_release.set()
        with pytest.raises(asyncio.CancelledError):
            await _bounded(first)

        assert resource.state == "open"
        assert factory.clients[0].close_calls == 0
        await _bounded(resource.aclose())
    finally:
        lifecycle_release.set()
        await _cancel_and_reap(first)
        if resource.state != "closed":
            await _bounded(resource.aclose())

    assert resource.state == "closed"
    assert factory.clients[0].close_calls == 1


@pytest.mark.asyncio
async def test_close_intent_blocks_late_start_and_request_until_restart(
    monkeypatch,
):
    factory = _ClientFactory(close_blocks=True)
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", factory)
    resource = _resource_type()(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    startup_entered = asyncio.Event()
    publish_release = asyncio.Event()
    open_published = asyncio.Event()
    lifecycle_return_release = asyncio.Event()
    original_start_lifecycle = resource._start_lifecycle
    admitted_clients = []
    original_admit = resource._admit

    async def gated_start_lifecycle():
        startup_entered.set()
        await _bounded(publish_release.wait())
        succeeded = await original_start_lifecycle()
        open_published.set()
        await _bounded(lifecycle_return_release.wait())
        return succeeded

    async def observed_admit():
        client = await original_admit()
        admitted_clients.append(client)
        return client

    resource._start_lifecycle = gated_start_lifecycle
    resource._admit = observed_admit
    first_start = asyncio.create_task(resource.start())
    close_waiter = None
    late_start = None
    final_close = None
    try:
        await _bounded(startup_entered.wait())
        close_waiter = asyncio.create_task(resource.aclose())
        await _wait_until(lambda: resource._close_task is not None)
        authoritative_close = resource._close_task

        publish_release.set()
        await _bounded(open_published.wait())
        assert resource.state == "open"
        assert resource._close_task is authoritative_close

        late_start = asyncio.create_task(resource.start())
        await _next_loop_turn()
        request_result = await _bounded(_request(resource))

        assert request_result is transport_module.OPENAI_JSON_TRANSPORT_FAILURE
        assert admitted_clients == [None]
        assert resource.active_calls == 0
        assert late_start.done() is False
        assert len(factory.clients) == 1

        lifecycle_return_release.set()
        await _bounded(factory.clients[0].close_started.wait())
        assert late_start.done() is False
        factory.clients[0].close_release.set()
        await _bounded(close_waiter)
        await _bounded(first_start)
        await _bounded(late_start)

        assert len(factory.clients) == 2
        assert resource.state == "open"
        assert [client.close_calls for client in factory.clients] == [1, 0]

        final_close = asyncio.create_task(resource.aclose())
        await _bounded(factory.clients[1].close_started.wait())
        factory.clients[1].close_release.set()
        await _bounded(final_close)
    finally:
        publish_release.set()
        lifecycle_return_release.set()
        for client in factory.clients:
            client.close_release.set()
        for task in (first_start, close_waiter, late_start, final_close):
            if task is not None:
                await _cancel_and_reap(task)
        for client in factory.clients:
            client.close_release.set()
        if resource.state not in ("closed", "broken"):
            try:
                await _bounded(resource.aclose())
            except transport_module.OpenAIJSONTransportLifecycleError:
                pass

    assert resource.state == "closed"
    assert [client.close_calls for client in factory.clients] == [1, 1]


@pytest.mark.asyncio
async def test_late_generation_finish_cannot_own_next_generation(
    monkeypatch,
):
    factory = _ClientFactory()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", factory)
    resource = _resource_type()(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    generation_one_finish_entered = asyncio.Event()
    generation_one_finish_release = asyncio.Event()
    generation_two_start_entered = asyncio.Event()
    generation_two_start_release = asyncio.Event()
    original_finish_start_intent = resource._finish_start_intent
    original_start_lifecycle = resource._start_lifecycle
    finish_call_count = 0
    lifecycle_call_count = 0

    async def gated_finish_start_intent(*args, **kwargs):
        nonlocal finish_call_count
        finish_call_count += 1
        if finish_call_count == 1:
            generation_one_finish_entered.set()
            await _bounded(generation_one_finish_release.wait())
        return await original_finish_start_intent(*args, **kwargs)

    async def gated_start_lifecycle():
        nonlocal lifecycle_call_count
        lifecycle_call_count += 1
        if lifecycle_call_count == 2:
            generation_two_start_entered.set()
            await _bounded(generation_two_start_release.wait())
        return await original_start_lifecycle()

    resource._finish_start_intent = gated_finish_start_intent
    resource._start_lifecycle = gated_start_lifecycle
    generation_one_start = asyncio.create_task(resource.start())
    generation_two_start = None
    try:
        await _bounded(generation_one_finish_entered.wait())
        assert resource.state == "open"
        await _bounded(resource.aclose())
        assert resource.state == "closed"
        assert factory.clients[0].close_calls == 1

        generation_two_start = asyncio.create_task(resource.start())
        await _bounded(generation_two_start_entered.wait())
        generation_one_finish_release.set()
        await _bounded(generation_one_start)

        generation_two_start.cancel()
        await _next_loop_turn()
        finished_before_generation_two = generation_two_start.done()
        generation_two_start_release.set()
        with pytest.raises(asyncio.CancelledError):
            await _bounded(generation_two_start)
        await _wait_until(lambda: resource.state != "starting")
        terminal_state = resource.state
        generation_two_close_calls = factory.clients[1].close_calls
        if resource.state == "open":
            await _bounded(resource.aclose())
    finally:
        generation_one_finish_release.set()
        generation_two_start_release.set()
        await _cancel_and_reap(generation_one_start)
        if generation_two_start is not None:
            await _cancel_and_reap(generation_two_start)
        if resource.state == "open":
            await _bounded(resource.aclose())

    assert finished_before_generation_two is False
    assert terminal_state == "closed"
    assert generation_two_close_calls == 1
    assert [client.close_calls for client in factory.clients] == [1, 1]


@pytest.mark.asyncio
async def test_cancelled_start_waiter_does_not_close_surviving_owner(
    monkeypatch,
):
    factory = _ClientFactory()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", factory)
    resource = _resource_type()(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    start_entered = asyncio.Event()
    start_release = asyncio.Event()
    original_start_lifecycle = resource._start_lifecycle

    async def blocked_start_lifecycle():
        start_entered.set()
        await _bounded(start_release.wait())
        return await original_start_lifecycle()

    resource._start_lifecycle = blocked_start_lifecycle
    first = asyncio.create_task(resource.start())
    second = None
    try:
        await _bounded(start_entered.wait())
        second = asyncio.create_task(resource.start())
        await _wait_until(lambda: second._fut_waiter is not None)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await _bounded(first)
        start_release.set()
        await _bounded(second)

        assert resource.state == "open"
        assert len(factory.clients) == 1
        assert factory.clients[0].close_calls == 0
        assert resource._close_task is None
        await _bounded(resource.aclose())
    finally:
        start_release.set()
        await _cancel_and_reap(first)
        if second is not None:
            await _cancel_and_reap(second)
        if resource.state == "open":
            await _bounded(resource.aclose())

    assert factory.clients[0].close_calls == 1
    assert resource.state == "closed"


@pytest.mark.asyncio
async def test_last_of_multiple_cancelled_start_waiters_rolls_back_once(
    monkeypatch,
):
    factory = _ClientFactory()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", factory)
    resource = _resource_type()(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    start_entered = asyncio.Event()
    start_release = asyncio.Event()
    original_start_lifecycle = resource._start_lifecycle

    async def blocked_start_lifecycle():
        start_entered.set()
        await _bounded(start_release.wait())
        return await original_start_lifecycle()

    resource._start_lifecycle = blocked_start_lifecycle
    waiters = [asyncio.create_task(resource.start()) for _ in range(3)]
    try:
        await _bounded(start_entered.wait())
        await _wait_until(
            lambda: all(waiter._fut_waiter is not None for waiter in waiters)
        )
        for waiter in waiters[:2]:
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await _bounded(waiter)
        assert resource._close_task is None

        waiters[-1].cancel()
        await _next_loop_turn()
        last_finished_before_release = waiters[-1].done()
        rollback_task = resource._close_task
        start_release.set()
        with pytest.raises(asyncio.CancelledError):
            await _bounded(waiters[-1])
    finally:
        start_release.set()
        for waiter in waiters:
            await _cancel_and_reap(waiter)
        if resource.state == "open":
            await _bounded(resource.aclose())

    assert last_finished_before_release is False
    assert rollback_task is not None
    assert resource.state == "closed"
    assert len(factory.clients) == 1
    assert factory.clients[0].close_calls == 1
    assert resource._start_task is None
    assert resource._close_task is None
    assert resource.cleanup_task_count == 0


@pytest.mark.asyncio
async def test_cancelled_close_during_starting_still_closes_owned_client(
    monkeypatch,
):
    factory = _ClientFactory()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", factory)
    resource = _resource_type()(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    start_entered = asyncio.Event()
    start_release = asyncio.Event()
    original_start_lifecycle = resource._start_lifecycle

    async def blocked_start_lifecycle():
        start_entered.set()
        await _bounded(start_release.wait())
        return await original_start_lifecycle()

    resource._start_lifecycle = blocked_start_lifecycle
    start_task = asyncio.create_task(resource.start())
    close_task = None
    try:
        await _bounded(start_entered.wait())
        assert resource.state == "starting"

        close_task = asyncio.create_task(resource.aclose())
        await _wait_until(lambda: resource._close_task is not None)
        close_task.cancel()
        await _next_loop_turn()
        finished_before_start = close_task.done()
        start_release.set()
        await _bounded(start_task)

        with pytest.raises(asyncio.CancelledError) as caught:
            await _bounded(close_task)
        state_after_cancelled_close = resource.state
        close_calls_after_cancelled_close = (
            factory.clients[0].close_calls if factory.clients else 0
        )
    finally:
        start_release.set()
        await _cancel_and_reap(start_task)
        if close_task is not None:
            await _cancel_and_reap(close_task)
        if resource.state != "closed":
            await _bounded(resource.aclose())

    assert finished_before_start is False
    assert caught.value.args == ()
    assert close_task.cancelling() == 1
    assert state_after_cancelled_close == "closed"
    assert close_calls_after_cancelled_close == 1
    assert resource.cleanup_task_count == 0


@pytest.mark.asyncio
async def test_concurrent_close_during_starting_shares_one_close_intent(
    monkeypatch,
):
    factory = _ClientFactory()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", factory)
    resource = _resource_type()(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    start_entered = asyncio.Event()
    start_release = asyncio.Event()
    original_start_lifecycle = resource._start_lifecycle

    async def blocked_start_lifecycle():
        start_entered.set()
        await _bounded(start_release.wait())
        return await original_start_lifecycle()

    resource._start_lifecycle = blocked_start_lifecycle
    start_task = asyncio.create_task(resource.start())
    first_close = None
    second_close = None
    try:
        await _bounded(start_entered.wait())
        first_close = asyncio.create_task(resource.aclose())
        await _wait_until(lambda: resource._close_task is not None)
        first_close_intent = resource._close_task
        second_close = asyncio.create_task(resource.aclose())
        await _wait_until(
            lambda: (
                resource._close_task is first_close_intent
                and not second_close.done()
            )
        )
        shared_while_starting = (
            first_close_intent is not None
            and resource._close_task is first_close_intent
        )
        start_release.set()
        await _bounded(
            asyncio.gather(start_task, first_close, second_close)
        )
    finally:
        start_release.set()
        await _cancel_and_reap(start_task)
        if first_close is not None:
            await _cancel_and_reap(first_close)
        if second_close is not None:
            await _cancel_and_reap(second_close)

    assert shared_while_starting is True
    assert resource.state == "closed"
    assert len(factory.clients) == 1
    assert factory.clients[0].close_calls == 1
    assert resource.cleanup_task_count == 0


@pytest.mark.asyncio
async def test_explicit_restart_creates_and_closes_a_new_owned_client(
    monkeypatch,
):
    factory = _ClientFactory()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", factory)
    resource = _resource_type()(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )

    await resource.start()
    await resource.aclose()
    await resource.start()
    await resource.aclose()

    assert len(factory.clients) == 2
    assert [client.close_calls for client in factory.clients] == [1, 1]
    assert resource.state == "closed"


@pytest.mark.asyncio
async def test_borrowed_transport_is_never_closed():
    borrowed = _RecordingTransport()
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )

    await resource.start()
    first = await _request(resource)
    second = await _request(resource)
    await resource.aclose()

    assert first.succeeded is True
    assert second.succeeded is True
    assert borrowed.close_calls == 0
    assert len(borrowed.calls) == 2
    assert resource.active_calls == 0
    assert resource.cleanup_task_count == 0


@pytest.mark.asyncio
async def test_overlapping_calls_own_independent_responses():
    streams: list[_GateReadStream] = []

    def respond(request):
        stream = _GateReadStream(_response_body())
        streams.append(stream)
        return httpx.Response(200, stream=stream, request=request)

    borrowed = _RecordingTransport(respond)
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()

    calls = [
        asyncio.create_task(_request(resource)),
        asyncio.create_task(_request(resource)),
    ]
    try:
        await _wait_until(lambda: len(streams) == 2)
        await _bounded(
            asyncio.gather(*(stream.entered.wait() for stream in streams))
        )

        assert resource.active_calls == 2
        for stream in streams:
            stream.release.set()
        results = await _bounded(asyncio.gather(*calls))
        await _bounded(resource.aclose())
    finally:
        for stream in streams:
            stream.release.set()
        for task in calls:
            await _cancel_and_reap(task)
        if resource.state != "closed":
            await _bounded(resource.aclose())

    assert all(result.succeeded for result in results)
    assert [stream.close_calls for stream in streams] == [1, 1]
    assert resource.active_calls == 0
    assert borrowed.close_calls == 0


@pytest.mark.asyncio
async def test_close_drains_both_calls_and_rejects_new_admission():
    streams: list[_GateReadStream] = []

    def respond(request):
        stream = _GateReadStream(_response_body())
        streams.append(stream)
        return httpx.Response(200, stream=stream, request=request)

    borrowed = _RecordingTransport(respond)
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()
    calls = [
        asyncio.create_task(_request(resource)),
        asyncio.create_task(_request(resource)),
    ]
    close_task = None
    try:
        await _wait_until(lambda: len(streams) == 2)
        await _bounded(
            asyncio.gather(*(stream.entered.wait() for stream in streams))
        )

        close_task = asyncio.create_task(resource.aclose())
        await _wait_until(lambda: resource.state != "open")
        rejected = await _bounded(_request(resource))

        assert resource.state == "draining"
        assert rejected.succeeded is False
        assert close_task.done() is False
        assert len(borrowed.calls) == 2

        streams[0].release.set()
        await _bounded(calls[0])
        await _next_loop_turn()
        assert close_task.done() is False

        streams[1].release.set()
        await _bounded(calls[1])
        await _bounded(close_task)
    finally:
        for stream in streams:
            stream.release.set()
        for task in calls:
            await _cancel_and_reap(task)
        if close_task is not None:
            await _cancel_and_reap(close_task)
        if resource.state != "closed":
            await _bounded(resource.aclose())

    assert resource.state == "closed"
    assert borrowed.close_calls == 0
    assert resource.active_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("block_body_read", (True, False))
async def test_response_cleanup_survives_three_cancellations(
    block_body_read,
):
    stream = _BlockingCloseStream(block_body_read=block_body_read)
    borrowed = _RecordingTransport(
        lambda request: httpx.Response(
            200,
            stream=stream,
            request=request,
        )
    )
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()
    task = asyncio.create_task(_request(resource))
    try:
        if block_body_read:
            await _bounded(stream.read_started.wait())
            task.cancel()
            await _bounded(stream.close_started.wait())
        else:
            await _bounded(stream.close_started.wait())
            task.cancel()
        await _next_loop_turn()
        assert task.done() is False
        task.cancel()
        await _next_loop_turn()
        assert task.done() is False
        task.cancel()
        await _next_loop_turn()

        assert task.done() is False
        assert stream.close_calls == 1
        assert resource.active_calls == 1

        stream.close_release.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            await _bounded(task)
    finally:
        stream.read_release.set()
        stream.close_release.set()
        await _cancel_and_reap(task)
        if resource.state != "closed":
            await _bounded(resource.aclose())

    assert caught.value.args == ()
    assert task.cancelled() is True
    assert task.cancelling() == 3
    assert stream.close_completed.is_set()
    assert stream.close_calls == 1
    assert resource.active_calls == 0
    assert resource.cleanup_task_count == 0
@pytest.mark.asyncio
async def test_client_cleanup_survives_three_cancellations(monkeypatch):
    factory = _ClientFactory(close_blocks=True)
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", factory)
    resource = _resource_type()(
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()

    task = asyncio.create_task(resource.aclose())
    try:
        await _bounded(factory.clients[0].close_started.wait())
        for _ in range(3):
            task.cancel()
            await _next_loop_turn()

        assert task.done() is False
        assert factory.clients[0].close_calls == 1

        factory.clients[0].close_release.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            await _bounded(task)
    finally:
        factory.clients[0].close_release.set()
        await _cancel_and_reap(task)

    assert caught.value.args == ()
    assert task.cancelled() is True
    assert task.cancelling() == 3
    assert factory.clients[0].close_completed.is_set()
    assert factory.clients[0].close_calls == 1
    assert resource.state == "closed"
    assert resource.cleanup_task_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("collision", ("api_key", "base_url"))
async def test_complete_request_body_is_scanned_before_network(collision):
    borrowed = _RecordingTransport()
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    provider = _provider()
    await resource.start()

    result = await _request(
        resource,
        provider=provider,
        model_name=str(provider[collision]),
    )
    await resource.aclose()

    assert result.succeeded is False
    assert borrowed.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "runtime_private_material",
    (
        (
            "dsn=mysql://story_user:"
            "RUNTIME_DSN_PASSWORD_SENTINEL@database.internal/novel"
        ),
        "Authorization: Bearer RUNTIME_AUTHORIZATION_TOKEN_SENTINEL",
        "password=RUNTIME_PASSWORD_SENTINEL",
        "credentials: token=RUNTIME_CREDENTIAL_TOKEN_SENTINEL",
    ),
)
async def test_independent_runtime_private_material_is_blocked_before_network(
    runtime_private_material,
):
    borrowed = _RecordingTransport()
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()

    result = await _request(
        resource,
        messages=[
            {
                "role": "user",
                "content": runtime_private_material,
            }
        ],
    )
    await resource.aclose()

    assert result is transport_module.OPENAI_JSON_TRANSPORT_FAILURE
    assert borrowed.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sensitive_key", "runtime_value"),
    (
        ("password", "ARBITRARY_PASSWORD_VALUE_SENTINEL"),
        (
            "CrEdEnTiAlS",
            {"nested": "ARBITRARY_CREDENTIAL_VALUE_SENTINEL"},
        ),
        ("TOKEN", "ARBITRARY_TOKEN_VALUE_SENTINEL"),
        ("Authorization", "ARBITRARY_AUTHORIZATION_VALUE_SENTINEL"),
        ("dSn", ["ARBITRARY_DSN_VALUE_SENTINEL"]),
    ),
)
async def test_decoded_sensitive_message_keys_are_blocked_before_network(
    sensitive_key,
    runtime_value,
):
    borrowed = _RecordingTransport()
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()

    result = await _request(
        resource,
        messages=[
            {
                "role": "user",
                "content": "普通叙事要求",
                sensitive_key: runtime_value,
            }
        ],
    )
    await resource.aclose()

    assert result is transport_module.OPENAI_JSON_TRANSPORT_FAILURE
    assert borrowed.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forbidden_internal_key",
    (
        "rawSourceText",
        "raw_source_payload",
        "corpusText",
        "corpus_fragment",
        "sourceDocumentText",
        "source_document_payload",
        "rawText",
        "document_text",
    ),
)
async def test_nested_forbidden_internal_keys_are_blocked_before_network(
    forbidden_internal_key,
):
    borrowed = _RecordingTransport()
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()

    result = await _request(
        resource,
        messages=[
            {
                "role": "user",
                "content": "普通叙事要求",
                "metadata": {
                    "nested": {
                        forbidden_internal_key: (
                            "INTERNAL_MATERIAL_SENTINEL"
                        )
                    }
                },
            }
        ],
    )
    await resource.aclose()

    assert result is transport_module.OPENAI_JSON_TRANSPORT_FAILURE
    assert borrowed.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forbidden_internal_key",
    (
        "rawSourceText",
        "corpus_fragment",
        "source_document_payload",
        "password",
        "dsn",
    ),
)
@pytest.mark.parametrize(
    "empty_value",
    ("", None, [], {}),
    ids=("empty-string", "none", "empty-list", "empty-mapping"),
)
async def test_forbidden_internal_key_presence_blocks_empty_values(
    forbidden_internal_key,
    empty_value,
):
    borrowed = _RecordingTransport()
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()

    result = await _request(
        resource,
        messages=[
            {
                "role": "user",
                "content": "普通叙事要求",
                "metadata": {
                    "nested": {
                        forbidden_internal_key: empty_value,
                    }
                },
            }
        ],
    )
    await resource.aclose()

    assert result is transport_module.OPENAI_JSON_TRANSPORT_FAILURE
    assert borrowed.calls == []


@pytest.mark.asyncio
async def test_safe_message_keys_and_narrative_token_prose_are_allowed():
    borrowed = _RecordingTransport()
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()

    result = await _request(
        resource,
        messages=[
            {
                "role": "user",
                "content": (
                    "角色把 token 当作通行令牌的英文代号，"
                    "并围绕它设计普通剧情冲突。"
                ),
                "tokenBudget": "控制叙事篇幅",
                "credentialsArc": "角色逐渐赢得众人信任",
                "rawSceneSource": "场景来源是角色回忆",
                "sourceDocumentation": "世界观采用文档体叙事",
                "narrativeText": "这里只包含普通小说文本",
            }
        ],
    )
    await resource.aclose()

    assert result.succeeded is True
    assert len(borrowed.calls) == 1


@pytest.mark.asyncio
async def test_request_body_bytes_are_canonical_and_mapping_order_independent(
    monkeypatch,
):
    scanned_request_bytes: list[bytes] = []
    original_scan = transport_module.provider_response_text_contains_secret

    def capture_raw_scan(value, secrets):
        if isinstance(value, str) and '"model":"planning-model"' in value:
            scanned_request_bytes.append(value.encode("utf-8"))
        return original_scan(value, secrets)

    monkeypatch.setattr(
        transport_module,
        "provider_response_text_contains_secret",
        capture_raw_scan,
    )
    borrowed = _RecordingTransport()
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()
    role_first = {"role": "user", "content": "普通中文叙事"}
    content_first = {"content": "普通中文叙事", "role": "user"}

    first = await _request(resource, messages=[role_first])
    second = await _request(resource, messages=[content_first])
    await resource.aclose()

    expected = json.dumps(
        {
            "model": "planning-model",
            "messages": [role_first],
            "temperature": 0.4,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
            "stream": False,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    sent = [request.content for request in borrowed.calls]

    assert first.succeeded is True
    assert second.succeeded is True
    assert sent == [expected, expected]
    assert scanned_request_bytes == [expected, expected]
    assert all(
        request.headers["content-length"] == str(len(expected))
        for request in borrowed.calls
    )
    assert all(
        request.headers["content-type"] == "application/json"
        for request in borrowed.calls
    )


@pytest.mark.asyncio
async def test_requests_identity_encoding_and_reads_raw_bytes():
    borrowed = _RecordingTransport()
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()

    result = await _request(resource)
    await resource.aclose()

    assert result.succeeded is True
    assert borrowed.calls[0].headers["accept-encoding"] == "identity"


@pytest.mark.asyncio
@pytest.mark.parametrize("content_encoding", ("gzip", "br"))
async def test_nonidentity_encoding_is_rejected_before_raw_iteration(
    content_encoding,
):
    stream = _NeverIteratedStream()
    borrowed = _RecordingTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-encoding": content_encoding},
            stream=stream,
            request=request,
        )
    )
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=131_072,
    )
    await resource.start()

    result = await _request(resource)
    await resource.aclose()

    assert result.succeeded is False
    assert stream.iterated is False
    assert stream.close_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "chunks"),
    (
        ({"content-length": "9"}, [b"{}"]),
        ({}, [b"1234", b"5678", b"9"]),
    ),
)
async def test_declared_and_cumulative_raw_byte_budgets(headers, chunks):
    class ChunkStream(httpx.AsyncByteStream):
        def __init__(self):
            self.close_calls = 0

        async def __aiter__(self):
            for chunk in chunks:
                yield chunk

        async def aclose(self) -> None:
            self.close_calls += 1

    stream = ChunkStream()
    borrowed = _RecordingTransport(
        lambda request: httpx.Response(
            200,
            headers=headers,
            stream=stream,
            request=request,
        )
    )
    resource = _resource_type()(
        transport=borrowed,
        timeout_seconds=120.0,
        response_byte_limit=8,
    )
    await resource.start()

    result = await _request(resource)
    await resource.aclose()

    assert result.succeeded is False
    assert stream.close_calls == 1
    assert resource.active_calls == 0
    assert resource.cleanup_task_count == 0
