"""Strict, bounded parser for the text subset of OpenAI-compatible SSE."""

from __future__ import annotations

import codecs
import json
from collections.abc import Mapping

from backend.gateways.chapter_draft_provider import ChapterDraftProviderResponseError

_MAX_EVENT_BYTES = 64 * 1024
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


def _invalid() -> ChapterDraftProviderResponseError:
    return ChapterDraftProviderResponseError("provider response was invalid")


def _bounded_json(value: object) -> None:
    pending: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise _invalid() from None
        if isinstance(item, Mapping):
            pending.extend((nested, depth + 1) for nested in item.values())
        elif isinstance(item, list):
            pending.extend((nested, depth + 1) for nested in item)


class OpenAITextSSEParser:
    """Incrementally parse a terminal OpenAI chat-completion SSE response."""

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self._line = ""
        self._saw_cr = False
        self._data_lines: list[str] = []
        self._done = False

    def feed(self, chunk: bytes) -> tuple[str, ...]:
        if not isinstance(chunk, bytes):
            raise _invalid() from None
        try:
            text = self._decoder.decode(chunk, final=False)
        except UnicodeDecodeError:
            raise _invalid() from None
        emitted: list[str] = []
        for character in text:
            if self._saw_cr:
                self._saw_cr = False
                self._finish_line(emitted)
                if character == "\n":
                    continue
            if character == "\r":
                self._saw_cr = True
            elif character == "\n":
                self._finish_line(emitted)
            else:
                self._line += character
                if len(self._line.encode("utf-8")) > _MAX_EVENT_BYTES:
                    raise _invalid() from None
        return tuple(emitted)

    def finish(self) -> None:
        try:
            trailing = self._decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            raise _invalid() from None
        if trailing:
            self.feed(trailing.encode("utf-8"))
        if self._saw_cr:
            self._saw_cr = False
            self._finish_line([])
        if self._line or self._data_lines or not self._done:
            raise _invalid() from None

    def _finish_line(self, emitted: list[str]) -> None:
        line, self._line = self._line, ""
        if self._done:
            raise _invalid() from None
        if not line:
            if self._data_lines:
                emitted.extend(self._dispatch_event())
            return
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
        if sum(len(item.encode("utf-8")) for item in self._data_lines) > _MAX_EVENT_BYTES:
            raise _invalid() from None

    def _dispatch_event(self) -> tuple[str, ...]:
        data_lines, self._data_lines = self._data_lines, []
        data = "\n".join(data_lines)
        if data == "[DONE]":
            self._done = True
            return ()
        if len(data.encode("utf-8")) > _MAX_EVENT_BYTES:
            raise _invalid() from None
        try:
            payload = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (RecursionError, TypeError, ValueError, UnicodeError):
            raise _invalid() from None
        _bounded_json(payload)
        if not isinstance(payload, dict) or set(payload) - _ROOT_FIELDS:
            raise _invalid() from None
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise _invalid() from None
        choice = choices[0]
        if not isinstance(choice, dict) or set(choice) - _CHOICE_FIELDS:
            raise _invalid() from None
        index = choice.get("index")
        if type(index) is not int or index != 0:
            raise _invalid() from None
        delta = choice.get("delta")
        if not isinstance(delta, dict) or set(delta) - _DELTA_FIELDS:
            raise _invalid() from None
        content = delta.get("content")
        if content is None:
            return ()
        if not isinstance(content, str):
            raise _invalid() from None
        return (content,)
