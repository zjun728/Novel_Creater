from __future__ import annotations

from pathlib import Path
import os
import stat
import subprocess

import pytest

from backend.domain.project_packages import ProjectPackageIntegrity, ProjectPackageSensitiveData
from backend.services.project_packages import (
    TEMP_PREFIX,
    ProjectPackageService,
    ProjectPackageTempOwner,
    cleanup_stale_project_package_roots,
)


def test_temp_owner_modes_outside_corpus_and_idempotent_handoff_cleanup(tmp_path: Path) -> None:
    temp_parent = tmp_path / "temp"
    corpus = tmp_path / "corpus"
    temp_parent.mkdir()
    corpus.mkdir()
    owner = ProjectPackageTempOwner.create(temp_parent=temp_parent, managed_corpus_root=corpus)
    owner.archive_path.touch(mode=0o600, exist_ok=False)
    os.chmod(owner.archive_path, 0o600)

    assert owner.root.parent == temp_parent.resolve()
    assert owner.root.name.startswith(TEMP_PREFIX)
    if os.name != "nt":
        assert stat.S_IMODE(owner.root.stat().st_mode) == 0o700
        assert stat.S_IMODE(owner.archive_path.stat().st_mode) == 0o600
    cleanup = owner.handoff_cleanup()
    cleanup()
    cleanup()
    assert list(temp_parent.iterdir()) == []


def test_startup_cleanup_is_prefix_age_and_scan_bounded(tmp_path: Path) -> None:
    parent = tmp_path / "temp"
    parent.mkdir()
    now = 200_000.0
    ignored = parent / "other-old"
    ignored.mkdir()
    os.utime(ignored, (0, 0))
    for index in range(40):
        candidate = parent / f"{TEMP_PREFIX}{index:02d}"
        candidate.mkdir()
        os.utime(candidate, (0 if index < 33 else now, 0 if index < 33 else now))

    examined = cleanup_stale_project_package_roots(parent, now=now)

    assert examined <= 32
    assert ignored.exists()
    assert any(path.name.startswith(TEMP_PREFIX) for path in parent.iterdir())


def test_stale_cleanup_continues_after_candidate_failure_and_logs_fixed_warning(
    tmp_path: Path, monkeypatch, caplog,
) -> None:
    parent = tmp_path / "temp"
    parent.mkdir()
    candidates = [parent / f"{TEMP_PREFIX}{index}" for index in range(3)]
    for candidate in candidates:
        candidate.mkdir()
        os.utime(candidate, (0, 0))
    original_rmtree = __import__("shutil").rmtree

    def fail_first(candidate):
        if Path(candidate).name == candidates[0].name:
            raise OSError("PRIVATE_STALE_CANDIDATE_SECRET")
        original_rmtree(candidate)

    monkeypatch.setattr("backend.services.project_packages.shutil.rmtree", fail_first)
    with caplog.at_level("WARNING", logger="backend.project_packages"):
        examined = cleanup_stale_project_package_roots(parent, now=200_000.0)

    assert examined == 3
    assert candidates[0].exists()
    assert not candidates[1].exists()
    assert not candidates[2].exists()
    records = [record for record in caplog.records if record.name == "backend.project_packages"]
    assert [record.getMessage() for record in records] == [
        "project_package_stale_candidate_cleanup_failed"
    ]
    assert records[0].args == ()
    assert "PRIVATE_STALE_CANDIDATE_SECRET" not in caplog.text


def test_stale_cleanup_parent_scan_failure_logs_only_fixed_warning(
    tmp_path: Path, monkeypatch, caplog,
) -> None:
    parent = tmp_path / "temp"
    parent.mkdir()
    original_iterdir = Path.iterdir

    def fail_owned_parent(path):
        if path == parent.resolve():
            raise OSError("PRIVATE_STALE_PARENT_SECRET")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_owned_parent)
    with caplog.at_level("WARNING", logger="backend.project_packages"):
        assert cleanup_stale_project_package_roots(parent, now=200_000.0) == 0

    records = [record for record in caplog.records if record.name == "backend.project_packages"]
    assert [record.getMessage() for record in records] == [
        "project_package_stale_scan_failed"
    ]
    assert records[0].args == ()
    assert "PRIVATE_STALE_PARENT_SECRET" not in caplog.text


class _FailingRepository:
    async def read_snapshot(self, project_id, revision):
        raise ProjectPackageIntegrity("repository failed safely")


@pytest.mark.asyncio
async def test_repository_and_zip_failures_leave_zero_owned_roots(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    temp = tmp_path / "temp"
    corpus.mkdir()
    temp.mkdir()
    service = ProjectPackageService(
        repository=_FailingRepository(), managed_corpus_root=corpus, temp_parent=temp,
    )
    with pytest.raises(ProjectPackageIntegrity):
        await service.create_backup("project-db", 7)
    assert list(temp.iterdir()) == []


def test_temp_create_validation_failure_removes_created_root(tmp_path: Path, monkeypatch) -> None:
    temp = tmp_path / "temp"
    corpus = tmp_path / "corpus"
    temp.mkdir()
    corpus.mkdir()

    def make_bad_root(*, prefix, dir):
        bad_root = Path(dir) / "not-an-owned-root"
        bad_root.mkdir()
        return str(bad_root)

    monkeypatch.setattr("backend.services.project_packages.tempfile.mkdtemp", make_bad_root)
    with pytest.raises(ProjectPackageIntegrity, match="temporary storage is unavailable"):
        ProjectPackageTempOwner.create(temp_parent=temp, managed_corpus_root=corpus)
    assert list(temp.iterdir()) == []


def test_windows_missing_icacls_fails_closed_and_removes_created_root(
    tmp_path: Path, monkeypatch
) -> None:
    assert os.name == "nt"
    temp = tmp_path / "temp"
    corpus = tmp_path / "corpus"
    temp.mkdir()
    corpus.mkdir()

    def missing_icacls(*args, **kwargs):
        raise FileNotFoundError("icacls unavailable")

    monkeypatch.setattr(subprocess, "run", missing_icacls)
    with pytest.raises(ProjectPackageIntegrity, match="permissions are unavailable") as raised:
        ProjectPackageTempOwner.create(temp_parent=temp, managed_corpus_root=corpus)
    assert raised.value.__cause__ is None
    assert list(temp.iterdir()) == []
