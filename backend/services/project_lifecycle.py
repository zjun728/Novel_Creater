"""Transactional project lifecycle use cases."""

from __future__ import annotations

from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field

from backend.http_errors import (
    ProjectArchived,
    ProjectBusy,
    ProjectLifecycleConflict,
    ProjectNotFound,
)
from backend.services.projections import build_projection_bundle


class CreateProject(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    genre: str = ""
    description: str = ""
    target_words: int = 100_000
    target_chapters: int = 100


class ProjectResult(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    id: str
    title: str
    genre: str
    description: str
    target_words: int
    target_chapters: int
    current_chapter: int
    status: str
    archived_at: int | None
    lifecycle_revision: int

    @classmethod
    def from_command(cls, command: CreateProject) -> "ProjectResult":
        return cls(
            **command.model_dump(),
            current_chapter=0,
            status="drafting",
            archived_at=None,
            lifecycle_revision=0,
        )

    @classmethod
    def from_row(cls, row) -> "ProjectResult":
        return cls(**{field: row[field] for field in cls.model_fields})


class ProjectLifecycleService:
    def __init__(
        self,
        repository,
        transaction_factory,
        connection_factory=None,
        *,
        model_binding_service=None,
    ):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.model_binding_service = model_binding_service

    @staticmethod
    def bootstrap_idempotency_key(project_id: str) -> str:
        return sha256(f"{project_id}/revision-0".encode("utf-8")).hexdigest()

    async def create(self, command: CreateProject) -> ProjectResult:
        empty_hash = build_projection_bundle(0, ()).content_hash
        async with self.transaction_factory() as session:
            if self.model_binding_service is None:
                raise RuntimeError("model binding service is not configured")
            await self.model_binding_service.lock_project_creation(session)
            await self.repository.insert_project(session, command)
            await self.repository.insert_bootstrap_revision(
                session,
                command.id,
                content_hash=empty_hash,
                idempotency_key=self.bootstrap_idempotency_key(command.id),
            )
            await self.repository.insert_projection_head(
                session,
                command.id,
                content_hash=empty_hash,
            )
            await self.repository.insert_contract_head0(session, command.id)
            await self.model_binding_service.initialize_project(
                session, command.id
            )
        return ProjectResult.from_command(command)

    def _connection(self):
        if self.connection_factory is None:
            raise RuntimeError("read connection factory is not configured")
        return self.connection_factory()

    async def list_active(self) -> list[ProjectResult]:
        async with self._connection() as session:
            rows = await self.repository.list_active(session)
        return [ProjectResult.from_row(row) for row in rows]

    async def list_archived(self) -> list[ProjectResult]:
        async with self._connection() as session:
            rows = await self.repository.list_archived(session)
        return [ProjectResult.from_row(row) for row in rows]

    async def get(
        self, project_id: str, *, include_archived: bool = False
    ) -> ProjectResult:
        async with self._connection() as session:
            row = await self.repository.get_any(session, project_id)
        if row is None:
            raise ProjectNotFound()
        if row["archived_at"] is not None and not include_archived:
            raise ProjectArchived()
        return ProjectResult.from_row(row)

    async def rename(self, project_id: str, title: str) -> ProjectResult:
        async with self.transaction_factory() as session:
            row = await self.repository.lock_active_project(session, project_id)
            if row is None:
                row = await self.repository.lock_any(session, project_id)
                if row is None:
                    raise ProjectNotFound()
                raise ProjectArchived()
            if not await self.repository.rename(session, project_id, title):
                raise ProjectLifecycleConflict()
            updated = await self.repository.get_any(session, project_id)
            if updated is None:
                raise ProjectLifecycleConflict()
            return ProjectResult.from_row(updated)

    async def archive(
        self,
        project_id: str,
        expected_lifecycle_revision: int,
    ) -> ProjectResult:
        async with self.transaction_factory() as session:
            row = await self._lock_lifecycle_project(session, project_id)
            if row["archived_at"] is not None:
                raise ProjectArchived()
            self._require_revision(row, expected_lifecycle_revision)
            await self._require_not_busy(session, project_id)
            if not await self.repository.archive(
                session,
                project_id,
                expected_lifecycle_revision,
            ):
                raise ProjectLifecycleConflict()
            return await self._read_changed_project(session, project_id)

    async def restore(
        self,
        project_id: str,
        expected_lifecycle_revision: int,
    ) -> ProjectResult:
        async with self.transaction_factory() as session:
            row = await self._lock_lifecycle_project(session, project_id)
            if row["archived_at"] is None:
                raise ProjectLifecycleConflict()
            self._require_revision(row, expected_lifecycle_revision)
            await self._require_not_busy(session, project_id)
            if not await self.repository.restore(
                session,
                project_id,
                expected_lifecycle_revision,
            ):
                raise ProjectLifecycleConflict()
            return await self._read_changed_project(session, project_id)

    async def permanently_delete(
        self,
        project_id: str,
        expected_lifecycle_revision: int,
    ) -> None:
        async with self.transaction_factory() as session:
            row = await self._lock_lifecycle_project(session, project_id)
            if row["archived_at"] is None:
                raise ProjectLifecycleConflict()
            self._require_revision(row, expected_lifecycle_revision)
            await self._require_not_busy(session, project_id)
            if not await self.repository.permanently_delete(
                session,
                project_id,
                expected_lifecycle_revision,
            ):
                raise ProjectLifecycleConflict()

    async def _lock_lifecycle_project(self, session, project_id: str):
        row = await self.repository.lock_any(session, project_id)
        if row is None:
            raise ProjectNotFound()
        return row

    @staticmethod
    def _require_revision(row, expected_lifecycle_revision: int) -> None:
        if row["lifecycle_revision"] != expected_lifecycle_revision:
            raise ProjectLifecycleConflict()

    async def _require_not_busy(self, session, project_id: str) -> None:
        if await self.repository.has_unfinished_operation(session, project_id):
            raise ProjectBusy()

    async def _read_changed_project(
        self, session, project_id: str
    ) -> ProjectResult:
        row = await self.repository.get_any(session, project_id)
        if row is None:
            raise ProjectLifecycleConflict()
        return ProjectResult.from_row(row)
