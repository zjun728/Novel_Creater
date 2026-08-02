from __future__ import annotations

import asyncio
import gzip
import json

import httpx
import pytest

from backend.gateways.chapter_draft_provider import (
    MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES,
    ChapterDraftProviderGateway,
    ChapterDraftProviderHTTPError,
    ChapterDraftProviderResponseError,
    ChapterDraftProviderTransportError,
)


def _provider():
    return {
        "model_name": "fake-model",
        "base_url": "https://provider.invalid/v1",
        "api_key": "PRIVATE_PROVIDER_KEY",
    }


async def _generate(gateway):
    return await gateway.generate(
        provider=_provider(),
        messages=({"role": "user", "content": "facts"},),
        generation_config={"temperature": 0.2, "maxOutputTokens": 4500},
    )


async def _stream(gateway):
    values = []
    async for value in gateway.stream(
        provider=_provider(),
        messages=({"role": "user", "content": "facts"},),
        generation_config={"temperature": 0.2, "maxOutputTokens": 4500},
    ):
        values.append(value)
    return values


class GuardedOversizedStream(httpx.AsyncByteStream):
    def __init__(self):
        self.yields = 0
        self.read_past_limit = False

    async def __aiter__(self):
        self.yields += 1
        yield b"x" * MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES
        self.yields += 1
        yield b"x"
        self.read_past_limit = True
        yield b"REMOTE-BODY-MUST-NOT-BE-READ"


class StaticStream(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content = content

    async def __aiter__(self):
        yield self.content


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.iterated = False
        self.close_calls = 0

    async def __aiter__(self):
        self.iterated = True
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.close_calls += 1


@pytest.mark.asyncio
async def test_stream_sends_exact_sse_request_and_yields_text_from_raw_bytes():
    requests = []
    stream = ChunkStream(
        [
            b'data: {"choices":[{"index":0,"delta":{"content":"one"}}]}\n\n',
            b'data: {"choices":[{"index":0,"delta":{"content":" two"}}]}\n\n',
            b"data: [DONE]\n\n",
        ]
    )

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    gateway = ChapterDraftProviderGateway(transport=httpx.MockTransport(handler))
    assert await _stream(gateway) == ["one", " two"]
    assert json.loads(requests[0].content)["stream"] is True
    assert requests[0].headers["accept"] == "text/event-stream"
    assert requests[0].headers["accept-encoding"] == "identity"
    assert stream.iterated is True
    assert stream.close_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    (
        {},
        {"content-type": "application/json"},
        {"content-type": "text/event-stream; charset=utf-8"},
        [(b"content-type", b"text/event-stream"), (b"content-type", b"text/event-stream")],
        {"content-type": "text/event-stream, application/json"},
        {"content-type": "text/event-stream", "content-encoding": "gzip"},
        {"content-type": "text/event-stream", "content-encoding": "identity, gzip"},
        [(b"content-type", b"text/event-stream"), (b"content-encoding", b"identity"), (b"content-encoding", b"identity")],
    ),
)
async def test_stream_rejects_invalid_representation_before_iterating_body(headers):
    stream = ChunkStream([b"REMOTE-BODY-MUST-NOT-BE-READ"])
    gateway = ChapterDraftProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers=headers, stream=stream)
        )
    )

    with pytest.raises(ChapterDraftProviderResponseError) as caught:
        await _stream(gateway)

    assert stream.iterated is False
    assert caught.value.__cause__ is None
    assert "REMOTE-BODY-MUST-NOT-BE-READ" not in repr(caught.value)


@pytest.mark.asyncio
async def test_stream_enforces_declared_and_raw_wire_byte_limits():
    declared_stream = ChunkStream([b"REMOTE-BODY-MUST-NOT-BE-READ"])
    gateway = ChapterDraftProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={
                    "content-type": "text/event-stream",
                    "content-length": str(MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES + 1),
                },
                stream=declared_stream,
            )
        )
    )
    with pytest.raises(ChapterDraftProviderResponseError):
        await _stream(gateway)
    assert declared_stream.iterated is False

    overflow_stream = ChunkStream(
        [b"x" * MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES, b"x"]
    )
    gateway = ChapterDraftProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=overflow_stream,
            )
        )
    )
    with pytest.raises(ChapterDraftProviderResponseError):
        await _stream(gateway)
    assert overflow_stream.iterated is True


@pytest.mark.asyncio
async def test_stream_cancellation_closes_response_and_reraises_cancellation():
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingStream(ChunkStream):
        async def __aiter__(self):
            self.iterated = True
            entered.set()
            await release.wait()
            yield b"data: [DONE]\n\n"

    stream = BlockingStream([])
    gateway = ChapterDraftProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=stream
            )
        )
    )
    task = asyncio.create_task(_stream(gateway))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.close_calls == 1


@pytest.mark.asyncio
async def test_stream_uses_one_absolute_1200_second_deadline(monkeypatch):
    import backend.gateways.chapter_draft_provider as provider_module

    recorded = []
    original_timeout_at = asyncio.timeout_at

    def capture_timeout_at(when):
        recorded.append(when)
        return original_timeout_at(when)

    monkeypatch.setattr(provider_module.asyncio, "timeout_at", capture_timeout_at)
    gateway = ChapterDraftProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=ChunkStream([b"data: [DONE]\n\n"]),
            )
        )
    )

    assert await _stream(gateway) == []
    assert len(recorded) == 1
    assert 1_199.0 < recorded[0] - asyncio.get_running_loop().time() < 1_200.1


