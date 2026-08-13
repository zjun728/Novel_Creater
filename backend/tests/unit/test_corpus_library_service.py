from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from hashlib import sha256
import importlib

import pytest

SOURCE_ID = "11111111-1111-1111-1111-111111111111"


def library_module():
    return importlib.import_module("backend.services.corpus_library")


def http_errors_module():
    return importlib.import_module("backend.http_errors")


@pytest.mark.parametrize(
    ("display_name", "tags", "notes", "expected"),
    (
        (
            "  典\u3000籍  ",
            (" 玄幻 ", "参考", "玄幻"),
            "  第一行\r\n第二行  ",
            ("典 籍", ("玄幻", "参考"), "第一行\n第二行"),
        ),
        (None, (), "", ("默认书名", (), "")),
    ),
)
def test_import_search_metadata_is_normalized_and_deduplicated(
    display_name, tags, notes, expected
):
    result = library_module().normalize_corpus_metadata(
        display_name=display_name,
        reference_tags=tags,
        notes=notes,
        fallback_display_name="默认书名",
    )

    assert (
        result.display_name,
        result.reference_tags,
        result.notes,
    ) == expected


@pytest.mark.parametrize(
    "overrides",
    (
        {"display_name": "名" * 301},
        {"reference_tags": tuple(f"tag-{index}" for index in range(13))},
        {"reference_tags": ("标" * 41,)},
        {"notes": "注" * 1001},
    ),
)
def test_import_search_metadata_is_bounded(overrides):
    values = {
        "display_name": "默认",
        "reference_tags": (),
        "notes": "",
        "fallback_display_name": "默认",
        **overrides,
    }

    with pytest.raises(ValueError):
        library_module().normalize_corpus_metadata(**values)


class MemoryCorpusRepository:
    def __init__(self):
        self.row = {
            "id": SOURCE_ID,
            "revision": 2,
            "revision_id": "revision-2",
            "source_hash": "b" * 64,
            "title": " 北境 风物 ",
            "relative_path": "synthetic/book.txt",
            "reference_tags": ("玄幻", "战争"),
            "notes": "只用于合成测试",
            "encoding": "utf-8",
            "status": "analyzed",
            "archived_at": None,
            "chapter_count": 2,
            "fragment_count": 4,
            "reference_count": 0,
            "historical_reference_count": 0,
        }
        self.versions = [
            {
                **self.row,
                "revision": 2,
                "revision_id": "revision-2",
                "source_hash": "b" * 64,
                "reference_count": 0,
                "is_current": True,
            },
            {
                **self.row,
                "revision": 1,
                "revision_id": "revision-1",
                "source_hash": "a" * 64,
                "reference_count": 0,
                "is_current": False,
            },
        ]
        self.deleted = False
        self.archive_calls = 0
        self.restore_calls = 0
        self.blob_candidates = ()
        self.deletion_commands = {}

    async def lock_schema_guard(self, _session):
        return None

    async def lock_source_deletion(self, _session, source_id):
        command = self.deletion_commands.get(source_id)
        return deepcopy(command) if command is not None else None

    async def list_pending_source_deletions(self, _session, *, limit):
        return tuple(
            deepcopy(command)
            for command in self.deletion_commands.values()
            if command["status"] in (
                "restore_pending", "cleanup_pending"
            )
        )[:limit]

    async def upsert_source_deletion(
        self,
        _session,
        *,
        source_id,
        expected_revision,
        status,
        tombstones,
        now,
    ):
        existing = self.deletion_commands.get(source_id)
        self.deletion_commands[source_id] = {
            "source_id": source_id,
            "expected_revision": expected_revision,
            "status": status,
            "tombstones_json": deepcopy(list(tombstones)),
            "created_at": (
                existing["created_at"] if existing is not None else now
            ),
            "updated_at": now,
        }

    async def mark_source_deletion_succeeded(
        self, _session, source_id, expected_revision, now
    ):
        command = self.deletion_commands[source_id]
        assert command["expected_revision"] == expected_revision
        command["status"] = "succeeded"
        command["updated_at"] = now
        return True

    async def cancel_source_deletion(
        self, _session, source_id, expected_revision
    ):
        command = self.deletion_commands.get(source_id)
        if (
            command is None
            or command["expected_revision"] != expected_revision
            or command["status"] != "restore_pending"
        ):
            return False
        del self.deletion_commands[source_id]
        return True

    async def list_library_sources(self, _session, *, search, state, limit):
        rows = () if self.deleted else (deepcopy(self.row),)
        if state == "active":
            rows = tuple(row for row in rows if row["archived_at"] is None)
        elif state == "archived":
            rows = tuple(row for row in rows if row["archived_at"] is not None)
        needle = " ".join((search or "").casefold().split())
        if needle:
            rows = tuple(
                row for row in rows
                if needle in " ".join((
                    row["title"],
                    *row["reference_tags"],
                    row["notes"],
                )).casefold()
            )
        return rows[:limit]

    async def find_library_source(self, _session, source_id, preview_chars):
        if self.deleted or source_id != SOURCE_ID:
            return None
        return {**deepcopy(self.row), "preview": "节" * preview_chars}

    async def list_source_versions(
        self, _session, source_id, *, before_revision, limit
    ):
        if self.deleted or source_id != SOURCE_ID:
            return ()
        rows = tuple(
            version for version in deepcopy(self.versions)
            if before_revision is None
            or version["revision"] < before_revision
        )
        return rows[:limit + 1]

    async def lock_library_source(self, _session, source_id):
        if self.deleted or source_id != SOURCE_ID:
            return None
        return deepcopy(self.row)

    async def archive_source(self, _session, source_id, expected_revision, archived_at):
        assert source_id == SOURCE_ID
        assert expected_revision == self.row["revision"]
        self.archive_calls += 1
        self.row["archived_at"] = archived_at
        for version in self.versions:
            version["archived_at"] = archived_at
        return True

    async def restore_source(self, _session, source_id, expected_revision):
        assert source_id == SOURCE_ID
        assert expected_revision == self.row["revision"]
        self.restore_calls += 1
        self.row["archived_at"] = None
        for version in self.versions:
            version["archived_at"] = None
        return True

    async def source_reference_counts(self, _session, source_id):
        assert source_id == SOURCE_ID
        return tuple({
            "revision": version["revision"],
            "reference_count": version["reference_count"],
        } for version in self.versions)

    async def lock_source_blobs(self, _session, source_id):
        assert source_id == SOURCE_ID
        return tuple(deepcopy(self.blob_candidates))

    async def delete_source(self, _session, source_id):
        assert source_id == SOURCE_ID
        self.deleted = True
        return True

    async def delete_unreferenced_blobs(self, _session, candidates):
        return tuple(deepcopy(tuple(candidates)))


