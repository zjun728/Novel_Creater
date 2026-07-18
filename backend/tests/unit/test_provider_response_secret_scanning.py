from __future__ import annotations

import importlib
from urllib.parse import quote

import pytest


def _scanner(name):
    module = importlib.import_module("backend.security.provider_secrets")
    scanner = getattr(module, name, None)
    if scanner is None:
        pytest.fail(f"shared Provider response scanner is missing: {name}")
    return scanner


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
