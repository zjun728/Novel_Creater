"""Bounded, deterministic retrieval candidates for corpus recommendation."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field


MAX_CORPUS_CANDIDATES = 20
MAX_CORPUS_CANDIDATE_CHARS = 300
MAX_CORPUS_TOTAL_CHARS = 4_000
_RETRIEVAL_EXCERPT_CHARS = 200
_HASH = r"^[0-9a-f]{64}$"


class CorpusCandidate(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    source_id: str = Field(min_length=1, max_length=36)
    source_revision_id: str = Field(min_length=1, max_length=36)
    source_revision: int = Field(gt=0)
    source_hash: str = Field(pattern=_HASH)
    chapter_id: str = Field(min_length=1, max_length=36)
    fragment_id: str = Field(min_length=1, max_length=36)
    fragment_hash: str = Field(pattern=_HASH)
    window_start: int = Field(ge=0)
    window_end: int = Field(gt=0)
    excerpt: str = Field(min_length=1, max_length=MAX_CORPUS_CANDIDATE_CHARS)


def _normalize(value: object) -> str:
    folded = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(
        "".join(
            character
            if unicodedata.category(character)[0] in {"L", "N"}
            else " "
            for character in folded
        ).split()
    )


def _is_hangul_lead(character: str) -> bool:
    codepoint = ord(character)
    return 0x1100 <= codepoint <= 0x115F or 0xA960 <= codepoint <= 0xA97C


def _is_hangul_vowel(character: str) -> bool:
    codepoint = ord(character)
    return 0x1160 <= codepoint <= 0x11A7 or 0xD7B0 <= codepoint <= 0xD7C6


def _is_hangul_trail(character: str) -> bool:
    codepoint = ord(character)
    return 0x11A8 <= codepoint <= 0x11FF or 0xD7CB <= codepoint <= 0xD7FB


def _normalization_units(text: str):
    """Yield source spans that Unicode normalization cannot split safely."""

    index = 0
    while index < len(text):
        start = index
        index += 1
        if (
            _is_hangul_lead(text[start])
            and index < len(text)
            and _is_hangul_vowel(text[index])
        ):
            index += 1
            if index < len(text) and _is_hangul_trail(text[index]):
                index += 1
        while index < len(text) and unicodedata.combining(text[index]):
            index += 1
        yield start, index


def _normalize_with_boundaries(text: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Normalize text while retaining each output character's source span."""

    characters: list[str] = []
    boundaries: list[tuple[int, int]] = []
    separator: tuple[int, int] | None = None
    for start, end in _normalization_units(text):
        folded = unicodedata.normalize("NFKC", text[start:end]).casefold()
        for character in folded:
            if unicodedata.category(character)[0] in {"L", "N"}:
                if separator is not None and characters:
                    characters.append(" ")
                    boundaries.append(separator)
                separator = None
                characters.append(character)
                boundaries.append((start, end))
            elif separator is None:
                separator = (start, end)
            else:
                separator = (separator[0], end)
    normalized = "".join(characters)
    if normalized != _normalize(text):
        raise ValueError("corpus text normalization boundaries are invalid")
    return normalized, tuple(boundaries)


def _ngrams(value: object) -> frozenset[str]:
    grams: set[str] = set()
    for token in _normalize(value).split():
        compact = token.replace(" ", "")
        if not compact:
            continue
        if len(compact) == 1:
            grams.add(compact)
            continue
        for size in (2, 3):
            if len(compact) >= size:
                grams.update(
                    compact[index : index + size]
                    for index in range(len(compact) - size + 1)
                )
    return frozenset(grams)


def _tags(value: object) -> tuple[str, ...]:
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        item[:100]
        for item in value[:20]
        if isinstance(item, str) and item.strip()
    )