@asynccontextmanager
async def boundary():
    yield object()


def service(repository=None, *, managed_root=None, transaction_factory=boundary):
    return library_module().CorpusLibraryService(
        repository or MemoryCorpusRepository(),
        managed_root=managed_root,
        transaction_factory=transaction_factory,
        connection_factory=boundary,
        clock=lambda: 1_900_000_000_000,
    )


@pytest.mark.asyncio
async def test_library_search_and_detail_are_bounded_and_explain_delete_state():
    library = service()

    rows = await library.list_sources(search="玄幻", state="active")
    detail = await library.get_source(SOURCE_ID, preview_chars=1200)
    versions = await library.list_versions(
        SOURCE_ID, cursor=None, limit=1
    )

    assert len(rows) == 1
    assert detail["preview"] == "节" * 1200
    assert detail["delete_eligible"] is False
    assert detail["delete_reason"] == "source_not_archived"
    assert [row["revision"] for row in versions["items"]] == [2]
    assert versions["nextCursor"] == 2
    second_page = await library.list_versions(
        SOURCE_ID, cursor=versions["nextCursor"], limit=1
    )
    assert [row["revision"] for row in second_page["items"]] == [1]
    assert second_page["nextCursor"] is None
    assert all(
        row["reference_count"] == 0
        for row in (*versions["items"], *second_page["items"])
    )


@pytest.mark.asyncio
async def test_archive_restore_are_compare_and_swap_and_idempotent():
    repository = MemoryCorpusRepository()
    library = service(repository)

    archived = await library.archive(SOURCE_ID, expected_revision=2)
    replay = await library.archive(SOURCE_ID, expected_revision=2)
    restored = await library.restore(SOURCE_ID, expected_revision=2)
    restore_replay = await library.restore(SOURCE_ID, expected_revision=2)

    assert archived["archived_at"] == replay["archived_at"] == 1_900_000_000_000
    assert restored["archived_at"] is restore_replay["archived_at"] is None
    assert repository.archive_calls == 1
    assert repository.restore_calls == 1
    with pytest.raises(http_errors_module().CorpusLifecycleConflict):
        await library.archive(SOURCE_ID, expected_revision=1)


