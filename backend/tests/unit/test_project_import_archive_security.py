from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import struct
import zipfile

import pytest

from backend.domain.project_imports import ProjectImportInvalid, ProjectImportTooLarge
from backend.security.project_import_archives import VerifiedArchiveEntry, verify_raw_zip_envelope


def _valid_archive(path: Path) -> bytes:
    info = zipfile.ZipInfo("project/graph.jsonl", date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        archive.comment = b""
        archive.writestr(info, b'{"ok":true}\n')
    return path.read_bytes()


def _central_offset(data: bytes) -> int:
    eocd = data.rfind(b"PK\x05\x06")
    return struct.unpack_from("<I", data, eocd + 16)[0]


def test_verifies_stored_phase6b_envelope_and_streamed_digest(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    payload = _valid_archive(path)

    verified = verify_raw_zip_envelope(path)

    assert verified == (
        VerifiedArchiveEntry(
            path="project/graph.jsonl",
            byte_length=len(b'{"ok":true}\n'),
            crc32=zipfile.crc32(b'{"ok":true}\n'),
            sha256=sha256(b'{"ok":true}\n').hexdigest(),
            offset=49,
        ),
    )
    assert path.read_bytes() == payload


@pytest.mark.parametrize("mutation", [
    lambda value: b"prefix" + value,
    lambda value: value + b"trailing",
    lambda value: value[:_central_offset(value) + 8] + b"\x08\x00" + value[_central_offset(value) + 10:],
    lambda value: value[:_central_offset(value) + 10] + b"\x08\x00" + value[_central_offset(value) + 12:],
    lambda value: value[:_central_offset(value) + 46] + b"\\" + value[_central_offset(value) + 47:],
])
def test_rejects_raw_envelope_mutations_without_echoing_archive_data(tmp_path: Path, mutation) -> None:
    path = tmp_path / "package.zip"
    path.write_bytes(mutation(_valid_archive(path)))

    with pytest.raises(ProjectImportInvalid, match="invalid project import archive") as raised:
        verify_raw_zip_envelope(path)

    assert raised.value.__cause__ is None
    assert "graph" not in str(raised.value)


def test_rejects_archive_limit_before_opening_zip(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "package.zip"
    _valid_archive(path)
    monkeypatch.setattr("backend.security.project_import_archives.MAX_ARCHIVE_BYTES", 1)

    with pytest.raises(ProjectImportTooLarge, match="configured limit") as raised:
        verify_raw_zip_envelope(path)

    assert raised.value.__cause__ is None
