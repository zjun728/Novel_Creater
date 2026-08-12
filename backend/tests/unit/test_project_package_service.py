from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import asyncio
import csv
import os
import subprocess
import zipfile

import pytest

from backend.domain.project_packages import (
    PackageRecord,
    ProjectPackageIntegrity,
    ProjectPackageInvalid,
    ProjectPackageSensitiveData,
    ProjectPackageTooLarge,
)
from backend.repositories.project_packages import FrozenCorpusBlob, ProjectPackageSnapshot
from backend.security.paths import ensure_managed_corpus_blob_parent
from backend.services.project_packages import (
    ProjectPackageService,
    ProjectPackageTempOwner,
    cleanup_project_package_file,
)


def _snapshot(
    *,
    corpus: tuple[FrozenCorpusBlob, ...] = (),
    secret: bytes = b"",
    title: str = "password",
    projection: dict[str, object] | None = None,
):
    return ProjectPackageSnapshot(
        source_project_logical_id="project:1", lifecycle_revision=7,
        graph_records=(PackageRecord("project", "project:1", data={"title": title}),),
        operation_records=(), provider_history_records=(), frozen_asset_records=(),
        corpus_revision_records=(), corpus_blobs=corpus, projection_validation=projection or {},
        referenced_secret_values=(secret,), counts={"project": 1},
    )


class _Repository:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error

    async def read_snapshot(self, project_id, expected_lifecycle_revision):
        if self.error is not None:
            raise self.error
        return self.result


def _service(tmp_path: Path, snapshot, **kwargs) -> ProjectPackageService:
    corpus = tmp_path / "corpus"
    temp = tmp_path / "temp"
    corpus.mkdir(exist_ok=True)
    temp.mkdir(exist_ok=True)
    return ProjectPackageService(
        repository=_Repository(snapshot), managed_corpus_root=corpus, temp_parent=temp, **kwargs,
    )


def _windows_current_sid() -> str:
    result = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        shell=False,
        text=True,
        timeout=5,
    )
    return next(csv.reader(result.stdout.splitlines()))[1]


def _windows_acl(path: Path, acl_file: Path) -> tuple[str, str]:
    shown = subprocess.run(
        ["icacls", os.fspath(path)],
        check=True,
        capture_output=True,
        shell=False,
        timeout=5,
    ).stdout.decode(errors="replace")
    subprocess.run(
        ["icacls", os.fspath(path), "/save", os.fspath(acl_file), "/c"],
        check=True,
        capture_output=True,
        shell=False,
        timeout=5,
    )
    saved = acl_file.read_bytes().decode("utf-16-le")
    return shown, next(line for line in saved.splitlines() if line.startswith("D:"))


@pytest.mark.asyncio
async def test_service_verifies_and_packages_exact_owned_corpus_bytes(tmp_path: Path) -> None:
    raw = b"owned corpus bytes\x00password"
    digest = sha256(raw).hexdigest()
    blob = FrozenCorpusBlob("corpus-blob:1", digest, len(raw), f"sha256/{digest[:2]}/{digest}")
    service = _service(tmp_path, _snapshot(corpus=(blob,)))
    blob_path = ensure_managed_corpus_blob_parent(tmp_path / "corpus", digest)
    blob_path.write_bytes(raw)

    package = await service.create_backup("project-db", 7)
    try:
        assert package.path.is_file()
        assert package.package_sha256 == sha256(package.path.read_bytes()).hexdigest()
        assert package.download_name == "project-backup.zip"
        with zipfile.ZipFile(package.path) as archive:
            assert archive.read(f"corpus/blobs/sha256/{digest}") == raw
    finally:
        package.cleanup()
        cleanup_project_package_file(package)
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.asyncio
async def test_windows_temp_root_and_archive_have_private_noninherited_acl(tmp_path: Path) -> None:
    assert os.name == "nt"
    service = _service(tmp_path, _snapshot())
    temp_parent = tmp_path / "temp"
    subprocess.run(
        [
            "icacls",
            os.fspath(temp_parent),
            "/inheritance:e",
            "/grant:r",
            "*S-1-1-0:(OI)(CI)R",
        ],
        check=True,
        capture_output=True,
        shell=False,
        timeout=5,
    )

    package = await service.create_backup("project-db", 7)
    try:
        sid = _windows_current_sid()
        for index, path in enumerate((package.path.parent, package.path)):
            shown, sddl = _windows_acl(path, tmp_path / f"acl-{index}.txt")
            assert "(I)" not in shown
            assert sddl.startswith("D:P")
            assert sddl.count("(A;") == 1
            assert f";;;{sid})" in sddl
    finally:
        package.cleanup()
    assert list(temp_parent.iterdir()) == []


