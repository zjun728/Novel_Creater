from __future__ import annotations

from hashlib import sha256

import pytest

from backend.domain import corpus as corpus_domain
from backend.domain.corpus import decode_source, normalize_text, parse_chapters


SYNTHETIC_TEXT = (
    " \t\r\n\r\n"
    "第一章 雨夜试灯\r\n"
    "阿遥把纸灯放到窗边。\r\n\r\n"
    "第二章 晨桥回声\n"
    "石桥下传来三声水响。\n"
)


def _write_source(tmp_path, codec: str, *, bom: bool = False):
    prefix = b"\xef\xbb\xbf" if bom else b""
    raw = prefix + SYNTHETIC_TEXT.encode(codec)
    path = tmp_path / f"chapters-{codec}-bom-{bom}.txt"
    path.write_bytes(raw)
    return raw


def _decode_raw_range(raw: bytes, start: int, end: int, encoding: str) -> str:
    return raw[start:end].decode(encoding)


@pytest.mark.parametrize(
    ("codec", "bom"),
    (("utf-8", False), ("utf-8", True), ("gb18030", False)),
)
def test_byte_offset_builder_scans_segments_once_and_rebuilds_exact_slices(
    tmp_path,
    monkeypatch,
    codec,
    bom,
):
    text = "".join(
        f"第{order}章 风向{order}\r\n纸鸢掠过第{order}座短桥。\r\n"
        for order in range(1, 301)
    )
    prefix = b"\xef\xbb\xbf" if bom else b""
    raw = prefix + text.encode(codec)
    (tmp_path / f"offsets-{codec}-{bom}.txt").write_bytes(raw)
    decoded = decode_source(raw)
    boundaries = sorted({0, len(text), *range(0, len(text), 7)})

    builder = getattr(corpus_domain, "_build_byte_offsets", None)
    assert builder is not None, "parser needs a single-pass byte offset builder"
    encoded_length = getattr(corpus_domain, "_encoded_length", None)
    assert encoded_length is not None
    encoded_segments = []

    def track_encoded_length(segment, encoding):
        encoded_segments.append(segment)
        return encoded_length(segment, encoding)

    monkeypatch.setattr(
        corpus_domain,
        "_encoded_length",
        track_encoded_length,
    )

    offsets = builder(decoded, boundaries)

    assert "".join(encoded_segments) == text
    assert sum(map(len, encoded_segments)) == len(text)
    for start, end in zip(boundaries, boundaries[1:]):
        raw_start = 0 if start == 0 else offsets[start]
        assert raw[raw_start : offsets[end]].decode(decoded.encoding) == text[
            start:end
        ]


@pytest.mark.parametrize(
    ("codec", "bom"),
    (("utf-8", False), ("utf-8", True), ("gb18030", False)),
)
def test_parse_chapters_preserves_exact_byte_and_normalized_ranges(
    tmp_path,
    codec,
    bom,
):
    raw = _write_source(tmp_path, codec, bom=bom)
    decoded = decode_source(raw)

    chapters = parse_chapters(decoded)

    assert tuple(chapter.chapter_order for chapter in chapters) == (1, 2)
    assert tuple(chapter.title for chapter in chapters) == (
        "第一章 雨夜试灯",
        "第二章 晨桥回声",
    )
    assert chapters == parse_chapters(decoded)

    previous_raw_end = 0
    previous_char_end = 0
    whole_normalized = normalize_text(decoded.text)
    for chapter in chapters:
        assert (
            0
            <= previous_raw_end
            <= chapter.raw_byte_start
            < chapter.raw_byte_end
            <= len(raw)
        )
        assert previous_char_end <= chapter.normalized_char_start
        assert chapter.normalized_char_start < chapter.normalized_char_end
        assert whole_normalized[
            chapter.normalized_char_start : chapter.normalized_char_end
        ] == chapter.normalized_text
        assert normalize_text(
            whole_normalized[
                previous_char_end : chapter.normalized_char_start
            ]
        ) == ""
        exact_decoded = _decode_raw_range(
            raw,
            chapter.raw_byte_start,
            chapter.raw_byte_end,
            decoded.encoding,
        )
        assert normalize_text(exact_decoded) == chapter.normalized_text
        assert chapter.normalized_char_end - chapter.normalized_char_start == len(
            chapter.normalized_text
        )
        assert chapter.content_hash == sha256(
            chapter.normalized_text.encode("utf-8")
        ).hexdigest()
        assert "\r" not in chapter.normalized_text

        raw_gap = raw[previous_raw_end : chapter.raw_byte_start]
        assert normalize_text(raw_gap.decode(decoded.encoding)) == ""
        previous_raw_end = chapter.raw_byte_end
        previous_char_end = chapter.normalized_char_end

    trailing_gap = raw[previous_raw_end:]
    assert normalize_text(trailing_gap.decode(decoded.encoding)) == ""


