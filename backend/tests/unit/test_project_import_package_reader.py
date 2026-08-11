from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from backend.domain.project_packages import PackageRecord, build_structured_entries
from backend.services.project_packages import write_deterministic_zip
from backend.domain.project_imports import ProjectImportInvalid
from backend.domain.project_imports import ProjectImportSensitiveData


class _Snapshot:
    source_project_logical_id = "project:1"
    counts = {"project": 1}
    frozen_asset_records = ()
    corpus_revision_records = ()
    operation_records = ()
    provider_history_records = ()
    projection_validation = {
        "arcProjections": {"count": 0, "hashes": []},
        "currentStateProjections": {"count": 0, "hashes": []},
        "memoryViews": {"count": 0, "hashes": []},
        "plotThreadProjections": {"count": 0, "hashes": []},
        "projectionHeads": {"count": 0, "hashes": []},
    }

    def __init__(self) -> None:
        self.graph_records = (PackageRecord("project", "project:1", data={"title": "测试项目"}),)


def test_reads_a_real_phase6b_package_and_returns_safe_summary(tmp_path: Path) -> None:
    from backend.domain.project_import_plans import read_verified_project_package

    archive = tmp_path / "project.zip"
    snapshot = _Snapshot()
    write_deterministic_zip(
        archive,
        build_structured_entries(snapshot),
        project_logical_id=snapshot.source_project_logical_id,
        counts=snapshot.counts,
    )

    verified = read_verified_project_package(archive)

    assert verified.archive_path == archive
    assert verified.summary.source_title == "测试项目"
    assert verified.summary.proposed_title == "测试项目（导入）"
    assert dict(verified.summary.counts) == {"project": 1}


