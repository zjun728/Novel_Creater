"""Pure, deterministic transforms for local text corpus imports."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
import unicodedata
from uuid import UUID, uuid5


PARSER_VERSION = "corpus-parser-v1"
NORMALIZER_VERSION = "corpus-normalizer-v1"
FRAGMENTER_VERSION = "corpus-fragmenter-v1"
INDEX_VERSION = "corpus-index-v1"

PREVIEW_DEFAULT_CHARS = 600
PREVIEW_MAX_CHARS = 1200
FRAGMENT_PAGE_DEFAULT = 10
FRAGMENT_PAGE_MAX = 20
FRAGMENT_PREVIEW_CHARS = 240

# Import-time fragments are deliberately smaller than LONGTEXT and bounded
# independently from all API preview controls.
FRAGMENT_MAX_CHARS = 1200
MAX_CHAPTER_TITLE_CHARS = 300
MAX_HEADING_LINE_CHARS = 100

_UTF8_BOM = b"\xef\xbb\xbf"
_FRAGMENT_NAMESPACE = UUID("83dcab93-a2c3-4ce4-bf3a-8581f7feef7a")
_HEADING_RE = re.compile(
    rf"(?m)^[ \t\u3000]*(?=[^\r\n]{{1,{MAX_HEADING_LINE_CHARS}}}"
    r"[ \t\u3000]*\r?$)(?P<title>"
    r"(?:第[0-9０-９一二三四五六七八九十百千万零〇两]+[章节回卷部篇]"
    r"|序章|楔子|尾声|后记|番外)"
    r"(?:(?:(?:[ \t\u3000]+|[：:])(?P<separated_label>[^\r\n]+))"
    r"|(?P<compact_label>[^\s：:]{1,20}))?"
    r")[ \t\u3000]*\r?$"
)
_ALLOWED_CONTROLS = frozenset("\t\n\r")
_COMPACT_SENTENCE_ENDINGS = frozenset("。！？!?；;，,")
_PROSE_LABEL_PREFIXES = (
    "讲述",
    "描写",
    "介绍",
    "说明",
    "叙述",
    "是",
    "的",
    "为",
    "在",
    "有",
    "把",
    "将",
    "被",
    "让",
    "与",
    "和",
    "及",
    "从",
    "由",
)


class CorpusDecodeError(ValueError):
    """Stable and non-sensitive failure at the corpus decoding boundary."""

    code = "CORPUS_DECODE_INVALID"
    safe_message = "corpus source is not valid supported text"

    def __init__(self) -> None:
        super().__init__(f"{self.code}: {self.safe_message}")


@dataclass(frozen=True, slots=True)
class DecodedSource:
    """Decoded text plus the exact immutable bytes from which it came."""

    raw_bytes: bytes
    text: str
    encoding: str
    source_hash: str


@dataclass(frozen=True, slots=True)
class CorpusChapter:
    """A chapter row shaped for ``corpus_chapters`` publication."""

    chapter_order: int
    title: str
    raw_byte_start: int
    raw_byte_end: int
    normalized_char_start: int
    normalized_char_end: int
    normalized_text: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class CorpusFragment:
    """A deterministic fragment row and its allowlisted search metadata."""

    id: str
    chapter_id: str
    fragment_order: int
    chapter_char_start: int
    chapter_char_end: int
    normalized_text: str
    content_hash: str
    analysis_version: str = FRAGMENTER_VERSION

    @property
    def index_payload(self) -> dict[str, str]:
        """Return a fresh JSON-ready payload with an exact field allowlist."""

        return {
            "schemaVersion": INDEX_VERSION,
            "fragmentId": self.id,
            "chapterId": self.chapter_id,
            "contentHash": self.content_hash,
            "normalizerVersion": NORMALIZER_VERSION,
        }


def _hash_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _is_noncharacter(codepoint: int) -> bool:
    return 0xFDD0 <= codepoint <= 0xFDEF or codepoint & 0xFFFF in (
        0xFFFE,
        0xFFFF,
    )


def _require_textual(decoded: str) -> None:
    """Reject deterministic binary sentinels after strict codec decoding.

    GB18030 maps a very large part of the byte space, so codec success alone is
    not a sufficient text boundary. NUL, non-text C0/C1 controls, surrogates and
    Unicode noncharacters are rejected for every supported encoding.
    """

    for character in decoded:
        codepoint = ord(character)
        if character in _ALLOWED_CONTROLS:
            continue
        if unicodedata.category(character) in ("Cc", "Cs"):
            raise CorpusDecodeError()
        if _is_noncharacter(codepoint):
            raise CorpusDecodeError()


def _decoded(raw: bytes, encoding: str) -> str:
    try:
        text = raw.decode(encoding, errors="strict")
    except UnicodeDecodeError:
        raise CorpusDecodeError() from None
    _require_textual(text)
    return text


def decode_source(raw: bytes) -> DecodedSource:
    """Decode exact bytes as BOM UTF-8, strict UTF-8, then strict GB18030."""

    if not isinstance(raw, bytes):
        raise TypeError("raw must be bytes")

    if raw.startswith(_UTF8_BOM):
        text = _decoded(raw, "utf-8-sig")
        encoding = "utf-8-sig"
    else:
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            try:
                text = raw.decode("gb18030", errors="strict")
            except UnicodeDecodeError:
                raise CorpusDecodeError() from None
            if text.encode("gb18030", errors="strict") != raw:
                raise CorpusDecodeError()
            _require_textual(text)
            encoding = "gb18030"
        else:
            _require_textual(text)
            encoding = "utf-8"

    return DecodedSource(
        raw_bytes=raw,
        text=text,
        encoding=encoding,
        source_hash=_hash_bytes(raw),
    )


def _normalize_core(text: str) -> str:
    without_bom = text.removeprefix("\ufeff")
    lf_text = without_bom.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", lf_text)


def normalize_text(text: str) -> str:
    """Apply the named corpus normalizer: BOM removal, NFC and LF newlines."""

    if not isinstance(text, str):
        raise TypeError("text must be str")
    return _normalize_core(text).strip()


def _encoded_length(segment: str, encoding: str) -> int:
    return len(segment.encode(encoding))


def _build_byte_offsets(
    source: DecodedSource,
    boundaries: list[int] | tuple[int, ...],
) -> dict[int, int]:
    """Map character boundaries with one forward pass over disjoint segments."""

    ordered = sorted(set(boundaries))
    if any(
        isinstance(boundary, bool)
        or not isinstance(boundary, int)
        or not 0 <= boundary <= len(source.text)
        for boundary in ordered
    ):
        raise ValueError("character boundaries must be within decoded text")

    segment_encoding = (
        "utf-8" if source.encoding == "utf-8-sig" else source.encoding
    )
    character_cursor = 0
    byte_cursor = len(_UTF8_BOM) if source.encoding == "utf-8-sig" else 0
    offsets: dict[int, int] = {}
    for boundary in ordered:
        segment = source.text[character_cursor:boundary]
        byte_cursor += _encoded_length(segment, segment_encoding)
        offsets[boundary] = byte_cursor
        character_cursor = boundary
    return offsets


def _title(value: str) -> str:
    normalized = normalize_text(value)
    return normalized[:MAX_CHAPTER_TITLE_CHARS]


def _is_approved_heading(match: re.Match[str]) -> bool:
    """Apply one conservative prose policy to separated and compact labels.

    A short unpunctuated prose line cannot always be distinguished from a real
    compact title. The parser intentionally prefers a missed heading over a
    broad false split; downstream import preflight chapter counts expose misses.
    """

    label = match.group("separated_label") or match.group("compact_label")
    if label is None:
        return True
    label = label.strip()
    return not (
        not label
        or label[-1] in _COMPACT_SENTENCE_ENDINGS
        or label.startswith(_PROSE_LABEL_PREFIXES)
    )


def _chapter_spans(source: DecodedSource) -> list[tuple[int, int, str]]:
    matches = tuple(
        match
        for match in _HEADING_RE.finditer(source.text)
        if _is_approved_heading(match)
    )
    if not matches:
        return [(0, len(source.text), "全文")]

    spans: list[tuple[int, int, str]] = []
    first_start = matches[0].start()
    if normalize_text(source.text[:first_start]):
        spans.append((0, first_start, "前言"))

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(
            source.text
        )
        spans.append((match.start(), end, _title(match.group("title"))))
    return spans


def parse_chapters(source: DecodedSource) -> tuple[CorpusChapter, ...]:
    """Parse exact chapter ranges with deliberately conservative headings.

    Heading ambiguity is resolved toward under-splitting, never broad prose
    splitting; import preflight chapter counts are expected to expose misses.
    """

    if not isinstance(source, DecodedSource):
        raise TypeError("source must be DecodedSource")
    if not normalize_text(source.text):
        return ()

    spans = _chapter_spans(source)
    byte_offsets = _build_byte_offsets(
        source,
        tuple(
            boundary
            for character_start, character_end, _ in spans
            for boundary in (character_start, character_end)
        ),
    )
    chapters: list[CorpusChapter] = []
    whole_core = _normalize_core(source.text)
    whole_leading_trim = len(whole_core) - len(whole_core.lstrip())
    source_character_cursor = 0
    whole_core_cursor = 0
    for character_start, character_end, title in spans:
        gap = source.text[source_character_cursor:character_start]
        whole_core_cursor += len(_normalize_core(gap))
        raw_start = 0 if character_start == 0 else byte_offsets[character_start]
        raw_end = (
            len(source.raw_bytes)
            if character_end == len(source.text)
            else byte_offsets[character_end]
        )
        exact_text = source.raw_bytes[raw_start:raw_end].decode(
            source.encoding,
            errors="strict",
        )
        chapter_core = _normalize_core(exact_text)
        normalized = chapter_core.strip()
        if not normalized:
            whole_core_cursor += len(chapter_core)
            source_character_cursor = character_end
            continue
        leading_trim = len(chapter_core) - len(chapter_core.lstrip())
        normalized_start = (
            whole_core_cursor + leading_trim - whole_leading_trim
        )
        normalized_end = (
            whole_core_cursor
            + len(chapter_core.rstrip())
            - whole_leading_trim
        )
        chapters.append(
            CorpusChapter(
                chapter_order=len(chapters) + 1,
                title=title,
                raw_byte_start=raw_start,
                raw_byte_end=raw_end,
                normalized_char_start=normalized_start,
                normalized_char_end=normalized_end,
                normalized_text=normalized,
                content_hash=_hash_bytes(normalized.encode("utf-8")),
            )
        )
        whole_core_cursor += len(chapter_core)
        source_character_cursor = character_end
    return tuple(chapters)


def _fragment_end(text: str, start: int, max_chars: int) -> int:
    hard_end = min(start + max_chars, len(text))
    if hard_end == len(text):
        return hard_end
    window = text[start:hard_end]
    newline = window.rfind("\n", max_chars // 2)
    return start + newline + 1 if newline >= 0 else hard_end


def fragment_chapter(
    chapter: CorpusChapter,
    chapter_id: str,
    *,
    max_chars: int = FRAGMENT_MAX_CHARS,
) -> tuple[CorpusFragment, ...]:
    """Split a chapter into stable, covering, non-overlapping fragments."""

    if not isinstance(chapter, CorpusChapter):
        raise TypeError("chapter must be CorpusChapter")
    if not isinstance(chapter_id, str) or not chapter_id or len(chapter_id) > 36:
        raise ValueError(
            "chapter_id must be a non-empty string of at most 36 chars"
        )
    if (
        isinstance(max_chars, bool)
        or not isinstance(max_chars, int)
        or not 1 <= max_chars <= FRAGMENT_MAX_CHARS
    ):
        raise ValueError(
            f"max_chars must be an integer between 1 and {FRAGMENT_MAX_CHARS}"
        )

    fragments: list[CorpusFragment] = []
    start = 0
    while start < len(chapter.normalized_text):
        end = _fragment_end(chapter.normalized_text, start, max_chars)
        normalized = chapter.normalized_text[start:end]
        content_hash = _hash_bytes(normalized.encode("utf-8"))
        order = len(fragments) + 1
        identity = (
            f"{FRAGMENTER_VERSION}:{chapter_id}:{order}:"
            f"{start}:{end}:{content_hash}"
        )
        fragment_id = str(uuid5(_FRAGMENT_NAMESPACE, identity))
        fragments.append(
            CorpusFragment(
                id=fragment_id,
                chapter_id=chapter_id,
                fragment_order=order,
                chapter_char_start=start,
                chapter_char_end=end,
                normalized_text=normalized,
                content_hash=content_hash,
                analysis_version=FRAGMENTER_VERSION,
            )
        )
        start = end
    return tuple(fragments)
