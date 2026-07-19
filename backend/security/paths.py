"""Fail-closed containment for local files selected from untrusted paths."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
from urllib.parse import unquote


_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_MAX_PERCENT_DECODING_PASSES = 8
_LOWERCASE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


def managed_corpus_storage_key(content_hash: str) -> str:
    """Derive one canonical storage key from a SHA-256 digest only."""

    if (
        type(content_hash) is not str
        or _LOWERCASE_SHA256.fullmatch(content_hash) is None
    ):
        raise UnsafeLocalPath("Managed corpus identity must be lowercase SHA-256")
    return f"sha256/{content_hash[:2]}/{content_hash}"


def managed_corpus_blob_path(root: Path, content_hash: str) -> Path:
    """Resolve the hash-derived managed blob path below an existing root."""

    storage_key = managed_corpus_storage_key(content_hash)
    try:
        supplied_root = Path(root)
        if _is_reparse_or_symlink(supplied_root):
            raise UnsafeLocalPath(
                "Managed corpus root cannot be a filesystem link"
            )
        resolved_root = supplied_root.resolve(strict=True)
    except UnsafeLocalPath:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise UnsafeLocalPath("Managed corpus root does not exist safely") from exc
    if not resolved_root.is_dir() or _is_reparse_or_symlink(resolved_root):
        raise UnsafeLocalPath("Managed corpus root must be a regular directory")
    parts = tuple(storage_key.split("/"))
    candidate = resolved_root
    missing_parent = False
    for index, part in enumerate(parts):
        candidate = candidate / part
        if missing_parent:
            continue
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            missing_parent = True
            continue
        except OSError as exc:
            raise UnsafeLocalPath(
                "Managed corpus blob path cannot be inspected safely"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or bool(
            getattr(metadata, "st_file_attributes", 0)
            & _FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise UnsafeLocalPath(
                "Managed corpus blob path crosses a filesystem link"
            )
        is_final = index == len(parts) - 1
        if not is_final and not stat.S_ISDIR(metadata.st_mode):
            raise UnsafeLocalPath(
                "Managed corpus blob parent must be a directory"
            )
        if is_final and not stat.S_ISREG(metadata.st_mode):
            raise UnsafeLocalPath(
                "Managed corpus blob must be a regular file"
            )
        try:
            resolved_component = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise UnsafeLocalPath(
                "Managed corpus blob path does not resolve safely"
            ) from exc
        if not _is_contained(resolved_root, resolved_component):
            raise UnsafeLocalPath(
                "Managed corpus blob escapes its configured root"
            )
    if not _is_contained(resolved_root, candidate):
        raise UnsafeLocalPath("Managed corpus blob escapes its configured root")
    return candidate


def ensure_managed_corpus_blob_parent(
    root: Path, content_hash: str
) -> Path:
    """Create hash-derived parent directories one component at a time."""

    final = managed_corpus_blob_path(root, content_hash)
    resolved_root = Path(root).resolve(strict=True)
    for directory in (resolved_root / "sha256", final.parent):
        try:
            directory.mkdir(exist_ok=True)
            metadata = directory.lstat()
            resolved = directory.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise UnsafeLocalPath(
                "Managed corpus blob parent cannot be created safely"
            ) from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or _is_reparse_or_symlink(directory)
            or not _is_contained(resolved_root, resolved)
        ):
            raise UnsafeLocalPath(
                "Managed corpus blob parent is unsafe"
            )
    return managed_corpus_blob_path(resolved_root, content_hash)


__all__ = (
    "UnsafeLocalPath",
    "ensure_managed_corpus_blob_parent",
    "managed_corpus_blob_path",
    "managed_corpus_storage_key",
    "resolve_spa_file",
    "resolve_under_root",
)
