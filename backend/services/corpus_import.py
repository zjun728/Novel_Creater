"""Safe discovery and three-phase publication for local corpus text."""

from __future__ import annotations

import base64
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import time
from uuid import uuid4

from backend.domain.corpus import (
    FRAGMENTER_VERSION,
    INDEX_VERSION,
    NORMALIZER_VERSION,
    PARSER_VERSION,
    decode_source,
    fragment_chapter,
    parse_chapters,
)
from backend.http_errors import (
    CorpusImportConflict,
    CorpusImportFailed,
    CorpusRequestInvalid,
    CorpusResourceNotFound,
)
from backend.security.paths import UnsafeLocalPath, resolve_under_root
from backend.config import require_corpus_root


DISCOVERY_DEFAULT_LIMIT = 50
DISCOVERY_MAX_LIMIT = 200
SOURCE_LIST_LIMIT = 200
CHAPTER_LIST_LIMIT = 200
IDEMPOTENCY_KEY_PATTERN = r"^[a-z0-9][a-z0-9_-]{15,63}$"
_IDEMPOTENCY_KEY = re.compile(IDEMPOTENCY_KEY_PATTERN)
_REPARSE_POINT = 0x400


class CorpusDiscoveryCursorError(ValueError):
    """An opaque discovery cursor failed strict decoding."""

    def __init__(self) -> None:
        super().__init__("corpus discovery cursor is invalid")


def _is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _is_readable_file(path: Path) -> bool:
    try:
        with path.open("rb") as source:
            source.read(1)
    except (OSError, ValueError):
        return False
    return True


def _sort_key(relative_path: str) -> tuple[str, str]:
    return relative_path.casefold(), relative_path