def test_reader_uses_bounded_member_and_archive_streams(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.domain.project_import_plans import read_verified_project_package

    archive = tmp_path / "project.zip"
    snapshot = _Snapshot()
    write_deterministic_zip(archive, build_structured_entries(snapshot), project_logical_id="project:1", counts={"project": 1})

    monkeypatch.setattr(Path, "read_bytes", lambda *_: (_ for _ in ()).throw(AssertionError("read_bytes")))
    monkeypatch.setattr(zipfile.ZipFile, "read", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ZipFile.read")))

    assert read_verified_project_package(archive).summary.source_title == "测试项目"


def test_reader_requires_exactly_the_manifest_root_project(tmp_path: Path) -> None:
    from backend.domain.project_import_plans import read_verified_project_package

    archive = tmp_path / "project.zip"
    snapshot = _Snapshot()
    snapshot.graph_records = (PackageRecord("project", "project:2", data={"title": "other"}),)
    write_deterministic_zip(archive, build_structured_entries(snapshot), project_logical_id="project:1", counts={"project": 1})

    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        read_verified_project_package(archive)


@pytest.mark.parametrize("raw", [
    b'{"idempotencyKey":"run-once"}',
    b'{"providerProfileId":"provider:1"}',
    b'{"localPath":"C:/private/data"}',
])
def test_import_json_rejects_executable_and_local_identity_aliases(raw: bytes) -> None:
    from backend.domain.project_import_plans import _json

    with pytest.raises(ProjectImportSensitiveData) as raised:
        _json(raw)
    assert raised.value.__cause__ is None


def test_reader_streams_jsonl_without_materializing_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.domain.project_import_plans as plans

    archive = tmp_path / "project.zip"
    snapshot = _Snapshot()
    write_deterministic_zip(archive, build_structured_entries(snapshot), project_logical_id="project:1", counts={"project": 1})
    real = plans._member_bytes

    def forbid_jsonl(package, verified):
        if verified.path.endswith(".jsonl"):
            raise AssertionError("materialized jsonl")
        return real(package, verified)

    monkeypatch.setattr(plans, "_member_bytes", forbid_jsonl)
    assert plans.read_verified_project_package(archive).summary.source_title == "测试项目"


@pytest.mark.asyncio
async def test_reader_accepts_real_repository_snapshot_with_engine_option_ref(tmp_path: Path) -> None:
    from backend.repositories.project_packages import ProjectPackageRepository
    from backend.tests.unit import test_project_package_repository as repository_tests
    from backend.domain.project_import_plans import read_verified_project_package

    _contract, rows, extra_rows = repository_tests._minimal_creation_contract_fixture(
        contract_id="contract-db", seed_id="seed-db", seed_revision_id="seed-revision-db",
        engine_batch_id="batch-db", engine_option_id="engine-db", style_contract_id="style-contract-db",
        style_template_id="style-template-db",
    )
    session = repository_tests._SnapshotSession({"projects": [repository_tests._owned_row("projects", id="project-db", lifecycle_revision=7, title="P")], **rows}, extra_rows=extra_rows)
    snapshot = await ProjectPackageRepository(pool=repository_tests._SnapshotPool(session), session_factory=lambda value: value).read_snapshot("project-db", 7)
    archive = tmp_path / "repository.zip"
    write_deterministic_zip(archive, build_structured_entries(snapshot), project_logical_id=snapshot.source_project_logical_id, counts=snapshot.counts)

    verified = read_verified_project_package(archive)

    assert ("story-engine-option", "story-engine-option:1") in verified.graph_index


@pytest.mark.parametrize("raw", [
    b'{"data":{},"data":{},"entityType":"project","logicalId":"project:1","order":0,"revision":0}\n',
    b'{"revision":0,"order":0,"logicalId":"project:1","entityType":"project","data":{}}\n',
])
def test_record_parser_rejects_duplicate_or_noncanonical_wire_bytes(raw: bytes) -> None:
    from backend.domain.project_import_plans import _record

    with pytest.raises(ProjectImportInvalid) as raised:
        _record(raw)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("projection", [
    {"arcProjections": {"count": 1, "hashes": []}},
    {"unknown": {"count": 0, "hashes": []}},
])
def test_projection_rejects_open_or_inconsistent_summary(projection: dict[str, object]) -> None:
    from backend.domain.project_import_plans import _projection
    from backend.domain.project_packages import canonical_line

    with pytest.raises(ProjectImportInvalid):
        _projection(canonical_line(projection))


def test_reader_rejects_manifest_count_mismatch_from_production_writer(tmp_path: Path) -> None:
    from backend.domain.project_import_plans import read_verified_project_package

    archive = tmp_path / "bad-count.zip"
    snapshot = _Snapshot()
    write_deterministic_zip(archive, build_structured_entries(snapshot), project_logical_id="project:1", counts={"project": 2})

    with pytest.raises(ProjectImportInvalid) as raised:
        read_verified_project_package(archive)
    assert raised.value.__cause__ is None


def test_reader_rejects_graph_member_digest_mismatch_after_valid_raw_envelope(tmp_path: Path) -> None:
    from backend.domain.project_import_plans import read_verified_project_package
    from backend.security.project_import_archives import verify_raw_zip_envelope

    source, mutated = tmp_path / "source.zip", tmp_path / "mutated.zip"
    snapshot = _Snapshot()
    write_deterministic_zip(source, build_structured_entries(snapshot), project_logical_id="project:1", counts={"project": 1})
    with zipfile.ZipFile(source, "r", allowZip64=False) as original, zipfile.ZipFile(mutated, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as target:
        target.comment = b""
        for info in original.infolist():
            copied = zipfile.ZipInfo(info.filename, info.date_time)
            copied.compress_type, copied.create_system, copied.external_attr = info.compress_type, info.create_system, info.external_attr
            copied.extra, copied.comment = info.extra, info.comment
            data = original.read(info.filename)
            if info.filename == "project/graph.jsonl":
                data = data.replace(b"\xe6", b"\xe7", 1)
            target.writestr(copied, data)

    assert verify_raw_zip_envelope(mutated)
    with pytest.raises(ProjectImportInvalid) as raised:
        read_verified_project_package(mutated)
    assert raised.value.__cause__ is None
