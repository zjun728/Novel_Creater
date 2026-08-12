"""Strict, bounded parser for the text subset of OpenAI-compatible SSE."""

from __future__ import annotations

import json
from collections.abc import Mapping

from backend.gateways.chapter_draft_provider import ChapterDraftProviderResponseError

_MAX_EVENT_BYTES = 64 * 1024
_MAX_EVENT_LINES = 1_024
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 2_048
_ROOT_FIELDS = frozenset(
    {
        "id",
        "object",
        "created",
        "model",
        "system_fingerprint",
        "service_tier",
        "usage",
        "choices",
    }
)
_CHOICE_FIELDS = frozenset({"index", "delta", "logprobs", "finish_reason"})
_DELTA_FIELDS = frozenset({"role", "content"})
_FINISH_REASONS = frozenset(
    {"stop", "length", "content_filter", "tool_calls", "function_call"}
)


def _invalid() -> ChapterDraftProviderResponseError:
    return ChapterDraftProviderResponseError("provider response was invalid")


def _reject_duplicate_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, nested in pairs:
        if key in value:
            raise ValueError
        value[key] = nested
    return value


def _validate_strict_utf8(value: str) -> None:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise _invalid() from None


def _bounded_json(value: object) -> None:
    pending: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise _invalid() from None
        if isinstance(item, str):
            _validate_strict_utf8(item)
        elif isinstance(item, Mapping):
            for key, nested in item.items():
                pending.append((key, depth + 1))
                pending.append((nested, depth + 1))
        elif isinstance(item, list):
            pending.extend((nested, depth + 1) for nested in item)


class OpenAITextSSEParser:
    """Incrementally parse a terminal OpenAI chat-completion SSE response."""

    def __init__(self) -> None:
        self._line = bytearray()
        self._saw_cr = False
        self._data_lines: list[str] = []
        self._event_bytes = 0
        self._event_lines = 0
        self._done = False

    def feed(self, chunk: bytes) -> tuple[str, ...]:
        if not isinstance(chunk, bytes):
            raise _invalid() from None
        if self._done and chunk:
            raise _invalid() from None
        emitted: list[str] = []
        for value in chunk:
            if self._saw_cr:
                self._saw_cr = False
                if value == 0x0A:
                    self._count_event_byte()
                    self._finish_line(emitted)
                    continue
                self._finish_line(emitted)
            if self._done:
                raise _invalid() from None
            self._count_event_byte()
            if value == 0x0D:
                self._saw_cr = True
            elif value == 0x0A:
                self._finish_line(emitted)
            else:
                self._line.append(value)
        return tuple(emitted)

    def finish(self) -> None:
        if self._saw_cr:
            self._saw_cr = False
            self._finish_line([])
        if self._line or self._data_lines or not self._done:
            raise _invalid() from None

    def _count_event_byte(self) -> None:
        self._event_bytes += 1
        if self._event_bytes > _MAX_EVENT_BYTES:
            raise _invalid() from None

    def _finish_line(self, emitted: list[str]) -> None:
        raw_line = bytes(self._line)
        self._line.clear()
        if self._done:
            raise _invalid() from None
        if not raw_line:
            if self._data_lines:
                emitted.extend(self._dispatch_event())
            self._reset_event_bounds()
            return
        self._event_lines += 1
        if self._event_lines > _MAX_EVENT_LINES:
            raise _invalid() from None
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            raise _invalid() from None
        if line.startswith(":"):
            return
        field, separator, value = line.partition(":")
        if not separator:
            value = ""
        elif value.startswith(" "):
            value = value[1:]
        if field != "data":
            raise _invalid() from None
        self._data_lines.append(value)

    def _reset_event_bounds(self) -> None:
        self._event_bytes = 0
        self._event_lines = 0

    def _dispatch_event(self) -> tuple[str, ...]:
        data_lines, self._data_lines = self._data_lines, []
        data = "\n".join(data_lines)
        if data == "[DONE]":
            self._done = True
            return ()
        if len(data.encode("utf-8")) > _MAX_EVENT_BYTES:
            raise _invalid() from None
        try:
            payload = json.loads(
                data,
                object_pairs_hook=_reject_duplicate_members,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
        except (RecursionError, TypeError, ValueError, UnicodeError):
            raise _invalid() from None
        _bounded_json(payload)
        if not isinstance(payload, dict) or set(payload) - _ROOT_FIELDS:
            raise _invalid() from None
        self._validate_root_metadata(payload)
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise _invalid() from None
        choice = choices[0]
        if not isinstance(choice, dict) or set(choice) - _CHOICE_FIELDS:
            raise _invalid() from None
        index = choice.get("index")
        if type(index) is not int or index != 0:
            raise _invalid() from None
        if choice.get("logprobs") is not None:
            raise _invalid() from None
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and (
            not isinstance(finish_reason, str)
            or finish_reason not in _FINISH_REASONS
        ):
            raise _invalid() from None
        delta = choice.get("delta")
        if not isinstance(delta, dict) or set(delta) - _DELTA_FIELDS:
            raise _invalid() from None
        if "role" in delta and delta["role"] != "assistant":
            raise _invalid() from None
        content = delta.get("content")
        if content is None:
            return ()
        if not isinstance(content, str):
            raise _invalid() from None
        return (content,)

    @staticmethod
    def _validate_root_metadata(payload: dict[str, object]) -> None:
        for field in ("id", "object", "model"):
            if field in payload and not isinstance(payload[field], str):
                raise _invalid() from None
        if "created" in payload and type(payload["created"]) is not int:
            raise _invalid() from None
        for field in ("system_fingerprint", "service_tier"):
            value = payload.get(field)
            if field in payload and value is not None and not isinstance(value, str):
                raise _invalid() from None
        if payload.get("usage") is not None:
            raise _invalid() from None
