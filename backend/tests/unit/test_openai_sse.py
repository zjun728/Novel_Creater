from __future__ import annotations

import json

import pytest

from backend.gateways.openai_sse import OpenAITextSSEParser
from backend.gateways.chapter_draft_provider import ChapterDraftProviderResponseError


def _frame(value: object) -> bytes:
    return b"data: " + json.dumps(value, ensure_ascii=False).encode("utf-8") + b"\n\n"


def _choice(content: object = "text") -> dict[str, object]:
    return {"choices": [{"index": 0, "delta": {"content": content}}]}


def test_parser_handles_utf8_and_crlf_splits_and_multiline_data():
    parser = OpenAITextSSEParser()

    assert parser.feed(b"data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"\xe4") == ()
    assert parser.feed(b"\xbd\xa0\"}}]}\r") == ()
    assert parser.feed(b"\n\r\n") == ("你",)
    assert parser.feed(b": keepalive\n") == ()
    assert parser.feed(b"data: {\"choices\":[{\"index\":0,\n") == ()
    assert parser.feed(
        b"data: \"delta\":{\"content\":\"" + "好".encode("utf-8") + b"\"}}]}\n\n"
    ) == ("好",)
    assert parser.feed(b"data: [DONE]\n\n") == ()
    parser.finish()


def test_parser_accepts_role_and_finish_frames_but_only_text_deltas():
    parser = OpenAITextSSEParser()

    assert parser.feed(_frame({"choices": [{"index": 0, "delta": {"role": "assistant"}}]})) == ()
    assert parser.feed(_frame({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})) == ()
    assert parser.feed(_frame(_choice("正文"))) == ("正文",)
    assert parser.feed(b"data: [DONE]\n\n") == ()
    parser.finish()


@pytest.mark.parametrize(
    "payload",
    (
        {"choices": []},
        {"choices": [{"index": 1, "delta": {"content": "x"}}]},
        {"choices": [{"index": 0, "delta": {"content": "x"}}, {"index": 0, "delta": {"content": "y"}}]},
        {"choices": [{"delta": {"content": "x"}}]},
        {"choices": [{"index": 0, "delta": {"content": ["x"]}}]},
        {"choices": [{"index": 0, "delta": {"content": 1}}]},
    ),
)
def test_parser_rejects_invalid_choice_shapes_and_non_text_content(payload):
    parser = OpenAITextSSEParser()

    with pytest.raises(ChapterDraftProviderResponseError) as caught:
        parser.feed(_frame(payload))

    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "wire",
    (
        b"event: message\ndata: {}\n\n",
        b"id: 1\ndata: {}\n\n",
        b"retry: 10\ndata: {}\n\n",
        b"unknown: nope\n\n",
        b"data: {not-json}\n\n",
        b"data: [DONE]\n\ndata: [DONE]\n\n",
        b"data: [DONE]\n\ndata: {}\n\n",
        b"data: [DONE]\n\n: trailing-comment\n",
        b"data: \xff\n\n",
    ),
)
def test_parser_fails_closed_for_invalid_sse_or_terminal_order(wire):
    parser = OpenAITextSSEParser()

    with pytest.raises(ChapterDraftProviderResponseError) as caught:
        parser.feed(wire)

    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "wire",
    (
        b"data: {\"choices\":[",
        b"data: [DONE]\n",
        b": keepalive\n",
    ),
)
def test_parser_finish_requires_complete_terminal_stream(wire):
    parser = OpenAITextSSEParser()
    parser.feed(wire)

    with pytest.raises(ChapterDraftProviderResponseError) as caught:
        parser.finish()

    assert caught.value.__cause__ is None


def test_parser_rejects_oversized_and_recursively_nested_json():
    parser = OpenAITextSSEParser()
    oversized = b"data: " + b"x" * (64 * 1024 + 1) + b"\n\n"
    with pytest.raises(ChapterDraftProviderResponseError):
        parser.feed(oversized)

    nested = "[" * 300 + "0" + "]" * 300
    parser = OpenAITextSSEParser()
    with pytest.raises(ChapterDraftProviderResponseError):
        parser.feed(b"data: " + nested.encode() + b"\n\n")