@pytest.mark.asyncio
async def test_permanent_delete_requires_archived_zero_reference_source_and_one_danger_flag(
    workspace_tmp_path,
):
    repository = MemoryCorpusRepository()
    managed_root = workspace_tmp_path / "managed"
    managed_root.mkdir()
    library = service(repository, managed_root=managed_root)

    errors = http_errors_module()
    with pytest.raises(errors.CorpusPermanentDeleteForbidden):
        await library.permanently_delete(
            SOURCE_ID,
            expected_revision=2,
            confirm_permanent_delete=True,
        )

    await library.archive(SOURCE_ID, expected_revision=2)
    repository.versions[1]["reference_count"] = 1
    with pytest.raises(errors.CorpusPermanentDeleteForbidden) as referenced:
        await library.permanently_delete(
            SOURCE_ID,
            expected_revision=2,
            confirm_permanent_delete=True,
        )
    assert referenced.value.code == "CorpusPermanentDeleteForbidden"
    assert repository.deleted is False

    repository.versions[1]["reference_count"] = 0
    with pytest.raises(errors.CorpusPermanentDeleteForbidden):
        await library.permanently_delete(
            SOURCE_ID,
            expected_revision=2,
            confirm_permanent_delete=False,
        )

    await library.permanently_delete(
        SOURCE_ID,
        expected_revision=2,
        confirm_permanent_delete=True,
    )
    assert repository.deleted is True
    with pytest.raises(errors.CorpusResourceNotFound):
        await library.get_source(SOURCE_ID, preview_chars=100)


@pytest.mark.asyncio
async def test_blob_tombstone_is_restored_when_database_commit_fails(
    workspace_tmp_path,
):
    content_hash = "d" * 64
    managed_root = workspace_tmp_path / "managed"
    blob = managed_root / "sha256" / "dd" / content_hash
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"managed synthetic bytes")
    repository = MemoryCorpusRepository()
    repository.row["archived_at"] = 1_900_000_000_000
    repository.blob_candidates = ({
        "content_hash": content_hash,
        "byte_length": len(b"managed synthetic bytes"),
        "storage_key": f"sha256/dd/{content_hash}",
    },)

    @asynccontextmanager
    async def failed_commit():
        yield object()
        raise RuntimeError("synthetic commit failure")

    library = service(
        repository,
        managed_root=managed_root,
        transaction_factory=failed_commit,
    )
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        await library.permanently_delete(SOURCE_ID, 2, True)

    assert blob.read_bytes() == b"managed synthetic bytes"
    assert not (managed_root / ".deleting").exists()
    assert not (managed_root / ".project-import-staging" / ".claims").exists()


@pytest.mark.asyncio
async def test_permanent_delete_cancellation_releases_every_partially_acquired_claim(
    workspace_tmp_path, monkeypatch,
):
    managed_root = workspace_tmp_path / "managed"
    managed_root.mkdir()
    repository = MemoryCorpusRepository()
    repository.row["archived_at"] = 1_900_000_000_000
    values = tuple((sha256(data).hexdigest(), data) for data in (b"first", b"second"))
    repository.blob_candidates = tuple({
        "content_hash": digest,
        "byte_length": len(data),
        "storage_key": f"sha256/{digest[:2]}/{digest}",
    } for digest, data in values)
    claims = importlib.import_module("backend.services.project_imports")
    real_acquire = claims.ProjectImportStaging._acquire_claim
    calls = 0

    async def cancel_second(self, item):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise asyncio.CancelledError()
        return await real_acquire(self, item)

    monkeypatch.setattr(claims.ProjectImportStaging, "_acquire_claim", cancel_second)
    with pytest.raises(asyncio.CancelledError):
        await service(repository, managed_root=managed_root).permanently_delete(
            SOURCE_ID, 2, True,
        )

    assert calls == 2
    assert repository.deleted is False
    assert not (managed_root / ".project-import-staging" / ".claims").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_name", [
    "ProjectImportCommandStateConflict", "ProjectImportPersistenceError",
])
async def test_permanent_delete_maps_digest_claim_failure_to_lifecycle_conflict(
    workspace_tmp_path, monkeypatch, error_name,
):
    managed_root = workspace_tmp_path / "managed"
    managed_root.mkdir()
    repository = MemoryCorpusRepository()
    repository.row["archived_at"] = 1_900_000_000_000
    digest = sha256(b"shared").hexdigest()
    repository.blob_candidates = ({
        "content_hash": digest, "byte_length": 6,
        "storage_key": f"sha256/{digest[:2]}/{digest}",
    },)
    claims = importlib.import_module("backend.services.project_imports")
    claim_error = getattr(
        importlib.import_module("backend.repositories.project_imports"), error_name,
    )()

    async def fail_acquire(self, item):
        raise claim_error

    monkeypatch.setattr(claims.ProjectImportStaging, "_acquire_claim", fail_acquire)
    with pytest.raises(http_errors_module().CorpusLifecycleConflict) as raised:
        await service(repository, managed_root=managed_root).permanently_delete(
            SOURCE_ID, 2, True,
        )

    assert raised.value.code == "CorpusLifecycleConflict"
    assert raised.value.__cause__ is None
    assert str(raised.value) == str(http_errors_module().CorpusLifecycleConflict())
    assert repository.deleted is False


