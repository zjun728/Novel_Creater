"""Byte-level validation of the constrained Phase 6 project ZIP envelope."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import os
import stat
import struct
import zipfile

from backend.domain.project_imports import ProjectImportInvalid, ProjectImportTooLarge
from backend.domain.project_packages import (
    MAX_ARCHIVE_BYTES,
    MAX_CORPUS_BLOB_BYTES,
    MAX_ENTRY_COUNT,
    MAX_STRUCTURED_ENTRY_BYTES,
    MAX_TOTAL_ENTRY_BYTES,
)
from backend.security.project_package_paths import validate_entry_paths


_EOCD = b"PK\x05\x06"
_CENTRAL = b"PK\x01\x02"
_LOCAL = b"PK\x03\x04"
_ZIP64 = (b"PK\x06\x06", b"PK\x06\x07")
_CHUNK_BYTES = 64 * 1024
_DOS_EPOCH_DATE = 0x21


@dataclass(frozen=True, slots=True)
class VerifiedArchiveEntry:
    path: str
    byte_length: int
    crc32: int
    sha256: str
    offset: int


def _invalid() -> ProjectImportInvalid:
    return ProjectImportInvalid("invalid project import archive")


def _too_large() -> ProjectImportTooLarge:
    return ProjectImportTooLarge("project import archive exceeds configured limit")


def _read_exact(handle, offset: int, size: int) -> bytes:
    handle.seek(offset)
    value = handle.read(size)
    if len(value) != size:
        raise _invalid()
    return value


def _entry_path(raw: bytes) -> str:
    try:
        value = raw.decode("ascii", "strict")
        validate_entry_paths((value,))
        return value
    except Exception:
        raise _invalid() from None


def verify_raw_zip_envelope(path: Path) -> tuple[VerifiedArchiveEntry, ...]:
    """Parse and authenticate a Phase 6B ZIP without extracting any member."""

    try:
        archive_path = Path(path)
        metadata = archive_path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise _invalid()
        size = metadata.st_size
        if size > MAX_ARCHIVE_BYTES:
            raise _too_large()
        if size < 22:
            raise _invalid()
        with archive_path.open("rb") as handle:
            tail_size = min(size, 22 + 65535)
            tail_offset = size - tail_size
            tail = _read_exact(handle, tail_offset, tail_size)
            eocd_at = tail.rfind(_EOCD)
            if eocd_at < 0:
                raise _invalid()
            eocd_offset = tail_offset + eocd_at
            if eocd_offset + 22 > size:
                raise _invalid()
            disk, cd_disk, disk_entries, entries, cd_size, cd_offset, comment_size = struct.unpack_from("<HHHHIIH", tail, eocd_at + 4)
            if comment_size != 0 or eocd_offset + 22 != size or disk or cd_disk or disk_entries != entries:
                raise _invalid()
            if entries == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF or any(marker in tail for marker in _ZIP64):
                raise _invalid()
            if entries > MAX_ENTRY_COUNT:
                raise _too_large()
            if cd_offset > eocd_offset or cd_size != eocd_offset - cd_offset:
                raise _invalid()
            central = _read_exact(handle, cd_offset, cd_size)
            cursor = 0
            seen_paths: list[str] = []
            records: list[tuple[str, int, int, int, int]] = []
            for _ in range(entries):
                if cursor + 46 > len(central) or central[cursor:cursor + 4] != _CENTRAL:
                    raise _invalid()
                values = struct.unpack_from("<HHHHHHIIIHHHHHII", central, cursor + 4)
                made_by, needed, flags, method, dos_time, dos_date, crc, compressed, uncompressed, name_size, extra_size, entry_comment_size, disk_start, _internal, external, local_offset = values
                end = cursor + 46 + name_size + extra_size + entry_comment_size
                if end > len(central) or (made_by >> 8) != 3 or needed != 20 or flags != 0 or method != 0 or dos_time != 0 or dos_date != _DOS_EPOCH_DATE or extra_size or entry_comment_size or disk_start or compressed != uncompressed:
                    raise _invalid()
                if (external >> 16) != 0o100600:
                    raise _invalid()
                name = _entry_path(central[cursor + 46:cursor + 46 + name_size])
                seen_paths.append(name)
                records.append((name, crc, uncompressed, local_offset, cursor))
                cursor = end
            if cursor != len(central):
                raise _invalid()
            try:
                validate_entry_paths(seen_paths)
            except Exception:
                raise _invalid() from None
            if len(set(seen_paths)) != len(seen_paths):
                raise _invalid()
            total = 0
            expected_local = 0
            parsed: list[tuple[str, int, int, int]] = []
            for name, crc, length, local_offset, _ in records:
                limit = MAX_CORPUS_BLOB_BYTES if name.startswith("corpus/blobs/sha256/") else MAX_STRUCTURED_ENTRY_BYTES
                if length > limit:
                    raise _too_large()
                total += length
                if total > MAX_TOTAL_ENTRY_BYTES or local_offset != expected_local:
                    raise _too_large() if total > MAX_TOTAL_ENTRY_BYTES else _invalid()
                header = _read_exact(handle, local_offset, 30)
                if header[:4] != _LOCAL:
                    raise _invalid()
                needed, flags, method, dos_time, dos_date, local_crc, compressed, uncompressed, name_size, extra_size = struct.unpack_from("<HHHHHIIIHH", header, 4)
                name_bytes = _read_exact(handle, local_offset + 30, name_size)
                if needed != 20 or flags != 0 or method != 0 or dos_time != 0 or dos_date != _DOS_EPOCH_DATE or extra_size or local_crc != crc or compressed != length or uncompressed != length or name_bytes != name.encode("ascii"):
                    raise _invalid()
                data_offset = local_offset + 30 + name_size
                expected_local = data_offset + length
                if expected_local > cd_offset:
                    raise _invalid()
                parsed.append((name, crc, length, data_offset))
            if expected_local != cd_offset:
                raise _invalid()
        verified: list[VerifiedArchiveEntry] = []
        with zipfile.ZipFile(archive_path, "r", allowZip64=False) as package:
            infos = package.infolist()
            if len(infos) != len(parsed):
                raise _invalid()
            for info, (name, crc, length, offset) in zip(infos, parsed, strict=True):
                if info.filename != name or info.CRC != crc or info.file_size != length or info.header_offset != offset - 30 - len(name):
                    raise _invalid()
                digest = sha256()
                copied = 0
                with package.open(info, "r") as source:
                    while True:
                        chunk = source.read(_CHUNK_BYTES)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > length:
                            raise _invalid()
                        digest.update(chunk)
                if copied != length:
                    raise _invalid()
                verified.append(VerifiedArchiveEntry(name, length, crc, digest.hexdigest(), offset))
        return tuple(verified)
    except (ProjectImportInvalid, ProjectImportTooLarge):
        raise
    except (OSError, RuntimeError, ValueError, struct.error, zipfile.BadZipFile):
        raise _invalid() from None
