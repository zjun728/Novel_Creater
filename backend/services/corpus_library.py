"""Bounded corpus browsing and compare-and-swap lifecycle commands."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import time
import unicodedata

from backend.config import require_managed_corpus_root
from backend.domain.corpus import PREVIEW_MAX_CHARS
from backend.http_errors import (
    CorpusLifecycleConflict,
    CorpusPermanentDeleteForbidden,
    CorpusRequestInvalid,
    CorpusResourceNotFound,
)
from backend.security.paths import (
    UnsafeLocalPath,
    managed_corpus_blob_path,
    managed_corpus_storage_key,
)


MAX_DISPLAY_NAME_CHARS = 300
MAX_REFERENCE_TAGS = 12
MAX_REFERENCE_TAG_CHARS = 40
MAX_NOTES_CHARS = 1000
LIBRARY_LIST_LIMIT = 200
MAX_SEARCH_CHARS = 200
VERSION_LIST_DEFAULT = 50
VERSION_LIST_MAX = 100
DELETION_RECONCILE_LIMIT = 25
LIBRARY_STATES = frozenset(("active", "archived", "all"))
_REPARSE_POINT = 0x400


@dataclass(frozen=True, slots=True)
class CorpusSearchMetadata:
    display_name: str
    reference_tags: tuple[str, ...]
    notes: str


def _single_line(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _notes(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return normalized.replace("\r\n", "\n").replace("\r", "\n").strip()


def normalize_corpus_metadata(
    *,
    display_name: str | None,
    reference_tags,
    notes: str,
    fallback_display_name: str,
) -> CorpusSearchMetadata:
    """Normalize bounded, revisioned search metadata without affecting bytes."""

    if display_name is not None and type(display_name) is not str:
        raise ValueError("display_name must be text or null")
    if type(fallback_display_name) is not str:
        raise ValueError("fallback_display_name must be text")
    selected_name = _single_line(
        display_name if display_name is not None else fallback_display_name
    )
    if not selected_name or len(selected_name) > MAX_DISPLAY_NAME_CHARS:
        raise ValueError("display_name is outside its fixed bound")

    if not isinstance(reference_tags, (tuple, list)):
        raise ValueError("reference_tags must be a sequence")
    if len(reference_tags) > MAX_REFERENCE_TAGS:
        raise ValueError("reference_tags exceeds its fixed item bound")
    normalized_tags: list[str] = []
    seen: set[str] = set()
    for value in reference_tags:
        if type(value) is not str:
            raise ValueError("reference tag must be text")
        normalized = _single_line(value)
        if not normalized or len(normalized) > MAX_REFERENCE_TAG_CHARS:
            raise ValueError("reference tag is outside its fixed bound")
        identity = normalized.casefold()
        if identity in seen:
            continue
        seen.add(identity)
        normalized_tags.append(normalized)

    if type(notes) is not str:
        raise ValueError("notes must be text")
    normalized_notes = _notes(notes)
    if len(normalized_notes) > MAX_NOTES_CHARS:
        raise ValueError("notes exceeds its fixed bound")
    return CorpusSearchMetadata(
        display_name=selected_name,
        reference_tags=tuple(normalized_tags),
        notes=normalized_notes,
    )


def _tags(row: dict) -> tuple[str, ...]:
    value = row.get("reference_tags")
    if value is None:
        value = row.get("reference_tags_json", ())
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = ()
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(str(item) for item in value)


def _reference_total(row: dict) -> int:
    return int(row.get("reference_count") or 0) + int(
        row.get("historical_reference_count") or 0
    )


def _deletion_state(row: dict) -> tuple[bool, str | None]:
    if row.get("archived_at") is None:
        return False, "source_not_archived"
    if _reference_total(row) > 0:
        return False, "source_referenced"
    return True, None


def _public_row(row) -> dict:
    result = dict(row)
    result["reference_tags"] = _tags(result)
    eligible, reason = _deletion_state(result)
    result["delete_eligible"] = eligible
    result["delete_reason"] = reason
    return result


class CorpusLibraryService:
    def __init__(
        self,
        repository,
        *,
        managed_root: Path | None = None,
        transaction_factory,
        connection_factory,
        clock=None,
    ) -> None:
        self.repository = repository
        self.managed_root = managed_root
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.clock = clock or (lambda: int(time.time() * 1000))

    async def list_sources(
        self, *, search: str | None = None, state: str | None = None
    ) -> tuple[dict, ...]:
        await self.reconcile_pending_deletions()
        if search is not None and (
            type(search) is not str or len(search) > MAX_SEARCH_CHARS
        ):
            raise CorpusRequestInvalid()
        selected_state = state or "active"
        if selected_state not in LIBRARY_STATES:
            raise CorpusRequestInvalid()
        normalized_search = _single_line(search or "")
        async with self.connection_factory() as session:
            rows = await self.repository.list_library_sources(
                session,
                search=normalized_search,
                state=selected_state,
                limit=LIBRARY_LIST_LIMIT,
            )
        return tuple(_public_row(row) for row in rows)

    async def get_source(
        self, source_id: str, preview_chars: int
    ) -> dict:
        await self.reconcile_pending_deletions()
        if (
            type(preview_chars) is not int
            or isinstance(preview_chars, bool)
            or not 1 <= preview_chars <= PREVIEW_MAX_CHARS
        ):
            raise CorpusRequestInvalid()
        async with self.connection_factory() as session:
            row = await self.repository.find_library_source(
                session, source_id, preview_chars
            )
        if row is None:
            raise CorpusResourceNotFound()
        result = _public_row(row)
        result["preview"] = str(result.get("preview") or "")[:preview_chars]
        return result

    async def list_versions(
        self,
        source_id: str,
        *,
        cursor: int | None = None,
        limit: int = VERSION_LIST_DEFAULT,
    ) -> dict:
        await self.reconcile_pending_deletions()
        if (
            cursor is not None
            and (
                isinstance(cursor, bool)
                or type(cursor) is not int
                or cursor < 1
            )
        ):
            raise CorpusRequestInvalid()
        if (
            isinstance(limit, bool)
            or type(limit) is not int
            or not 1 <= limit <= VERSION_LIST_MAX
        ):
            raise CorpusRequestInvalid()
        async with self.connection_factory() as session:
            rows = tuple(
                await self.repository.list_source_versions(
                    session,
                    source_id,
                    before_revision=cursor,
                    limit=limit,
                )
            )
        if not rows:
            if cursor is not None:
                return {"items": (), "nextCursor": None}
            raise CorpusResourceNotFound()
        page = rows[:limit]
        return {
            "items": tuple(_public_row(row) for row in page),
            "nextCursor": (
                int(page[-1]["revision"]) if len(rows) > limit else None
            ),
        }

    @staticmethod
    def _require_revision(row: dict, expected_revision: int) -> None:
        if (
            isinstance(expected_revision, bool)
            or type(expected_revision) is not int
            or expected_revision < 1
            or int(row["revision"]) != expected_revision
        ):
            raise CorpusLifecycleConflict()

    async def _changed_row(self, session, source_id: str) -> dict:
        row = await self.repository.find_library_source(session, source_id, 1)
        if row is None:
            raise CorpusLifecycleConflict()
        return _public_row(row)

    async def archive(
        self, source_id: str, expected_revision: int
    ) -> dict:
        await self.reconcile_pending_deletions()
        async with self.transaction_factory() as session:
            row = await self.repository.lock_library_source(session, source_id)
            if row is None:
                raise CorpusResourceNotFound()
            self._require_revision(row, expected_revision)
            if row.get("archived_at") is not None:
                return await self._changed_row(session, source_id)
            if not await self.repository.archive_source(
                session, source_id, expected_revision, self.clock()
            ):
                raise CorpusLifecycleConflict()
            return await self._changed_row(session, source_id)

    async def restore(
        self, source_id: str, expected_revision: int
    ) -> dict:
        await self.reconcile_pending_deletions()
        async with self.transaction_factory() as session:
            row = await self.repository.lock_library_source(session, source_id)
            if row is None:
                raise CorpusResourceNotFound()
            self._require_revision(row, expected_revision)
            if row.get("archived_at") is None:
                return await self._changed_row(session, source_id)
            if not await self.repository.restore_source(
                session, source_id, expected_revision
            ):
                raise CorpusLifecycleConflict()
            return await self._changed_row(session, source_id)

    async def reconcile_pending_deletions(self) -> int:
        """Advance one bounded batch of previously authorized deletes."""

        async with self.connection_factory() as session:
            pending = tuple(
                await self.repository.list_pending_source_deletions(
                    session, limit=DELETION_RECONCILE_LIMIT
                )
            )
        completed = 0
        for command in pending:
            try:
                result = await self.permanently_delete(
                    command["source_id"],
                    int(command["expected_revision"]),
                    True,
                )
            except (
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
                UnsafeLocalPath,
            ) as exc:
                raise CorpusLifecycleConflict() from exc
            if result["cleanup_pending"]:
                raise CorpusLifecycleConflict()
            completed += 1
        return completed

    async def _lock_deletable_source(
        self, session, source_id: str, expected_revision: int
    ):
        row = await self.repository.lock_library_source(session, source_id)
        if row is None:
            raise CorpusResourceNotFound()
        self._require_revision(row, expected_revision)
        if row.get("archived_at") is None:
            raise CorpusPermanentDeleteForbidden()
        counts = tuple(
            await self.repository.source_reference_counts(
                session, source_id
            )
        )
        if any(
            int(item.get("reference_count") or 0) > 0
            for item in counts
        ):
            raise CorpusPermanentDeleteForbidden()
        return tuple(
            await self.repository.lock_source_blobs(session, source_id)
        )

    async def _prepare_deletion(
        self, source_id: str, expected_revision: int
    ):
        async with self.transaction_factory() as session:
            await self.repository.lock_schema_guard(session)
            command = await self.repository.lock_source_deletion(
                session, source_id
            )
            if command is not None:
                if int(command["expected_revision"]) != expected_revision:
                    raise CorpusLifecycleConflict()
                return command
            candidates = await self._lock_deletable_source(
                session, source_id, expected_revision
            )
            tombstones = self._tombstone_documents(
                candidates,
                source_id=source_id,
                expected_revision=expected_revision,
            )
            now = self.clock()
            await self.repository.upsert_source_deletion(
                session,
                source_id=source_id,
                expected_revision=expected_revision,
                status="restore_pending",
                tombstones=tombstones,
                now=now,
            )
            return {
                "source_id": source_id,
                "expected_revision": expected_revision,
                "status": "restore_pending",
                "tombstones_json": tombstones,
                "created_at": now,
                "updated_at": now,
            }

    async def permanently_delete(
        self,
        source_id: str,
        expected_revision: int,
        confirm_permanent_delete: bool,
    ) -> dict[str, bool]:
        if confirm_permanent_delete is not True:
            raise CorpusPermanentDeleteForbidden()
        require_managed_corpus_root(self.managed_root)
        prepared = await self._prepare_deletion(
            source_id, expected_revision
        )
        if prepared["status"] == "succeeded":
            return {"cleanup_pending": False}
        moves: list[tuple[Path, Path]] = []
        tombstones = list(self._tombstones_from_command(prepared))
        cancelled_error: Exception | None = None
        try:
            async with self.transaction_factory() as session:
                await self.repository.lock_schema_guard(session)
                command = await self.repository.lock_source_deletion(
                    session, source_id
                )
                if command is None:
                    raise CorpusLifecycleConflict()
                if int(command["expected_revision"]) != expected_revision:
                    raise CorpusLifecycleConflict()
                tombstones = list(self._tombstones_from_command(command))
                if command["status"] == "succeeded":
                    return {"cleanup_pending": False}
                resume_cleanup = command["status"] == "cleanup_pending"
                if resume_cleanup:
                    moves = self._moves_from_tombstones(tombstones)
                elif command["status"] == "restore_pending":
                    moves = self._moves_from_tombstones(tombstones)
                    self._restore_blob_deletions(moves)
                    moves = []
                else:
                    raise CorpusLifecycleConflict()
                if not resume_cleanup:
                    try:
                        candidates = await self._lock_deletable_source(
                            session, source_id, expected_revision
                        )
                    except (
                        CorpusLifecycleConflict,
                        CorpusPermanentDeleteForbidden,
                        CorpusResourceNotFound,
                    ) as exc:
                        if not await self.repository.cancel_source_deletion(
                            session, source_id, expected_revision
                        ):
                            raise CorpusLifecycleConflict() from exc
                        cancelled_error = exc
                    if cancelled_error is None:
                        if not await self.repository.delete_source(
                            session, source_id
                        ):
                            raise CorpusLifecycleConflict()
                        deleted_blobs = tuple(
                            await self.repository.delete_unreferenced_blobs(
                                session, candidates
                            )
                        )
                        self._stage_blob_deletions(
                            deleted_blobs,
                            source_id=source_id,
                            expected_revision=expected_revision,
                            moves=moves,
                            tombstones=tombstones,
                        )
                        await self.repository.upsert_source_deletion(
                            session,
                            source_id=source_id,
                            expected_revision=expected_revision,
                            status="cleanup_pending",
                            tombstones=tombstones,
                            now=self.clock(),
                        )
        except Exception as operation_error:
            try:
                self._restore_blob_deletions(moves)
            except Exception as restore_error:
                raise CorpusLifecycleConflict() from BaseExceptionGroup(
                    "corpus deletion failed and blob restore needs retry",
                    [operation_error, restore_error],
                )
            raise
        if cancelled_error is not None:
            raise cancelled_error
        try:
            self._finish_blob_deletions(moves)
        except (OSError, RuntimeError, ValueError, UnsafeLocalPath):
            return {"cleanup_pending": True}
        if not await self._mark_deletion_succeeded(
            source_id, expected_revision
        ):
            return {"cleanup_pending": True}
        return {"cleanup_pending": False}

    async def _mark_deletion_succeeded(
        self, source_id: str, expected_revision: int
    ) -> bool:
        try:
            async with self.transaction_factory() as session:
                await self.repository.lock_schema_guard(session)
                command = await self.repository.lock_source_deletion(
                    session, source_id
                )
                if command is None:
                    return False
                if (
                    int(command["expected_revision"]) != expected_revision
                    or command["status"] not in (
                        "cleanup_pending", "succeeded"
                    )
                ):
                    raise CorpusLifecycleConflict()
                if command["status"] == "succeeded":
                    return True
                return await self.repository.mark_source_deletion_succeeded(
                    session, source_id, expected_revision, self.clock()
                )
        except CorpusLifecycleConflict:
            raise
        except Exception:
            return False

    @staticmethod
    def _regular_file_state(path: Path) -> bool:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise UnsafeLocalPath(
                "Managed corpus file cannot be inspected safely"
            ) from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or bool(
                getattr(metadata, "st_file_attributes", 0)
                & _REPARSE_POINT
            )
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise UnsafeLocalPath(
                "Managed corpus file must be regular and not a link"
            )
        return True

    def _deletion_root(self) -> Path:
        root = require_managed_corpus_root(self.managed_root)
        deleting = root / ".deleting"
        try:
            deleting.mkdir(exist_ok=True)
            resolved = deleting.resolve(strict=True)
            if (
                resolved.parent != root.resolve(strict=True)
                or deleting.is_symlink()
                or bool(
                    getattr(deleting.lstat(), "st_file_attributes", 0)
                    & 0x400
                )
            ):
                raise OSError("managed deletion root is unsafe")
        except (OSError, RuntimeError, ValueError) as exc:
            raise CorpusLifecycleConflict() from exc
        return resolved

    def _tombstone_documents(
        self,
        rows,
        *,
        source_id: str,
        expected_revision: int,
    ) -> list[dict[str, str]]:
        documents = []
        seen: set[str] = set()
        for row in rows:
            content_hash = row["content_hash"]
            expected_key = managed_corpus_storage_key(content_hash)
            if row.get("storage_key") != expected_key:
                raise CorpusLifecycleConflict()
            if content_hash in seen:
                raise CorpusLifecycleConflict()
            seen.add(content_hash)
            command_hash = sha256(
                f"{source_id}:{expected_revision}:{content_hash}".encode(
                    "utf-8"
                )
            ).hexdigest()
            documents.append({
                "contentHash": content_hash,
                "storageKey": expected_key,
                "tombstoneName": (
                    f"{content_hash}.{command_hash}.part"
                ),
            })
        return documents

    def _stage_blob_deletions(
        self,
        rows,
        *,
        source_id: str,
        expected_revision: int,
        moves: list[tuple[Path, Path]],
        tombstones: list[dict[str, str]],
    ) -> None:
        deleting = self._deletion_root() if rows else None
        by_hash = {
            item["contentHash"]: item for item in tombstones
        }
        try:
            for row in rows:
                content_hash = row["content_hash"]
                expected_key = managed_corpus_storage_key(content_hash)
                if row.get("storage_key") != expected_key:
                    raise UnsafeLocalPath(
                        "Managed corpus registry key is invalid"
                    )
                final = managed_corpus_blob_path(
                    require_managed_corpus_root(self.managed_root),
                    content_hash,
                )
                if (
                    not self._regular_file_state(final)
                    or final.stat().st_size != int(row["byte_length"])
                    or sha256(final.read_bytes()).hexdigest() != content_hash
                ):
                    raise UnsafeLocalPath(
                        "Managed corpus blob failed deletion verification"
                    )
                command_hash = sha256(
                    f"{source_id}:{expected_revision}:{content_hash}".encode(
                        "utf-8"
                    )
                ).hexdigest()
                item = by_hash.get(content_hash)
                expected_name = f"{content_hash}.{command_hash}.part"
                if (
                    item is None
                    or item["storageKey"] != expected_key
                    or item["tombstoneName"] != expected_name
                ):
                    raise UnsafeLocalPath(
                        "Managed corpus deletion intent is incomplete"
                    )
                trash = deleting / item["tombstoneName"]
                if self._regular_file_state(trash):
                    raise UnsafeLocalPath(
                        "Managed corpus tombstone already exists"
                    )
                if managed_corpus_blob_path(
                    require_managed_corpus_root(self.managed_root),
                    content_hash,
                ) != final:
                    raise UnsafeLocalPath(
                        "Managed corpus blob path changed"
                )
                os.replace(final, trash)
                moves.append((final, trash))
                if (
                    self._regular_file_state(final)
                    or not self._regular_file_state(trash)
                    or sha256(trash.read_bytes()).hexdigest()
                    != content_hash
                ):
                    raise UnsafeLocalPath(
                        "Managed corpus tombstone move failed verification"
                    )
            return None
        except (OSError, RuntimeError, ValueError, UnsafeLocalPath) as exc:
            raise CorpusLifecycleConflict() from exc

    def _tombstones_from_command(
        self, command
    ) -> tuple[dict[str, str], ...]:
        document = command.get("tombstones_json", ())
        if isinstance(document, str):
            try:
                document = json.loads(document)
            except json.JSONDecodeError as exc:
                raise CorpusLifecycleConflict() from exc
        if not isinstance(document, list):
            if isinstance(document, tuple):
                document = list(document)
            else:
                raise CorpusLifecycleConflict()
        result = []
        for item in document:
            if not isinstance(item, dict) or set(item) != {
                "contentHash", "storageKey", "tombstoneName",
            }:
                raise CorpusLifecycleConflict()
            content_hash = item["contentHash"]
            expected_key = managed_corpus_storage_key(content_hash)
            expected_prefix = f"{content_hash}."
            name = item["tombstoneName"]
            if (
                item["storageKey"] != expected_key
                or type(name) is not str
                or not name.startswith(expected_prefix)
                or not name.endswith(".part")
                or "/" in name
                or "\\" in name
            ):
                raise CorpusLifecycleConflict()
            result.append(dict(item))
        return tuple(result)

    def _moves_from_tombstones(
        self, tombstones
    ) -> list[tuple[Path, Path]]:
        if not tombstones:
            return []
        deleting = self._deletion_root()
        root = require_managed_corpus_root(self.managed_root)
        moves = []
        for item in tombstones:
            final = managed_corpus_blob_path(root, item["contentHash"])
            trash = deleting / item["tombstoneName"]
            if trash.parent != deleting:
                raise CorpusLifecycleConflict()
            self._regular_file_state(trash)
            moves.append((final, trash))
        return moves

    @staticmethod
    def _restore_blob_deletions(moves) -> None:
        deleting_roots: set[Path] = set()
        failures: list[Exception] = []
        for final, trash in reversed(tuple(moves)):
            deleting_roots.add(trash.parent)
            try:
                final_exists = CorpusLibraryService._regular_file_state(
                    final
                )
                trash_exists = CorpusLibraryService._regular_file_state(
                    trash
                )
                expected_hash = final.name
                if not trash_exists:
                    if not final_exists:
                        failures.append(
                            OSError("managed corpus blob and tombstone are missing")
                        )
                    elif (
                        sha256(final.read_bytes()).hexdigest()
                        != expected_hash
                    ):
                        failures.append(
                            OSError("managed corpus blob hash is invalid")
                        )
                    continue
                if (
                    sha256(trash.read_bytes()).hexdigest()
                    != expected_hash
                ):
                    raise OSError(
                        "managed corpus tombstone hash is invalid"
                    )
                if final_exists:
                    if (
                        sha256(final.read_bytes()).hexdigest()
                        != expected_hash
                    ):
                        raise OSError(
                            "managed corpus blob hash is invalid"
                        )
                    trash.unlink()
                else:
                    if not final.parent.is_dir():
                        raise OSError(
                            "managed corpus blob parent is missing"
                        )
                    os.replace(trash, final)
                if (
                    not CorpusLibraryService._regular_file_state(final)
                    or CorpusLibraryService._regular_file_state(trash)
                    or sha256(final.read_bytes()).hexdigest()
                    != expected_hash
                ):
                    raise OSError(
                        "managed corpus blob restore failed verification"
                    )
            except (OSError, UnsafeLocalPath) as exc:
                failures.append(exc)
        for deleting in deleting_roots:
            try:
                deleting.rmdir()
            except OSError:
                pass
        if failures:
            raise ExceptionGroup(
                "one or more managed corpus blobs could not be restored",
                failures,
            )

    @staticmethod
    def _finish_blob_deletions(moves) -> None:
        deleting = None
        for _, trash in moves:
            deleting = trash.parent
            try:
                if CorpusLibraryService._regular_file_state(trash):
                    trash.unlink()
            except (OSError, UnsafeLocalPath):
                raise
        if deleting is not None:
            try:
                deleting.rmdir()
            except OSError:
                pass


__all__ = (
    "CorpusLibraryService",
    "CorpusSearchMetadata",
    "LIBRARY_STATES",
    "MAX_DISPLAY_NAME_CHARS",
    "MAX_NOTES_CHARS",
    "MAX_REFERENCE_TAGS",
    "MAX_REFERENCE_TAG_CHARS",
    "VERSION_LIST_DEFAULT",
    "VERSION_LIST_MAX",
    "normalize_corpus_metadata",
)
