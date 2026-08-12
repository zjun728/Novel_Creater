from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import stat
import zipfile

import pytest

from backend.domain.project_packages import (
    PackageEntry,
    PackageRecord,
    ProjectPackageInvalid,
    ProjectPackageTooLarge,
    build_structured_entries,
)
from backend.services.project_packages import write_deterministic_zip


class _Snapshot:
    source_project_logical_id = "project:1"
    lifecycle_revision = 7
    frozen_asset_records = ()
    corpus_revision_records = ()
    operation_records = ()
    provider_history_records = ()
    projection_validation = {"z": {"count": 0, "hashes": ()}}
    counts = {"project": 2}

    def __init__(self, graph_records):
        self.graph_records = graph_records


def test_zip_is_byte_identical_across_input_order_and_wallclock(tmp_path: Path, monkeypatch) -> None:
    first = PackageRecord("project", "project:1", data={"title": "One"})
    second = PackageRecord("project", "project:2", data={"title": "Two"})
    paths = (tmp_path / "first.zip", tmp_path / "second.zip")

    monkeypatch.setattr("time.time", lambda: 1)
    first_hash = write_deterministic_zip(
        paths[0], build_structured_entries(_Snapshot((first, second))),
        project_logical_id="project:1", counts={"project": 2},
    )
    monkeypatch.setattr("time.time", lambda: 9_999_999_999)
    second_hash = write_deterministic_zip(
        paths[1], build_structured_entries(_Snapshot((second, first))),
        project_logical_id="project:1", counts={"project": 2},
    )

    archive = paths[0].read_bytes()
    assert archive == paths[1].read_bytes()
    assert first_hash == second_hash == sha256(archive).hexdigest()
    with zipfile.ZipFile(paths[0]) as package:
        infos = package.infolist()
        assert [info.filename for info in infos] == sorted(info.filename for info in infos)
        assert package.comment == b""
        for info in infos:
            assert info.filename.isascii()
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.extra == b""
            assert info.comment == b""
            assert info.flag_bits & 0x08 == 0
            assert info.create_system == 3
            assert stat.S_IFMT(info.external_attr >> 16) == stat.S_IFREG
            assert stat.S_IMODE(info.external_attr >> 16) == 0o600
        manifest = package.read("manifest.json")
        assert manifest.endswith(b"\n")
        assert package.read("manifest.sha256") == sha256(manifest).hexdigest().encode("ascii") + b"\n"


def test_package_entry_rejects_bytes_subclasses() -> None:
    class BytesSubclass(bytes):
        pass

    with pytest.raises(ProjectPackageInvalid, match="invalid package value"):
        PackageEntry("project/graph.jsonl", BytesSubclass(b"x"))


def test_zip_rejects_archive_at_exact_configured_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("backend.domain.project_packages.MAX_ARCHIVE_BYTES", 1)

    with pytest.raises(ProjectPackageTooLarge, match="configured limit") as raised:
        write_deterministic_zip(
            tmp_path / "limited.zip",
            build_structured_entries(_Snapshot((PackageRecord("project", "project:1", data={"title": "x"}),))),
            project_logical_id="project:1",
            counts={"project": 1},
        )

    assert raised.value.__cause__ is None