@pytest.mark.asyncio
async def test_stream_maps_remote_failures_to_safe_existing_gateway_errors():
    secret = "mysql://user:REMOTE_PASSWORD@provider.invalid/database"
    gateway = ChapterDraftProviderGateway(
        transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError(secret)))
    )
    with pytest.raises(ChapterDraftProviderTransportError) as transport_error:
        await _stream(gateway)

    gateway = ChapterDraftProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, content=secret.encode())
        )
    )
    with pytest.raises(ChapterDraftProviderHTTPError) as http_error:
        await _stream(gateway)

    for error in (transport_error.value, http_error.value):
        assert error.__cause__ is None
        assert secret not in repr(error)


@pytest.mark.asyncio
async def test_gateway_stops_chunked_response_immediately_after_byte_ceiling():
    stream = GuardedOversizedStream()
    gateway = ChapterDraftProviderGateway(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, stream=stream)
        )
    )

    with pytest.raises(ChapterDraftProviderResponseError) as caught:
        await _generate(gateway)

    assert stream.yields == 2
    assert stream.read_past_limit is False
    assert "REMOTE-BODY-MUST-NOT-BE-READ" not in repr(caught.value)


@pytest.mark.asyncio
async def test_gateway_rejects_declared_oversize_without_reading_body():
    class UnreadStream(httpx.AsyncByteStream):
        def __init__(self):
            self.read = False

        async def __aiter__(self):
            self.read = True
            yield b"REMOTE-BODY-MUST-NOT-BE-READ"

    stream = UnreadStream()
    gateway = ChapterDraftProviderGateway(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={
                    "content-length": str(
                        MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES + 1
                    )
                },
                stream=stream,
            )
        )
    )

    with pytest.raises(ChapterDraftProviderResponseError) as caught:
        await _generate(gateway)

    assert stream.read is False
    assert "REMOTE-BODY-MUST-NOT-BE-READ" not in repr(caught.value)


@pytest.mark.asyncio
async def test_gateway_allows_maximum_astral_chapter_inside_bounded_envelope():
    content = "😀" * 100_000
    envelope = json.dumps(
        {"choices": [{"message": {"content": content}}]},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert len(envelope) < MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES
    gateway = ChapterDraftProviderGateway(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, stream=StaticStream(envelope))
        )
    )

    assert await _generate(gateway) == content


@pytest.mark.asyncio
async def test_gateway_rejects_gzip_before_decoding_or_reading_remote_body():
    decoded = b"REMOTE-BODY-MUST-NOT-BE-DECODED" + (
        b"x" * (MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES * 2)
    )
    compressed = gzip.compress(decoded)
    assert len(compressed) < 4_096

    class UnreadCompressedStream(httpx.AsyncByteStream):
        def __init__(self):
            self.read = False

        async def __aiter__(self):
            self.read = True
            yield compressed

    stream = UnreadCompressedStream()
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={
                "content-encoding": "gzip",
                "content-length": str(len(compressed)),
            },
            stream=stream,
        )

    gateway = ChapterDraftProviderGateway(transport=httpx.MockTransport(handler))

    with pytest.raises(ChapterDraftProviderResponseError) as caught:
        await _generate(gateway)

    assert requests[0].headers["accept-encoding"] == "identity"
    assert stream.read is False
    assert caught.value.__cause__ is None
    assert "REMOTE-BODY-MUST-NOT-BE-DECODED" not in repr(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_headers",
    [
        [],
        [(b"content-encoding", b"identity")],
        [(b"content-encoding", b" Identity ")],
    ],
)
async def test_gateway_accepts_only_absent_or_single_identity_encoding(
    response_headers,
):
    content = "合法正文"
    envelope = json.dumps(
        {"choices": [{"message": {"content": content}}]},
        ensure_ascii=False,
    ).encode("utf-8")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers=response_headers,
            stream=StaticStream(envelope),
        )

    gateway = ChapterDraftProviderGateway(transport=httpx.MockTransport(handler))

    assert await _generate(gateway) == content
    assert requests[0].headers["accept-encoding"] == "identity"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_headers",
    [
        [(b"content-encoding", b"gzip")],
        [(b"content-encoding", b"br")],
        [(b"content-encoding", b"identity, gzip")],
        [
            (b"content-encoding", b"identity"),
            (b"content-encoding", b"identity"),
        ],
    ],
)
async def test_gateway_rejects_unknown_listed_or_repeated_content_encoding(
    response_headers,
):
    class UnreadStream(httpx.AsyncByteStream):
        def __init__(self):
            self.read = False

        async def __aiter__(self):
            self.read = True
            yield b"REMOTE-BODY-MUST-NOT-BE-READ"

    stream = UnreadStream()
    gateway = ChapterDraftProviderGateway(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers=response_headers,
                stream=stream,
            )
        )
    )

    with pytest.raises(ChapterDraftProviderResponseError) as caught:
        await _generate(gateway)

    assert stream.read is False
    assert caught.value.__cause__ is None
    assert "REMOTE-BODY-MUST-NOT-BE-READ" not in repr(caught.value)
