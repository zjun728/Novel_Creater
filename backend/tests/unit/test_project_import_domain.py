from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.domain.project_imports import OwnedImportQuarantine, ProjectImportInvalid, ProjectImportTooLarge


async def _chunks(*values: bytes):
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_quarantine_copies_async_upload_to_private_owned_file_and_cleans_up(tmp_path: Path) -> None:
    parent = tmp_path / "quarantine"
    parent.mkdir()
    owner = OwnedImportQuarantine.create(temp_parent=parent)

    handoff = await owner.copy_upload(_chunks(b"alpha", b"beta"))

    assert handoff == owner.archive_path
    assert handoff.read_bytes() == b"alphabeta"
    owner.cleanup()
    owner.cleanup()
    assert list(parent.iterdir()) == []


@pytest.mark.asyncio
async def test_quarantine_rejects_oversize_upload_and_leaves_no_residue(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "quarantine"
    parent.mkdir()
    monkeypatch.setattr("backend.domain.project_imports.MAX_ARCHIVE_BYTES", 2)
    owner = OwnedImportQuarantine.create(temp_parent=parent)

    with pytest.raises(ProjectImportTooLarge, match="configured limit") as raised:
        await owner.copy_upload(_chunks(b"abc"))

    assert raised.value.__cause__ is None
    assert list(parent.iterdir()) == []


@pytest.mark.asyncio
async def test_cancelled_upload_remains_primary_and_cleans_owned_root(tmp_path: Path) -> None:
    parent = tmp_path / "quarantine"
    parent.mkdir()
    owner = OwnedImportQuarantine.create(temp_parent=parent)

    async def cancelled():
        yield b"partial"
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await owner.copy_upload(cancelled())

    assert list(parent.iterdir()) == []


@pytest.mark.asyncio
async def test_quarantine_rejects_oversized_async_iterable_chunk_before_writing(tmp_path: Path) -> None:
    parent = tmp_path / "quarantine"
    parent.mkdir()
    owner = OwnedImportQuarantine.create(temp_parent=parent)
    import backend.domain.project_imports as imports

    async def oversized():
        yield b"x" * (imports.UPLOAD_READ_CHUNK_BYTES + 1)

    with pytest.raises(ProjectImportTooLarge, match="configured limit"):
        await owner.copy_upload(oversized())
    assert list(parent.iterdir()) == []


@pytest.mark.asyncio
async def test_quarantine_rejects_reader_ignoring_chunk_bound_before_writing(tmp_path: Path) -> None:
    parent = tmp_path / "quarantine"
    parent.mkdir()
    owner = OwnedImportQuarantine.create(temp_parent=parent)
    import backend.domain.project_imports as imports

    class IgnoringReader:
        calls = 0

        async def read(self, size: int) -> bytes:
            self.calls += 1
            return b"x" * (imports.UPLOAD_READ_CHUNK_BYTES + 1)

    reader = IgnoringReader()
    with pytest.raises(ProjectImportTooLarge, match="configured limit"):
        await owner.copy_upload(reader)
    assert reader.calls == 1
    assert list(parent.iterdir()) == []


@pytest.mark.asyncio
async def test_quarantine_preserves_arbitrary_iterator_exception_after_cleanup(tmp_path: Path) -> None:
    parent = tmp_path / "quarantine"
    parent.mkdir()
    owner = OwnedImportQuarantine.create(temp_parent=parent)

    async def broken():
        raise KeyError("sentinel")
        yield b"unused"

    with pytest.raises(KeyError, match="sentinel"):
        await owner.copy_upload(broken())
    assert list(parent.iterdir()) == []


def test_quarantine_permission_failure_removes_created_root(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "quarantine"
    parent.mkdir()

    def fail(*args, **kwargs):
        raise ProjectImportInvalid("invalid project import archive")

    monkeypatch.setattr("backend.domain.project_imports.apply_private_permissions", fail)
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        OwnedImportQuarantine.create(temp_parent=parent)
    assert list(parent.iterdir()) == []


def test_quarantine_permission_failure_retries_cleanup_before_returning(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "quarantine"
    parent.mkdir()
    import backend.domain.project_imports as imports

    def fail_permission(*args, **kwargs):
        raise imports.PrivateFilePermissionsError("no detail")

    original = imports.shutil.rmtree
    attempts = 0

    def fail_cleanup_once(path, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("unavailable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(imports, "apply_private_permissions", fail_permission)
    monkeypatch.setattr(imports.shutil, "rmtree", fail_cleanup_once)
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        OwnedImportQuarantine.create(temp_parent=parent)
    assert attempts >= 2
    assert list(parent.iterdir()) == []


@pytest.mark.parametrize("failure", ["resolve", "validation"])
def test_quarantine_establishes_cleanup_ownership_before_fallible_root_checks(
    tmp_path: Path, monkeypatch, failure: str
) -> None:
    parent = tmp_path / "quarantine"
    parent.mkdir()
    import backend.domain.project_imports as imports

    real_mkdtemp = imports.tempfile.mkdtemp
    created: list[Path] = []

    def make_real_root(*args, **kwargs):
        root = Path(real_mkdtemp(*args, **kwargs))
        created.append(root)
        return str(root)

    monkeypatch.setattr(imports.tempfile, "mkdtemp", make_real_root)
    if failure == "resolve":
        real_resolve = Path.resolve
        resolve_attempts = 0

        def fail_created_resolve(self: Path, *args, **kwargs):
            nonlocal resolve_attempts
            if created and self == created[0] and resolve_attempts == 0:
                resolve_attempts += 1
                raise RuntimeError("unavailable")
            return real_resolve(self, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", fail_created_resolve)
    else:
        real_is_link = imports._is_link
        link_attempts = 0

        def fail_validation_once(path):
            nonlocal link_attempts
            if created and path == created[0] and link_attempts == 0:
                link_attempts += 1
                return True
            return real_is_link(path)

        monkeypatch.setattr(imports, "_is_link", fail_validation_once)

    original_rmtree = imports.shutil.rmtree
    attempts = 0

    def fail_cleanup_once(path, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("unavailable")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(imports.shutil, "rmtree", fail_cleanup_once)
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive") as raised:
        OwnedImportQuarantine.create(temp_parent=parent)
    assert raised.value.__cause__ is None
    assert created
    assert attempts >= 2
    assert list(parent.iterdir()) == []


def test_quarantine_cleanup_failure_is_retryable(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "quarantine"
    parent.mkdir()
    owner = OwnedImportQuarantine.create(temp_parent=parent)
    import backend.domain.project_imports as imports

    original = imports.shutil.rmtree
    calls = 0

    def fail_once(path, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("cleanup unavailable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(imports.shutil, "rmtree", fail_once)
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        owner.cleanup()
    owner.cleanup()
    assert list(parent.iterdir()) == []
