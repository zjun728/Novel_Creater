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
    CorpusLifecycleConflict,
    CorpusRequestInvalid,
    CorpusResourceNotFound,
)
from backend.security.paths import (
    UnsafeLocalPath,
    ensure_managed_corpus_blob_parent,
    managed_corpus_blob_path,
    managed_corpus_storage_key,
    resolve_under_root,
)
from backend.config import require_corpus_root, require_managed_corpus_root
from backend.services.corpus_library import normalize_corpus_metadata


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
        managed_root: Path | None = None,
        transaction_factory,
        connection_factory,
        parser_version: str = PARSER_VERSION,
        normalizer_version: str = NORMALIZER_VERSION,
        fragmenter_version: str = FRAGMENTER_VERSION,
        index_version: str = INDEX_VERSION,
        file_reader=None,
        stage_writer=None,
        id_factory=None,
        clock=None,
    ) -> None:
        self.repository = repository
        self.corpus_root = corpus_root
        self.managed_root = managed_root
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
        self.stage_writer = stage_writer or self._write_stage
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

    @staticmethod
    def _write_stage(path: Path, raw: bytes) -> None:
        with path.open("xb") as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())

    def _stage(self, raw: bytes, source_hash: str) -> tuple[Path, Path]:
        try:
            managed_root = require_managed_corpus_root(self.managed_root)
            staging_root = managed_root / ".staging"
            staging_root.mkdir(exist_ok=True)
            staging_root = staging_root.resolve(strict=True)
            if (
                staging_root.parent != managed_root.resolve(strict=True)
                or _is_reparse(staging_root)
            ):
                raise UnsafeLocalPath("managed staging root is unsafe")
            stage = staging_root / f"{uuid4().hex}.part"
            self.stage_writer(stage, raw)
            if stage.stat().st_size != len(raw):
                raise OSError("managed corpus stage length mismatch")
            final = managed_corpus_blob_path(managed_root, source_hash)
            return stage, final
        except (OSError, RuntimeError, TypeError, ValueError, UnsafeLocalPath):
            try:
                if "stage" in locals() and stage.exists():
                    stage.unlink()
            except OSError:
                pass
            raise CorpusImportFailed() from None

    def _finalize_stage(
        self,
        stage: Path,
        final: Path,
        *,
        source_hash: str,
        byte_length: int,
    ) -> None:
        try:
            managed_root = require_managed_corpus_root(self.managed_root)
            checked_final = ensure_managed_corpus_blob_parent(
                managed_root, source_hash
            )
            if checked_final != final:
                raise OSError("managed corpus target changed")
            if final.exists():
                if (
                    not final.is_file()
                    or final.stat().st_size != byte_length
                    or sha256(final.read_bytes()).hexdigest() != source_hash
                ):
                    raise OSError("managed corpus blob verification failed")
                return
            checked_final = managed_corpus_blob_path(
                managed_root, source_hash
            )
            if checked_final != final:
                raise OSError("managed corpus target changed")
            os.replace(stage, final)
            if managed_corpus_blob_path(managed_root, source_hash) != final:
                raise OSError("managed corpus target changed")
            if (
                final.stat().st_size != byte_length
                or sha256(final.read_bytes()).hexdigest() != source_hash
            ):
                raise OSError("managed corpus blob finalization failed")
        except OSError:
            raise CorpusImportFailed() from None

    @staticmethod
    def _same_revision(
        row: dict,
        *,
        source_hash: str,
        versions: dict[str, str],
        metadata,
    ) -> bool:
        raw_tags = row.get("reference_tags_json", ())
        if isinstance(raw_tags, str):
            try:
                raw_tags = json.loads(raw_tags)
            except json.JSONDecodeError:
                raw_tags = ()
        return (
            row.get("source_hash") == source_hash
            and row.get("parser_version") == versions["parserVersion"]
            and row.get("normalizer_version") == versions["normalizerVersion"]
            and row.get("fragmenter_version") == versions["fragmenterVersion"]
            and row.get("index_version") == versions["indexVersion"]
            and row.get("title") == metadata.display_name
            and tuple(raw_tags) == metadata.reference_tags
            and row.get("notes", "") == metadata.notes
        )

    async def _publish(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        relative_path: str,
        decoded,
        prepared,
        metadata,
        metadata_explicit: bool,
        source_id: str | None,
        create_distinct_source: bool,
        stage: Path,
        final: Path,
    ) -> dict:
        async with self.transaction_factory() as session:
            await self.repository.lock_schema_guard(session)
            self._finalize_stage(
                stage,
                final,
                source_hash=decoded.source_hash,
                byte_length=len(decoded.raw_bytes),
            )
            existing_run = await self.repository.find_import_by_key(
                session, idempotency_key, for_update=True
            )
            if existing_run is not None:
                if existing_run["request_hash"] != request_hash:
                    raise CorpusImportConflict()
                completed = self._completed_run(existing_run)
                if completed is not None:
                    return completed

            completed_at = self.clock()
            storage_key = managed_corpus_storage_key(decoded.source_hash)
            await self.repository.insert_or_validate_blob(
                session,
                content_hash=decoded.source_hash,
                byte_length=len(decoded.raw_bytes),
                storage_key=storage_key,
                created_at=completed_at,
            )
            if existing_run is None:
                existing_run = {
                    "id": self.id_factory(),
                    "idempotency_key": idempotency_key,
                    "request_hash": request_hash,
                    "relative_path": relative_path,
                    "source_hash": decoded.source_hash,
                    "byte_length": len(decoded.raw_bytes),
                    "status": "reserved",
                    "versions": self.versions,
                    "created_at": completed_at,
                    "corpus_source_id": None,
                    "source_revision_id": None,
                    "source_revision": None,
                    "public_error_code": None,
                    "completed_at": None,
                }
                await self.repository.insert_import(session, existing_run)

            dedupe = None
            history = ()
            if source_id is not None:
                history = tuple(
                    await self.repository.lock_source_revisions(session, source_id)
                )
                if not history:
                    raise CorpusResourceNotFound()
                if history[0].get("archived_at") is not None:
                    raise CorpusLifecycleConflict()
                current = history[-1]
                dedupe = (
                    current
                    if self._same_revision(
                        current,
                        source_hash=decoded.source_hash,
                        versions=self.versions,
                        metadata=metadata,
                    )
                    else None
                )
            elif not create_distinct_source:
                dedupe = await self.repository.find_global_analysis_source(
                    session,
                    source_hash=decoded.source_hash,
                    parser_version=self.parser_version,
                    normalizer_version=self.normalizer_version,
                    fragmenter_version=self.fragmenter_version,
                    index_version=self.index_version,
                )
                if (
                    dedupe is not None
                    and metadata_explicit
                    and not self._same_revision(
                        dedupe,
                        source_hash=decoded.source_hash,
                        versions=self.versions,
                        metadata=metadata,
                    )
                ):
                    source_id = dedupe.get("source_id") or dedupe["id"]
                    history = tuple(
                        await self.repository.lock_source_revisions(
                            session, source_id
                        )
                    )
                    dedupe = None
                elif dedupe is None:
                    content_source = (
                        await self.repository.find_global_content_source(
                            session, decoded.source_hash
                        )
                    )
                    if content_source is not None:
                        source_id = content_source["source_id"]
                        history = tuple(
                            await self.repository.lock_source_revisions(
                                session, source_id
                            )
                        )

            if dedupe is not None:
                await self.repository.mark_import_succeeded(
                    session, existing_run["id"],
                    dedupe.get("source_id") or dedupe["id"],
                    dedupe["revision_id"], int(dedupe["revision"]), completed_at,
                )
                return {
                    **existing_run,
                    "status": "succeeded",
                    "corpus_source_id": dedupe.get("source_id") or dedupe["id"],
                    "source_revision_id": dedupe["revision_id"],
                    "source_revision": int(dedupe["revision"]),
                    "public_error_code": None,
                    "completed_at": completed_at,
                }

            revisions = [int(row["revision"]) for row in history]
            if revisions and revisions != list(range(1, revisions[-1] + 1)):
                raise RuntimeError("corpus source revision history is invalid")
            source_id = history[0]["source_id"] if history else self.id_factory()
            revision_id = self.id_factory()
            source_row = {
                "id": source_id,
                "revision_id": revision_id,
                "source_key": history[0]["source_key"] if history else source_id,
                "revision": revisions[-1] + 1 if revisions else 1,
                "relative_path": relative_path,
                "title": metadata.display_name,
                "author": "unknown",
                "reference_tags": metadata.reference_tags,
                "notes": metadata.notes,
                "provenance": {
                    "sourceLabel": relative_path,
                    "importedBy": "author",
                },
                "source_hash": decoded.source_hash,
                "file_size": len(decoded.raw_bytes),
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
                session, existing_run["id"], source_id, revision_id,
                int(source_row["revision"]), completed_at,
            )
            return {
                **existing_run,
                "status": "succeeded",
                "corpus_source_id": source_id,
                "source_revision_id": revision_id,
                "source_revision": int(source_row["revision"]),
                "public_error_code": None,
                "completed_at": completed_at,
            }

    async def import_source(
        self,
        relative_path: str,
        idempotency_key: str,
        *,
        source_id: str | None = None,
        create_distinct_source: bool = False,
        display_name: str | None = None,
        reference_tags=(),
        notes: str = "",
    ) -> dict[str, object]:
        idempotency_key = _checked_idempotency_key(idempotency_key)
        relative_path, raw, source_hash = self._phase_a(relative_path)
        try:
            metadata = normalize_corpus_metadata(
                display_name=display_name,
                reference_tags=reference_tags,
                notes=notes,
                fallback_display_name=Path(relative_path).stem,
            )
        except (TypeError, ValueError):
            raise CorpusRequestInvalid() from None
        if source_id is not None and (
            type(source_id) is not str or not source_id or len(source_id) > 36
        ):
            raise CorpusRequestInvalid()
        if type(create_distinct_source) is not bool:
            raise CorpusRequestInvalid()
        if source_id is not None and create_distinct_source:
            raise CorpusRequestInvalid()
        metadata_explicit = (
            display_name is not None
            or bool(reference_tags)
            or bool(notes)
        )
        request_hash = _hash_document({
            "relativePath": relative_path,
            "sourceHash": source_hash,
            "versions": self.versions,
            "sourceId": source_id,
            "createDistinctSource": create_distinct_source,
            "displayName": metadata.display_name,
            "referenceTags": metadata.reference_tags,
            "notes": metadata.notes,
            "metadataExplicit": metadata_explicit,
        })
        stage = None
        try:
            stage, final = self._stage(raw, source_hash)
            decoded, prepared = self._parse(raw)
            return await self._publish(
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                relative_path=relative_path,
                decoded=decoded,
                prepared=prepared,
                metadata=metadata,
                metadata_explicit=metadata_explicit,
                source_id=source_id,
                create_distinct_source=create_distinct_source,
                stage=stage,
                final=final,
            )
        except (
            CorpusImportConflict,
            CorpusLifecycleConflict,
            CorpusRequestInvalid,
            CorpusResourceNotFound,
        ):
            raise
        except Exception:
            raise CorpusImportFailed() from None
        finally:
            if stage is not None:
                try:
                    stage.unlink(missing_ok=True)
                except OSError:
                    pass

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