@pytest.mark.asyncio
async def test_windows_archive_acl_failure_is_fixed_and_cleans(tmp_path: Path, monkeypatch) -> None:
    assert os.name == "nt"
    service = _service(tmp_path, _snapshot())
    real_run = subprocess.run
    icacls_calls = 0

    def fail_archive_acl(args, **kwargs):
        nonlocal icacls_calls
        if Path(args[0]).name.casefold() == "icacls":
            icacls_calls += 1
            if icacls_calls == 2:
                raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fail_archive_acl)
    with pytest.raises(ProjectPackageIntegrity, match="permissions are unavailable") as raised:
        await service.create_backup("project-db", 7)
    assert raised.value.__cause__ is None
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ("missing", "length", "hash", "symlink", "escape", "oversize"))
async def test_corpus_integrity_failures_are_fixed_and_leave_no_residue(
    tmp_path: Path, failure: str, monkeypatch
) -> None:
    raw = b"original"
    digest = sha256(raw).hexdigest()
    expected_length = len(raw)
    if failure == "oversize":
        expected_length = 99
        monkeypatch.setattr("backend.services.project_packages.MAX_CORPUS_BLOB_BYTES", 8)
    blob = FrozenCorpusBlob("corpus-blob:1", digest, expected_length, f"sha256/{digest[:2]}/{digest}")
    service = _service(tmp_path, _snapshot(corpus=(blob,)))
    path = ensure_managed_corpus_blob_parent(tmp_path / "corpus", digest)
    if failure not in {"missing", "escape"}:
        path.write_bytes(b"changed" if failure == "hash" else raw + (b"x" if failure == "length" else b""))
    if failure == "symlink":
        path.unlink()
        target = tmp_path / "outside"
        target.write_bytes(raw)
        try:
            os.symlink(target, path)
        except OSError:
            path.write_bytes(raw)
            monkeypatch.setattr(
                "backend.services.project_packages._is_link",
                lambda candidate: candidate == path,
            )
    if failure == "escape":
        outside = tmp_path / "outside"
        outside.write_bytes(raw)
        monkeypatch.setattr(
            "backend.services.project_packages.managed_corpus_blob_path",
            lambda root, content_hash: outside,
        )

    error_type = ProjectPackageTooLarge if failure == "oversize" else ProjectPackageIntegrity
    with pytest.raises(error_type) as raised:
        await service.create_backup("project-db", 7)
    assert raised.value.__cause__ is None
    assert repr(raised.value) in {
        "ProjectPackageIntegrity('project package corpus integrity check failed')",
        "ProjectPackageTooLarge('project package exceeds configured limit')",
    }
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ("structured", "corpus"))
async def test_exact_referenced_secret_scan_is_safe_and_cleans(location: str, tmp_path: Path) -> None:
    secret = b"EXACT_PRIVATE_SENTINEL"
    corpus = ()
    title = secret.decode() if location == "structured" else "password"
    if location == "corpus":
        digest = sha256(b"prefix" + secret + b"suffix").hexdigest()
        corpus = (FrozenCorpusBlob("corpus-blob:1", digest, 34, f"sha256/{digest[:2]}/{digest}"),)
    service = _service(tmp_path, _snapshot(corpus=corpus, secret=secret, title=title))
    if corpus:
        path = ensure_managed_corpus_blob_parent(tmp_path / "corpus", corpus[0].content_hash)
        path.write_bytes(b"prefix" + secret + b"suffix")

    with pytest.raises(ProjectPackageSensitiveData, match="sensitive value") as raised:
        await service.create_backup("project-db", 7)
    assert raised.value.__cause__ is None
    assert secret.decode() not in str(raised.value)
    assert secret.decode() not in repr(raised.value.__traceback__)
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret_text",
    (
        'quote"secret',
        "back\\slash",
        "line\nbreak",
        "tab\tbreak",
        '密钥"片段',
    ),
)
async def test_json_escaped_secret_in_structured_record_is_rejected(
    tmp_path: Path, secret_text: str
) -> None:
    secret = secret_text.encode("utf-8")
    service = _service(tmp_path, _snapshot(secret=secret, title=secret_text))
    package = None
    try:
        with pytest.raises(ProjectPackageSensitiveData, match="sensitive value") as raised:
            package = await service.create_backup("project-db", 7)
        assert raised.value.__cause__ is None
        assert secret_text not in str(raised.value)
    finally:
        if package is not None:
            package.cleanup()
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.asyncio
async def test_json_escaped_secret_in_projection_is_rejected(tmp_path: Path) -> None:
    secret_text = 'projection\n"secret'
    secret = secret_text.encode("utf-8")
    service = _service(
        tmp_path,
        _snapshot(secret=secret, projection={"evidence": secret_text}),
    )
    package = None
    try:
        with pytest.raises(ProjectPackageSensitiveData, match="sensitive value"):
            package = await service.create_backup("project-db", 7)
    finally:
        if package is not None:
            package.cleanup()
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.asyncio
async def test_corpus_does_not_match_json_escaped_secret_variant(tmp_path: Path) -> None:
    secret = b'raw"secret'
    escaped_only = b'raw\\"secret'
    digest = sha256(escaped_only).hexdigest()
    blob = FrozenCorpusBlob(
        "corpus-blob:1", digest, len(escaped_only), f"sha256/{digest[:2]}/{digest}"
    )
    service = _service(tmp_path, _snapshot(corpus=(blob,), secret=secret))
    path = ensure_managed_corpus_blob_parent(tmp_path / "corpus", digest)
    path.write_bytes(escaped_only)

    package = await service.create_backup("project-db", 7)
    package.cleanup()
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.asyncio
async def test_non_utf8_referenced_secret_fails_fixed_and_cleans(tmp_path: Path) -> None:
    service = _service(tmp_path, _snapshot(secret=b"\xff"))

    with pytest.raises(ProjectPackageInvalid, match="secret value") as raised:
        await service.create_backup("project-db", 7)
    assert raised.value.__cause__ is None
    assert "\\xff" not in str(raised.value)
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.asyncio
async def test_empty_secret_is_skipped_and_password_word_is_not_a_match(tmp_path: Path) -> None:
    package = await _service(tmp_path, _snapshot()).create_backup("project-db", 7)
    package.cleanup()
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.asyncio
async def test_zip_failure_is_fixed_and_leaves_no_residue(tmp_path: Path) -> None:
    sentinel = "PRIVATE_ZIP_FAILURE_SENTINEL"

    def fail_zip(*args, **kwargs):
        raise RuntimeError(sentinel)

    service = _service(tmp_path, _snapshot(), zip_writer=fail_zip)
    with pytest.raises(ProjectPackageIntegrity, match="archive creation failed") as raised:
        await service.create_backup("project-db", 7)

    assert raised.value.__cause__ is None
    assert sentinel not in str(raised.value)
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.asyncio
async def test_service_cancellation_is_not_reclassified_and_cleans(tmp_path: Path) -> None:
    def cancel_zip(*args, **kwargs):
        raise asyncio.CancelledError

    service = _service(tmp_path, _snapshot(), zip_writer=cancel_zip)
    with pytest.raises(asyncio.CancelledError):
        await service.create_backup("project-db", 7)
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.asyncio
async def test_service_failure_retries_owned_temp_cleanup_once_and_keeps_primary(
    tmp_path: Path, monkeypatch,
) -> None:
    primary = ProjectPackageIntegrity("fixed primary")
    attempts = 0
    original_cleanup = ProjectPackageTempOwner.cleanup

    def fail_zip(*_args, **_kwargs):
        raise primary

    def fail_cleanup_once(owner):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ProjectPackageIntegrity("fixed cleanup")
        original_cleanup(owner)

    monkeypatch.setattr(ProjectPackageTempOwner, "cleanup", fail_cleanup_once)
    service = _service(tmp_path, _snapshot(), zip_writer=fail_zip)

    with pytest.raises(ProjectPackageIntegrity) as captured:
        await service.create_backup("project-db", 7)

    assert captured.value is primary
    assert attempts == 2
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.asyncio
async def test_permanent_cleanup_failure_keeps_cancellation_and_logs_only_fixed_warning(
    tmp_path: Path, monkeypatch, caplog,
) -> None:
    primary = asyncio.CancelledError()
    cleanup_secret = "PRIVATE_CLEANUP_PATH_SECRET_SENTINEL"
    attempts = 0
    owners: list[ProjectPackageTempOwner] = []
    original_cleanup = ProjectPackageTempOwner.cleanup

    def cancel_zip(*_args, **_kwargs):
        raise primary

    def fail_cleanup(owner):
        nonlocal attempts
        attempts += 1
        owners.append(owner)
        raise RuntimeError(cleanup_secret)

    monkeypatch.setattr(ProjectPackageTempOwner, "cleanup", fail_cleanup)
    service = _service(tmp_path, _snapshot(), zip_writer=cancel_zip)
    with caplog.at_level("WARNING", logger="backend.project_packages"):
        with pytest.raises(asyncio.CancelledError) as captured:
            await service.create_backup("project-db", 7)

    assert captured.value is primary
    assert attempts == 2
    records = [
        record for record in caplog.records
        if record.name == "backend.project_packages"
    ]
    assert [record.getMessage() for record in records] == [
        "project_package_service_cleanup_failed"
    ]
    assert records[0].args == ()
    assert cleanup_secret not in caplog.text

    monkeypatch.setattr(ProjectPackageTempOwner, "cleanup", original_cleanup)
    original_cleanup(owners[-1])
    assert list((tmp_path / "temp").iterdir()) == []


@pytest.mark.asyncio
async def test_handoff_cleanup_covers_cancel_and_background_duplicate(tmp_path: Path) -> None:
    package = await _service(tmp_path, _snapshot()).create_backup("project-db", 7)

    async def cancelled_consumer() -> None:
        try:
            raise asyncio.CancelledError
        finally:
            package.cleanup()

    with pytest.raises(asyncio.CancelledError):
        await cancelled_consumer()
    cleanup_project_package_file(package)
    assert list((tmp_path / "temp").iterdir()) == []
