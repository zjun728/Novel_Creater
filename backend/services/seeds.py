"""Atomic immutable seed CRUD, selection CAS, and backend readiness facts."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.seeds import SeedPayload
from backend.http_errors import SeedConflict, SeedLocked, SeedNotFound


_STRICT = ConfigDict(strict=True, frozen=True, extra="forbid")


class CreateSeed(BaseModel):
    model_config = _STRICT
    project_id: str = Field(min_length=1)
    payload: SeedPayload


class EditSeed(BaseModel):
    model_config = _STRICT
    project_id: str = Field(min_length=1)
    seed_id: str = Field(min_length=1)
    payload: SeedPayload
    expected_seed_revision: int = Field(gt=0)
    expected_selection_revision: int = Field(ge=0)


class SelectSeed(BaseModel):
    model_config = _STRICT
    project_id: str = Field(min_length=1)
    seed_id: str = Field(min_length=1)
    expected_seed_revision: int = Field(gt=0)
    expected_selection_revision: int = Field(ge=0)


class DeleteSeed(BaseModel):
    model_config = _STRICT
    project_id: str = Field(min_length=1)
    seed_id: str = Field(min_length=1)
    expected_seed_revision: int = Field(gt=0)
    expected_selection_revision: int = Field(ge=0)


class SeedResult(BaseModel):
    model_config = _STRICT
    id: str
    project_id: str
    status: str
    revision: int = Field(gt=0)
    revision_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: SeedPayload
    is_selected: bool
    selection_revision: int = Field(ge=0)


class SelectedSeedResult(BaseModel):
    model_config = _STRICT
    selected: SeedResult | None
    seed_ready: bool
    contract_ready: bool
    reasons: tuple[str, ...]


def _decode_payload(value: object) -> SeedPayload:
    if isinstance(value, str):
        value = json.loads(value)
    return SeedPayload.model_validate(value)


def _selection_revision(selection: Mapping | None) -> int:
    return int(selection["selection_revision"]) if selection else 0


class SeedService:
    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        connection_factory=None,
        id_factory=None,
        clock=None,
    ):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.clock = clock or (lambda: int(time.time() * 1000))

    async def _lock_project_for_mutation(self, session, project_id: str) -> None:
        if await self.repository.lock_project(session, project_id) is None:
            raise SeedNotFound()
        if await self.repository.count_final_chapters(session, project_id):
            raise SeedLocked()

    @staticmethod
    def _result(
        row: Mapping,
        *,
        is_selected: bool | None = None,
        selection_revision: int | None = None,
    ) -> SeedResult:
        return SeedResult(
            id=row["id"],
            project_id=row["project_id"],
            status=row["status"],
            revision=int(row["revision"]),
            revision_id=row.get("revision_id", row.get("id")),
            content_hash=row["content_hash"],
            payload=_decode_payload(row["payload_json"]),
            is_selected=(
                bool(row.get("is_selected"))
                if is_selected is None else is_selected
            ),
            selection_revision=(
                int(row.get("selection_revision") or 0)
                if selection_revision is None else selection_revision
            ),
        )

    async def create(self, command: CreateSeed) -> SeedResult:
        async with self.transaction_factory() as session:
            await self._lock_project_for_mutation(session, command.project_id)
            selection = await self.repository.lock_selection(
                session, command.project_id
            )
            selection_revision = _selection_revision(selection)
            seed_id = self.id_factory()
            revision_id = self.id_factory()
            now = self.clock()
            payload_json = canonical_json(command.payload)
            content_hash = canonical_hash(command.payload)
            identity = {
                "id": seed_id, "project_id": command.project_id,
                "status": "candidate", "created_at": now, "updated_at": now,
            }
            revision = {
                "id": revision_id, "project_id": command.project_id,
                "seed_id": seed_id, "revision": 1,
                "payload_json": payload_json, "content_hash": content_hash,
                "created_at": now,
            }
            head = {
                "seed_id": seed_id, "revision_id": revision_id,
                "revision": 1, "content_hash": content_hash,
                "updated_at": now,
            }
            await self.repository.insert_identity(session, identity)
            await self.repository.insert_revision(session, revision)
            await self.repository.insert_head(session, head)
        return SeedResult(
            id=seed_id, project_id=command.project_id, status="candidate",
            revision=1, revision_id=revision_id, content_hash=content_hash,
            payload=command.payload, is_selected=False,
            selection_revision=selection_revision,
        )

    async def edit(self, command: EditSeed) -> SeedResult:
        async with self.transaction_factory() as session:
            await self._lock_project_for_mutation(session, command.project_id)
            head = await self.repository.lock_seed_head(
                session, command.project_id, command.seed_id
            )
            if head is None:
                raise SeedNotFound()
            if int(head["revision"]) != command.expected_seed_revision:
                raise SeedConflict()
            selection = await self.repository.lock_selection(
                session, command.project_id
            )
            if _selection_revision(selection) != command.expected_selection_revision:
                raise SeedConflict()

            revision_number = int(head["revision"]) + 1
            revision_id = self.id_factory()
            now = self.clock()
            payload_json = canonical_json(command.payload)
            content_hash = canonical_hash(command.payload)
            revision = {
                "id": revision_id, "project_id": command.project_id,
                "seed_id": command.seed_id, "revision": revision_number,
                "payload_json": payload_json, "content_hash": content_hash,
                "created_at": now,
            }
            await self.repository.insert_revision(session, revision)
            await self.repository.update_head(
                session,
                {
                    "seed_id": command.seed_id, "revision_id": revision_id,
                    "revision": revision_number, "content_hash": content_hash,
                    "updated_at": now,
                },
            )
            is_selected = bool(
                selection and selection["seed_id"] == command.seed_id
            )
            selection_revision = _selection_revision(selection)
            if is_selected:
                selection_revision += 1
                await self.repository.advance_selected_revision(
                    session,
                    {
                        "project_id": command.project_id,
                        "seed_revision_id": revision_id,
                        "seed_hash": content_hash,
                        "selection_revision": selection_revision,
                        "updated_at": now,
                    },
                )
        return SeedResult(
            id=command.seed_id, project_id=command.project_id,
            status=head["status"], revision=revision_number,
            revision_id=revision_id, content_hash=content_hash,
            payload=command.payload, is_selected=is_selected,
            selection_revision=selection_revision,
        )

    async def select(self, command: SelectSeed) -> SeedResult:
        async with self.transaction_factory() as session:
            await self._lock_project_for_mutation(session, command.project_id)
            head = await self.repository.lock_seed_head(
                session, command.project_id, command.seed_id
            )
            if head is None:
                raise SeedNotFound()
            if int(head["revision"]) != command.expected_seed_revision:
                raise SeedConflict()
            selection = await self.repository.lock_selection(
                session, command.project_id
            )
            current_revision = _selection_revision(selection)
            if current_revision != command.expected_selection_revision:
                raise SeedConflict()
            now = self.clock()
            new_revision = current_revision + 1
            row = {
                "project_id": command.project_id,
                "seed_id": command.seed_id,
                "seed_revision_id": head["revision_id"],
                "seed_hash": head["content_hash"],
                "selection_revision": new_revision,
                "selected_at": now,
                "updated_at": now,
            }
            if selection is None:
                await self.repository.insert_selection(session, row)
            else:
                await self.repository.replace_selection(session, row)
        return self._result(
            head, is_selected=True, selection_revision=new_revision
        )

    async def delete(self, command: DeleteSeed) -> None:
        async with self.transaction_factory() as session:
            await self._lock_project_for_mutation(session, command.project_id)
            head = await self.repository.lock_seed_head(
                session, command.project_id, command.seed_id
            )
            if head is None:
                raise SeedNotFound()
            if int(head["revision"]) != command.expected_seed_revision:
                raise SeedConflict()
            selection = await self.repository.lock_selection(
                session, command.project_id
            )
            if _selection_revision(selection) != command.expected_selection_revision:
                raise SeedConflict()
            selected = bool(
                selection and selection["seed_id"] == command.seed_id
            )
            dependencies = await self.repository.dependency_count(
                session, command.project_id, command.seed_id
            )
            if selected or dependencies:
                await self.repository.archive(
                    session, command.project_id, command.seed_id, self.clock()
                )
            else:
                await self.repository.physical_delete(
                    session, command.project_id, command.seed_id
                )

    def _connection(self):
        if self.connection_factory is None:
            raise RuntimeError("read connection factory is not configured")
        return self.connection_factory()

    async def list(self, project_id: str) -> tuple[SeedResult, ...]:
        async with self._connection() as session:
            if hasattr(self.repository, "read_project"):
                if await self.repository.read_project(session, project_id) is None:
                    raise SeedNotFound()
            rows = await self.repository.list_heads(session, project_id)
        return tuple(self._result(row) for row in rows)

    async def get_selected(self, project_id: str) -> SelectedSeedResult:
        async with self._connection() as session:
            if await self.repository.read_project(session, project_id) is None:
                raise SeedNotFound()
            selected = await self.repository.read_selection(session, project_id)
            contract = await self.repository.read_contract_facts(
                session, project_id
            )
        if selected is None:
            return SelectedSeedResult(
                selected=None, seed_ready=False, contract_ready=False,
                reasons=("seed_not_selected",),
            )
        result = self._result(selected, is_selected=True)
        has_contract = bool(contract and int(contract.get("revision") or 0) > 0)
        if not has_contract:
            return SelectedSeedResult(
                selected=result, seed_ready=False, contract_ready=False,
                reasons=("creation_contract_missing",),
            )
        matches = (
            contract.get("seed_id") == result.id
            and contract.get("seed_revision_id") == result.revision_id
            and contract.get("seed_hash") == result.content_hash
        )
        if not matches:
            return SelectedSeedResult(
                selected=result, seed_ready=False, contract_ready=False,
                reasons=("selected_seed_drift",),
            )
        return SelectedSeedResult(
            selected=result, seed_ready=True, contract_ready=False,
            reasons=("binding_not_verified",),
        )