def _best_window(text: str, queries: tuple[str, ...]) -> tuple[int, int, str]:
    normalized, boundaries = _normalize_with_boundaries(text)
    full_hits = tuple(
        (offset, query)
        for query in queries
        if query and (offset := normalized.find(query)) >= 0
    )
    if full_hits:
        hit, needle = min(full_hits, key=lambda item: item[0])
    else:
        grams = frozenset().union(*(_ngrams(query) for query in queries))
        gram_hits = tuple(
            (offset, gram)
            for gram in grams
            if (offset := normalized.find(gram)) >= 0
        )
        hit, needle = (
            min(gram_hits, key=lambda item: (item[0], -len(item[1]), item[1]))
            if gram_hits else (0, "")
        )
    hit_start = boundaries[hit][0] if needle else 0
    start = max(0, hit_start - _RETRIEVAL_EXCERPT_CHARS // 4)
    end = min(len(text), start + _RETRIEVAL_EXCERPT_CHARS)
    start = max(0, end - _RETRIEVAL_EXCERPT_CHARS)
    while start < end and text[start].isspace():
        start += 1
    while start < end and text[end - 1].isspace():
        end -= 1
    excerpt = text[start:end]
    return start, end, excerpt


class CorpusCandidateCollector:
    """Keep only the global top-K while deterministic keyset pages stream by."""

    def __init__(self, query_texts: tuple[str, ...]) -> None:
        if (
            not isinstance(query_texts, tuple)
            or not 1 <= len(query_texts) <= 20
            or sum(len(value) for value in query_texts) > 40_000
        ):
            raise ValueError("corpus retrieval query is invalid")
        self._normalized_queries = tuple(
            query for value in query_texts if (query := _normalize(value))
        )
        self._query_grams = frozenset().union(
            *(_ngrams(value) for value in self._normalized_queries)
        )
        self._ranked: list[tuple[int, str, CorpusCandidate]] = []

    def add_rows(self, rows: tuple[Mapping[str, object], ...]) -> None:
        if not isinstance(rows, tuple) or len(rows) > 500:
            raise ValueError("corpus retrieval rows are invalid")
        if not self._query_grams:
            return
        for row in rows:
            try:
                fragment_id = str(row["fragment_id"])
                text = str(row["normalized_text"])
                if not text:
                    continue
                fields = (
                    (8, " ".join(_tags(row.get("reference_tags_json")))),
                    (6, row.get("display_name")),
                    (5, row.get("chapter_title")),
                    (1, text),
                )
                score = sum(
                    weight * len(self._query_grams.intersection(_ngrams(value)))
                    for weight, value in fields
                )
                if score <= 0:
                    continue
                local_start, local_end, excerpt = _best_window(
                    text,
                    self._normalized_queries,
                )
                chapter_start = int(row["chapter_char_start"])
                candidate = CorpusCandidate(
                    source_id=str(row["source_id"]),
                    source_revision_id=str(row["source_revision_id"]),
                    source_revision=int(row["source_revision"]),
                    source_hash=str(row["source_hash"]),
                    chapter_id=str(row["chapter_id"]),
                    fragment_id=fragment_id,
                    fragment_hash=str(row["fragment_hash"]),
                    window_start=chapter_start + local_start,
                    window_end=chapter_start + local_end,
                    excerpt=excerpt,
                )
            except (KeyError, TypeError, ValueError):
                continue
            self._ranked.append((score, fragment_id, candidate))
            self._ranked.sort(key=lambda item: (-item[0], item[1]))
            del self._ranked[MAX_CORPUS_CANDIDATES:]

    def result(self) -> tuple[CorpusCandidate, ...]:
        result: list[CorpusCandidate] = []
        used_chars = 0
        for _, _, candidate in self._ranked:
            if used_chars + len(candidate.excerpt) > MAX_CORPUS_TOTAL_CHARS:
                continue
            result.append(candidate)
            used_chars += len(candidate.excerpt)
        return tuple(result)


def build_corpus_candidates(
    rows: tuple[Mapping[str, object], ...],
    query_texts: tuple[str, ...],
) -> tuple[CorpusCandidate, ...]:
    """Rank one bounded page using the same streaming top-K collector."""

    collector = CorpusCandidateCollector(query_texts)
    collector.add_rows(rows)
    return collector.result()


__all__ = (
    "CorpusCandidate",
    "CorpusCandidateCollector",
    "MAX_CORPUS_CANDIDATES",
    "MAX_CORPUS_CANDIDATE_CHARS",
    "MAX_CORPUS_TOTAL_CHARS",
    "build_corpus_candidates",
)
