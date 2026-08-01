from __future__ import annotations

import gzip
import json

import httpx
import pytest

from backend.gateways.chapter_draft_provider import (
    MAX_CHAPTER_DRAFT_PROVIDER_RESPONSE_BYTES,
    ChapterDraftProviderGateway,
    ChapterDraftProviderResponseError,
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
