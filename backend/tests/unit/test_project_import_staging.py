import asyncio
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from backend.domain.project_imports import ProjectImportInvalid
from backend.repositories.project_imports import ProjectImportCommandStateConflict
from backend.security.paths import managed_corpus_blob_path
from backend.services import project_imports
from backend.services.project_imports import ProjectImportService
from contextlib import asynccontextmanager


COMMAND = "11111111-1111-4111-8111-111111111111"


def _package(tmp_path: Path, data: bytes, *, archive_data: bytes | None = None):
    digest = sha256(data).hexdigest()
    archive = tmp_path / "package.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr(f"corpus/blobs/sha256/{digest}", data if archive_data is None else archive_data)
    package = SimpleNamespace(archive_path=archive)
    plan = SimpleNamespace(blobs=((digest, len(data)),), id_map_hash="a" * 64)
    return package, plan, digest


def _no_acl(monkeypatch):
    monkeypatch.setattr(project_imports, "apply_private_permissions", lambda *_args, **_kwargs: None)


@pytest.mark.asyncio
async def test_stage_writes_manifest_before_safe_promotion(tmp_path, monkeypatch):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"corpus")

    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    assert (staging.root / project_imports.STAGING_MANIFEST).is_file()
    assert staging.manifest["blobs"][0] == {
        "byteLength": 6,
        "contentHash": digest,
        "created": False,
        "storageKey": f"sha256/{digest[:2]}/{digest}",
    }
    persisted = []
    await staging.promote(persisted.append)
    assert managed_corpus_blob_path(managed, digest).read_bytes() == b"corpus"
    assert staging.blobs[0].created is True
    assert persisted


def test_stage_rejects_short_or_hash_mismatched_source(tmp_path, monkeypatch):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, _ = _package(tmp_path, b"expected", archive_data=b"wrong")
    with pytest.raises(ProjectImportInvalid):
        project_imports.ProjectImportStaging.stage(
            package, plan, managed_corpus_root=managed, command_id=COMMAND,
        )
    assert list((managed / project_imports.STAGING_DIRECTORY).iterdir()) == []


def test_stage_acl_failure_uses_validated_owned_cleanup(tmp_path, monkeypatch):
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, _ = _package(tmp_path, b"expected")
    calls = 0

    def fail_file_acl(path, *, is_directory):
        nonlocal calls
        calls += 1
        if not is_directory:
            raise project_imports.PrivateFilePermissionsError()

    monkeypatch.setattr(project_imports, "apply_private_permissions", fail_file_acl)
    with pytest.raises(ProjectImportInvalid):
        project_imports.ProjectImportStaging.stage(
            package, plan, managed_corpus_root=managed, command_id=COMMAND,
        )
    assert calls >= 3
    assert list((managed / project_imports.STAGING_DIRECTORY).iterdir()) == []


def test_existing_matching_blob_is_reused_and_mismatch_is_never_overwritten(tmp_path, monkeypatch):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"same")
    destination = managed_corpus_blob_path(managed, digest)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"same")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    assert staging.blobs[0].created is False
    staging.cleanup_root()

    destination.write_bytes(b"evil")
    with pytest.raises(ProjectImportCommandStateConflict):
        project_imports.ProjectImportStaging.stage(
            package, plan, managed_corpus_root=managed,
            command_id="22222222-2222-4222-8222-222222222222",
        )
    assert destination.read_bytes() == b"evil"


@pytest.mark.asyncio
async def test_link_failure_leaves_no_claim_of_target_creation(tmp_path, monkeypatch):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"bytes")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    monkeypatch.setattr(project_imports.os, "link", lambda *_: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        await staging.promote(lambda _: None)
    assert not managed_corpus_blob_path(managed, digest).exists()


@pytest.mark.asyncio
async def test_concurrent_same_digest_has_one_actual_installer(tmp_path, monkeypatch):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    first = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    second = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed,
        command_id="22222222-2222-4222-8222-222222222222",
    )
    await asyncio.gather(
        first.promote(lambda _: None), second.promote(lambda _: None),
    )
    assert sorted((first.blobs[0].created, second.blobs[0].created)) == [False, True]
    assert managed_corpus_blob_path(managed, digest).read_bytes() == b"shared"


@pytest.mark.asyncio
async def test_prewritten_owner_with_link_failure_never_deletes_later_winner(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    temp = tmp_path / "temp"
    managed.mkdir()
    temp.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    failed = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    winner = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed,
        command_id="22222222-2222-4222-8222-222222222222",
    )
    real_link = project_imports.os.link

    def fail_first_link(source, destination):
        if COMMAND in str(source):
            raise OSError("injected")
        return real_link(source, destination)

    monkeypatch.setattr(project_imports.os, "link", fail_first_link)
    with pytest.raises(OSError):
        await failed.promote(lambda _: None)
    assert failed.blobs[0].created is True  # crash-recovery decision was persisted
    assert failed._installed_hashes == set()
    await winner.promote(lambda _: None)
    assert winner._installed_hashes == {digest}

    class Repository:
        async def corpus_blob_is_referenced(self, session, *, content_hash):
            return False

    @asynccontextmanager
    async def connect():
        yield object()

    service = ProjectImportService(
        repository=Repository(), managed_corpus_root=managed, temp_parent=temp,
        connection_factory=connect,
    )
    await service._cleanup_unreferenced_created(failed)
    assert managed_corpus_blob_path(managed, digest).read_bytes() == b"shared"


def test_stage_cleanup_retries_one_owned_filesystem_failure(tmp_path, monkeypatch):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, _ = _package(tmp_path, b"bytes")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    original = project_imports.shutil.rmtree
    calls = 0

    def flaky(path, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError()
        return original(path, *args, **kwargs)

    monkeypatch.setattr(project_imports.shutil, "rmtree", flaky)
    staging.cleanup_root()
    assert calls == 2
    assert not staging.root.exists()