@pytest.mark.asyncio
async def test_permanent_delete_waits_for_same_digest_publisher_commit(
    workspace_tmp_path, monkeypatch,
):
    raw = b"shared publication bytes"
    content_hash = sha256(raw).hexdigest()
    managed_root = workspace_tmp_path / "managed"
    blob = managed_root / "sha256" / content_hash[:2] / content_hash
    blob.parent.mkdir(parents=True)
    blob.write_bytes(raw)
    repository = MemoryCorpusRepository()
    repository.row["archived_at"] = 1_900_000_000_000
    repository.blob_candidates = ({
        "content_hash": content_hash,
        "byte_length": len(raw),
        "storage_key": f"sha256/{content_hash[:2]}/{content_hash}",
    },)
    publisher_committed = False

    async def delete_unreferenced(_session, candidates):
        return () if publisher_committed else tuple(candidates)

    repository.delete_unreferenced_blobs = delete_unreferenced
    claims = importlib.import_module("backend.services.project_imports")
    owner = claims._digest_claim_owner(
        managed_root, owner_id="publisher",
        blobs=(claims.StagedBlob(
            content_hash, len(raw),
            f"sha256/{content_hash[:2]}/{content_hash}", False,
        ),),
    )
    claim = await owner._acquire_claim(owner.blobs[0])
    owner._held_claims[content_hash] = claim
    waiting = asyncio.Event()

    async def controlled_sleep(_delay):
        waiting.set()
        await asyncio.sleep(0)

    monkeypatch.setattr(claims, "_claim_sleep", controlled_sleep)
    deletion = asyncio.create_task(
        service(repository, managed_root=managed_root).permanently_delete(
            SOURCE_ID, 2, True,
        )
    )
    await waiting.wait()
    assert repository.deleted is False
    publisher_committed = True
    owner._release_held_claims()
    await deletion

    assert repository.deleted is True
    assert blob.read_bytes() == raw
    assert not claim.parent.exists()


@pytest.mark.asyncio
async def test_committed_delete_cleanup_failure_is_persisted_and_retryable(
    workspace_tmp_path,
    monkeypatch,
):
    raw = b"retryable synthetic bytes"
    content_hash = sha256(raw).hexdigest()
    managed_root = workspace_tmp_path / "managed"
    blob = managed_root / "sha256" / content_hash[:2] / content_hash
    blob.parent.mkdir(parents=True)
    blob.write_bytes(raw)
    repository = MemoryCorpusRepository()
    repository.row["archived_at"] = 1_900_000_000_000
    repository.blob_candidates = ({
        "content_hash": content_hash,
        "byte_length": len(raw),
        "storage_key": f"sha256/{content_hash[:2]}/{content_hash}",
    },)
    library = service(
        repository,
        managed_root=managed_root,
    )
    original_finish = library._finish_blob_deletions
    attempts = 0

    def fail_once(moves):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("synthetic post-commit cleanup failure")
        return original_finish(moves)

    monkeypatch.setattr(library, "_finish_blob_deletions", fail_once)

    first = await library.permanently_delete(SOURCE_ID, 2, True)
    replay = await library.permanently_delete(SOURCE_ID, 2, True)

    assert first["cleanup_pending"] is True
    assert replay["cleanup_pending"] is False
    assert not blob.exists()
    assert not (managed_root / ".deleting").exists()


@pytest.mark.asyncio
async def test_restore_replay_rejects_a_tombstone_file_link(
    workspace_tmp_path,
):
    content_hash = "f" * 64
    managed_root = workspace_tmp_path / "managed"
    final = managed_root / "sha256" / "ff" / content_hash
    final.parent.mkdir(parents=True)
    deleting = managed_root / ".deleting"
    deleting.mkdir()
    outside = workspace_tmp_path / "outside.txt"
    outside.write_bytes(b"outside sentinel")
    tombstone_name = f"{content_hash}.{'1' * 64}.part"
    trash = deleting / tombstone_name
    try:
        trash.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")
    repository = MemoryCorpusRepository()
    repository.row["archived_at"] = 1_900_000_000_000
    repository.deletion_commands[SOURCE_ID] = {
        "source_id": SOURCE_ID,
        "expected_revision": 2,
        "status": "restore_pending",
        "tombstones_json": [{
            "contentHash": content_hash,
            "storageKey": f"sha256/ff/{content_hash}",
            "tombstoneName": tombstone_name,
        }],
        "created_at": 1,
        "updated_at": 1,
    }
    library = service(repository, managed_root=managed_root)

    with pytest.raises(http_errors_module().CorpusLifecycleConflict):
        await library.permanently_delete(SOURCE_ID, 2, True)

    assert outside.read_bytes() == b"outside sentinel"
    assert not final.exists()
    assert not final.is_symlink()