def test_normalized_ranges_slice_the_whole_normalized_source(tmp_path):
    text = (
        "  e\u0301序言从旧钟声开始。\r\n\r\n"
        "第一章 灯影\r\n守灯人记下蓝色刻度。\r\n\r\n\r\n"
        "第二章：桥声\r\n石桥回应了两次。\r\n"
    )
    raw = text.encode("utf-8")
    (tmp_path / "whole-normalized-ranges.txt").write_bytes(raw)
    decoded = decode_source(raw)

    chapters = parse_chapters(decoded)
    whole_normalized = normalize_text(decoded.text)

    assert len(chapters) == 3
    for chapter in chapters:
        assert whole_normalized[
            chapter.normalized_char_start : chapter.normalized_char_end
        ] == chapter.normalized_text
    assert chapters[1].normalized_char_start > chapters[0].normalized_char_end
    assert chapters[2].normalized_char_start > chapters[1].normalized_char_end


def test_parse_chapters_retains_nonempty_preface_as_a_chapter(tmp_path):
    text = "写在前面：钟匠只留下了一张地图。\r\n\r\n第一章 开门\r\n门轴轻响。\r\n"
    raw = text.encode("utf-8")
    (tmp_path / "preface.txt").write_bytes(raw)

    chapters = parse_chapters(decode_source(raw))

    assert tuple(chapter.title for chapter in chapters) == ("前言", "第一章 开门")
    assert chapters[0].raw_byte_start == 0
    assert chapters[0].raw_byte_end == chapters[1].raw_byte_start
    assert chapters[0].normalized_text == "写在前面：钟匠只留下了一张地图。"


def test_parse_chapters_treats_unheaded_text_as_one_whole_chapter(tmp_path):
    raw = "微风穿过空站台。\r\n值夜人合上登记簿。".encode("gb18030")
    (tmp_path / "whole.txt").write_bytes(raw)

    chapters = parse_chapters(decode_source(raw))

    assert len(chapters) == 1
    assert chapters[0].title == "全文"
    assert chapters[0].raw_byte_start == 0
    assert chapters[0].raw_byte_end == len(raw)
    assert chapters[0].normalized_text == "微风穿过空站台。\n值夜人合上登记簿。"


def test_prose_that_starts_with_heading_words_is_not_split(tmp_path):
    text = (
        "第一章是全书的开端。\r\n"
        "第一章是全书的开端\r\n"
        "叙述者仍在解释旧日历。\r\n"
        "番外的人群逐渐散去。\n"
        "车站重新安静下来。\n"
    )
    raw = text.encode("utf-8")
    (tmp_path / "heading-like-prose.txt").write_bytes(raw)

    chapters = parse_chapters(decode_source(raw))

    assert len(chapters) == 1
    assert chapters[0].title == "全文"
    assert chapters[0].normalized_text == normalize_text(text)


@pytest.mark.parametrize(
    "prose_line",
    (
        "第一章 是全书的开端。",
        "第一章讲述村中旧事",
        "第一章描写少年返乡",
        "第一章介绍了主要人物",
    ),
)
def test_separated_and_compact_heading_like_prose_is_not_split(
    tmp_path,
    prose_line,
):
    text = f"{prose_line}\r\n叙述者继续整理旧日历。\r\n"
    raw = text.encode("utf-8")
    (tmp_path / "shared-prose-policy.txt").write_bytes(raw)

    chapters = parse_chapters(decode_source(raw))

    assert len(chapters) == 1
    assert chapters[0].title == "全文"
    assert chapters[0].normalized_text == normalize_text(text)


def test_overlong_heading_candidate_is_not_split(tmp_path):
    first_line = "第一章 " + "很长的正文说明" * 20 + "。"
    text = f"{first_line}\n下一行仍是正文。\n"
    raw = text.encode("utf-8")
    (tmp_path / "overlong-heading-candidate.txt").write_bytes(raw)

    chapters = parse_chapters(decode_source(raw))

    assert len(chapters) == 1
    assert chapters[0].title == "全文"


@pytest.mark.parametrize(
    "heading",
    (
        "第一章",
        "第二章 灯影",
        "第三章：桥声",
        "第一章小村少年",
        "第12章风起",
        "序章：旧站",
        "番外 雨后",
    ),
)
def test_explicit_heading_variants_remain_supported(tmp_path, heading):
    text = f"{heading}\r\n守夜人合上值班簿。\r\n"
    raw = text.encode("utf-8")
    (tmp_path / "approved-heading.txt").write_bytes(raw)

    chapters = parse_chapters(decode_source(raw))

    assert len(chapters) == 1
    assert chapters[0].title == heading


def test_parse_chapters_returns_no_rows_for_normalized_empty_source():
    decoded = decode_source(b"\xef\xbb\xbf \r\n\t\n")

    assert parse_chapters(decoded) == ()
