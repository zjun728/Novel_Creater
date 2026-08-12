"""Command-owned file staging and orchestration for atomic project imports."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import time
from types import MappingProxyType
from uuid import UUID, uuid4
import zipfile

from backend.database import connection, transaction
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.project_import_plans import (
    ProjectImportSummary,
    VerifiedProjectPackage,
    build_publication_plan,
    read_verified_project_package,
)
from backend.domain.project_imports import OwnedImportQuarantine, ProjectImportInvalid
from backend.repositories.project_imports import (
    MAX_IMPORT_LEASE_MS,
    ProjectImportCommandStateConflict,
    ProjectImportCommandView,
    ProjectImportPersistenceError,
    ProjectImportRepository,
)
from backend.security.paths import (
    UnsafeLocalPath,
    ensure_managed_corpus_blob_parent,
    managed_corpus_blob_path,
    managed_corpus_storage_key,
)
from backend.security.private_files import PrivateFilePermissionsError, apply_private_permissions


STAGING_DIRECTORY = ".project-import-staging"
STAGING_MANIFEST = "manifest.json"
CLAIM_DIRECTORY = ".claims"
RECOVERY_SCAN_LIMIT = 32
CLAIM_WAIT_SECONDS = 30.0
CLAIM_INITIAL_BACKOFF_SECONDS = 0.01
CLAIM_MAX_BACKOFF_SECONDS = 0.25
_HASH = re.compile(r"[0-9a-f]{64}")
_KEY = re.compile(r"[a-z0-9_-]{16,64}")


def _invalid() -> ProjectImportInvalid:
    return ProjectImportInvalid("invalid project import archive")


def _claim_monotonic() -> float:
    return time.monotonic()


async def _claim_sleep(delay: float) -> None:
    await asyncio.sleep(delay)


def _cleanup_owned_directory(root: Path, parent: Path) -> None:
    """Validate one exact owned child and retry a transient removal failure once."""
    if not root.exists():
        return
    try:
        resolved_parent = parent.resolve(strict=True)
        resolved = root.resolve(strict=True)
        if root.is_symlink() or not root.is_dir() or resolved.parent != resolved_parent:
            raise _invalid()
    except ProjectImportInvalid:
        raise
    except (OSError, RuntimeError, ValueError):
        raise _invalid() from None
    for attempt in range(2):
        try:
            shutil.rmtree(resolved)
            return
        except (OSError, RuntimeError, ValueError):
            if attempt:
                raise _invalid() from None


def _cleanup_quarantine(owner: OwnedImportQuarantine) -> None:
    for attempt in range(2):
        try:
            owner.cleanup()
            return
        except BaseException:
            if attempt:
                raise


@dataclass(frozen=True, slots=True)
class ImportProjectRequest:
    command_id: str
    idempotency_key: str
    expected_package_hash: str
    new_title: str

    def __post_init__(self) -> None:
        try:
            UUID(self.command_id)
        except (TypeError, ValueError, AttributeError):
            raise _invalid() from None
        title = self.new_title.strip() if isinstance(self.new_title, str) else ""
        if (
            not isinstance(self.command_id, str)
            or not isinstance(self.idempotency_key, str)
            or _KEY.fullmatch(self.idempotency_key) is None
            or not isinstance(self.expected_package_hash, str)
            or _HASH.fullmatch(self.expected_package_hash) is None
            or title != self.new_title
            or not 1 <= len(title) <= 200
        ):
            raise _invalid()


def build_import_request_fingerprint(
    *, package_hash: str, manifest_hash: str, package_version: int,
    normalized_title: str, command_id: str, idempotency_key: str,
) -> str:
    """Hash exactly the closed import decision fields using their public names."""
    return canonical_hash({
        "commandId": command_id,
        "idempotencyKey": idempotency_key,
        "manifestHash": manifest_hash,
        "normalizedTitle": normalized_title,
        "packageHash": package_hash,
        "packageVersion": package_version,
    })


@dataclass(frozen=True, slots=True)
class StagedBlob:
    content_hash: str
    byte_length: int
    storage_key: str
    created: bool

    def public_value(self) -> dict[str, object]:
        return {
            "byteLength": self.byte_length,
            "contentHash": self.content_hash,
            "created": self.created,
            "storageKey": self.storage_key,
        }


@dataclass(slots=True)
class ProjectImportStaging:
    managed_root: Path
    command_id: str
    root: Path
    blobs: tuple[StagedBlob, ...]
    _cleaned: bool = False
    _installed_hashes: set[str] = field(default_factory=set, init=False)

    @classmethod
    def stage(
        cls, package: VerifiedProjectPackage, plan, *, managed_corpus_root: Path,
        command_id: str,
    ) -> "ProjectImportStaging":
        try:
            UUID(command_id)
            managed = Path(managed_corpus_root).resolve(strict=True)
            staging_parent = managed / STAGING_DIRECTORY
            staging_parent.mkdir(exist_ok=True)
            apply_private_permissions(staging_parent, is_directory=True)
            root = staging_parent / command_id
            if root.exists():
                if root.is_symlink() or not root.is_dir() or root.resolve(strict=True).parent != staging_parent.resolve(strict=True):
                    raise _invalid()
                manifest_path = root / STAGING_MANIFEST
                if manifest_path.exists():
                    prior = json.loads(manifest_path.read_text("utf-8"))
                    if not isinstance(prior, dict) or prior.get("commandId") != command_id:
                        raise _invalid()
                elif any(item.is_symlink() or (item.name != STAGING_MANIFEST and _HASH.fullmatch(item.name) is None) for item in root.iterdir()):
                    raise _invalid()
                _cleanup_owned_directory(root, staging_parent)
            root.mkdir(exist_ok=False)
            apply_private_permissions(root, is_directory=True)
            staged: list[StagedBlob] = []
            with zipfile.ZipFile(package.archive_path, "r") as archive:
                for content_hash, byte_length in plan.blobs:
                    source_name = f"corpus/blobs/sha256/{content_hash}"
                    data = archive.read(source_name)
                    if len(data) != byte_length or sha256(data).hexdigest() != content_hash:
                        raise _invalid()
                    stage_file = root / content_hash
                    descriptor = os.open(stage_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, "wb") as target:
                        target.write(data)
                    apply_private_permissions(stage_file, is_directory=False)
                    destination = managed_corpus_blob_path(managed, content_hash)
                    if destination.exists():
                        existing = destination.read_bytes()
                        if len(existing) != byte_length or sha256(existing).hexdigest() != content_hash:
                            raise ProjectImportCommandStateConflict()
                    staged.append(StagedBlob(
                        content_hash, byte_length,
                        managed_corpus_storage_key(content_hash), False,
                    ))
            manifest = {
                "blobs": [item.public_value() for item in staged],
                "commandId": command_id,
                "idMapHash": plan.id_map_hash,
            }
            manifest_path = root / STAGING_MANIFEST
            descriptor = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as target:
                target.write(canonical_json(manifest).encode("utf-8"))
            apply_private_permissions(manifest_path, is_directory=False)
            return cls(managed, command_id, root, tuple(staged))
        except BaseException as error:
            if "root" in locals():
                try:
                    _cleanup_owned_directory(root, staging_parent)
                except BaseException:
                    pass
            if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit, ProjectImportInvalid, ProjectImportCommandStateConflict)):
                raise
            raise _invalid() from None

    @property
    def manifest(self) -> Mapping[str, object]:
        return MappingProxyType({
            "blobs": [item.public_value() for item in self.blobs],
            "commandId": self.command_id,
            "idMapHash": json.loads((self.root / STAGING_MANIFEST).read_text("utf-8"))["idMapHash"],
        })

    def _write_manifest(self) -> None:
        value = dict(self.manifest)
        target = self.root / STAGING_MANIFEST
        temporary = self.root / f"{STAGING_MANIFEST}.new"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical_json(value).encode("utf-8"))
        apply_private_permissions(temporary, is_directory=False)
        os.replace(temporary, target)
        apply_private_permissions(target, is_directory=False)

    async def _acquire_claim(self, item: StagedBlob) -> Path:
        claim_parent = self.root.parent / CLAIM_DIRECTORY
        claim = claim_parent / item.content_hash
        deadline = _claim_monotonic() + CLAIM_WAIT_SECONDS
        delay = CLAIM_INITIAL_BACKOFF_SECONDS
        attempted = False

        async def wait_for_retry() -> None:
            nonlocal delay
            remaining = deadline - _claim_monotonic()
            if remaining <= 0:
                raise ProjectImportCommandStateConflict() from None
            await _claim_sleep(min(delay, remaining))
            delay = min(delay * 2, CLAIM_MAX_BACKOFF_SECONDS)

        def cleanup_created_claim(created_identity: os.stat_result) -> None:
            try:
                current_identity = os.stat(claim, follow_symlinks=False)
                if os.path.samestat(created_identity, current_identity):
                    claim.unlink()
            except BaseException:
                pass

        def cleanup_empty_claim_parent() -> None:
            try:
                claim_parent.rmdir()
            except BaseException:
                pass

        def cleanup_failed_attempt(
            *, created_identity: os.stat_result | None, parent_created: bool,
        ) -> None:
            if created_identity is not None:
                cleanup_created_claim(created_identity)
            if parent_created or created_identity is not None:
                cleanup_empty_claim_parent()

        while True:
            if attempted and _claim_monotonic() >= deadline:
                raise ProjectImportCommandStateConflict() from None
            attempted = True
            created_identity = None
            try:
                parent_created = False
                try:
                    claim_parent.mkdir(exist_ok=False)
                    parent_created = True
                except FileExistsError:
                    pass
                if claim_parent.is_symlink() or not claim_parent.is_dir():
                    claim_parent.lstat()
                    raise ProjectImportPersistenceError()
                if parent_created:
                    apply_private_permissions(claim_parent, is_directory=True)
                try:
                    descriptor = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    await wait_for_retry()
                    continue
                created_identity = os.fstat(descriptor)
                output = None
                try:
                    output = os.fdopen(descriptor, "w", encoding="ascii")
                    output.write(self.command_id)
                    output.flush()
                    output.close()
                except BaseException:
                    if output is not None:
                        try:
                            output.close()
                        except BaseException:
                            pass
                    try:
                        open_identity = os.fstat(descriptor)
                        if os.path.samestat(created_identity, open_identity):
                            os.close(descriptor)
                    except OSError:
                        pass
                    raise
                apply_private_permissions(claim, is_directory=False)
                return claim
            except FileNotFoundError:
                cleanup_failed_attempt(
                    created_identity=created_identity, parent_created=parent_created,
                )
                await wait_for_retry()
                continue
            except ProjectImportPersistenceError:
                cleanup_failed_attempt(
                    created_identity=created_identity, parent_created=parent_created,
                )
                raise
            except (OSError, PrivateFilePermissionsError, RuntimeError, ValueError):
                cleanup_failed_attempt(
                    created_identity=created_identity, parent_created=parent_created,
                )
                raise ProjectImportPersistenceError() from None
            except BaseException:
                cleanup_failed_attempt(
                    created_identity=created_identity, parent_created=parent_created,
                )
                raise

    def _release_claim(self, claim: Path) -> None:
        try:
            if claim.is_file() and not claim.is_symlink() and claim.read_text("ascii") == self.command_id:
                claim.unlink()
                try:
                    claim.parent.rmdir()
                except OSError:
                    pass
        except (OSError, UnicodeError):
            raise _invalid() from None

    async def promote(self, persist_manifest: Callable[[str], object]) -> None:
        values = list(self.blobs)

        async def persist_decision(index: int, item: StagedBlob, created: bool) -> None:
            values[index] = StagedBlob(
                item.content_hash, item.byte_length, item.storage_key, created,
            )
            self.blobs = tuple(values)
            self._write_manifest()
            result = persist_manifest(canonical_json(dict(self.manifest)))
            if hasattr(result, "__await__"):
                await result

        for index, item in enumerate(values):
            source = self.root / item.content_hash
            claim = await self._acquire_claim(item)
            try:
                destination = managed_corpus_blob_path(self.managed_root, item.content_hash)
                created = False
                if destination.exists():
                    data = destination.read_bytes()
                    if len(data) != item.byte_length or sha256(data).hexdigest() != item.content_hash:
                        raise ProjectImportCommandStateConflict()
                    await persist_decision(index, item, False)
                else:
                    destination = ensure_managed_corpus_blob_parent(self.managed_root, item.content_hash)
                    # The claim makes this ownership decision exclusive among importers.
                    # Persist it before the no-overwrite install so a crash is recoverable.
                    await persist_decision(index, item, True)
                    try:
                        os.link(source, destination)
                        created = True
                        # Runtime cleanup ownership begins only after this exact
                        # command wins the atomic no-overwrite installation.
                        self._installed_hashes.add(item.content_hash)
                        apply_private_permissions(destination, is_directory=False)
                    except FileExistsError:
                        data = destination.read_bytes()
                        if len(data) != item.byte_length or sha256(data).hexdigest() != item.content_hash:
                            raise ProjectImportCommandStateConflict()
                        await persist_decision(index, item, False)
                if created:
                    # Re-emit the same canonical authority after ACL verification.
                    await persist_decision(index, item, True)
                source.unlink(missing_ok=True)
            finally:
                self._release_claim(claim)

    def cleanup_root(self) -> None:
        if not self._cleaned:
            _cleanup_owned_directory(
                self.root, self.managed_root / STAGING_DIRECTORY,
            )
            self._cleaned = True


class ProjectImportService:
    def __init__(
        self, *, repository: ProjectImportRepository, managed_corpus_root: Path,
        temp_parent: Path, connection_factory=connection, transaction_factory=transaction,
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
        owner_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._repository = repository
        self._managed_root = Path(managed_corpus_root)
        self._temp_parent = Path(temp_parent)
        self._connection = connection_factory
        self._transaction = transaction_factory
        self._clock = clock
        self._owner_factory = owner_factory

    async def _verified(self, upload) -> tuple[OwnedImportQuarantine, VerifiedProjectPackage]:
        owner = OwnedImportQuarantine.create(temp_parent=self._temp_parent)
        try:
            await owner.store_upload(upload)
            return owner, read_verified_project_package(owner.archive_path)
        except BaseException:
            try:
                _cleanup_quarantine(owner)
            except BaseException:
                pass
            raise

    async def preflight(self, upload) -> ProjectImportSummary:
        owner, package = await self._verified(upload)
        try:
            return package.summary
        finally:
            _cleanup_quarantine(owner)

    async def get_command(self, command_id: str) -> ProjectImportCommandView:
        try:
            UUID(command_id)
        except (TypeError, ValueError, AttributeError):
            raise ProjectImportCommandStateConflict() from None
        async with self._connection() as session:
            view = await self._repository.read_command(
                session, command_id=command_id, now_ms=self._clock(),
            )
        if view is None:
            raise ProjectImportCommandStateConflict()
        return view

    async def _cleanup_unreferenced_created(
        self, staging: ProjectImportStaging, *, recovery_manifest: bool = False,
    ) -> None:
        """Remove only this command's byte-identical, still-unreferenced promotions."""
        async with self._connection() as session:
            for item in staging.blobs:
                if (
                    item.content_hash not in staging._installed_hashes
                    and not (recovery_manifest and item.created)
                ):
                    continue
                referenced = await self._repository.corpus_blob_is_referenced(
                    session, content_hash=item.content_hash,
                )
                if referenced:
                    continue
                path = managed_corpus_blob_path(self._managed_root, item.content_hash)
                if not path.is_file() or path.is_symlink():
                    continue
                data = path.read_bytes()
                if len(data) == item.byte_length and sha256(data).hexdigest() == item.content_hash:
                    path.unlink()

    async def _clear_reclaimed_command_root(self, command_id: str) -> None:
        """Reconcile the exact root after this service has acquired its command lease."""
        parent = self._managed_root.resolve(strict=True) / STAGING_DIRECTORY
        if not parent.exists():
            return
        parent = parent.resolve(strict=True)
        root = parent / command_id
        if not root.exists():
            return
        if root.is_symlink() or not root.is_dir() or root.resolve(strict=True).parent != parent:
            raise _invalid()
        manifest_path = root / STAGING_MANIFEST
        if manifest_path.exists():
            try:
                value = json.loads(manifest_path.read_text("utf-8"))
                if value.get("commandId") != command_id or not isinstance(value.get("blobs"), list):
                    raise ValueError
                blobs = tuple(StagedBlob(
                    item["contentHash"], item["byteLength"], item["storageKey"], item["created"],
                ) for item in value["blobs"])
                if any(
                    _HASH.fullmatch(item.content_hash) is None
                    or item.storage_key != managed_corpus_storage_key(item.content_hash)
                    or type(item.byte_length) is not int or item.byte_length < 0
                    or type(item.created) is not bool
                    for item in blobs
                ):
                    raise ValueError
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                raise _invalid() from None
            await self._cleanup_unreferenced_created(
                ProjectImportStaging(self._managed_root, command_id, root, blobs),
                recovery_manifest=True,
            )
        elif any(item.is_symlink() or _HASH.fullmatch(item.name) is None for item in root.iterdir()):
            raise _invalid()
        _cleanup_owned_directory(root, parent)

    async def _persist_manifest(
        self, *, command_id: str, fingerprint: str, owner_token: str,
        manifest_json: str,
    ) -> None:
        async with self._transaction() as session:
            await self._repository.persist_staging_manifest(
                session, command_id=command_id,
                request_fingerprint=fingerprint, owner_token=owner_token,
                manifest_json=manifest_json, now_ms=self._clock(),
            )

    async def import_project(self, upload, request: ImportProjectRequest) -> ProjectImportCommandView:
        if type(request) is not ImportProjectRequest:
            raise _invalid()
        quarantine, package = await self._verified(upload)
        staging: ProjectImportStaging | None = None
        owner_token = self._owner_factory()
        fingerprint = ""
        leased = False
        published = False
        primary_error: BaseException | None = None
        try:
            if package.package_hash != request.expected_package_hash:
                raise _invalid()
            plan = build_publication_plan(package, request.command_id, request.new_title)
            fingerprint = build_import_request_fingerprint(
                package_hash=package.package_hash, manifest_hash=package.manifest_hash,
                package_version=package.summary.package_version,
                normalized_title=request.new_title, command_id=request.command_id,
                idempotency_key=request.idempotency_key,
            )
            now = self._clock()
            async with self._transaction() as session:
                reserved = await self._repository.reserve_command(
                    session, command_id=request.command_id,
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=fingerprint, package_hash=package.package_hash,
                    manifest_hash=package.manifest_hash,
                    package_version=package.summary.package_version,
                    target_project_id=plan.target_project_id,
                    normalized_title=request.new_title, now_ms=now,
                )
                if reserved.status == "succeeded":
                    return reserved
                await self._repository.acquire_lease(
                    session, command_id=request.command_id,
                    request_fingerprint=fingerprint, owner_token=owner_token,
                    now_ms=now, lease_expires_at=now + MAX_IMPORT_LEASE_MS,
                )
                leased = True
            await self._clear_reclaimed_command_root(request.command_id)
            staging = ProjectImportStaging.stage(
                package, plan, managed_corpus_root=self._managed_root,
                command_id=request.command_id,
            )
            await self._persist_manifest(
                command_id=request.command_id, fingerprint=fingerprint,
                owner_token=owner_token,
                manifest_json=canonical_json(dict(staging.manifest)),
            )

            async def persist_promoted_manifest(value: str) -> None:
                await self._persist_manifest(
                    command_id=request.command_id, fingerprint=fingerprint,
                    owner_token=owner_token, manifest_json=value,
                )

            await staging.promote(persist_promoted_manifest)
            async with self._transaction() as session:
                await self._repository.publish_project(
                    session, plan, now=self._clock(), request_fingerprint=fingerprint,
                    owner_token=owner_token,
                )
            published = True
            return await self.get_command(request.command_id)
        except BaseException as error:
            primary_error = error
            raise
        finally:
            if staging is not None:
                try:
                    if not published:
                        await self._cleanup_unreferenced_created(staging)
                    staging.cleanup_root()
                except BaseException:
                    pass
            if primary_error is not None and leased and fingerprint:
                try:
                    async with self._transaction() as session:
                        await self._repository.mark_failed(
                            session, command_id=request.command_id,
                            request_fingerprint=fingerprint, owner_token=owner_token,
                            now_ms=self._clock(),
                        )
                except BaseException:
                    pass
            try:
                _cleanup_quarantine(quarantine)
            except BaseException:
                pass


