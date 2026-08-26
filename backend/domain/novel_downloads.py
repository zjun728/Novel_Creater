"""Closed, deterministic domain values for finalized-novel downloads."""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
import re
from typing import Self
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.domain.finalized_chapter_structure import (
    FinalizedChapterLink,
    FinalizedChapterStructureError,
    validate_and_sort_finalized_chapter_links,
)


MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_FILENAME_FORBIDDEN = frozenset('<>:"/\\|?*')
_MARKDOWN_TITLE_PUNCTUATION = frozenset("\\#[]()`*_<>!")


class DownloadScope(StrEnum):
    BOOK = "book"
    VOLUME = "volume"
    CHAPTER = "chapter"


class DownloadFormat(StrEnum):
    TXT = "txt"
    MARKDOWN = "markdown"


class NovelDownloadDomainError(ValueError):
    """Base error for deterministic novel download failures."""


class NovelDownloadScopeNotFoundError(NovelDownloadDomainError):
    """The selected finalized chapter scope does not exist."""


class NovelDownloadIntegrityError(NovelDownloadDomainError):
    """A persisted finalized chapter is not safe to render."""


class NovelDownloadTooLargeError(NovelDownloadDomainError):
    """The complete deterministic download exceeds its fixed size limit."""


class _FrozenDownloadValue(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class NovelDownloadSelector(_FrozenDownloadValue):
    scope: DownloadScope
    format: DownloadFormat
    volume_id: str | None = Field(default=None, min_length=1)
    chapter_number: int | None = None

    @model_validator(mode="after")
    def scope_fields_are_exact(self) -> Self:
        if self.scope is DownloadScope.BOOK:
            if self.volume_id is not None or self.chapter_number is not None:
                raise ValueError("book scope must not include volume_id or chapter_number")
        elif self.scope is DownloadScope.VOLUME:
            if self.volume_id is None or self.chapter_number is not None:
                raise ValueError("volume scope requires volume_id only")
        elif self.volume_id is not None or self.chapter_number is None or self.chapter_number < 1:
            raise ValueError("chapter scope requires a positive chapter_number only")
        return self


class FinalizedChapterMetadata(_FrozenDownloadValue):
    chapter_number: int = Field(ge=1)
    chapter_title: str = Field(min_length=1)
    volume_id: str = Field(min_length=1)
    volume_order: int = Field(ge=1)
    volume_title: str = Field(min_length=1)


class FinalizedChapterSnapshot(FinalizedChapterMetadata):
    content: str
    content_hash: str = Field(pattern=_HASH_PATTERN)


class NovelDownloadMetadata(_FrozenDownloadValue):
    book_title: str = Field(min_length=1)
    chapters: tuple[FinalizedChapterMetadata, ...]

    @model_validator(mode="after")
    def chapter_links_are_closed(self) -> Self:
        _validate_chapter_links(self.chapters, error_type=ValueError)
        return self


class NovelDownloadSnapshot(_FrozenDownloadValue):
    book_title: str = Field(min_length=1)
    chapters: tuple[FinalizedChapterSnapshot, ...]

    @model_validator(mode="after")
    def chapter_links_are_closed(self) -> Self:
        _validate_chapter_links(self.chapters, error_type=ValueError)
        return self


class SafeAttachmentNames(_FrozenDownloadValue):
    ascii_filename: str = Field(min_length=1)
    unicode_filename: str = Field(min_length=1)

    @field_validator("ascii_filename", "unicode_filename")
    @classmethod
    def filename_is_not_a_path(cls, value: str) -> str:
        if any(
            character in _FILENAME_FORBIDDEN
            or unicodedata.category(character).startswith("C")
            for character in value
        ):
            raise ValueError("attachment filename must not contain path or control characters")
        return value


def _validate_chapter_links(
    chapters: tuple[FinalizedChapterMetadata, ...]
    | tuple[FinalizedChapterSnapshot, ...],
    *,
    error_type: type[Exception],
) -> None:
    try:
        validate_and_sort_finalized_chapter_links(
            tuple(
                FinalizedChapterLink(
                    chapter_number=chapter.chapter_number,
                    volume_id=chapter.volume_id,
                    volume_order=chapter.volume_order,
                    volume_title=chapter.volume_title,
                )
                for chapter in chapters
            )
        )
    except FinalizedChapterStructureError as exc:
        raise error_type(str(exc)) from None


def _verify_final_prose(chapters: tuple[FinalizedChapterSnapshot, ...]) -> None:
    _validate_chapter_links(chapters, error_type=NovelDownloadIntegrityError)
    for chapter in chapters:
        actual_hash = sha256(chapter.content.encode("utf-8")).hexdigest()
        if actual_hash != chapter.content_hash:
            raise NovelDownloadIntegrityError(
                f"final prose hash does not match chapter {chapter.chapter_number}"
            )


def _matches_selector(
    chapter: FinalizedChapterSnapshot,
    selector: NovelDownloadSelector,
) -> bool:
    if selector.scope is DownloadScope.BOOK:
        return True
    if selector.scope is DownloadScope.VOLUME:
        return chapter.volume_id == selector.volume_id
    return chapter.chapter_number == selector.chapter_number


def select_chapters(
    snapshot: NovelDownloadSnapshot,
    selector: NovelDownloadSelector,
) -> tuple[FinalizedChapterSnapshot, ...]:
    """Return the exact selected finalized chapters in global chapter order."""

    matching = tuple(
        chapter
        for chapter in snapshot.chapters
        if _matches_selector(chapter, selector)
    )
    if not matching:
        raise NovelDownloadScopeNotFoundError(
            "requested download scope has no finalized chapters"
        )
    selected = tuple(sorted(matching, key=lambda chapter: chapter.chapter_number))
    _verify_final_prose(selected)
    return selected


def _flatten_title(value: str, *, markdown: bool) -> str:
    flattened = re.sub(r"\s+", " ", value).strip()
    if not markdown:
        return flattened
    return "".join(
        f"\\{character}"
        if character in _MARKDOWN_TITLE_PUNCTUATION
        else character
        for character in flattened
    )


def _normalized_prose(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _append_utf8(output: bytearray, value: str) -> None:
    encoded = value.encode("utf-8")
    if len(output) + len(encoded) > MAX_DOWNLOAD_BYTES:
        raise NovelDownloadTooLargeError("rendered download exceeds 128 MiB")
    output.extend(encoded)


def render_novel_download(
    snapshot: NovelDownloadSnapshot,
    selector: NovelDownloadSelector,
) -> bytes:
    """Render a selected verified finalized-novel slice as deterministic UTF-8."""

    chapters = select_chapters(snapshot, selector)
    markdown = selector.format is DownloadFormat.MARKDOWN
    book_title = _flatten_title(snapshot.book_title, markdown=markdown)
    output = bytearray()
    is_first_part = True

    def append_part(value: str) -> None:
        nonlocal is_first_part
        if not is_first_part:
            _append_utf8(output, "\n\n")
        _append_utf8(output, value)
        is_first_part = False

    append_part(f"# {book_title}" if markdown else book_title)
    current_volume_id: str | None = None
    for chapter in chapters:
        if chapter.volume_id != current_volume_id:
            volume_title = _flatten_title(chapter.volume_title, markdown=markdown)
            if markdown:
                append_part(f"## 第 {chapter.volume_order} 卷 · {volume_title}")
            else:
                append_part(
                    f"===== 第 {chapter.volume_order} 卷 · {volume_title} ====="
                )
            current_volume_id = chapter.volume_id
        chapter_title = _flatten_title(chapter.chapter_title, markdown=markdown)
        if markdown:
            append_part(f"### 第 {chapter.chapter_number} 章 · {chapter_title}")
        else:
            append_part(f"----- 第 {chapter.chapter_number} 章 · {chapter_title} -----")
        append_part(_normalized_prose(chapter.content))
    while output and output[-1] == ord("\n"):
        output.pop()
    _append_utf8(output, "\n")
    return bytes(output)


def _safe_filename_stem(value: str) -> str:
    safe = "".join(
        character
        for character in unicodedata.normalize("NFC", value)
        if character not in _FILENAME_FORBIDDEN
        and not unicodedata.category(character).startswith("C")
    )
    return safe.strip(". ")[:120] or "novel-download"


def _ascii_filename_stem(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode(
        "ascii", "ignore"
    ).decode("ascii")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_value).strip(".-")
    return safe[:120] or "novel-download"


def safe_attachment_names(
    book_title: str,
    format: DownloadFormat,
) -> SafeAttachmentNames:
    """Return router-ready ASCII and Unicode attachment names, never a path."""

    if type(book_title) is not str:
        raise TypeError("book_title must be a string")
    if not isinstance(format, DownloadFormat):
        raise TypeError("format must be a DownloadFormat")
    suffix = ".txt" if format is DownloadFormat.TXT else ".md"
    unicode_stem = _safe_filename_stem(book_title)
    return SafeAttachmentNames(
        ascii_filename=f"{_ascii_filename_stem(unicode_stem)}{suffix}",
        unicode_filename=f"{unicode_stem}{suffix}",
    )


__all__ = (
    "DownloadFormat",
    "DownloadScope",
    "FinalizedChapterMetadata",
    "FinalizedChapterSnapshot",
    "MAX_DOWNLOAD_BYTES",
    "NovelDownloadDomainError",
    "NovelDownloadIntegrityError",
    "NovelDownloadMetadata",
    "NovelDownloadScopeNotFoundError",
    "NovelDownloadSelector",
    "NovelDownloadSnapshot",
    "NovelDownloadTooLargeError",
    "SafeAttachmentNames",
    "render_novel_download",
    "safe_attachment_names",
    "select_chapters",
)
