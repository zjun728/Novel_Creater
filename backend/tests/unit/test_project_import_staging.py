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
    try:
        with pytest.raises(OSError):
            await staging.promote(lambda _: None)
    finally:
        staging.cleanup_root()
    assert not managed_corpus_blob_path(managed, digest).exists()
    assert not staging.root.exists()
    assert not (staging.root.parent / project_imports.CLAIM_DIRECTORY).exists()


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
async def test_same_digest_waits_for_delayed_manifest_winner_and_leaves_no_residue(
    tmp_path, monkeypatch,
):
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
    manifest_started = asyncio.Event()
    release_manifest = asyncio.Event()
    wait_rounds = 0
    link_calls = 0
    real_link = project_imports.os.link

    async def delayed_manifest(_value):
        manifest_started.set()
        await release_manifest.wait()

    def counted_link(source, destination):
        nonlocal link_calls
        link_calls += 1
        return real_link(source, destination)

    async def controlled_sleep(_delay):
        nonlocal wait_rounds
        wait_rounds += 1
        if wait_rounds == 65:
            release_manifest.set()
        await asyncio.sleep(0)

    monkeypatch.setattr(project_imports.os, "link", counted_link)
    monkeypatch.setattr(project_imports, "_claim_sleep", controlled_sleep)
    first_task = asyncio.create_task(first.promote(delayed_manifest))
    await manifest_started.wait()
    second_task = asyncio.create_task(second.promote(lambda _value: None))
    await asyncio.gather(first_task, second_task)

    assert wait_rounds >= 65
    assert link_calls == 1
    assert sorted((first.blobs[0].created, second.blobs[0].created)) == [False, True]
    first.cleanup_root()
    second.cleanup_root()
    staging_parent = managed / project_imports.STAGING_DIRECTORY
    assert list(staging_parent.iterdir()) == []
    assert not (staging_parent / project_imports.CLAIM_DIRECTORY).exists()
    assert managed_corpus_blob_path(managed, digest).read_bytes() == b"shared"


@pytest.mark.asyncio
async def test_claim_wait_uses_exact_monotonic_deadline_and_capped_backoff(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    owner = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    waiter = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed,
        command_id="22222222-2222-4222-8222-222222222222",
    )
    claim = await owner._acquire_claim(owner.blobs[0])
    now = 100.0
    sleeps = []

    def monotonic():
        return now

    async def sleep(delay):
        nonlocal now
        sleeps.append(delay)
        now += delay

    monkeypatch.setattr(project_imports, "_claim_monotonic", monotonic)
    monkeypatch.setattr(project_imports, "_claim_sleep", sleep)
    try:
        with pytest.raises(ProjectImportCommandStateConflict):
            await waiter._acquire_claim(waiter.blobs[0])
    finally:
        owner._release_claim(claim)
        owner.cleanup_root()
        waiter.cleanup_root()

    assert sleeps[:6] == pytest.approx([0.01, 0.02, 0.04, 0.08, 0.16, 0.25])
    assert max(sleeps) == pytest.approx(0.25)
    assert sum(sleeps) == pytest.approx(30.0)
    assert now == pytest.approx(130.0)
    assert not claim.exists()
    assert not owner.root.exists()
    assert not waiter.root.exists()
    assert not claim.parent.exists()


