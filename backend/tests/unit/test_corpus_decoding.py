from __future__ import annotations

from hashlib import sha256

import pytest

from backend.domain.corpus import (
    FRAGMENT_PAGE_DEFAULT,
    FRAGMENT_PAGE_MAX,
    FRAGMENT_PREVIEW_CHARS,
    FRAGMENTER_VERSION,
    INDEX_VERSION,
    NORMALIZER_VERSION,
    PARSER_VERSION,
    PREVIEW_DEFAULT_CHARS,
    PREVIEW_MAX_CHARS,
    CorpusDecodeError,
    decode_source,
)


SYNTHETIC_TEXT = (
    "  \r\n\r\n第一章 雨夜试灯\r\n阿遥把纸灯放到窗边。\n"
    "第二章 晨桥回声\n石桥下传来三声水响。\n"
)


@pytest.mark.parametrize(
    ("codec", "expected_encoding", "prefix"),
    (
        ("utf-8", "utf-8", b""),
        ("utf-8", "utf-8-sig", b"\xef\xbb\xbf"),
        ("gb18030", "gb18030", b""),
    ),
)
def test_decode_source_is_deterministic_and_hashes_exact_runtime_bytes(
    tmp_path,
    codec,
    expected_encoding,
    prefix,
):
    source_path = tmp_path / f"synthetic-{expected_encoding}.txt"
    raw = prefix + SYNTHETIC_TEXT.encode(codec)
    source_path.write_bytes(raw)

    first = decode_source(source_path.read_bytes())
    replay = decode_source(source_path.read_bytes())

    assert first == replay
    assert first.raw_bytes == raw
    assert first.source_hash == sha256(raw).hexdigest()
    assert first.encoding == expected_encoding
    assert first.text == SYNTHETIC_TEXT
    assert "阿遥" in first.text
    assert "\r\n" in first.text


@pytest.mark.parametrize(
    "raw",
    (
        b"\x00\x01\x02binary\xff\xfe",
        b"plain\x00text",
        b"\xef\xbb\xbfvalid-prefix\xff",
        b"\x81",
    ),
)
def test_decode_source_rejects_invalid_or_obviously_binary_payload_stably(raw):
    with pytest.raises(CorpusDecodeError) as first:
        decode_source(raw)
    with pytest.raises(CorpusDecodeError) as replay:
        decode_source(raw)

    assert first.value.code == "CORPUS_DECODE_INVALID"
    assert str(first.value) == str(replay.value)
    assert raw.hex() not in str(first.value)


def test_corpus_pipeline_versions_and_public_bounds_are_explicit():
    assert all(
        isinstance(version, str) and version
        for version in (
            PARSER_VERSION,
            NORMALIZER_VERSION,
            FRAGMENTER_VERSION,
            INDEX_VERSION,
        )
    )
    assert PREVIEW_DEFAULT_CHARS == 600
    assert PREVIEW_MAX_CHARS == 1200
    assert FRAGMENT_PAGE_DEFAULT == 10
    assert FRAGMENT_PAGE_MAX == 20
    assert FRAGMENT_PREVIEW_CHARS == 240
