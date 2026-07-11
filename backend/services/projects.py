"""Atomic project foundation use cases."""

from __future__ import annotations

from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field

from backend.services.projections import build_projection_bundle


class CreateProject(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    genre: str = Field(max_length=120)
    description: str
    target_words: int = Field(gt=0)
    target_chapters: int = Field(gt=0)


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

    @classmethod
    def from_command(cls, command: CreateProject) -> "ProjectResult":
        return cls(
            **command.model_dump(), current_chapter=0, status="drafting"
        )


class UpdateProject(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    title: str | None = None
    genre: str | None = None
    description: str | None = None
    target_words: int | None = Field(default=None, gt=0)
    target_chapters: int | None = Field(default=None, gt=0)
    current_chapter: int | None = Field(default=None, ge=0)
    status: str | None = None


class ProjectService:
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
                session, command.id, content_hash=empty_hash
            )
            await self.repository.insert_contract_head0(session, command.id)
            await self.model_binding_service.initialize_project(session, command.id)
        return ProjectResult.from_command(command)

    async def delete(self, project_id: str) -> None:
        async with self.transaction_factory() as session:
            await self.repository.delete(session, project_id)

    def _connection(self):
        if self.connection_factory is None:
            raise RuntimeError("read connection factory is not configured")
        return self.connection_factory()

    async def list(self):
        async with self._connection() as session:
            return await self.repository.list(session)

    async def get(self, project_id: str):
        async with self._connection() as session:
            return await self.repository.get(session, project_id)

    async def update(self, project_id: str, command: UpdateProject):
        changes = command.model_dump(exclude_none=True)
        async with self.transaction_factory() as session:
            if await self.repository.get(session, project_id) is None:
                return None
            await self.repository.update(session, project_id, changes)
            return await self.repository.get(session, project_id)

    async def content_state(self, project_id: str):
        async with self._connection() as session:
            return await self.repository.content_state(session, project_id)
