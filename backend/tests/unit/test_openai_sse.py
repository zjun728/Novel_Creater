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


@pytest.mark.parametrize("prefix", (b"data:\n", b": comment\n"))
def test_parser_bounds_empty_data_and_comment_lines_before_event_boundary(prefix):
    parser = OpenAITextSSEParser()

    with pytest.raises(ChapterDraftProviderResponseError):
        parser.feed(prefix * 1_025)


def test_parser_resets_framing_counters_at_each_event_boundary():
    parser = OpenAITextSSEParser()
    comments = b": c\n" * 1_024 + b"\n"

    assert parser.feed(comments) == ()
    assert parser.feed(comments) == ()
    assert parser.feed(b"data: [DONE]\n\n") == ()
    parser.finish()


def test_parser_handles_a_long_line_split_into_single_byte_chunks():
    content = "x" * 32_000
    wire = _frame(_choice(content))
    parser = OpenAITextSSEParser()
    emitted = []

    for value in wire:
        emitted.extend(parser.feed(bytes((value,))))
    parser.feed(b"data: [DONE]\n\n")
    parser.finish()

    assert emitted == [content]


@pytest.mark.parametrize(
    ("root_updates", "choice_updates", "delta_updates"),
    (
        ({}, {}, {"role": 7}),
        ({}, {}, {"role": "user"}),
        ({}, {"finish_reason": {}}, {}),
        ({}, {"logprobs": "invalid"}, {}),
        ({"id": 1}, {}, {}),
        ({"object": []}, {}, {}),
        ({"model": {}}, {}, {}),
        ({"created": True}, {}, {}),
        ({"created": "1"}, {}, {}),
        ({"system_fingerprint": 1}, {}, {}),
        ({"service_tier": []}, {}, {}),
        ({"usage": {}}, {}, {}),
    ),
)
def test_parser_type_closes_every_admitted_json_sibling(
    root_updates, choice_updates, delta_updates
):
    payload = _choice(None)
    payload.update(root_updates)
    payload["choices"][0].update(choice_updates)
    payload["choices"][0]["delta"].update(delta_updates)
    parser = OpenAITextSSEParser()

    with pytest.raises(ChapterDraftProviderResponseError):
        parser.feed(_frame(payload))


@pytest.mark.parametrize(
    "finish_reason",
    (None, "stop", "length", "content_filter", "tool_calls", "function_call"),
)
def test_parser_accepts_closed_compatible_metadata_shapes(finish_reason):
    payload = _choice(None)
    payload.update(
        {
            "id": "chunk-id",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "fake-model",
            "system_fingerprint": None,
            "service_tier": "default",
            "usage": None,
        }
    )
    payload["choices"][0].update(
        {"finish_reason": finish_reason, "logprobs": None}
    )
    payload["choices"][0]["delta"]["role"] = "assistant"
    parser = OpenAITextSSEParser()

    assert parser.feed(_frame(payload)) == ()
    assert parser.feed(b"data: [DONE]\n\n") == ()
    parser.finish()


@pytest.mark.parametrize(
    "json_text",
    (
        '{"choices":[{"index":0,"delta":{}}],"choices":[{"index":0,"delta":{}}]}',
        '{"choices":[{"index":0,"index":0,"delta":{}}]}',
        '{"choices":[{"index":0,"delta":{"content":"a","content":"b"}}]}',
        '{"usage":{"nested":1,"nested":2},"choices":[{"index":0,"delta":{}}]}',
    ),
)
def test_parser_rejects_duplicate_members_at_every_object_depth(json_text):
    sentinel = "REMOTE_DUPLICATE_VALUE_SENTINEL"
    parser = OpenAITextSSEParser()

    with pytest.raises(ChapterDraftProviderResponseError) as caught:
        parser.feed(b"data: " + json_text.replace("b", sentinel).encode() + b"\n\n")

    assert caught.value.__cause__ is None
    assert sentinel not in repr(caught.value)


@pytest.mark.parametrize(
    "json_text",
    (
        r'{"choices":[{"index":0,"delta":{"content":"\ud800"}}]}',
        r'{"model":"\udfff","choices":[{"index":0,"delta":{}}]}',
        r'{"\ud800":"value","choices":[{"index":0,"delta":{}}]}',
    ),
)
def test_parser_rejects_lone_surrogates_in_all_json_strings_and_keys(json_text):
    parser = OpenAITextSSEParser()

    with pytest.raises(ChapterDraftProviderResponseError) as caught:
        parser.feed(b"data: " + json_text.encode("ascii") + b"\n\n")

    assert caught.value.__cause__ is None


def test_parser_preserves_valid_supplementary_unicode():
    parser = OpenAITextSSEParser()

    assert parser.feed(_frame(_choice("😀"))) == ("😀",)
    assert parser.feed(b"data: [DONE]\n\n") == ()
    parser.finish()
