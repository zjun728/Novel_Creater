from __future__ import annotations

from hashlib import sha256

import pytest

from backend.domain import corpus as corpus_domain
from backend.domain.corpus import (
    FRAGMENTER_VERSION,
    INDEX_VERSION,
    NORMALIZER_VERSION,
    decode_source,
    fragment_chapter,
    parse_chapters,
)


def _chapter(tmp_path):
    text = (
        "第一章 风铃次序\r\n"
        "甲把蓝绳系在檐角。\r\n"
        "乙把铜铃移到门侧。\n"
        "雨停后，两人按影子的方向交换位置。\n"
    )
    raw = b"\xef\xbb\xbf" + text.encode("utf-8")
    (tmp_path / "fragment-source.txt").write_bytes(raw)
    return parse_chapters(decode_source(raw))[0]


def test_fragment_chapter_is_bounded_nonoverlapping_and_deterministic(tmp_path):
    chapter = _chapter(tmp_path)

    fragments = fragment_chapter(chapter, "chapter-0001", max_chars=18)
    replay = fragment_chapter(chapter, "chapter-0001", max_chars=18)

    assert fragments == replay
    assert len(fragments) > 1
    assert tuple(fragment.fragment_order for fragment in fragments) == tuple(
        range(1, len(fragments) + 1)
    )

    previous_end = 0
    for fragment in fragments:
        assert fragment.chapter_id == "chapter-0001"
        assert fragment.chapter_char_start == previous_end
        assert fragment.chapter_char_start < fragment.chapter_char_end
        assert fragment.chapter_char_end - fragment.chapter_char_start <= 18
        assert fragment.normalized_text == chapter.normalized_text[
            fragment.chapter_char_start : fragment.chapter_char_end
        ]
        assert fragment.content_hash == sha256(
            fragment.normalized_text.encode("utf-8")
        ).hexdigest()
        assert fragment.analysis_version == FRAGMENTER_VERSION
        previous_end = fragment.chapter_char_end

    assert previous_end == len(chapter.normalized_text)
    assert "".join(
        fragment.normalized_text for fragment in fragments
    ) == chapter.normalized_text


def test_fragment_index_payload_has_exact_allowlisted_metadata(tmp_path):
    chapter = _chapter(tmp_path)

    fragment = fragment_chapter(chapter, "chapter-0001", max_chars=18)[0]
    payload = fragment.index_payload

    assert payload == {
        "schemaVersion": INDEX_VERSION,
        "fragmentId": fragment.id,
        "chapterId": "chapter-0001",
        "contentHash": fragment.content_hash,
        "normalizerVersion": NORMALIZER_VERSION,
    }
    assert set(payload) == {
        "schemaVersion",
        "fragmentId",
        "chapterId",
        "contentHash",
        "normalizerVersion",
    }
    rendered = repr(payload).casefold()
    assert "normalized" not in rendered
    assert "raw" not in rendered
    assert "source" not in rendered
    assert "path" not in rendered


def test_fragment_ids_change_with_chapter_identity_but_text_hash_does_not(tmp_path):
    chapter = _chapter(tmp_path)

    first = fragment_chapter(chapter, "chapter-0001", max_chars=18)[0]
    second = fragment_chapter(chapter, "chapter-0002", max_chars=18)[0]

    assert first.id != second.id
    assert first.content_hash == second.content_hash
    assert first.index_payload["chapterId"] != second.index_payload["chapterId"]


def test_fragment_identity_uses_fragmenter_version_not_index_version(
    tmp_path,
    monkeypatch,
):
    chapter = _chapter(tmp_path)
    baseline = fragment_chapter(chapter, "chapter-0001", max_chars=18)[0]

    next_fragmenter = f"{FRAGMENTER_VERSION}-next"
    monkeypatch.setattr(
        corpus_domain,
        "FRAGMENTER_VERSION",
        next_fragmenter,
    )
    fragmenter_changed = fragment_chapter(
        chapter,
        "chapter-0001",
        max_chars=18,
    )[0]
    monkeypatch.setattr(
        corpus_domain,
        "FRAGMENTER_VERSION",
        FRAGMENTER_VERSION,
    )
    monkeypatch.setattr(corpus_domain, "INDEX_VERSION", f"{INDEX_VERSION}-next")
    index_changed = fragment_chapter(
        chapter,
        "chapter-0001",
        max_chars=18,
    )[0]

    assert fragmenter_changed.id != baseline.id
    assert fragmenter_changed.analysis_version == next_fragmenter
    assert index_changed.id == baseline.id
    assert index_changed.index_payload["schemaVersion"] == f"{INDEX_VERSION}-next"


@pytest.mark.parametrize("max_chars", (0, -1, 1201, True, 3.5))
def test_fragment_chapter_rejects_unbounded_or_invalid_sizes(tmp_path, max_chars):
    chapter = _chapter(tmp_path)

    with pytest.raises(ValueError, match="max_chars"):
        fragment_chapter(chapter, "chapter-0001", max_chars=max_chars)
