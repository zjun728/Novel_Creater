from __future__ import annotations

from collections.abc import Mapping
import importlib
import json
from types import TracebackType
from urllib.parse import quote

import httpx
import pytest


def _scanner(name):
    module = importlib.import_module("backend.security.provider_secrets")
    scanner = getattr(module, name, None)
    if scanner is None:
        pytest.fail(f"shared Provider response scanner is missing: {name}")
    return scanner


def _assert_no_sensitive_error_graph(
    error: BaseException,
    sentinels: tuple[str, ...],
) -> None:
    """Inspect every recoverable production error reference for secrets."""

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

    joined = "\n".join(evidence)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert all(sentinel not in joined for sentinel in sentinels)


def test_provider_response_text_validation_requires_str_nonblank_strict_utf8():
    validate = _scanner("validate_provider_response_text")
    valid = "  星河😀中文  "

    assert validate(valid) == valid
    assert validate(valid, strip=True) == "星河😀中文"
    for invalid in ({}, [], "", " \r\n", "\ud800", "\udfff"):
        with pytest.raises(ValueError, match="provider response text is invalid"):
            validate(invalid)


@pytest.mark.parametrize(
    ("value", "secrets"),
    (
        ("\ud800", ("long-secret",)),
        ("ordinary response", ("\udfff-long-secret",)),
    ),
)
def test_raw_response_scanner_never_leaks_unicode_errors(value, secrets):
    scanner = _scanner("provider_response_text_contains_secret")

    with pytest.raises(ValueError) as exc_info:
        scanner(value, secrets)

    assert type(exc_info.value) is ValueError
    assert str(exc_info.value) == "provider response text is invalid"


def test_decoded_response_scanner_matches_short_secrets_only_as_exact_scalars_or_keys():
    scanner = _scanner("provider_response_value_contains_secret")

    assert scanner({"tagline": "short"}, ("short",)) is True
    assert scanner({"short": "safe"}, ("short",)) is True
    assert scanner("short", ("short",)) is True
    assert scanner({"tagline": "ordinary short prose"}, ("short",)) is False
    assert scanner({"xylophone": "safe"}, ("x",)) is False


def test_decoded_response_scanner_matches_long_secrets_as_substrings():
    scanner = _scanner("provider_response_value_contains_secret")

    assert scanner(
        {"tagline": "prefix long-secret-value suffix"},
        ("long-secret-value",),
    ) is True


def test_decoded_response_scanner_rejects_surrogate_scalars_without_codec_error():
    scanner = _scanner("provider_response_value_contains_secret")

    with pytest.raises(ValueError) as exc_info:
        scanner({"name": "\ud800"}, ("long-secret",))

    assert type(exc_info.value) is ValueError
    assert str(exc_info.value) == "provider response text is invalid"


def test_raw_response_scanner_preserves_encoded_long_secret_detection_only():
    scanner = _scanner("provider_response_text_contains_secret")
    long_secret = "https://private.example/v1"
    mixed_case_encoding = "https%3a%2F%2fprivate.example%2Fv1"

    assert scanner(
        f'{{"echo":"{quote(long_secret, safe="")}"}}',
        (long_secret,),
    ) is True
    assert scanner(
        f'{{"echo":"{mixed_case_encoding}"}}',
        (long_secret,),
    ) is True
    assert scanner('{"tagline":"ordinary x prose"}', ("x",)) is False


def test_decoded_response_scanner_fails_closed_on_excessive_structure():
    scanner = _scanner("provider_response_value_contains_secret")
    payload: object = "safe"
    for _ in range(34):
        payload = [payload]

    with pytest.raises(ValueError, match="response structure exceeds scan limits"):
        scanner(payload, ("short",), max_depth=32)


@pytest.mark.parametrize(
    "secret_path",
    (
        ("storyBlockRef", "id"),
        ("stageRefs", 0, "id"),
        ("sceneTaskRefs", 0, "contentHash"),
        ("scenes", 0),
    ),
)
def test_decoded_response_scanner_covers_complete_outline_content(
    secret_path,
):
    scanner = _scanner("provider_response_value_contains_secret")
    secret = "long-outline-provider-secret"
    payload = {
        "storyBlockRef": {"id": "block-1", "contentHash": "a" * 64},
        "stageRefs": [{"id": "stage-1", "contentHash": "b" * 64}],
        "sceneTaskRefs": [{"id": "task-1", "contentHash": "c" * 64}],
        "scenes": ["ordinary scene"],
    }
    target = payload
    for part in secret_path[:-1]:
        target = target[part]
    target[secret_path[-1]] = f"prefix {secret} suffix"

    assert scanner(payload, (secret,)) is True