def _encode_cursor(key: tuple[str, str]) -> str:
    document = json.dumps(
        {"after": list(key), "v": 1},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(document).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if cursor is None:
        return None
    if type(cursor) is not str or not cursor or len(cursor) > 4096:
        raise CorpusDiscoveryCursorError()
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(
            cursor + padding, altchars=b"-_", validate=True
        )
        document = json.loads(raw.decode("ascii"))
    except (ValueError, UnicodeError, json.JSONDecodeError):
        raise CorpusDiscoveryCursorError() from None
    if (
        type(document) is not dict
        or set(document) != {"after", "v"}
        or document["v"] != 1
        or type(document["after"]) is not list
        or len(document["after"]) != 2
        or any(type(value) is not str for value in document["after"])
    ):
        raise CorpusDiscoveryCursorError()
    return document["after"][0], document["after"][1]


def _walk_candidates(root: Path):
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = tuple(os.scandir(directory))
        except OSError:
            yield None, "unreadable"
            continue
        for entry in entries:
            path = Path(entry.path)
            if _is_reparse(path):
                yield None, "reparse"
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    yield None, "unsafeType"
                    continue
            except OSError:
                yield None, "unreadable"
                continue
            yield path, None


def discover_corpus(
    root: Path, *, cursor: str | None = None, limit: int = DISCOVERY_DEFAULT_LIMIT
) -> dict[str, object]:
    """Recursively enumerate eligible text files without exposing the root."""

    if type(limit) is not int or not 1 <= limit <= DISCOVERY_MAX_LIMIT:
        raise ValueError("limit must be an integer between 1 and 200")
    after = _decode_cursor(cursor)
    try:
        resolved_root = Path(root).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise CorpusRequestInvalid() from None
    if not resolved_root.is_dir() or _is_reparse(resolved_root):
        raise CorpusRequestInvalid()

    reason_counts: Counter[str] = Counter()
    eligible: list[dict[str, object]] = []
    for path, reason in _walk_candidates(resolved_root):
        if reason is not None:
            reason_counts[reason] += 1
            continue
        assert path is not None
        if path.suffix.casefold() != ".txt":
            reason_counts["nonTxt"] += 1
            continue
        relative_path = path.relative_to(resolved_root).as_posix()
        try:
            safe = resolve_under_root(resolved_root, relative_path, suffix=".txt")
        except UnsafeLocalPath:
            reason_counts["traversal"] += 1
            continue
        if not _is_readable_file(safe):
            reason_counts["unreadable"] += 1
            continue
        try:
            byte_size = safe.stat().st_size
        except OSError:
            reason_counts["unreadable"] += 1
            continue
        eligible.append({
            "relativePath": relative_path,
            "byteSize": byte_size,
            "preflightStatus": "eligible",
        })

    eligible.sort(key=lambda item: _sort_key(item["relativePath"]))
    if after is not None:
        eligible = [
            item for item in eligible
            if _sort_key(item["relativePath"]) > after
        ]
    page = eligible[:limit]
    next_cursor = None
    if len(eligible) > limit:
        next_cursor = _encode_cursor(_sort_key(page[-1]["relativePath"]))
    return {
        "items": page,
        "nextCursor": next_cursor,
        "reasonCounts": dict(sorted(reason_counts.items())),
        "scanStrategy": "recursive",
    }


def _hash_document(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _checked_version(value: str, name: str) -> str:
    if type(value) is not str or not value or len(value) > 64:
        raise ValueError(f"{name} must be non-empty text of at most 64 characters")
    return value


def _checked_idempotency_key(value: str) -> str:
    if type(value) is not str or _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise CorpusRequestInvalid()
    return value


class CorpusImportService:
    def __init__(
        self,
        repository,
        *,
        corpus_root: Path | None,
        transaction_factory,
        connection_factory,
        parser_version: str = PARSER_VERSION,
        normalizer_version: str = NORMALIZER_VERSION,
        fragmenter_version: str = FRAGMENTER_VERSION,
        index_version: str = INDEX_VERSION,
        file_reader=None,
        id_factory=None,
        clock=None,
    ) -> None:
        self.repository = repository
        self.corpus_root = corpus_root
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.parser_version = _checked_version(parser_version, "parser_version")
        self.normalizer_version = _checked_version(
            normalizer_version, "normalizer_version"
        )
        self.fragmenter_version = _checked_version(
            fragmenter_version, "fragmenter_version"
        )
        self.index_version = _checked_version(index_version, "index_version")
        self.file_reader = file_reader or (lambda path: path.read_bytes())
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.clock = clock or (lambda: int(time.time() * 1000))

    @property
    def versions(self) -> dict[str, str]:
        return {
            "parserVersion": self.parser_version,
            "normalizerVersion": self.normalizer_version,
            "fragmenterVersion": self.fragmenter_version,
            "indexVersion": self.index_version,
        }

    async def discovery(self, cursor=None, limit=DISCOVERY_DEFAULT_LIMIT):
        try:
            return discover_corpus(
                require_corpus_root(self.corpus_root), cursor=cursor, limit=limit
            )
        except (CorpusDiscoveryCursorError, RuntimeError):
            raise CorpusRequestInvalid() from None

    def _phase_a(self, relative_path: str) -> tuple[str, bytes, str]:
        try:
            root = require_corpus_root(self.corpus_root)
            safe = resolve_under_root(
                root, relative_path, suffix=".txt"
            )
            root = root.resolve(strict=True)
            normalized_relative = safe.relative_to(root).as_posix()
            if len(normalized_relative) > 2048:
                raise UnsafeLocalPath("relative corpus path is too long")
            raw = self.file_reader(safe)
            if type(raw) is not bytes:
                raise OSError("corpus reader returned non-bytes")
        except (OSError, RuntimeError, TypeError, ValueError, UnsafeLocalPath):
            raise CorpusRequestInvalid() from None
        return normalized_relative, raw, sha256(raw).hexdigest()

    async def _reserve(
        self,
        *,
        idempotency_key: str,
        relative_path: str,
        source_hash: str,
        request_hash: str,
        byte_length: int,
    ) -> tuple[dict, bool]:
        async with self.transaction_factory() as session:
            await self.repository.lock_schema_guard(session)
            existing = await self.repository.find_import_by_key(
                session, idempotency_key, for_update=True
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise CorpusImportConflict()
                return existing, False
            row = {
                "id": self.id_factory(),
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "relative_path": relative_path,
                "source_hash": source_hash,
                "byte_length": byte_length,
                "status": "reserved",
                "versions": self.versions,
                "created_at": self.clock(),
                "corpus_source_id": None,
                "public_error_code": None,
                "completed_at": None,
            }
            await self.repository.insert_import(session, row)
            return row, True

    @staticmethod
    def _completed_run(row: dict) -> dict | None:
        status = row.get("status")
        if status == "succeeded":
            if not row.get("corpus_source_id"):
                raise CorpusImportFailed()
            return row
        if status == "failed":
            raise CorpusImportFailed()
        if status in ("reserved", "running"):
            return None
        raise CorpusImportFailed()

    async def _settle_failure(
        self, run: dict, error_code: str
    ) -> dict:
        async with self.transaction_factory() as session:
            await self.repository.lock_schema_guard(session)
            current = await self.repository.find_import_by_key(
                session, run["idempotency_key"], for_update=True
            )
            if (
                current is None
                or current.get("id") != run.get("id")
                or current.get("request_hash") != run.get("request_hash")
            ):
                raise CorpusImportFailed()
            completed = self._completed_run(current)
            if completed is not None:
                return completed
            completed_at = self.clock()
            await self.repository.mark_import_failed(
                session, run["id"], error_code, completed_at
            )
            return {
                **current,
                "status": "failed",
                "corpus_source_id": None,
                "public_error_code": error_code,
                "completed_at": completed_at,
            }

    def _parse(self, raw: bytes):
        decoded = decode_source(raw)
        chapters = parse_chapters(decoded)
        if not chapters:
            raise ValueError("empty corpus source")
        prepared = []
        for chapter in chapters:
            chapter_id = self.id_factory()
            fragments = fragment_chapter(chapter, chapter_id)
            prepared.append((chapter_id, chapter, fragments))
        return decoded, tuple(prepared)

    async def _publish(
        self,
        *,
        run: dict,
        relative_path: str,
        raw: bytes,
        decoded,
        prepared,
    ) -> dict:
        source_key = sha256(relative_path.casefold().encode("utf-8")).hexdigest()
        async with self.transaction_factory() as session:
            await self.repository.lock_schema_guard(session)
            existing_run = await self.repository.find_import_by_key(
                session, run["idempotency_key"], for_update=True
            )
            if existing_run is None or existing_run["id"] != run["id"]:
                raise RuntimeError("corpus import reservation disappeared")
            completed = self._completed_run(existing_run)
            if completed is not None:
                return completed
            dedupe = await self.repository.find_analysis_source(
                session,
                source_key=source_key,
                source_hash=decoded.source_hash,
                parser_version=self.parser_version,
                normalizer_version=self.normalizer_version,
                fragmenter_version=self.fragmenter_version,
                index_version=self.index_version,
            )
            completed_at = self.clock()
            if dedupe is not None:
                await self.repository.mark_import_succeeded(
                    session, run["id"], dedupe["id"],
                    dedupe["revision_id"], int(dedupe["revision"]), completed_at,
                )
                return {
                    **existing_run,
                    "status": "succeeded",
                    "corpus_source_id": dedupe["id"],
                    "public_error_code": None,
                    "completed_at": completed_at,
                }

            history = await self.repository.list_source_revisions_for_update(
                session, source_key
            )
            revisions = [int(row["revision"]) for row in history]
            if revisions and revisions != list(range(1, revisions[-1] + 1)):
                raise RuntimeError("corpus source revision history is invalid")
            source_id = (
                history[0]["source_id"] if history else self.id_factory()
            )
            revision_id = self.id_factory()
            source_row = {
                "id": source_id,
                "revision_id": revision_id,
                "source_key": source_key,
                "revision": revisions[-1] + 1 if revisions else 1,
                "relative_path": relative_path,
                "title": Path(relative_path).stem[:300],
                "author": "unknown",
                "source_hash": decoded.source_hash,
                "file_size": len(raw),
                "encoding": decoded.encoding,
                "parser_version": self.parser_version,
                "normalizer_version": self.normalizer_version,
                "fragmenter_version": self.fragmenter_version,
                "index_version": self.index_version,
                "imported_at": completed_at,
                "analyzed_at": completed_at,
            }
            await self.repository.insert_source(session, source_row)
            for chapter_id, chapter, fragments in prepared:
                await self.repository.insert_chapter(session, {
                    "id": chapter_id,
                    "corpus_source_id": source_id,
                    "source_revision_id": revision_id,
                    "source_revision": source_row["revision"],
                    "source_hash": decoded.source_hash,
                    "chapter_order": chapter.chapter_order,
                    "title": chapter.title,
                    "raw_byte_start": chapter.raw_byte_start,
                    "raw_byte_end": chapter.raw_byte_end,
                    "normalized_char_start": chapter.normalized_char_start,
                    "normalized_char_end": chapter.normalized_char_end,
                    "normalized_text": chapter.normalized_text,
                    "content_hash": chapter.content_hash,
                    "created_at": completed_at,
                })
                for fragment in fragments:
                    await self.repository.insert_fragment(session, {
                        "id": fragment.id,
                        "corpus_source_id": source_id,
                        "corpus_chapter_id": chapter_id,
                        "fragment_order": fragment.fragment_order,
                        "chapter_char_start": fragment.chapter_char_start,
                        "chapter_char_end": fragment.chapter_char_end,
                        "normalized_text": fragment.normalized_text,
                        "content_hash": fragment.content_hash,
                        "index_payload": {
                            "schemaVersion": self.index_version,
                            "fragmentId": fragment.id,
                            "chapterId": chapter_id,
                            "contentHash": fragment.content_hash,
                            "normalizerVersion": self.normalizer_version,
                        },
                        "analysis_version": self.fragmenter_version,
                        "created_at": completed_at,
                    })
            await self.repository.mark_import_succeeded(
                session, run["id"], source_id, revision_id,
                int(source_row["revision"]), completed_at,
            )
            return {
                **existing_run,
                "status": "succeeded",
                "corpus_source_id": source_id,
                "public_error_code": None,
                "completed_at": completed_at,
            }

    async def import_source(
        self, relative_path: str, idempotency_key: str
    ) -> dict[str, object]:
        idempotency_key = _checked_idempotency_key(idempotency_key)
        relative_path, raw, source_hash = self._phase_a(relative_path)
        request_hash = _hash_document({
            "relativePath": relative_path,
            "sourceHash": source_hash,
            "versions": self.versions,
        })
        run, created = await self._reserve(
            idempotency_key=idempotency_key,
            relative_path=relative_path,
            source_hash=source_hash,
            request_hash=request_hash,
            byte_length=len(raw),
        )
        if not created:
            completed = self._completed_run(run)
            if completed is not None:
                return completed
        try:
            decoded, prepared = self._parse(raw)
        except Exception:
            settled = await self._settle_failure(run, "CORPUS_PARSE_FAILED")
            completed = self._completed_run(settled)
            if completed is not None:
                return completed
            raise CorpusImportFailed() from None
        try:
            return await self._publish(
                run=run, relative_path=relative_path, raw=raw,
                decoded=decoded, prepared=prepared,
            )
        except CorpusImportFailed:
            raise
        except Exception:
            settled = await self._settle_failure(
                run, "CORPUS_PUBLICATION_FAILED"
            )
            completed = self._completed_run(settled)
            if completed is not None:
                return completed
            raise CorpusImportFailed() from None

    async def get_import(self, import_id: str):
        async with self.connection_factory() as session:
            row = await self.repository.find_import_by_id(session, import_id)
        if row is None:
            raise CorpusResourceNotFound()
        return row

    async def list_sources(self):
        async with self.connection_factory() as session:
            return tuple(await self.repository.list_sources(
                session, limit=SOURCE_LIST_LIMIT
            ))

    async def get_source(self, source_id: str, preview_chars: int):
        async with self.connection_factory() as session:
            row = await self.repository.find_source(
                session, source_id, preview_chars
            )
        if row is None:
            raise CorpusResourceNotFound()
        return row

    async def list_chapters(self, source_id: str):
        async with self.connection_factory() as session:
            if not await self.repository.source_exists(session, source_id):
                raise CorpusResourceNotFound()
            return tuple(await self.repository.list_chapters(
                session, source_id, limit=CHAPTER_LIST_LIMIT
            ))

    async def list_fragments(self, chapter_id: str, cursor: int, limit: int):
        async with self.connection_factory() as session:
            if not await self.repository.chapter_exists(session, chapter_id):
                raise CorpusResourceNotFound()
            rows = tuple(await self.repository.list_fragments(
                session, chapter_id, after_order=cursor, limit=limit
            ))
        page = rows[:limit]
        return {
            "items": page,
            "nextCursor": page[-1]["fragment_order"] if len(rows) > limit else None,
        }


__all__ = (
    "CorpusDiscoveryCursorError", "CorpusImportService",
    "IDEMPOTENCY_KEY_PATTERN", "discover_corpus",
)
