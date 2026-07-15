"""A schema-restricted RFC 8785 JSON canonicalization profile."""

from __future__ import annotations

import hashlib
import json
from typing import NoReturn


MIN_SAFE_INTEGER = -(2**53) + 1
MAX_SAFE_INTEGER = (2**53) - 1


class JCSCanonicalizationError(ValueError):
    """The value cannot be represented by this schema-restricted JCS profile."""

    def __init__(self, message: str = "Value is not valid restricted JCS.", *, kind: str = "invalid"):
        super().__init__(message)
        self.kind = kind


def _raise_invalid() -> NoReturn:
    raise JCSCanonicalizationError()


def _validate_string(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        _raise_invalid()


def _validate_value(value: object, ancestors: set[int] | None = None) -> None:
    if ancestors is None:
        ancestors = set()
    if type(value) is str:
        _validate_string(value)
        return
    if type(value) is int:
        if MIN_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            return
        _raise_invalid()
    if type(value) is list:
        identity = id(value)
        if identity in ancestors:
            _raise_invalid()
        ancestors.add(identity)
        try:
            for item in value:
                _validate_value(item, ancestors)
        finally:
            ancestors.remove(identity)
        return
    if type(value) is dict:
        identity = id(value)
        if identity in ancestors:
            _raise_invalid()
        ancestors.add(identity)
        try:
            for key, item in value.items():
                if type(key) is not str:
                    _raise_invalid()
                _validate_string(key)
                _validate_value(item, ancestors)
        finally:
            ancestors.remove(identity)
        return
    _raise_invalid()


def loads_rejecting_duplicates(raw: bytes) -> object:
    """Decode strict UTF-8 JSON and reject duplicate keys at every object depth."""

    if type(raw) is not bytes:
        _raise_invalid()
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise JCSCanonicalizationError() from error

    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise JCSCanonicalizationError(kind="duplicate")
            result[key] = value
        return result

    def reject_constant(_: str) -> NoReturn:
        _raise_invalid()

    try:
        value = json.loads(
            text,
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
        _validate_value(value)
    except JCSCanonicalizationError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as error:
        raise JCSCanonicalizationError() from error
    return value


def _escape_string(value: str) -> str:
    _validate_string(value)
    escaped: list[str] = ['"']
    short_escapes = {
        0x08: "\\b",
        0x09: "\\t",
        0x0A: "\\n",
        0x0C: "\\f",
        0x0D: "\\r",
    }
    for character in value:
        codepoint = ord(character)
        if character == '"':
            escaped.append('\\"')
        elif character == "\\":
            escaped.append("\\\\")
        elif codepoint in short_escapes:
            escaped.append(short_escapes[codepoint])
        elif codepoint <= 0x1F:
            escaped.append(f"\\u{codepoint:04x}")
        else:
            escaped.append(character)
    escaped.append('"')
    return "".join(escaped)


def _canonical_text(value: object) -> str:
    if type(value) is str:
        return _escape_string(value)
    if type(value) is int:
        if MIN_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            return str(value)
        _raise_invalid()
    if type(value) is list:
        return "[" + ",".join(_canonical_text(item) for item in value) + "]"
    if type(value) is dict:
        entries: list[str] = []
        for key in sorted(value, key=lambda item: _utf16_sort_key(item)):
            entries.append(_escape_string(key) + ":" + _canonical_text(value[key]))
        return "{" + ",".join(entries) + "}"
    _raise_invalid()


def _utf16_sort_key(value: object) -> bytes:
    if type(value) is not str:
        _raise_invalid()
    _validate_string(value)
    return value.encode("utf-16-be")


def canonicalize(value: object) -> bytes:
    """Return RFC 8785-compatible UTF-8 bytes for dict/list/str/strict-int values."""

    try:
        _validate_value(value)
        return _canonical_text(value).encode("utf-8")
    except JCSCanonicalizationError:
        raise
    except RecursionError as error:
        raise JCSCanonicalizationError() from error


def canonical_sha256(value: object) -> str:
    """Return the lowercase SHA-256 digest of the canonical UTF-8 bytes."""

    return hashlib.sha256(canonicalize(value)).hexdigest()
