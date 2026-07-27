"""Shared bounded OpenAI-compatible JSON transport with no error leakage."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math

import httpx

from backend.domain.provider_policy import provider_type_is_supported
from backend.prompts.planning import (
    _is_private_manifest_key,
    planning_text_contains_private_material,
)
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    provider_response_text_contains_secret,
    provider_response_value_contains_secret,
    validate_provider_response_text,
)

_ADDITIONAL_PRIVATE_REQUEST_KEYS = frozenset(
    {
        "credential",
        "credentials",
        "dsn",
    }
)


@dataclass(frozen=True, slots=True)
class OpenAIJSONTransportResult:
    """Success value or a content-free failure sentinel."""

    succeeded: bool
    cancelled: bool = False
    value: object | None = None


OPENAI_JSON_TRANSPORT_FAILURE = OpenAIJSONTransportResult(
    succeeded=False,
)
OPENAI_JSON_TRANSPORT_CANCELLED = OpenAIJSONTransportResult(
    succeeded=False,
    cancelled=True,
)

NEW = "new"
STARTING = "starting"
OPEN = "open"
DRAINING = "draining"
CLOSING = "closing"
CLOSED = "closed"
BROKEN = "broken"

_LIFECYCLE_ERROR = "OpenAI JSON transport lifecycle failed"


class OpenAIJSONTransportLifecycleError(RuntimeError):
    """Fixed lifecycle failure with no Provider or cleanup detail."""


def _raise_lifecycle_error() -> None:
    raise OpenAIJSONTransportLifecycleError(_LIFECYCLE_ERROR) from None


def _raise_clean_cancelled_error() -> None:
    raise asyncio.CancelledError()


@dataclass(slots=True)
class _StartGeneration:
    waiters: int = 0
    owners: int = 0


class _MemoryRawStream(httpx.AsyncByteStream):
    def __init__(
        self,
        content: bytes,
        owner: httpx.Response | None = None,
    ):
        self._content = content
        self._owner = owner

    async def __aiter__(self):
        yield self._content

    async def aclose(self) -> None:
        owner = self._owner
        self._owner = None
        self._content = b""
        if owner is not None:
            await owner.aclose()


class _BorrowedAsyncTransport(httpx.AsyncBaseTransport):
    """Delegate requests without taking ownership of transport lifecycle."""

    def __init__(self, transport: httpx.AsyncBaseTransport):
        self._transport = transport

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        response = await self._transport.handle_async_request(request)
        if not response.is_stream_consumed:
            return response
        content = response.content
        status_code = response.status_code
        headers = response.headers
        extensions = response.extensions
        return httpx.Response(
            status_code,
            headers=headers,
            stream=_MemoryRawStream(content, response),
            extensions=extensions,
            request=request,
        )

    async def aclose(self) -> None:
        return None


async def _settle_independent_task(
    task: asyncio.Task,
    *,
    initial_cancellation_observed: int = 0,
) -> tuple[object, asyncio.Task | None, int]:
    """Await one cleanup task to terminal despite repeated cancellation."""

    current = asyncio.current_task()
    observed = initial_cancellation_observed
    if current is not None:
        for _ in range(initial_cancellation_observed):
            current.uncancel()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if current is None:
                continue
            if current.cancelling() == 0:
                continue
            current.uncancel()
            observed += 1
    return task.result(), current, observed


def _restore_cancellations(
    current: asyncio.Task | None,
    observed: int,
) -> None:
    if current is None:
        return
    for _ in range(observed):
        current.cancel()


async def _defer_response_close() -> None:
    """No-op used while raw iteration is owned by a call finalizer."""

    return None


def _is_private_request_key(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = "".join(
        character
        for character in value.casefold()
        if character.isalnum()
    )
    return (
        _is_private_manifest_key(value)
        or normalized in _ADDITIONAL_PRIVATE_REQUEST_KEYS
    )


def _request_value_contains_private_material(value: object) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if planning_text_contains_private_material(item):
                return True
        elif isinstance(item, Mapping):
            for key, nested in item.items():
                if _is_private_request_key(key):
                    return True
                pending.append(key)
                pending.append(nested)
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return False


class OpenAIJSONTransport:
    """Lifespan-owned bounded OpenAI-compatible JSON transport."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: int | float,
        response_byte_limit: int,
    ):
        timeout_value = float(timeout_seconds)
        if (
            not math.isfinite(timeout_value)
            or timeout_value <= 0
            or type(response_byte_limit) is not int
            or response_byte_limit <= 0
        ):
            raise ValueError("invalid transport limits")
        self._borrowed_transport = transport
        self._timeout_seconds = timeout_value
        self._response_byte_limit = response_byte_limit
        self._state = NEW
        self._client: httpx.AsyncClient | None = None
        self._active_calls = 0
        self._lock = asyncio.Lock()
        self._drain = asyncio.Condition(self._lock)
        self._start_task: asyncio.Task | None = None
        self._start_generation: _StartGeneration | None = None
        self._close_task: asyncio.Task | None = None
        self._cleanup_tasks: set[asyncio.Task] = set()

    @property
    def state(self) -> str:
        return self._state

    @property
    def active_calls(self) -> int:
        return self._active_calls

    @property
    def cleanup_task_count(self) -> int:
        return len(self._cleanup_tasks)

    def _register_cleanup(
        self,
        coroutine,
        *,
        name: str,
    ) -> asyncio.Task:
        cleanup = asyncio.create_task(coroutine, name=name)
        self._cleanup_tasks.add(cleanup)
        cleanup.add_done_callback(self._cleanup_tasks.discard)
        return cleanup

    async def _start_lifecycle(self) -> bool:
        client = None
        succeeded = False
        try:
            client_transport = (
                _BorrowedAsyncTransport(self._borrowed_transport)
                if self._borrowed_transport is not None
                else None
            )
            client = httpx.AsyncClient(
                transport=client_transport,
                timeout=httpx.Timeout(
                    connect=15,
                    read=self._timeout_seconds,
                    write=30,
                    pool=15,
                ),
            )
            succeeded = True
        except BaseException:
            client = None

        async with self._lock:
            if succeeded:
                self._client = client
                self._state = OPEN
            else:
                self._client = None
                self._borrowed_transport = None
                self._start_generation = None
                self._state = BROKEN
            if self._start_task is asyncio.current_task():
                self._start_task = None
        client = None
        return succeeded

    async def start(self) -> None:
        while True:
            wait_for_close = False
            generation = None
            async with self._lock:
                if self._close_task is not None:
                    lifecycle = self._close_task
                    wait_for_close = True
                elif self._state == OPEN:
                    generation = self._start_generation
                    if generation is None:
                        lifecycle = None
                    else:
                        generation.owners += 1
                        return
                elif self._state == STARTING:
                    generation = self._start_generation
                    lifecycle = self._start_task
                    if generation is not None:
                        generation.waiters += 1
                elif self._state in (NEW, CLOSED):
                    generation = _StartGeneration(waiters=1)
                    self._start_generation = generation
                    self._state = STARTING
                    lifecycle = asyncio.create_task(
                        self._start_lifecycle(),
                        name="openai-json-transport-start",
                    )
                    self._start_task = lifecycle
                elif self._state in (DRAINING, CLOSING):
                    lifecycle = self._close_task
                    wait_for_close = True
                else:
                    lifecycle = None

            if lifecycle is None or (
                not wait_for_close and generation is None
            ):
                self = None
                generation = None
                lifecycle = None
                _raise_lifecycle_error()
            if wait_for_close:
                cancelled_while_waiting_for_close = False
                try:
                    await asyncio.shield(lifecycle)
                except asyncio.CancelledError:
                    cancelled_while_waiting_for_close = True
                except BaseException:
                    pass
                if cancelled_while_waiting_for_close:
                    self = None
                    generation = None
                    lifecycle = None
                    _raise_clean_cancelled_error()
                continue

            try:
                succeeded = await asyncio.shield(lifecycle)
            except asyncio.CancelledError:
                finish = asyncio.create_task(
                    self._finish_start_intent(
                        generation,
                        lifecycle,
                        claim_owner=False,
                        rollback_if_last=True,
                    ),
                    name="openai-json-transport-start-cancel",
                )
                _finished, current, observed = (
                    await _settle_independent_task(
                        finish,
                        initial_cancellation_observed=1,
                    )
                )
                finish = None
                generation = None
                lifecycle = None
                _restore_cancellations(current, observed)
                current = None
                return
            except BaseException:
                succeeded = False

            finish = asyncio.create_task(
                self._finish_start_intent(
                    generation,
                    lifecycle,
                    claim_owner=bool(succeeded),
                    rollback_if_last=False,
                ),
                name="openai-json-transport-start-finish",
            )
            _finished, current, observed = await _settle_independent_task(
                finish
            )
            finish = None
            if observed:
                rollback = asyncio.create_task(
                    self._rollback_unowned_start(
                        generation,
                        lifecycle,
                        relinquish_owner=bool(succeeded),
                    ),
                    name="openai-json-transport-start-rollback",
                )
                _rolled_back, _current, additional_observed = (
                    await _settle_independent_task(rollback)
                )
                rollback = None
                generation = None
                lifecycle = None
                _restore_cancellations(
                    current,
                    observed + additional_observed,
                )
                current = None
                return
            current = None
            generation = None
            lifecycle = None
            if not succeeded:
                self = None
                _raise_lifecycle_error()
            return

    def _ensure_close_intent_locked(
        self,
        start_lifecycle: asyncio.Task | None = None,
    ) -> asyncio.Task | None:
        if self._close_task is not None:
            return self._close_task
        if self._state == STARTING and start_lifecycle is not None:
            lifecycle = asyncio.create_task(
                self._close_after_start(start_lifecycle),
                name="openai-json-transport-close",
            )
            self._close_task = lifecycle
            return lifecycle
        if self._state == OPEN:
            self._state = DRAINING
            lifecycle = asyncio.create_task(
                self._close_lifecycle(),
                name="openai-json-transport-close",
            )
            self._close_task = lifecycle
            return lifecycle
        return self._close_task

    async def _finish_start_intent(
        self,
        generation: _StartGeneration,
        start_lifecycle: asyncio.Task,
        *,
        claim_owner: bool,
        rollback_if_last: bool,
    ) -> bool:
        rollback = None
        async with self._lock:
            generation.waiters -= 1
            if claim_owner:
                generation.owners += 1
            if (
                rollback_if_last
                and generation is self._start_generation
                and generation.waiters == 0
                and generation.owners == 0
            ):
                rollback = self._ensure_close_intent_locked(
                    start_lifecycle
                )
        start_lifecycle = None
        if rollback is None:
            return True
        try:
            return bool(await asyncio.shield(rollback))
        except BaseException:
            return False

    async def _rollback_unowned_start(
        self,
        generation: _StartGeneration,
        start_lifecycle: asyncio.Task,
        *,
        relinquish_owner: bool,
    ) -> bool:
        rollback = None
        async with self._lock:
            if relinquish_owner:
                generation.owners -= 1
            if (
                generation is self._start_generation
                and generation.waiters == 0
                and generation.owners == 0
            ):
                rollback = self._ensure_close_intent_locked(
                    start_lifecycle
                )
        start_lifecycle = None
        if rollback is None:
            return True
        try:
            return bool(await asyncio.shield(rollback))
        except BaseException:
            return False

    async def _close_client(self, client: httpx.AsyncClient) -> bool:
        succeeded = False
        try:
            await client.aclose()
            succeeded = True
        except BaseException:
            succeeded = False
        finally:
            client = None
        return succeeded

    async def _close_lifecycle(self) -> bool:
        client = None
        cleanup = None
        async with self._drain:
            while self._active_calls:
                await self._drain.wait()
            self._state = CLOSING
            client = self._client
            self._client = None

        if client is None:
            succeeded = True
        else:
            cleanup = self._register_cleanup(
                self._close_client(client),
                name="openai-json-transport-client-close",
            )
            succeeded, _current, _observed = (
                await _settle_independent_task(cleanup)
            )
            self._cleanup_tasks.discard(cleanup)
            cleanup = None
        client = None

        async with self._lock:
            if succeeded:
                self._state = CLOSED
            else:
                self._borrowed_transport = None
                self._state = BROKEN
            self._start_generation = None
            if self._close_task is asyncio.current_task():
                self._close_task = None
        return bool(succeeded)

    async def _close_after_start(
        self,
        start_lifecycle: asyncio.Task,
    ) -> bool:
        try:
            started = bool(await asyncio.shield(start_lifecycle))
        except BaseException:
            started = False
        start_lifecycle = None
        if not started:
            async with self._lock:
                self._borrowed_transport = None
                self._state = BROKEN
                self._start_generation = None
                if self._close_task is asyncio.current_task():
                    self._close_task = None
            return False

        async with self._lock:
            if self._state == OPEN:
                self._state = DRAINING
            elif self._state == CLOSED:
                if self._close_task is asyncio.current_task():
                    self._close_task = None
                return True
            elif self._state == BROKEN:
                if self._close_task is asyncio.current_task():
                    self._close_task = None
                return False
        return await self._close_lifecycle()

    async def aclose(self) -> None:
        while True:
            async with self._lock:
                if self._state == NEW:
                    self._state = CLOSED
                    self._start_generation = None
                    return
                if self._state == CLOSED:
                    return
                if self._close_task is not None:
                    lifecycle = self._close_task
                elif self._state == STARTING:
                    lifecycle = self._ensure_close_intent_locked(
                        self._start_task
                    )
                elif self._state == OPEN:
                    lifecycle = self._ensure_close_intent_locked()
                elif self._state in (DRAINING, CLOSING):
                    lifecycle = self._close_task
                else:
                    lifecycle = None

            if lifecycle is None:
                self = None
                lifecycle = None
                _raise_lifecycle_error()

            succeeded, current, observed = await _settle_independent_task(
                lifecycle
            )
            async with self._lock:
                if self._close_task is lifecycle:
                    self._close_task = None
            lifecycle = None
            if observed:
                _restore_cancellations(current, observed)
                current = None
                return
            current = None
            if not succeeded:
                self = None
                _raise_lifecycle_error()
            return

    async def _finalize_call(
        self,
        response: httpx.Response | None,
        client: httpx.AsyncClient,
    ) -> bool:
        succeeded = True
        try:
            if response is not None:
                await response.aclose()
        except BaseException:
            succeeded = False
        finally:
            response = None
            client = None
            async with self._drain:
                self._active_calls -= 1
                if self._active_calls == 0:
                    self._drain.notify_all()
        return succeeded

    async def _admit(self) -> httpx.AsyncClient | None:
        async with self._lock:
            if (
                self._state != OPEN
                or self._client is None
                or self._close_task is not None
            ):
                return None
            client = self._client
            self._active_calls += 1
            return client

    async def request(
        self,
        *,
        provider: Mapping[str, object],
        model_name: str,
        messages: Sequence[Mapping[str, str]],
    ) -> OpenAIJSONTransportResult:
        """Make one admitted bounded call and return no sensitive errors."""

        try:
            client = await self._admit()
        except asyncio.CancelledError:
            provider = None
            model_name = None
            messages = ()
            return OPENAI_JSON_TRANSPORT_CANCELLED
        if client is None:
            return OPENAI_JSON_TRANSPORT_FAILURE

        result = OPENAI_JSON_TRANSPORT_FAILURE
        cancelled = False
        response = None
        response_close = None
        cleanup = None
        current = None
        observed = 0
        close_succeeded = True
        initial_cancellation_observed = 0
        base_url = None
        api_key = None
        temperature = None
        max_output_value = None
        max_output_tokens = None
        endpoint = None
        authorization = None
        request_body = None
        rendered_request_body = None
        request_body_bytes = None
        secrets = ()
        request = None
        response_bytes = bytearray()
        content_encoding = None
        declared = None
        declared_size = None
        chunk = None
        remaining = None
        response_text = None
        envelope = None
        content = None
        decoded_value = None
        try:
            if not provider_type_is_supported(provider.get("provider_type")):
                raise ValueError("invalid runtime")
            if not isinstance(model_name, str) or not model_name.strip():
                raise ValueError("invalid runtime")
            base_url = provider["base_url"]
            api_key = provider["api_key"]
            if not isinstance(base_url, str) or not base_url.strip():
                raise ValueError("invalid runtime")
            if not isinstance(api_key, str) or not api_key.strip():
                raise ValueError("invalid runtime")
            temperature = float(provider["temperature"])
            max_output_value = provider.get("max_output_tokens")
            if max_output_value is None:
                max_output_value = provider["maxOutputTokens"]
            max_output_tokens = int(max_output_value)
            if (
                not math.isfinite(temperature)
                or temperature < 0
                or max_output_tokens <= 0
            ):
                raise ValueError("invalid runtime")

            endpoint = openai_chat_completions_endpoint(base_url.strip())
            authorization = f"Bearer {api_key.strip()}"
            secrets = normalize_provider_secrets((api_key, base_url))
            request_body = {
                "model": model_name.strip(),
                "messages": list(messages),
                "temperature": temperature,
                "max_tokens": max_output_tokens,
                "response_format": {"type": "json_object"},
                "stream": False,
            }
            rendered_request_body = json.dumps(
                request_body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            request_body_bytes = rendered_request_body.encode("utf-8")
            if (
                provider_response_text_contains_secret(
                    rendered_request_body,
                    secrets,
                )
                or provider_response_value_contains_secret(
                    request_body,
                    secrets,
                )
                or planning_text_contains_private_material(
                    rendered_request_body
                )
                or _request_value_contains_private_material(request_body)
            ):
                raise ValueError("unsafe request")

            request = client.build_request(
                "POST",
                endpoint,
                headers={
                    "Authorization": authorization,
                    "Accept-Encoding": "identity",
                    "Content-Type": "application/json",
                },
                content=request_body_bytes,
            )
            async with asyncio.timeout(self._timeout_seconds):
                response = await client.send(request, stream=True)
                if not response.is_success:
                    raise ValueError("remote failure")
                content_encoding = response.headers.get(
                    "content-encoding",
                    "",
                ).strip()
                if (
                    content_encoding
                    and content_encoding.casefold() != "identity"
                ):
                    raise ValueError("encoded response is forbidden")
                declared = response.headers.get("content-length")
                if declared is not None:
                    declared_size = int(declared)
                    if (
                        declared_size < 0
                        or declared_size > self._response_byte_limit
                    ):
                        raise ValueError("response too large")
                response_close = response.aclose
                response.aclose = _defer_response_close
                try:
                    async for chunk in response.aiter_raw():
                        remaining = (
                            self._response_byte_limit
                            + 1
                            - len(response_bytes)
                        )
                        if remaining > 0:
                            response_bytes.extend(chunk[:remaining])
                        if (
                            len(response_bytes)
                            > self._response_byte_limit
                            or len(chunk) > remaining
                        ):
                            raise ValueError("response too large")
                finally:
                    response.aclose = response_close
                    response_close = None

            response_text = bytes(response_bytes).decode("utf-8")
            if provider_response_text_contains_secret(
                response_text,
                secrets,
            ):
                raise ValueError("unsafe response")
            envelope = json.loads(response_text)
            if provider_response_value_contains_secret(envelope, secrets):
                raise ValueError("unsafe response")
            content = validate_provider_response_text(
                envelope["choices"][0]["message"]["content"],
                strip=True,
            )
            if provider_response_text_contains_secret(content, secrets):
                raise ValueError("unsafe response")
            decoded_value = json.loads(content)
            if provider_response_value_contains_secret(
                decoded_value,
                secrets,
            ):
                raise ValueError("unsafe response")
            result = OpenAIJSONTransportResult(
                succeeded=True,
                value=decoded_value,
            )
        except asyncio.CancelledError:
            cancelled = True
            initial_cancellation_observed = 1
            result = OPENAI_JSON_TRANSPORT_CANCELLED
        except Exception:
            result = OPENAI_JSON_TRANSPORT_FAILURE
        finally:
            cleanup = self._register_cleanup(
                self._finalize_call(response, client),
                name="openai-json-transport-response-close",
            )
            close_succeeded, current, observed = (
                await _settle_independent_task(
                    cleanup,
                    initial_cancellation_observed=(
                        initial_cancellation_observed
                    ),
                )
            )
            self._cleanup_tasks.discard(cleanup)
            response_bytes.clear()
            provider = None
            model_name = None
            messages = ()
            client = None
            response = None
            response_close = None
            cleanup = None
            base_url = None
            api_key = None
            temperature = None
            max_output_value = None
            max_output_tokens = None
            endpoint = None
            authorization = None
            request_body = None
            rendered_request_body = None
            request_body_bytes = None
            secrets = ()
            request = None
            response_bytes = None
            content_encoding = None
            declared = None
            declared_size = None
            chunk = None
            remaining = None
            response_text = None
            envelope = None
            content = None
            decoded_value = None
            initial_cancellation_observed = 0
            if observed:
                cancelled = True
                result = OPENAI_JSON_TRANSPORT_CANCELLED
            elif not close_succeeded:
                result = OPENAI_JSON_TRANSPORT_FAILURE
            if observed:
                _restore_cancellations(current, observed)
            current = None

        return result


def openai_chat_completions_endpoint(base_url: str) -> str:
    """Validate and join an OpenAI-compatible chat-completions endpoint."""

    parsed = httpx.URL(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise ValueError("OpenAI-compatible endpoint is invalid")
    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions"
    return str(parsed.copy_with(path=path))


async def request_openai_json(
    *,
    provider: Mapping[str, object],
    model_name: str,
    messages: Sequence[Mapping[str, str]],
    transport: httpx.AsyncBaseTransport | None,
    timeout_seconds: int | float,
    max_response_bytes: int,
) -> OpenAIJSONTransportResult:
    """Make one bounded call and return decoded JSON or a safe failure."""

    result = OPENAI_JSON_TRANSPORT_FAILURE
    decoded_value: object | None = None
    base_url = None
    api_key = None
    temperature = None
    max_output_value = None
    max_output_tokens = None
    timeout_value = None
    endpoint = None
    authorization = None
    request_body = None
    rendered_request_body = None
    secrets = ()
    client_transport = None
    client = None
    response = None
    response_bytes = bytearray()
    content_encoding = None
    declared = None
    declared_size = None
    chunk = None
    remaining = None
    response_text = None
    envelope = None
    content = None
    try:
        if not provider_type_is_supported(provider.get("provider_type")):
            raise ValueError("invalid runtime")
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("invalid runtime")
        base_url = provider["base_url"]
        api_key = provider["api_key"]
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("invalid runtime")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("invalid runtime")
        temperature = float(provider["temperature"])
        max_output_value = provider.get("max_output_tokens")
        if max_output_value is None:
            max_output_value = provider["maxOutputTokens"]
        max_output_tokens = int(max_output_value)
        timeout_value = float(timeout_seconds)
        if (
            not math.isfinite(temperature)
            or temperature < 0
            or max_output_tokens <= 0
            or not math.isfinite(timeout_value)
            or timeout_value <= 0
            or type(max_response_bytes) is not int
            or max_response_bytes <= 0
        ):
            raise ValueError("invalid runtime")

        endpoint = openai_chat_completions_endpoint(base_url.strip())
        authorization = f"Bearer {api_key.strip()}"
        secrets = normalize_provider_secrets((api_key, base_url))
        request_body = {
            "model": model_name.strip(),
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        rendered_request_body = json.dumps(
            request_body,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        if (
            provider_response_text_contains_secret(
                rendered_request_body,
                secrets,
            )
            or provider_response_value_contains_secret(
                request_body,
                secrets,
            )
        ):
            raise ValueError("unsafe request")
        client_transport = (
            _BorrowedAsyncTransport(transport)
            if transport is not None
            else None
        )

        async with asyncio.timeout(timeout_value):
            async with httpx.AsyncClient(
                transport=client_transport,
                timeout=httpx.Timeout(
                    connect=15,
                    read=timeout_value,
                    write=30,
                    pool=15,
                ),
            ) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    headers={
                        "Authorization": authorization,
                        "Accept-Encoding": "identity",
                    },
                    json=request_body,
                ) as response:
                    if not response.is_success:
                        raise ValueError("remote failure")
                    content_encoding = response.headers.get(
                        "content-encoding",
                        "",
                    ).strip()
                    if (
                        content_encoding
                        and content_encoding.casefold() != "identity"
                    ):
                        raise ValueError("encoded response is forbidden")
                    declared = response.headers.get("content-length")
                    if declared is not None:
                        declared_size = int(declared)
                        if (
                            declared_size < 0
                            or declared_size > max_response_bytes
                        ):
                            raise ValueError("response too large")
                    async for chunk in response.aiter_raw():
                        remaining = (
                            max_response_bytes + 1 - len(response_bytes)
                        )
                        if remaining > 0:
                            response_bytes.extend(chunk[:remaining])
                        if (
                            len(response_bytes) > max_response_bytes
                            or len(chunk) > remaining
                        ):
                            raise ValueError("response too large")

        response_text = bytes(response_bytes).decode("utf-8")
        if provider_response_text_contains_secret(response_text, secrets):
            raise ValueError("unsafe response")
        envelope = json.loads(response_text)
        if provider_response_value_contains_secret(envelope, secrets):
            raise ValueError("unsafe response")
        content = validate_provider_response_text(
            envelope["choices"][0]["message"]["content"],
            strip=True,
        )
        if provider_response_text_contains_secret(content, secrets):
            raise ValueError("unsafe response")
        decoded_value = json.loads(content)
        if provider_response_value_contains_secret(
            decoded_value,
            secrets,
        ):
            raise ValueError("unsafe response")
        result = OpenAIJSONTransportResult(
            succeeded=True,
            value=decoded_value,
        )
    except asyncio.CancelledError:
        result = OPENAI_JSON_TRANSPORT_CANCELLED
    except Exception:
        result = OPENAI_JSON_TRANSPORT_FAILURE
    finally:
        response_bytes.clear()
        provider = None
        model_name = None
        messages = ()
        transport = None
        base_url = None
        api_key = None
        temperature = None
        max_output_value = None
        max_output_tokens = None
        timeout_value = None
        endpoint = None
        authorization = None
        request_body = None
        rendered_request_body = None
        secrets = ()
        client_transport = None
        client = None
        response = None
        response_bytes = None
        content_encoding = None
        declared = None
        declared_size = None
        chunk = None
        remaining = None
        response_text = None
        envelope = None
        content = None
        decoded_value = None

    return result


__all__ = (
    "BROKEN",
    "CLOSED",
    "CLOSING",
    "DRAINING",
    "NEW",
    "OPEN",
    "OPENAI_JSON_TRANSPORT_CANCELLED",
    "OPENAI_JSON_TRANSPORT_FAILURE",
    "STARTING",
    "OpenAIJSONTransport",
    "OpenAIJSONTransportLifecycleError",
    "OpenAIJSONTransportResult",
    "openai_chat_completions_endpoint",
    "request_openai_json",
)
