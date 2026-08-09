"""Closed import-boundary values and ownership for uploaded project archives."""

from __future__ import annotations

from collections.abc import AsyncIterable
from dataclasses import dataclass, field
import asyncio
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Protocol

from backend.domain.project_packages import MAX_ARCHIVE_BYTES
from backend.security.private_files import PrivateFilePermissionsError, apply_private_permissions


QUARANTINE_PREFIX = "novel-creator-phase6c-"
QUARANTINE_FILENAME = "project-import.zip"
UPLOAD_READ_CHUNK_BYTES = 64 * 1024


class ProjectImportError(Exception):
    """Base class for public import boundary failures."""


class ProjectImportInvalid(ProjectImportError):
    pass


class ProjectImportTooLarge(ProjectImportError):
    pass


class ProjectImportSensitiveData(ProjectImportError):
    pass


def _invalid() -> ProjectImportInvalid:
    return ProjectImportInvalid("invalid project import archive")


def _too_large() -> ProjectImportTooLarge:
    return ProjectImportTooLarge("project import archive exceeds configured limit")


def _is_link(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


class _AsyncReadableUpload(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


async def _upload_chunks(upload: AsyncIterable[bytes] | _AsyncReadableUpload) -> AsyncIterable[bytes]:
    read = getattr(upload, "read", None)
    if callable(read):
        while True:
            chunk = await read(UPLOAD_READ_CHUNK_BYTES)
            if not chunk:
                return
            yield chunk
        return
    async for chunk in upload:  # type: ignore[union-attr]
        yield chunk


@dataclass(slots=True)
class OwnedImportQuarantine:
    """A single random, private upload directory that its caller alone may remove."""

    root: Path
    _archive_path: Path
    _parent: Path
    _cleaned: bool = field(default=False, init=False)

    @property
    def archive_path(self) -> Path:
        return self._archive_path

    @classmethod
    def create(cls, *, temp_parent: Path) -> "OwnedImportQuarantine":
        created_root: Path | None = None
        try:
            parent = Path(temp_parent).resolve(strict=True)
            if not parent.is_dir() or _is_link(parent):
                raise _invalid()
            created_root = Path(tempfile.mkdtemp(prefix=QUARANTINE_PREFIX, dir=parent))
            root = created_root.resolve(strict=True)
            if root.parent != parent or not root.name.startswith(QUARANTINE_PREFIX) or _is_link(root):
                raise _invalid()
            try:
                apply_private_permissions(root, is_directory=True)
            except PrivateFilePermissionsError:
                raise _invalid() from None
            archive_path = root / QUARANTINE_FILENAME
            descriptor = os.open(archive_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
            try:
                apply_private_permissions(archive_path, is_directory=False)
            except PrivateFilePermissionsError:
                raise _invalid() from None
            return cls(root=root, _archive_path=archive_path, _parent=parent)
        except ProjectImportError:
            if created_root is not None:
                shutil.rmtree(created_root, ignore_errors=True)
            raise
        except (OSError, RuntimeError, TypeError, ValueError):
            if created_root is not None:
                shutil.rmtree(created_root, ignore_errors=True)
            raise _invalid() from None

    async def copy_upload(self, upload: AsyncIterable[bytes] | _AsyncReadableUpload) -> Path:
        """Copy an upload in bounded reads; the client filename never influences storage."""

        total = 0
        try:
            with self._archive_path.open("wb") as target:
                async for chunk in _upload_chunks(upload):
                    if type(chunk) is not bytes:
                        raise _invalid()
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise _too_large()
                    target.write(chunk)
            return self._archive_path
        except asyncio.CancelledError:
            try:
                self.cleanup()
            except Exception:
                pass
            raise
        except ProjectImportError:
            self.cleanup()
            raise
        except (OSError, RuntimeError, TypeError, ValueError):
            try:
                self.cleanup()
            except Exception:
                pass
            raise _invalid() from None

    async def store_upload(self, upload: AsyncIterable[bytes] | _AsyncReadableUpload) -> Path:
        return await self.copy_upload(upload)

    def cleanup(self) -> None:
        if self._cleaned:
            return
        try:
            if not self.root.exists():
                self._cleaned = True
                return
            resolved = self.root.resolve(strict=True)
            if (
                resolved.parent != self._parent
                or resolved.name != self.root.name
                or not resolved.name.startswith(QUARANTINE_PREFIX)
                or _is_link(self.root)
                or not self.root.is_dir()
            ):
                raise _invalid()
            shutil.rmtree(resolved)
            self._cleaned = True
        except ProjectImportError:
            raise
        except (OSError, RuntimeError, ValueError):
            raise _invalid() from None
