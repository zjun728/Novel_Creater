"""Fail-closed containment for local files selected from untrusted paths."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
from urllib.parse import unquote


_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_MAX_PERCENT_DECODING_PASSES = 8


class UnsafeLocalPath(ValueError):
    """A local path is absent, not a regular file, or escapes its root."""


def _decoded_relative_parts(relative: str) -> tuple[str, ...]:
    if type(relative) is not str:
        raise UnsafeLocalPath("Local file path must be root-relative text")

    decoded = relative
    try:
        for _ in range(_MAX_PERCENT_DECODING_PASSES):
            next_value = unquote(decoded, errors="strict")
            if next_value == decoded:
                break
            decoded = next_value
        else:
            raise UnsafeLocalPath("Local file path encoding is unsafe")
    except (UnicodeDecodeError, ValueError) as exc:
        raise UnsafeLocalPath("Local file path encoding is unsafe") from exc

    if "\x00" in decoded:
        raise UnsafeLocalPath("Local file path encoding is unsafe")
    windows_path = PureWindowsPath(decoded)
    if windows_path.drive or windows_path.root:
        raise UnsafeLocalPath("Local file path must be root-relative")
    if PurePosixPath(decoded).is_absolute():
        raise UnsafeLocalPath("Local file path must be root-relative")

    parts = tuple(part for part in decoded.replace("\\", "/").split("/") if part)
    if not parts or any(part in {".", ".."} or ":" in part for part in parts):
        raise UnsafeLocalPath("Local file path contains unsafe components")
    return parts


def _is_reparse_or_symlink(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _reject_reparse_components(root: Path, parts: tuple[str, ...]) -> Path:
    candidate = root
    for part in parts:
        candidate = candidate / part
        try:
            if _is_reparse_or_symlink(candidate):
                raise UnsafeLocalPath("Local file path crosses a filesystem link")
        except (FileNotFoundError, NotADirectoryError, OSError) as exc:
            raise UnsafeLocalPath("Local file does not exist safely") from exc
    return candidate


def _is_contained(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_under_root(
    root: Path,
    relative: str,
    suffix: str | None = None,
) -> Path:
    """Resolve one existing regular file while remaining below ``root``."""
    try:
        resolved_root = Path(root).resolve(strict=True)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise UnsafeLocalPath("Local file root does not exist safely") from exc
    if not resolved_root.is_dir():
        raise UnsafeLocalPath("Local file root must be a directory")

    parts = _decoded_relative_parts(relative)
    candidate = _reject_reparse_components(resolved_root, parts)
    try:
        resolved_candidate = candidate.resolve(strict=True)
        candidate_metadata = candidate.lstat()
        resolved_metadata = resolved_candidate.stat()
    except (OSError, RuntimeError, ValueError) as exc:
        raise UnsafeLocalPath("Local file does not exist safely") from exc

    if not _is_contained(resolved_root, resolved_candidate):
        raise UnsafeLocalPath("Local file escapes its configured root")
    if not stat.S_ISREG(candidate_metadata.st_mode) or not stat.S_ISREG(
        resolved_metadata.st_mode
    ):
        raise UnsafeLocalPath("Local path must identify a regular file")
    if suffix is not None:
        if type(suffix) is not str or not suffix:
            raise UnsafeLocalPath("Required local file suffix is invalid")
        if resolved_candidate.suffix.casefold() != suffix.casefold():
            raise UnsafeLocalPath("Local file suffix is not allowed")
    return resolved_candidate


def resolve_spa_file(frontend_dist: Path, decoded_path: str) -> Path:
    """Return a contained SPA file, falling back to a contained index file."""
    try:
        return resolve_under_root(frontend_dist, decoded_path)
    except UnsafeLocalPath:
        return resolve_under_root(frontend_dist, "index.html", suffix=".html")


__all__ = ("UnsafeLocalPath", "resolve_spa_file", "resolve_under_root")
