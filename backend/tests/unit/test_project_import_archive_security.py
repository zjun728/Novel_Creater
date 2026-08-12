from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import struct
import warnings
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


def _eocd_offset(data: bytes) -> int:
    return data.rfind(b"PK\x05\x06")


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


def test_stored_payload_containing_zip64_signatures_is_not_a_zip64_envelope(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    payload = b"safe PK\x06\x06 data PK\x06\x07 payload"
    info = zipfile.ZipInfo("project/graph.jsonl", date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    with zipfile.ZipFile(path, "w", allowZip64=False) as archive:
        archive.writestr(info, payload)

    verified = verify_raw_zip_envelope(path)

    assert verified[0].sha256 == sha256(payload).hexdigest()


def test_rejects_structurally_placed_zip64_locator_and_record(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    original = _valid_archive(path)
    eocd = original.rfind(b"PK\x05\x06")
    zip64_record = b"PK\x06\x06" + struct.pack("<Q", 44) + b"\x00" * 44
    locator = b"PK\x06\x07" + struct.pack("<IQI", 0, eocd, 1)
    path.write_bytes(original[:eocd] + zip64_record + locator + original[eocd:])

    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        verify_raw_zip_envelope(path)


@pytest.mark.parametrize("offset,value", [
    (4, b"\xff\xff"),  # multi-disk EOCD
    (8, b"\x01\x00"),  # encrypted central flag
    (10, b"\x08\x00"),  # non-STORED central method
    (12, b"\x01\x00"),  # central timestamp
    (20, b"\xff\xff\xff\xff"),  # ZIP64 central compressed sentinel
])
def test_rejects_fixed_zip_metadata_mutations(tmp_path: Path, offset: int, value: bytes) -> None:
    path = tmp_path / "package.zip"
    data = _valid_archive(path)
    central = _central_offset(data)
    path.write_bytes(data[:central + offset] + value + data[central + offset + len(value):])

    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        verify_raw_zip_envelope(path)


@pytest.mark.parametrize("name", [
    "project\\graph.jsonl", "./project/graph.jsonl", "../project/graph.jsonl", "/project/graph.jsonl",
    "C:/project/graph.jsonl", "project/graph\x00.json", "project/gráph.jsonl",
    "unrecognized/document", "PROJECT/GRAPH.JSONL",
])
def test_rejects_each_unsafe_or_undeclared_member_path(tmp_path: Path, name: str) -> None:
    path = tmp_path / "package.zip"
    if name == "project\\graph.jsonl":
        data = _valid_archive(path)
        central = _central_offset(data)
        path.write_bytes(
            data[:37] + b"\\" + data[38:central + 53] + b"\\" + data[central + 54:]
        )
        with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
            verify_raw_zip_envelope(path)
        return
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    with zipfile.ZipFile(path, "w", allowZip64=False) as archive:
        archive.writestr(info, b"x")

    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        verify_raw_zip_envelope(path)


@pytest.mark.parametrize("external", [0o040700 << 16, 0o020600 << 16, 0o120777 << 16])
def test_rejects_directory_device_and_symlink_member_types(tmp_path: Path, external: int) -> None:
    path = tmp_path / "package.zip"
    info = zipfile.ZipInfo("project/graph.jsonl", date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = external
    with zipfile.ZipFile(path, "w", allowZip64=False) as archive:
        archive.writestr(info, b"x")

    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        verify_raw_zip_envelope(path)


def test_rejects_oversized_central_directory_before_reading_it(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "package.zip"
    original = _valid_archive(path)
    eocd = original.rfind(b"PK\x05\x06")
    padding = b"x" * (1024 * 1024)
    altered = bytearray(original[:eocd] + padding + original[eocd:])
    new_eocd = eocd + len(padding)
    old_size = struct.unpack_from("<I", altered, new_eocd + 12)[0]
    struct.pack_into("<I", altered, new_eocd + 12, old_size + len(padding))
    path.write_bytes(altered)
    import backend.security.project_import_archives as archives

    original_read = archives._read_exact
    requested: list[int] = []

    def tracked_read(handle, offset: int, size: int) -> bytes:
        requested.append(size)
        return original_read(handle, offset, size)

    monkeypatch.setattr(archives, "_read_exact", tracked_read)
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        verify_raw_zip_envelope(path)
    assert max(requested) < len(padding)


@pytest.mark.parametrize("names", [
    ("project/graph.jsonl", "project/graph.jsonl"),
    ("project/graph.jsonl", "PROJECT/GRAPH.JSONL"),
])
def test_rejects_duplicate_and_casefold_member_paths(tmp_path: Path, names: tuple[str, str]) -> None:
    path = tmp_path / "package.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", allowZip64=False) as archive:
            for name in names:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = 0o100600 << 16
                archive.writestr(info, b"x")
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        verify_raw_zip_envelope(path)


@pytest.mark.parametrize("constant,value,path_name", [
    ("MAX_ENTRY_COUNT", 0, "project/graph.jsonl"),
    ("MAX_TOTAL_ENTRY_BYTES", 0, "project/graph.jsonl"),
    ("MAX_STRUCTURED_ENTRY_BYTES", 0, "project/graph.jsonl"),
    ("MAX_CORPUS_BLOB_BYTES", 0, "corpus/blobs/sha256/" + "0" * 64),
])
def test_rejects_each_declared_entry_limit(tmp_path: Path, monkeypatch, constant: str, value: int, path_name: str) -> None:
    path = tmp_path / "package.zip"
    info = zipfile.ZipInfo(path_name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    with zipfile.ZipFile(path, "w", allowZip64=False) as archive:
        archive.writestr(info, b"x")
    monkeypatch.setattr("backend.security.project_import_archives." + constant, value)
    with pytest.raises(ProjectImportTooLarge, match="configured limit"):
        verify_raw_zip_envelope(path)


@pytest.mark.parametrize("offset,value", [
    (6, b"\x01\x00"), (8, b"\x08\x00"), (14, b"\x00\x00\x00\x00"),
    (18, b"\x00\x00\x00\x00"), (22, b"\x00\x00\x00\x00"),
])
def test_rejects_each_local_header_mismatch(tmp_path: Path, offset: int, value: bytes) -> None:
    path = tmp_path / "package.zip"
    data = _valid_archive(path)
    path.write_bytes(data[:offset] + value + data[offset + len(value):])
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        verify_raw_zip_envelope(path)


@pytest.mark.parametrize("kind", ["archive-comment", "entry-comment", "extra", "deflated", "timestamp", "mode"])
def test_rejects_comments_extras_nonstored_timestamp_and_mode(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "package.zip"
    info = zipfile.ZipInfo("project/graph.jsonl", date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED if kind == "deflated" else zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (0o100644 if kind == "mode" else 0o100600) << 16
    if kind == "entry-comment":
        info.comment = b"comment"
    if kind == "extra":
        info.extra = b"\x01\x00\x00\x00"
    if kind == "timestamp":
        info.date_time = (1980, 1, 1, 0, 0, 2)
    with zipfile.ZipFile(path, "w", compression=info.compress_type, allowZip64=False) as archive:
        archive.comment = b"comment" if kind == "archive-comment" else b""
        archive.writestr(info, b"x")
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        verify_raw_zip_envelope(path)


@pytest.mark.parametrize("field_offset", [4, 6, 8, 10])
def test_rejects_each_multidisk_eocd_field(tmp_path: Path, field_offset: int) -> None:
    path = tmp_path / "package.zip"
    data = _valid_archive(path)
    eocd = _eocd_offset(data)
    path.write_bytes(data[:eocd + field_offset] + b"\x02\x00" + data[eocd + field_offset + 2:])
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        verify_raw_zip_envelope(path)


def test_path_limit_accepts_exact_boundary_and_rejects_one_byte_over(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "package.zip"
    _valid_archive(path)
    import backend.security.project_package_paths as package_paths

    monkeypatch.setattr(package_paths, "MAX_ENTRY_PATH_BYTES", len("project/graph.jsonl"))
    assert verify_raw_zip_envelope(path)
    monkeypatch.setattr(package_paths, "MAX_ENTRY_PATH_BYTES", len("project/graph.jsonl") - 1)
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        verify_raw_zip_envelope(path)


@pytest.mark.parametrize("offset,value", [
    (20, b"\xff\xff\xff\xff"), (24, b"\xff\xff\xff\xff"),
    (42, b"\xff\xff\xff\xff"),
])
def test_rejects_each_central_zip64_sentinel(tmp_path: Path, offset: int, value: bytes) -> None:
    path = tmp_path / "package.zip"
    data = _valid_archive(path)
    central = _central_offset(data)
    path.write_bytes(data[:central + offset] + value + data[central + offset + len(value):])
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        verify_raw_zip_envelope(path)


def test_rejects_local_filename_mismatch_after_valid_central_path(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    data = _valid_archive(path)
    path.write_bytes(data[:30] + b"q" + data[31:])
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        verify_raw_zip_envelope(path)


def test_corrupted_stored_member_is_rejected_during_streamed_crc_verification(tmp_path: Path) -> None:
    path = tmp_path / "package.zip"
    data = _valid_archive(path)
    data_offset = 30 + len("project/graph.jsonl")
    path.write_bytes(data[:data_offset] + b"X" + data[data_offset + 1:])
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive"):
        verify_raw_zip_envelope(path)


def test_truncated_member_stream_reaches_exact_length_guard(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "package.zip"
    _valid_archive(path)
    import backend.security.project_import_archives as archives

    real_open = archives.zipfile.ZipFile.open
    real_invalid = archives._invalid
    invalid_calls = 0

    class TruncatedStream:
        def __init__(self, source) -> None:
            self._source = source

        def __enter__(self):
            self._source.__enter__()
            return self

        def __exit__(self, *args) -> None:
            self._source.__exit__(*args)

        def read(self, size: int = -1) -> bytes:
            self._source.read(size)
            return b""

    def open_truncated(self, *args, **kwargs):
        return TruncatedStream(real_open(self, *args, **kwargs))

    def record_invalid():
        nonlocal invalid_calls
        invalid_calls += 1
        return real_invalid()

    monkeypatch.setattr(archives.zipfile.ZipFile, "open", open_truncated)
    monkeypatch.setattr(archives, "_invalid", record_invalid)
    with pytest.raises(ProjectImportInvalid, match="invalid project import archive") as raised:
        verify_raw_zip_envelope(path)

    assert invalid_calls == 1
    assert raised.value.__cause__ is None
