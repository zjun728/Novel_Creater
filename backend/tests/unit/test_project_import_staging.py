import asyncio
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from backend.domain.project_imports import ProjectImportInvalid
from backend.repositories.project_imports import (
    ProjectImportCommandStateConflict,
    ProjectImportPersistenceError,
)
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
    destination = managed_corpus_blob_path(managed, digest)
    real_link = project_imports.os.link

    def fail_blob_link(source, target):
        if Path(target) == destination:
            raise OSError()
        return real_link(source, target)

    monkeypatch.setattr(project_imports.os, "link", fail_blob_link)
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
    claim_collisions = 0
    claim = first.root.parent / project_imports.CLAIM_DIRECTORY / digest
    real_link = project_imports.os.link

    async def delayed_manifest(_value):
        manifest_started.set()
        await release_manifest.wait()

    def counted_link(source, destination):
        nonlocal claim_collisions, link_calls
        if Path(destination) == managed_corpus_blob_path(managed, digest):
            link_calls += 1
        try:
            return real_link(source, destination)
        except FileExistsError:
            if Path(destination) == claim:
                claim_collisions += 1
                assert claim.read_text("ascii") == COMMAND
            raise

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
    assert claim_collisions >= 65
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
async def test_claim_deadline_is_rechecked_after_sleep_before_released_claim_can_open(
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
    real_link = project_imports.os.link
    now = 100.0
    claim_open_attempts = 0

    def monotonic():
        return now

    def counted_link(source, destination):
        nonlocal claim_open_attempts
        if Path(destination) == claim:
            claim_open_attempts += 1
        return real_link(source, destination)

    async def overshooting_sleep(_delay):
        nonlocal now
        now = 131.0
        owner._release_claim(claim)

    monkeypatch.setattr(project_imports, "_claim_monotonic", monotonic)
    monkeypatch.setattr(project_imports, "_claim_sleep", overshooting_sleep)
    monkeypatch.setattr(project_imports.os, "link", counted_link)
    try:
        with pytest.raises(ProjectImportCommandStateConflict):
            await waiter._acquire_claim(waiter.blobs[0])
    finally:
        if claim.exists():
            if claim.read_text("ascii") == waiter.command_id:
                waiter._release_claim(claim)
            else:
                owner._release_claim(claim)
        owner.cleanup_root()
        waiter.cleanup_root()

    assert claim_open_attempts == 1
    assert not owner.root.exists()
    assert not waiter.root.exists()
    assert not claim.parent.exists()


@pytest.mark.asyncio
async def test_claim_keeps_one_immediate_attempt_before_deadline_checks(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, _ = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    ticks = iter((100.0, 130.0))
    monkeypatch.setattr(project_imports, "_claim_monotonic", lambda: next(ticks))

    claim = await staging._acquire_claim(staging.blobs[0])
    staging._release_claim(claim)
    staging.cleanup_root()

    assert not staging.root.exists()
    assert not claim.parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_exists", [False, True])
async def test_claim_parent_acl_runs_once_only_when_parent_is_new(
    tmp_path, monkeypatch, parent_exists,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, _ = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    claim_parent = staging.root.parent / project_imports.CLAIM_DIRECTORY
    if parent_exists:
        claim_parent.mkdir()
    parent_acl_calls = 0

    def count_acl(path, *, is_directory):
        nonlocal parent_acl_calls
        if Path(path) == claim_parent:
            parent_acl_calls += 1

    monkeypatch.setattr(project_imports, "apply_private_permissions", count_acl)
    claim = await staging._acquire_claim(staging.blobs[0])
    staging._release_claim(claim)
    staging.cleanup_root()

    assert parent_acl_calls == (0 if parent_exists else 1)
    assert not staging.root.exists()
    assert not claim_parent.exists()


@pytest.mark.asyncio
async def test_claim_contention_does_not_repeat_acl_on_stable_existing_parent(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, _ = _package(tmp_path, b"shared")
    owner = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    waiter = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed,
        command_id="22222222-2222-4222-8222-222222222222",
    )
    claim = await owner._acquire_claim(owner.blobs[0])
    now = 100.0
    parent_acl_calls = 0

    def monotonic():
        return now

    async def sleep(delay):
        nonlocal now
        now += delay

    def count_acl(path, *, is_directory):
        nonlocal parent_acl_calls
        if Path(path) == claim.parent:
            parent_acl_calls += 1

    monkeypatch.setattr(project_imports, "_claim_monotonic", monotonic)
    monkeypatch.setattr(project_imports, "_claim_sleep", sleep)
    monkeypatch.setattr(project_imports, "apply_private_permissions", count_acl)
    try:
        with pytest.raises(ProjectImportCommandStateConflict):
            await waiter._acquire_claim(waiter.blobs[0])
    finally:
        owner._release_claim(claim)
        owner.cleanup_root()
        waiter.cleanup_root()

    assert parent_acl_calls == 0
    assert not owner.root.exists()
    assert not waiter.root.exists()
    assert not claim.parent.exists()


@pytest.mark.asyncio
async def test_claim_parent_disappearance_between_mkdir_and_validation_uses_bounded_wait(
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
    real_is_symlink = project_imports.Path.is_symlink
    now = 100.0
    sleeps = []

    def disappear_before_validation(path):
        if path == claim_parent and path.exists():
            path.rmdir()
        return real_is_symlink(path)

    def monotonic():
        return now

    async def sleep(delay):
        nonlocal now
        sleeps.append(delay)
        now += delay

    monkeypatch.setattr(project_imports.Path, "is_symlink", disappear_before_validation)
    monkeypatch.setattr(project_imports, "_claim_monotonic", monotonic)
    monkeypatch.setattr(project_imports, "_claim_sleep", sleep)
    try:
        with pytest.raises(ProjectImportCommandStateConflict):
            await staging._acquire_claim(staging.blobs[0])
    finally:
        staging.cleanup_root()

    assert sum(sleeps) == pytest.approx(project_imports.CLAIM_WAIT_SECONDS)
    assert now == pytest.approx(130.0)
    assert not staging.root.exists()
    assert not claim_parent.exists()


@pytest.mark.asyncio
async def test_claim_parent_disappearance_after_create_before_acl_uses_bounded_wait(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    claim_parent = staging.root.parent / project_imports.CLAIM_DIRECTORY
    claim = claim_parent / digest
    now = 100.0
    sleeps = []

    def monotonic():
        return now

    async def sleep(delay):
        nonlocal now
        sleeps.append(delay)
        now += delay

    def disappear_before_acl(path, *, is_directory):
        if not is_directory:
            Path(path).unlink()
            claim_parent.rmdir()
            raise FileNotFoundError()

    monkeypatch.setattr(project_imports, "_claim_monotonic", monotonic)
    monkeypatch.setattr(project_imports, "_claim_sleep", sleep)
    monkeypatch.setattr(project_imports, "apply_private_permissions", disappear_before_acl)
    try:
        with pytest.raises(ProjectImportCommandStateConflict):
            await staging._acquire_claim(staging.blobs[0])
    finally:
        staging.cleanup_root()

    assert sum(sleeps) == pytest.approx(project_imports.CLAIM_WAIT_SECONDS)
    assert now == pytest.approx(130.0)
    assert not staging.root.exists()
    assert not claim_parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["mkdir", "file", "symlink", "parent_acl", "claim_acl"],
)
async def test_claim_infrastructure_failures_are_fixed_persistence_errors(
    tmp_path, monkeypatch, failure,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    claim_parent = staging.root.parent / project_imports.CLAIM_DIRECTORY
    claim = claim_parent / digest

    if failure == "mkdir":
        real_mkdir = project_imports.Path.mkdir

        def fail_mkdir(path, *args, **kwargs):
            if path == claim_parent:
                raise PermissionError("secret mkdir path")
            return real_mkdir(path, *args, **kwargs)

        monkeypatch.setattr(project_imports.Path, "mkdir", fail_mkdir)
    elif failure == "file":
        claim_parent.write_text("malformed", encoding="ascii")
    elif failure == "symlink":
        claim_parent.mkdir()
        real_is_symlink = project_imports.Path.is_symlink
        monkeypatch.setattr(
            project_imports.Path, "is_symlink",
            lambda path: path == claim_parent or real_is_symlink(path),
        )
    else:
        def fail_acl(path, *, is_directory):
            if (
                (failure == "parent_acl" and Path(path) == claim_parent)
                or (failure == "claim_acl" and not is_directory)
            ):
                raise project_imports.PrivateFilePermissionsError("secret acl path")

        monkeypatch.setattr(project_imports, "apply_private_permissions", fail_acl)

    try:
        with pytest.raises(ProjectImportPersistenceError) as caught:
            await staging._acquire_claim(staging.blobs[0])
        if failure in ("mkdir", "parent_acl", "claim_acl"):
            assert not claim.exists()
            assert not claim_parent.exists()
    finally:
        if failure == "symlink" and claim_parent.exists():
            claim_parent.rmdir()
        elif claim_parent.exists() or claim_parent.is_symlink():
            if claim_parent.is_dir() and not claim_parent.is_symlink():
                for child in claim_parent.iterdir():
                    child.unlink()
                claim_parent.rmdir()
            else:
                claim_parent.unlink()
        staging.cleanup_root()

    assert caught.value.args == ("project import persistence failed",)
    assert caught.value.__cause__ is None
    assert not isinstance(caught.value, ProjectImportInvalid)
    assert not staging.root.exists()
    assert not claim_parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["fdopen", "write", "flush", "close"])
async def test_incomplete_claim_write_failures_leave_no_residue(
    tmp_path, monkeypatch, failure,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    claim_parent = staging.root.parent / project_imports.CLAIM_DIRECTORY
    claim = claim_parent / digest
    real_fdopen = project_imports.os.fdopen
    public_claim_was_visible = []

    class FaultyClaimWriter:
        def __init__(self, descriptor, *args, **kwargs):
            self._target = real_fdopen(descriptor, *args, **kwargs)

        @property
        def closed(self):
            return self._target.closed

        def __enter__(self):
            return self

        def __exit__(self, _type, _value, _traceback):
            self.close()

        def write(self, value):
            public_claim_was_visible.append(claim.exists())
            if failure == "write":
                self._target.write(value[:3])
                raise OSError("secret claim owner")
            return self._target.write(value)

        def flush(self):
            public_claim_was_visible.append(claim.exists())
            if failure == "flush":
                self._target.flush()
                raise OSError("secret claim owner")
            return self._target.flush()

        def close(self):
            public_claim_was_visible.append(claim.exists())
            if failure == "close":
                self._target.close()
                raise OSError("secret claim owner")
            return self._target.close()

    def fail_claim_owner(descriptor, *args, **kwargs):
        public_claim_was_visible.append(claim.exists())
        if failure == "fdopen":
            raise OSError("secret claim owner")
        return FaultyClaimWriter(descriptor, *args, **kwargs)

    monkeypatch.setattr(project_imports.os, "fdopen", fail_claim_owner)
    try:
        with pytest.raises(ProjectImportPersistenceError) as caught:
            await staging._acquire_claim(staging.blobs[0])
        assert not claim.exists()
        assert not claim_parent.exists()
    finally:
        staging.cleanup_root()

    assert caught.value.args == ("project import persistence failed",)
    assert caught.value.__cause__ is None
    assert public_claim_was_visible
    assert not any(public_claim_was_visible)
    assert not staging.root.exists()
    assert not claim.exists()
    assert not claim_parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["write", "flush", "close"])
async def test_claim_writer_failure_never_closes_reused_unrelated_descriptor(
    tmp_path, monkeypatch, failure,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, _ = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    unrelated = tmp_path / "unrelated"
    real_fdopen = project_imports.os.fdopen
    reused_descriptor = None

    class FaultyClaimWriter:
        def __init__(self, descriptor, *args, **kwargs):
            self._descriptor = descriptor
            self._target = real_fdopen(descriptor, *args, **kwargs)
            self._failed = False

        def fail_after_reuse(self):
            nonlocal reused_descriptor
            if self._failed:
                return
            self._failed = True
            self._target.close()
            reused_descriptor = project_imports.os.open(
                unrelated,
                project_imports.os.O_WRONLY
                | project_imports.os.O_CREAT
                | project_imports.os.O_EXCL,
                0o600,
            )
            assert reused_descriptor == self._descriptor
            raise OSError("secret claim owner")

        def write(self, value):
            if failure == "write":
                self.fail_after_reuse()
            return self._target.write(value)

        def flush(self):
            if failure == "flush":
                self.fail_after_reuse()
            return self._target.flush()

        def close(self):
            if failure == "close":
                self.fail_after_reuse()
            self._target.close()

    monkeypatch.setattr(
        project_imports.os,
        "fdopen",
        lambda descriptor, *args, **kwargs: FaultyClaimWriter(
            descriptor, *args, **kwargs,
        ),
    )
    try:
        with pytest.raises(ProjectImportPersistenceError):
            await staging._acquire_claim(staging.blobs[0])
        assert reused_descriptor is not None
        project_imports.os.write(reused_descriptor, b"unrelated")
    finally:
        if reused_descriptor is not None:
            try:
                project_imports.os.close(reused_descriptor)
            except OSError:
                pass
        staging.cleanup_root()

    assert unrelated.read_bytes() == b"unrelated"


@pytest.mark.asyncio
async def test_identity_check_then_unlink_never_deletes_atomic_replacement(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    claim_parent = staging.root.parent / project_imports.CLAIM_DIRECTORY
    claim = claim_parent / digest
    replacement = claim_parent / "winner.new"
    # A later attempt for the same command id is still a different filesystem object.
    winner = COMMAND
    real_fdopen = project_imports.os.fdopen

    class ReplacingClaimWriter:
        def __init__(self, descriptor, *args, **kwargs):
            self._target = real_fdopen(descriptor, *args, **kwargs)

        @property
        def closed(self):
            return self._target.closed

        def __enter__(self):
            return self

        def __exit__(self, _type, _value, _traceback):
            self.close()

        def write(self, value):
            self._target.write(value[:3])
            self._target.close()
            replacement.write_text(winner, encoding="ascii")
            project_imports.os.replace(replacement, claim)
            raise OSError("secret claim owner")

        def flush(self):
            return self._target.flush()

        def close(self):
            return self._target.close()

    monkeypatch.setattr(
        project_imports.os, "fdopen",
        lambda descriptor, *args, **kwargs: ReplacingClaimWriter(
            descriptor, *args, **kwargs,
        ),
    )
    # Reproduce the TOCTOU: identity validation observes the old object, then a
    # later winner replaces it before the path-based unlink executes.
    monkeypatch.setattr(project_imports.os.path, "samestat", lambda *_args: True)
    try:
        with pytest.raises(ProjectImportPersistenceError) as caught:
            await staging._acquire_claim(staging.blobs[0])
        assert claim.read_text("ascii") == winner
    finally:
        if claim.exists():
            claim.unlink()
        if claim_parent.exists():
            claim_parent.rmdir()
        staging.cleanup_root()

    assert caught.value.args == ("project import persistence failed",)
    assert caught.value.__cause__ is None
    assert not staging.root.exists()


@pytest.mark.asyncio
async def test_claim_acl_is_applied_before_publication(tmp_path, monkeypatch):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    claim_parent = staging.root.parent / project_imports.CLAIM_DIRECTORY
    claim = claim_parent / digest
    file_acl_targets = []

    def inspect_acl(path, *, is_directory):
        if not is_directory:
            file_acl_targets.append(Path(path))
            assert Path(path) != claim
            assert not claim.exists()
            assert Path(path).read_text("ascii") == COMMAND

    monkeypatch.setattr(project_imports, "apply_private_permissions", inspect_acl)
    acquired = await staging._acquire_claim(staging.blobs[0])
    try:
        assert acquired == claim
        assert claim.read_text("ascii") == COMMAND
        assert len(file_acl_targets) == 1
    finally:
        staging._release_claim(claim)
        staging.cleanup_root()

    assert not claim_parent.exists()


@pytest.mark.asyncio
async def test_published_claim_retries_transient_temporary_unlink_and_leaves_no_residue(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    claim_parent = staging.root.parent / project_imports.CLAIM_DIRECTORY
    real_unlink = project_imports.Path.unlink
    temporary_unlinks = 0

    def flaky_temporary_unlink(path, *args, **kwargs):
        nonlocal temporary_unlinks
        if path.parent == claim_parent and path.name.endswith(".tmp"):
            temporary_unlinks += 1
            if temporary_unlinks == 1:
                raise OSError("secret temporary claim path")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(project_imports.Path, "unlink", flaky_temporary_unlink)
    await staging.promote(lambda _value: None)
    staging.cleanup_root()

    assert temporary_unlinks == 2
    assert not claim_parent.exists()


@pytest.mark.asyncio
async def test_published_claim_permanent_temporary_unlink_is_fixed_persistence_error(
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
    real_unlink = project_imports.Path.unlink
    temporary_unlinks = 0

    def fail_temporary_unlink(path, *args, **kwargs):
        nonlocal temporary_unlinks
        if path.parent == claim_parent and path.name.endswith(".tmp"):
            temporary_unlinks += 1
            raise OSError("secret temporary claim path")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(project_imports.Path, "unlink", fail_temporary_unlink)
    try:
        with pytest.raises(ProjectImportPersistenceError) as caught:
            await staging.promote(lambda _value: None)
    finally:
        monkeypatch.setattr(project_imports.Path, "unlink", real_unlink)
        if claim_parent.exists():
            for child in claim_parent.iterdir():
                child.unlink()
            claim_parent.rmdir()
        staging.cleanup_root()

    assert temporary_unlinks == 2
    assert caught.value.args == ("project import persistence failed",)
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_published_claim_transient_cancel_cleans_alias_before_preserving_cancellation(
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
    real_unlink = project_imports.Path.unlink
    temporary_unlinks = 0

    def cancel_temporary_unlink(path, *args, **kwargs):
        nonlocal temporary_unlinks
        if path.parent == claim_parent and path.name.endswith(".tmp"):
            temporary_unlinks += 1
            if temporary_unlinks == 1:
                raise asyncio.CancelledError()
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(project_imports.Path, "unlink", cancel_temporary_unlink)
    residue = []
    try:
        with pytest.raises(asyncio.CancelledError):
            await staging.promote(lambda _value: None)
    finally:
        monkeypatch.setattr(project_imports.Path, "unlink", real_unlink)
        if claim_parent.exists():
            residue = list(claim_parent.iterdir())
        for child in residue:
            child.unlink()
        if claim_parent.exists():
            claim_parent.rmdir()
        staging.cleanup_root()

    assert temporary_unlinks == 2
    assert residue == []
    assert not claim_parent.exists()


@pytest.mark.asyncio
async def test_published_claim_permanent_cancel_is_preserved_with_explicit_alias_residue(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    claim_parent = staging.root.parent / project_imports.CLAIM_DIRECTORY
    real_unlink = project_imports.Path.unlink
    temporary_unlinks = 0

    def cancel_temporary_unlink(path, *args, **kwargs):
        nonlocal temporary_unlinks
        if path.parent == claim_parent and path.name.endswith(".tmp"):
            temporary_unlinks += 1
            raise asyncio.CancelledError()
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(project_imports.Path, "unlink", cancel_temporary_unlink)
    residue = []
    try:
        with pytest.raises(asyncio.CancelledError):
            await staging.promote(lambda _value: None)
        residue = list(claim_parent.iterdir())
        assert len(residue) == 1
        assert residue[0].name.startswith(f".{digest}.")
        assert residue[0].name.endswith(".tmp")
        assert not (claim_parent / digest).exists()
    finally:
        monkeypatch.setattr(project_imports.Path, "unlink", real_unlink)
        if claim_parent.exists():
            for child in claim_parent.iterdir():
                child.unlink()
            claim_parent.rmdir()
        staging.cleanup_root()

    assert temporary_unlinks == 2


def test_held_claim_release_retries_first_failure_and_still_releases_every_claim(
    tmp_path, monkeypatch,
):
    managed = tmp_path / "managed"
    root = managed / project_imports.STAGING_DIRECTORY / COMMAND
    claim_parent = root.parent / project_imports.CLAIM_DIRECTORY
    root.mkdir(parents=True)
    claim_parent.mkdir()
    first_digest = sha256(b"first").hexdigest()
    second_digest = sha256(b"second").hexdigest()
    first_claim = claim_parent / first_digest
    second_claim = claim_parent / second_digest
    first_claim.write_text(COMMAND, encoding="ascii")
    second_claim.write_text(COMMAND, encoding="ascii")
    staging = project_imports.ProjectImportStaging(
        managed, COMMAND, root,
        (
            project_imports.StagedBlob(first_digest, 5, "first", False),
            project_imports.StagedBlob(second_digest, 6, "second", False),
        ),
    )
    staging._held_claims.update({
        first_digest: first_claim,
        second_digest: second_claim,
    })
    real_unlink = project_imports.Path.unlink
    releases = []

    def flaky_first_release(path, *args, **kwargs):
        if path in (first_claim, second_claim):
            releases.append(path)
            if path == second_claim and releases.count(second_claim) == 1:
                raise OSError("secret claim path")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(project_imports.Path, "unlink", flaky_first_release)
    staging._release_held_claims()

    assert releases == [second_claim, second_claim, first_claim]
    assert staging._held_claims == {}
    assert not claim_parent.exists()


def test_held_claim_release_attempts_all_claims_before_fixed_permanent_error(
    tmp_path, monkeypatch,
):
    managed = tmp_path / "managed"
    root = managed / project_imports.STAGING_DIRECTORY / COMMAND
    claim_parent = root.parent / project_imports.CLAIM_DIRECTORY
    root.mkdir(parents=True)
    claim_parent.mkdir()
    first_digest = sha256(b"first").hexdigest()
    second_digest = sha256(b"second").hexdigest()
    first_claim = claim_parent / first_digest
    second_claim = claim_parent / second_digest
    first_claim.write_text(COMMAND, encoding="ascii")
    second_claim.write_text(COMMAND, encoding="ascii")
    staging = project_imports.ProjectImportStaging(
        managed, COMMAND, root,
        (
            project_imports.StagedBlob(first_digest, 5, "first", False),
            project_imports.StagedBlob(second_digest, 6, "second", False),
        ),
    )
    staging._held_claims.update({
        first_digest: first_claim,
        second_digest: second_claim,
    })
    real_unlink = project_imports.Path.unlink
    releases = []

    def fail_second_claim(path, *args, **kwargs):
        if path in (first_claim, second_claim):
            releases.append(path)
            if path == second_claim:
                raise OSError("secret claim path")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(project_imports.Path, "unlink", fail_second_claim)
    try:
        with pytest.raises(ProjectImportPersistenceError) as caught:
            staging._release_held_claims()
    finally:
        monkeypatch.setattr(project_imports.Path, "unlink", real_unlink)
        if claim_parent.exists():
            for child in claim_parent.iterdir():
                child.unlink()
            claim_parent.rmdir()

    assert releases == [second_claim, second_claim, first_claim]
    assert caught.value.args == ("project import persistence failed",)
    assert caught.value.__cause__ is None
    assert not first_claim.exists()


@pytest.mark.asyncio
async def test_successful_publication_does_not_swallow_permanent_claim_release_failure(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    temp = tmp_path / "temp"
    managed.mkdir()
    temp.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    package.package_hash = "a" * 64
    package.manifest_hash = "b" * 64
    package.summary = SimpleNamespace(package_version=1)
    plan.target_project_id = "target"
    running = SimpleNamespace(status="running")
    succeeded = SimpleNamespace(status="succeeded")

    class Repository:
        async def reserve_command(self, session, **kwargs):
            return running

        async def acquire_lease(self, session, **kwargs):
            return running

        async def persist_staging_manifest(self, session, **kwargs):
            return None

        async def publish_project(self, session, actual_plan, **kwargs):
            assert actual_plan is plan

        async def read_command(self, session, **kwargs):
            return succeeded

    @asynccontextmanager
    async def session():
        yield object()

    class Quarantine:
        def cleanup(self):
            return None

    service = ProjectImportService(
        repository=Repository(), managed_corpus_root=managed, temp_parent=temp,
        connection_factory=session, transaction_factory=session,
        clock=lambda: 10, owner_factory=lambda: "owner",
    )

    async def verified(_upload):
        return Quarantine(), package

    monkeypatch.setattr(service, "_verified", verified)
    monkeypatch.setattr(project_imports, "build_publication_plan", lambda *_args: plan)
    claim = managed / project_imports.STAGING_DIRECTORY / project_imports.CLAIM_DIRECTORY / digest
    real_unlink = project_imports.Path.unlink
    release_attempts = 0

    def fail_claim_release(path, *args, **kwargs):
        nonlocal release_attempts
        if path == claim:
            release_attempts += 1
            raise OSError("secret claim path")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(project_imports.Path, "unlink", fail_claim_release)
    try:
        with pytest.raises(ProjectImportPersistenceError) as caught:
            await service.import_project(
                object(), project_imports.ImportProjectRequest(
                    COMMAND, "same_import_key1", package.package_hash, "Imported",
                ),
            )
    finally:
        monkeypatch.setattr(project_imports.Path, "unlink", real_unlink)
        if claim.exists():
            claim.unlink()
        if claim.parent.exists():
            claim.parent.rmdir()

    assert release_attempts == 2
    assert caught.value.args == ("project import persistence failed",)
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "primary_error",
    [RuntimeError("primary publish failure"), asyncio.CancelledError()],
    ids=["failure", "cancel"],
)
async def test_primary_publish_error_precedes_held_claim_release_error(
    tmp_path, monkeypatch, primary_error,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    temp = tmp_path / "temp"
    managed.mkdir()
    temp.mkdir()
    package, plan, _ = _package(tmp_path, b"shared")
    package.package_hash = "a" * 64
    package.manifest_hash = "b" * 64
    package.summary = SimpleNamespace(package_version=1)
    plan.target_project_id = "target"
    running = SimpleNamespace(status="running")

    class Repository:
        async def reserve_command(self, session, **kwargs):
            return running

        async def acquire_lease(self, session, **kwargs):
            return running

        async def persist_staging_manifest(self, session, **kwargs):
            return None

        async def publish_project(self, session, actual_plan, **kwargs):
            assert actual_plan is plan
            raise primary_error

        async def corpus_blob_is_referenced(self, session, *, content_hash):
            return True

        async def mark_failed(self, session, **kwargs):
            return None

    @asynccontextmanager
    async def session():
        yield object()

    class Quarantine:
        def cleanup(self):
            return None

    service = ProjectImportService(
        repository=Repository(), managed_corpus_root=managed, temp_parent=temp,
        connection_factory=session, transaction_factory=session,
        clock=lambda: 10, owner_factory=lambda: "owner",
    )

    async def verified(_upload):
        return Quarantine(), package

    def fail_final_release(_staging):
        raise ProjectImportPersistenceError()

    monkeypatch.setattr(service, "_verified", verified)
    monkeypatch.setattr(project_imports, "build_publication_plan", lambda *_args: plan)
    monkeypatch.setattr(
        project_imports.ProjectImportStaging,
        "_release_held_claims",
        fail_final_release,
    )

    with pytest.raises(type(primary_error)) as caught:
        await service.import_project(
            object(), project_imports.ImportProjectRequest(
                COMMAND, "same_import_key1", package.package_hash, "Imported",
            ),
        )

    assert caught.value is primary_error
    assert not (
        managed / project_imports.STAGING_DIRECTORY / project_imports.CLAIM_DIRECTORY
    ).exists()


@pytest.mark.asyncio
async def test_claim_parent_file_is_persistence_failure_without_contention_wait(
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
        with pytest.raises(ProjectImportPersistenceError):
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


@pytest.mark.asyncio
async def test_failed_installer_cleanup_cannot_delete_later_same_digest_publication(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    temp = tmp_path / "temp"
    managed.mkdir()
    temp.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    package.package_hash = "a" * 64
    package.manifest_hash = "b" * 64
    package.summary = SimpleNamespace(package_version=1)
    plan.target_project_id = "target"
    failed = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    await failed.promote(lambda _value: None)
    assert failed._installed_hashes == {digest}

    cleanup_checked = asyncio.Event()
    release_cleanup_check = asyncio.Event()
    published = asyncio.Event()
    referenced = False
    winner_command = "22222222-2222-4222-8222-222222222222"
    running = SimpleNamespace(status="running")
    succeeded = SimpleNamespace(status="succeeded")

    class Repository:
        async def corpus_blob_is_referenced(self, session, *, content_hash):
            assert content_hash == digest
            observed = referenced
            cleanup_checked.set()
            await release_cleanup_check.wait()
            return observed

        async def reserve_command(self, session, **kwargs):
            return running

        async def acquire_lease(self, session, **kwargs):
            return running

        async def persist_staging_manifest(self, session, **kwargs):
            return None

        async def publish_project(self, session, actual_plan, **kwargs):
            nonlocal referenced
            assert actual_plan is plan
            referenced = True
            published.set()

        async def read_command(self, session, **kwargs):
            return succeeded

    @asynccontextmanager
    async def session():
        yield object()

    class Quarantine:
        def cleanup(self):
            return None

    service = ProjectImportService(
        repository=Repository(), managed_corpus_root=managed, temp_parent=temp,
        connection_factory=session, transaction_factory=session,
        clock=lambda: 10, owner_factory=lambda: "winner-owner",
    )

    async def verified(_upload):
        return Quarantine(), package

    monkeypatch.setattr(service, "_verified", verified)
    monkeypatch.setattr(project_imports, "build_publication_plan", lambda *_args: plan)

    cleanup = asyncio.create_task(service._cleanup_unreferenced_created(failed))
    await cleanup_checked.wait()
    winner = asyncio.create_task(service.import_project(
        object(), project_imports.ImportProjectRequest(
            winner_command, "later_import_key1", package.package_hash, "Imported",
        ),
    ))
    # Under the unsafe implementation the winner reaches publication while
    # cleanup is paused after observing "unreferenced". Under the synchronized
    # implementation it waits for cleanup's digest claim instead.
    for _ in range(10):
        if published.is_set():
            break
        await asyncio.sleep(0)
    release_cleanup_check.set()
    await asyncio.gather(cleanup, winner)

    assert referenced is True
    assert managed_corpus_blob_path(managed, digest).read_bytes() == b"shared"
    failed.cleanup_root()


@pytest.mark.asyncio
async def test_recovery_cleanup_reclaims_its_stale_digest_claim_before_revalidation(
    tmp_path, monkeypatch,
):
    _no_acl(monkeypatch)
    managed = tmp_path / "managed"
    temp = tmp_path / "temp"
    managed.mkdir()
    temp.mkdir()
    package, plan, digest = _package(tmp_path, b"shared")
    staging = project_imports.ProjectImportStaging.stage(
        package, plan, managed_corpus_root=managed, command_id=COMMAND,
    )
    await staging.promote(lambda _value: None)
    claim_parent = staging.root.parent / project_imports.CLAIM_DIRECTORY
    claim_parent.mkdir()
    (claim_parent / digest).write_text(COMMAND, encoding="ascii")

    class Repository:
        async def corpus_blob_is_referenced(self, session, *, content_hash):
            assert content_hash == digest
            return False

    @asynccontextmanager
    async def connect():
        yield object()

    service = ProjectImportService(
        repository=Repository(), managed_corpus_root=managed, temp_parent=temp,
        connection_factory=connect,
    )
    monkeypatch.setattr(project_imports, "CLAIM_WAIT_SECONDS", 0.0)
    try:
        await service._cleanup_unreferenced_created(staging, recovery_manifest=True)
    finally:
        if claim_parent.exists():
            for child in claim_parent.iterdir():
                child.unlink()
            claim_parent.rmdir()
        staging.cleanup_root()

    assert not managed_corpus_blob_path(managed, digest).exists()
    assert not claim_parent.exists()


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
