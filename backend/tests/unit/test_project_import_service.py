import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from backend.services.project_imports import (
    ImportProjectRequest,
    ProjectImportService,
    reconcile_project_import_staging,
)
from backend.repositories.project_imports import ProjectImportCommandView
from backend.repositories.project_imports import ProjectImportRecoveryCommand
from backend.domain.json_contracts import canonical_json
from backend.security.paths import managed_corpus_blob_path, managed_corpus_storage_key
from hashlib import sha256
from backend.services import project_imports


def test_request_is_closed_and_normalized():
    request = ImportProjectRequest(
        "11111111-1111-4111-8111-111111111111",
        "same_import_key1", "a" * 64, "Imported",
    )
    assert request.new_title == "Imported"
    with pytest.raises(Exception):
        ImportProjectRequest(request.command_id, request.idempotency_key, "A" * 64, " Imported ")


@pytest.mark.asyncio
async def test_preflight_cleanup_preserves_cancelled_error(tmp_path, monkeypatch):
    managed = tmp_path / "managed"
    temp = tmp_path / "temp"
    managed.mkdir()
    temp.mkdir()
    service = ProjectImportService(
        repository=object(), managed_corpus_root=managed, temp_parent=temp,
    )

    class Upload:
        async def read(self, _size):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await service.preflight(Upload())
    assert list(temp.iterdir()) == []


@pytest.mark.asyncio
async def test_reconcile_is_bounded_and_ignores_unowned_roots(tmp_path):
    managed = tmp_path / "managed"
    parent = managed / ".project-import-staging"
    parent.mkdir(parents=True)
    (parent / "unrelated").mkdir()
    for index in range(40):
        (parent / f"00000000-0000-4000-8000-{index:012d}").mkdir()

    class Session:
        pass

    class Repository:
        async def list_recovery_commands(self, session, **kwargs):
            return ()

    @asynccontextmanager
    async def connect():
        yield Session()

    assert await reconcile_project_import_staging(
        managed_corpus_root=managed, connection_factory=connect, now_ms=1,
        repository=Repository(),
    ) <= 32
    assert (parent / "unrelated").is_dir()


@pytest.mark.asyncio
async def test_reconcile_refuses_disk_manifest_that_differs_from_db_authority(tmp_path):
    managed = tmp_path / "managed"
    parent = managed / ".project-import-staging"
    parent.mkdir(parents=True)
    command = "11111111-1111-4111-8111-111111111111"
    data = b"owned"
    digest = sha256(data).hexdigest()
    target = managed_corpus_blob_path(managed, digest)
    target.parent.mkdir(parents=True)
    target.write_bytes(data)
    root = parent / command
    root.mkdir()
    disk = {
        "blobs": [{"byteLength": len(data), "contentHash": digest, "created": True,
                   "storageKey": managed_corpus_storage_key(digest)}],
        "commandId": command, "idMapHash": "a" * 64,
    }
    (root / "manifest.json").write_text(canonical_json(disk), encoding="utf-8")
    authority = {**disk, "blobs": [{**disk["blobs"][0], "created": False}]}

    class Repository:
        async def list_recovery_commands(self, session, **kwargs):
            return (ProjectImportRecoveryCommand(command, "failed", canonical_json(authority)),)

        async def fence_recovery_command(self, session, *, candidate, now_ms):
            return candidate

    @asynccontextmanager
    async def connect():
        yield object()

    assert await reconcile_project_import_staging(
        managed_corpus_root=managed, connection_factory=connect, now_ms=1,
        repository=Repository(), transaction_factory=connect,
    ) == 1
    assert root.is_dir()
    assert target.read_bytes() == data