@pytest.mark.asyncio
async def test_claim_parent_disappearance_obeys_exact_deadline_and_backoff(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, _ = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    now = 100.0
    sleeps = []
    attempts = 0
    real_open = project_imports.os.open

    def monotonic():
        return now

    async def sleep(delay):
        nonlocal now
        sleeps.append(delay)
        now += delay

    def disappearing_parent(path, flags, mode=0o777):
        nonlocal attempts
        if Path(path).parent.name == project_imports.CLAIM_DIRECTORY:
            attempts += 1
            if attempts > 1_000:
                raise AssertionError("claim recreation bypassed deadline")
            Path(path).parent.rmdir()
            raise FileNotFoundError()
        return real_open(path, flags, mode)

    monkeypatch.setattr(project_imports, "_claim_monotonic", monotonic)
    monkeypatch.setattr(project_imports, "_claim_sleep", sleep)
    monkeypatch.setattr(project_imports.os, "open", disappearing_parent)
    try:
        with pytest.raises(ProjectImportCommandStateConflict):
            await staging._acquire_claim(staging.blobs[0])
    finally:
        staging.cleanup_root()

    assert sleeps[:6] == pytest.approx([0.01, 0.02, 0.04, 0.08, 0.16, 0.25])
    assert max(sleeps) == pytest.approx(0.25)
    assert sum(sleeps) == pytest.approx(30.0)
    assert now == pytest.approx(130.0)
    assert not staging.root.exists()
    assert not (staging.root.parent / project_imports.CLAIM_DIRECTORY).exists()


@pytest.mark.asyncio
async def test_claim_parent_file_fails_immediately_without_contention_wait(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, _ = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    claim_parent = staging.root.parent / project_imports.CLAIM_DIRECTORY
    claim_parent.write_text("not-a-directory", encoding="ascii")

    async def unexpected_sleep(_delay):
        raise AssertionError("malformed claim parent was treated as contention")

    monkeypatch.setattr(project_imports, "_claim_sleep", unexpected_sleep)
    try:
        with pytest.raises(ProjectImportInvalid):
            await staging._acquire_claim(staging.blobs[0])
    finally:
        claim_parent.unlink()
        staging.cleanup_root()

    assert not staging.root.exists()


@pytest.mark.asyncio
async def test_claim_wait_cancellation_preserves_existing_owner(tmp_path, monkeypatch):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    owner = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    waiter = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed,
        command_id="22222222-2222-4222-8222-222222222222",
    )
    manifest_started = asyncio.Event()
    release_manifest = asyncio.Event()
    sleeping = asyncio.Event()

    async def delayed_manifest(_value):
        manifest_started.set()
        await release_manifest.wait()

    async def sleep(_delay):
        sleeping.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(project_imports, "_claim_sleep", sleep)
    owner_task = asyncio.create_task(owner.promote(delayed_manifest))
    await manifest_started.wait()
    acquisition = asyncio.create_task(waiter.promote(lambda _value: None))
    await sleeping.wait()
    acquisition.cancel()
    with pytest.raises(asyncio.CancelledError):
        await acquisition
    claim = owner.root.parent / project_imports.CLAIM_DIRECTORY / digest
    assert claim.read_text("ascii") == COMMAND
    release_manifest.set()
    await owner_task
    owner.cleanup_root()
    waiter.cleanup_root()
    assert not owner.root.exists()
    assert not waiter.root.exists()
    assert not claim.parent.exists()


@pytest.mark.asyncio
async def test_persist_failure_outer_cleanup_leaves_no_claim_or_root(tmp_path, monkeypatch):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, _ = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )

    async def fail_persist(_value):
        raise RuntimeError("injected")

    try:
        with pytest.raises(RuntimeError, match="injected"):
            await staging.promote(fail_persist)
    finally:
        staging.cleanup_root()

    assert not staging.root.exists()
    assert not (staging.root.parent / project_imports.CLAIM_DIRECTORY).exists()


@pytest.mark.asyncio
async def test_destination_conflict_outer_cleanup_leaves_no_claim_or_root(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    destination = managed_corpus_blob_path(managed, digest)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"evil")

    try:
        with pytest.raises(ProjectImportCommandStateConflict):
            await staging.promote(lambda _value: None)
    finally:
        staging.cleanup_root()

    assert destination.read_bytes() == b"evil"
    assert not staging.root.exists()
    assert not (staging.root.parent / project_imports.CLAIM_DIRECTORY).exists()


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