async def reconcile_project_import_staging(
    *, managed_corpus_root: Path, connection_factory=connection,
    transaction_factory=None, now_ms: int | None = None,
    repository: ProjectImportRepository | None = None,
) -> int:
    """Reconcile only the at-most-32 commands selected by database authority."""
    managed = Path(managed_corpus_root).resolve(strict=True)
    parent = managed / STAGING_DIRECTORY
    if not parent.is_dir():
        return 0
    now = int(time.time() * 1000) if now_ms is None else now_ms
    repo = ProjectImportRepository() if repository is None else repository
    async with connection_factory() as session:
        commands = await repo.list_recovery_commands(
            session, now_ms=now, limit=RECOVERY_SCAN_LIMIT,
        )
    recovery_transaction = connection_factory if transaction_factory is None else transaction_factory
    for candidate in commands:
        try:
            async with recovery_transaction() as session:
                command = await repo.fence_recovery_command(
                    session, candidate=candidate, now_ms=now,
                )
                if command is None:
                    continue
                root = parent / command.command_id
                UUID(command.command_id)
                if not root.exists() or not root.is_dir() or root.is_symlink():
                    continue
                manifest_path = root / STAGING_MANIFEST
                disk_text = manifest_path.read_text("utf-8")
                manifest = json.loads(disk_text)
                authority = json.loads(command.staging_manifest_json)
                if (
                    not isinstance(manifest, dict)
                    or set(manifest) != {"blobs", "commandId", "idMapHash"}
                    or manifest.get("commandId") != command.command_id
                    or _HASH.fullmatch(manifest.get("idMapHash", "")) is None
                    or not isinstance(manifest.get("blobs"), list)
                    or disk_text != canonical_json(manifest)
                    or canonical_json(authority) != disk_text
                ):
                    continue
                seen: set[str] = set()
                valid = True
                for blob in manifest["blobs"]:
                    if (
                        not isinstance(blob, dict)
                        or set(blob) != {"byteLength", "contentHash", "created", "storageKey"}
                        or not isinstance(blob.get("contentHash"), str)
                        or _HASH.fullmatch(blob["contentHash"]) is None
                        or blob["contentHash"] in seen
                        or type(blob.get("byteLength")) is not int
                        or blob["byteLength"] < 0
                        or type(blob.get("created")) is not bool
                        or blob.get("storageKey") != managed_corpus_storage_key(blob["contentHash"])
                    ):
                        valid = False
                        break
                    seen.add(blob["contentHash"])
                if not valid:
                    continue
                for blob in manifest["blobs"]:
                    digest = blob["contentHash"]
                    if blob["created"] is True:
                        referenced = await repo.corpus_blob_is_referenced(
                            session, content_hash=digest,
                        )
                        if not referenced:
                            path = managed_corpus_blob_path(managed, digest)
                            if path.is_file() and not path.is_symlink():
                                data = path.read_bytes()
                                if len(data) == blob["byteLength"] and sha256(data).hexdigest() == digest:
                                    path.unlink()
                    claim = parent / CLAIM_DIRECTORY / digest
                    if claim.is_file() and not claim.is_symlink() and claim.read_text("ascii") == command.command_id:
                        claim.unlink()
                        try:
                            claim.parent.rmdir()
                        except OSError:
                            pass
                _cleanup_owned_directory(root, parent)
        except (OSError, ValueError, TypeError, json.JSONDecodeError, UnsafeLocalPath):
            continue
    return len(commands)


__all__ = (
    "ImportProjectRequest", "ProjectImportService", "ProjectImportStaging",
    "RECOVERY_SCAN_LIMIT", "STAGING_DIRECTORY", "StagedBlob",
    "build_import_request_fingerprint", "reconcile_project_import_staging",
)