@pytest.mark.asyncio
async def test_recovery_fence_cleans_predecision_stale_claim_but_race_loser_does_nothing(tmp_path):
    managed = tmp_path / "managed"
    parent = managed / ".project-import-staging"
    claims = parent / ".claims"
    claims.mkdir(parents=True)
    command = "11111111-1111-4111-8111-111111111111"
    digest = sha256(b"claim").hexdigest()
    manifest = {
        "blobs": [{"byteLength": 5, "contentHash": digest, "created": False,
                   "storageKey": managed_corpus_storage_key(digest)}],
        "commandId": command, "idMapHash": "a" * 64,
    }
    root = parent / command
    root.mkdir()
    (root / "manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
    claim = claims / digest
    claim.write_text(command, encoding="ascii")
    candidate = ProjectImportRecoveryCommand(command, "running", canonical_json(manifest))

    class Repository:
        def __init__(self, fenced):
            self.fenced = fenced

        async def list_recovery_commands(self, session, **kwargs):
            return (candidate,)

        async def fence_recovery_command(self, session, **kwargs):
            return candidate if self.fenced else None

    @asynccontextmanager
    async def connect():
        yield object()

    assert await reconcile_project_import_staging(
        managed_corpus_root=managed, connection_factory=connect,
        transaction_factory=connect, repository=Repository(False), now_ms=10,
    ) == 1
    assert claim.read_text("ascii") == command and root.is_dir()

    assert await reconcile_project_import_staging(
        managed_corpus_root=managed, connection_factory=connect,
        transaction_factory=connect, repository=Repository(True), now_ms=10,
    ) == 1
    assert not claim.exists() and not root.exists()


@pytest.mark.asyncio
async def test_terminal_recovery_never_removes_claim_owned_by_another_command(tmp_path):
    managed = tmp_path / "managed"
    parent = managed / ".project-import-staging"
    claims = parent / ".claims"
    claims.mkdir(parents=True)
    command = "11111111-1111-4111-8111-111111111111"
    other = "22222222-2222-4222-8222-222222222222"
    digest = sha256(b"claim").hexdigest()
    manifest = {
        "blobs": [{"byteLength": 5, "contentHash": digest, "created": False,
                   "storageKey": managed_corpus_storage_key(digest)}],
        "commandId": command, "idMapHash": "a" * 64,
    }
    root = parent / command
    root.mkdir()
    (root / "manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
    claim = claims / digest
    claim.write_text(other, encoding="ascii")
    candidate = ProjectImportRecoveryCommand(command, "failed", canonical_json(manifest))

    class Repository:
        async def list_recovery_commands(self, session, **kwargs): return (candidate,)
        async def fence_recovery_command(self, session, **kwargs): return candidate

    @asynccontextmanager
    async def connect(): yield object()

    await reconcile_project_import_staging(
        managed_corpus_root=managed, connection_factory=connect,
        transaction_factory=connect, repository=Repository(), now_ms=10,
    )
    assert claim.read_text("ascii") == other
    assert root.is_dir()

    claim.unlink()
    await reconcile_project_import_staging(
        managed_corpus_root=managed, connection_factory=connect,
        transaction_factory=connect, repository=Repository(), now_ms=10,
    )
    assert not root.exists()
    assert not claims.exists()


@pytest.mark.asyncio
async def test_recovery_keeps_full_multi_blob_authority_when_one_claim_is_blocked(tmp_path):
    managed = tmp_path / "managed"
    parent = managed / ".project-import-staging"
    claims = parent / ".claims"
    claims.mkdir(parents=True)
    command = "11111111-1111-4111-8111-111111111111"
    values = tuple((sha256(data).hexdigest(), data) for data in (b"first", b"second"))
    manifest = {
        "blobs": [{
            "byteLength": len(data), "contentHash": digest, "created": False,
            "storageKey": managed_corpus_storage_key(digest),
        } for digest, data in values],
        "commandId": command, "idMapHash": "a" * 64,
    }
    root = parent / command
    root.mkdir()
    manifest_path = root / "manifest.json"
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
    blocked = claims / values[0][0]
    blocked.write_text("other:token", encoding="ascii")
    candidate = ProjectImportRecoveryCommand(command, "failed", canonical_json(manifest))

    class Repository:
        async def list_recovery_commands(self, session, **kwargs): return (candidate,)
        async def fence_recovery_command(self, session, **kwargs): return candidate

    @asynccontextmanager
    async def connect(): yield object()

    await reconcile_project_import_staging(
        managed_corpus_root=managed, connection_factory=connect,
        transaction_factory=connect, repository=Repository(), now_ms=10,
    )

    assert root.is_dir()
    assert manifest_path.read_text("utf-8") == canonical_json(manifest)
    assert blocked.read_text("ascii") == "other:token"


@pytest.mark.asyncio
async def test_recovery_retries_transient_claim_release_before_removing_authority(
    tmp_path, monkeypatch,
):
    managed = tmp_path / "managed"
    parent = managed / project_imports.STAGING_DIRECTORY
    parent.mkdir(parents=True)
    command = "11111111-1111-4111-8111-111111111111"
    digest = sha256(b"claim").hexdigest()
    manifest = {
        "blobs": [{
            "byteLength": 5, "contentHash": digest, "created": False,
            "storageKey": managed_corpus_storage_key(digest),
        }],
        "commandId": command, "idMapHash": "a" * 64,
    }
    root = parent / command
    root.mkdir()
    (root / "manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
    candidate = ProjectImportRecoveryCommand(command, "failed", canonical_json(manifest))

    class Repository:
        async def list_recovery_commands(self, session, **kwargs): return (candidate,)
        async def fence_recovery_command(self, session, **kwargs): return candidate

    @asynccontextmanager
    async def connect(): yield object()

    claim = parent / project_imports.CLAIM_DIRECTORY / digest
    real_unlink = project_imports.Path.unlink
    attempts = 0

    def fail_once(path, *args, **kwargs):
        nonlocal attempts
        if path == claim:
            attempts += 1
            if attempts == 1:
                raise OSError("transient release")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(project_imports.Path, "unlink", fail_once)
    assert await reconcile_project_import_staging(
        managed_corpus_root=managed, connection_factory=connect,
        transaction_factory=connect, repository=Repository(), now_ms=10,
    ) == 1

    assert attempts == 2
    assert not root.exists()
    assert not claim.parent.exists()


@pytest.mark.asyncio
async def test_recovery_permanent_release_failure_preserves_authority_and_scans_next(
    tmp_path, monkeypatch,
):
    managed = tmp_path / "managed"
    parent = managed / project_imports.STAGING_DIRECTORY
    parent.mkdir(parents=True)
    commands = (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    )
    digests = (sha256(b"first").hexdigest(), sha256(b"second").hexdigest())
    candidates = []
    roots = []
    for command, digest in zip(commands, digests, strict=True):
        manifest = {
            "blobs": [{
                "byteLength": 0, "contentHash": digest, "created": False,
                "storageKey": managed_corpus_storage_key(digest),
            }],
            "commandId": command, "idMapHash": "a" * 64,
        }
        root = parent / command
        root.mkdir()
        (root / "manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
        roots.append(root)
        candidates.append(ProjectImportRecoveryCommand(
            command, "failed", canonical_json(manifest),
        ))

    class Repository:
        async def list_recovery_commands(self, session, **kwargs): return tuple(candidates)
        async def fence_recovery_command(self, session, *, candidate, **kwargs): return candidate

    @asynccontextmanager
    async def connect(): yield object()

    blocked_claim = parent / project_imports.CLAIM_DIRECTORY / digests[0]
    real_unlink = project_imports.Path.unlink

    def fail_first_claim(path, *args, **kwargs):
        if path == blocked_claim:
            raise OSError("permanent release")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(project_imports.Path, "unlink", fail_first_claim)
    assert await reconcile_project_import_staging(
        managed_corpus_root=managed, connection_factory=connect,
        transaction_factory=connect, repository=Repository(), now_ms=10,
    ) == 2

    assert roots[0].is_dir()
    assert blocked_claim.is_file()
    assert not roots[1].exists()


@pytest.mark.asyncio
async def test_import_repreflights_reserves_stages_and_publishes_once(tmp_path, monkeypatch):
    events = []
    managed = tmp_path / "managed"
    temp = tmp_path / "temp"
    managed.mkdir()
    temp.mkdir()
    package = SimpleNamespace(
        package_hash="a" * 64, manifest_hash="b" * 64,
        summary=SimpleNamespace(package_version=1),
    )
    plan = SimpleNamespace(target_project_id="target", id_map_hash="c" * 64)
    command = "11111111-1111-4111-8111-111111111111"
    running = ProjectImportCommandView(command, "running", "preflighted", False, None, None)
    succeeded = ProjectImportCommandView(command, "succeeded", "succeeded", False, "target", None)

    class Repository:
        async def reserve_command(self, session, **kwargs):
            events.append("reserve")
            return running

        async def acquire_lease(self, session, **kwargs):
            events.append("lease")
            return running

        async def publish_project(self, session, actual_plan, **kwargs):
            assert actual_plan is plan
            events.append("publish")

        async def persist_staging_manifest(self, session, **kwargs):
            events.append("manifest")

        async def read_command(self, session, **kwargs):
            events.append("read")
            return succeeded

    class Session:
        async def fetchone(self, sql, args):
            return None

    transaction_count = 0

    @asynccontextmanager
    async def transact():
        nonlocal transaction_count
        transaction_count += 1
        yield Session()

    @asynccontextmanager
    async def connect():
        yield Session()

    class Quarantine:
        def cleanup(self):
            events.append("quarantine-clean")

    class Staging:
        manifest = MappingProxyType({"idMapHash": "c" * 64, "blobs": [], "commandId": command})
        blobs = ()

        async def promote(self, persist):
            events.append("promote")

        def cleanup_root(self):
            events.append("stage-clean")

    service = ProjectImportService(
        repository=Repository(), managed_corpus_root=managed, temp_parent=temp,
        connection_factory=connect, transaction_factory=transact,
        clock=lambda: 10, owner_factory=lambda: "owner",
    )

    async def verified(upload):
        events.append("preflight")
        return Quarantine(), package

    monkeypatch.setattr(service, "_verified", verified)
    monkeypatch.setattr(project_imports, "build_publication_plan", lambda *args: plan)
    monkeypatch.setattr(project_imports.ProjectImportStaging, "stage", lambda *args, **kwargs: Staging())

    result = await service.import_project(object(), ImportProjectRequest(
        command, "same_import_key1", "a" * 64, "Imported",
    ))
    assert result is succeeded
    assert transaction_count == 3
    assert events.index("preflight") < events.index("reserve") < events.index("manifest")
    assert events.index("manifest") < events.index("promote") < events.index("publish")
    assert events[-2:] == ["stage-clean", "quarantine-clean"]
