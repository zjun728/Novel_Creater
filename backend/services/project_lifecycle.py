"""Transactional project lifecycle use cases."""

from __future__ import annotations

from hashlib import sha256
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.model_bindings import TASK_KEYS, TaskKey
from backend.http_errors import (
    ProjectArchived,
    ProjectBusy,
    ProjectLifecycleConflict,
    ProjectNotFound,
)
from backend.services.bibles import BIBLE_POLICY_VERSION
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


class ProjectPreparationModelTask(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
    )

    task_key: TaskKey = Field(serialization_alias="taskKey")
    readiness: Literal["ready", "not_ready"]
    reasons: tuple[str, ...]


class ProjectPreparationCapabilities(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
    )

    view_preparation: bool = Field(serialization_alias="viewPreparation")
    edit_contract: bool = Field(serialization_alias="editContract")
    edit_bible: bool = Field(serialization_alias="editBible")
    generate_bible: bool = Field(serialization_alias="generateBible")


class ProjectPreparationResult(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
    )

    lifecycle: Literal["active", "archived"]
    active_selection: Literal["missing", "current"] = Field(
        serialization_alias="activeSelection"
    )
    contract: Literal["missing", "draft", "current", "superseded"]
    bible: Literal["missing", "draft", "current", "superseded"]
    model_tasks: tuple[ProjectPreparationModelTask, ...] = Field(
        serialization_alias="modelTasks"
    )
    capabilities: ProjectPreparationCapabilities
    next_action: Literal[
        "select_seed",
        "continue_contract",
        "continue_bible",
        "phase_boundary_planning",
        "archived_read_only",
    ] = Field(serialization_alias="nextAction")
    target_path: str | None = Field(serialization_alias="targetPath")
    reasons: tuple[str, ...]


def _value(source, name, default=None):
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


class ProjectLifecycleService:
    def __init__(
        self,
        repository,
        transaction_factory,
        connection_factory=None,
        *,
        model_binding_service=None,
        contract_service=None,
    ):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.model_binding_service = model_binding_service
        self.contract_service = contract_service

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
            await self.repository.insert_bible_head0(session, command.id)
            await self.repository.insert_planning_head0(session, command.id)
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

    @staticmethod
    def _model_tasks(rows) -> tuple[ProjectPreparationModelTask, ...]:
        rows = tuple(rows or ())
        keys = tuple(row.get("task_key") for row in rows)
        if keys != TASK_KEYS:
            return tuple(
                ProjectPreparationModelTask(
                    task_key=task_key,
                    readiness="not_ready",
                    reasons=("binding_incomplete",),
                )
                for task_key in TASK_KEYS
            )

        results = []
        for task_key, row in zip(TASK_KEYS, rows):
            reasons = []
            if row.get("resolution_status") != "bound":
                reasons.append("task_unbound")
            elif int(row.get("provider_ready") or 0) != 1:
                reasons.append("provider_unavailable")
            elif int(row.get("model_snapshot_matches") or 0) != 1:
                reasons.append("model_snapshot_mismatch")
            results.append(
                ProjectPreparationModelTask(
                    task_key=task_key,
                    readiness="not_ready" if reasons else "ready",
                    reasons=tuple(reasons),
                )
            )
        return tuple(results)

    @staticmethod
    def _contract_draft_is_current(snapshot, head_revision: int) -> bool:
        draft = snapshot.get("contract_draft")
        selection = snapshot.get("selection")
        if draft is None or selection is None:
            return False
        return (
            int(draft.get("selection_revision") or 0)
            == int(selection.get("selection_revision") or 0)
            and draft.get("seed_id") == selection.get("seed_id")
            and draft.get("seed_revision_id")
            == selection.get("seed_revision_id")
            and draft.get("seed_hash") == selection.get("seed_hash")
            and int(draft.get("base_head_revision") or 0) == head_revision
        )

    @classmethod
    def _contract_status(cls, snapshot, contract_result) -> str:
        head_revision = int(_value(contract_result, "revision") or 0)
        if cls._contract_draft_is_current(snapshot, head_revision):
            return "draft"
        if _value(contract_result, "contract_ready") is True:
            return "current"
        if head_revision > 0 or _value(contract_result, "has_contract") is True:
            return "superseded"
        return "missing"

    @staticmethod
    def _contract_basis(contract_result):
        if _value(contract_result, "contract_ready") is not True:
            return None
        seed = _value(contract_result, "seed_ref")
        try:
            basis = {
                "selection_revision": int(
                    _value(contract_result, "selection_revision")
                ),
                "seed_id": _value(seed, "id"),
                "seed_revision_id": _value(seed, "revision_id"),
                "seed_hash": _value(seed, "content_hash"),
                "contract_revision": int(_value(contract_result, "revision")),
                "creation_contract_id": _value(
                    contract_result, "creation_contract_id"
                ),
                "creation_hash": _value(contract_result, "creation_hash"),
                "style_contract_id": _value(
                    contract_result, "style_contract_id"
                ),
                "style_hash": _value(contract_result, "style_hash"),
                "policy_version": BIBLE_POLICY_VERSION,
            }
        except (TypeError, ValueError):
            return None
        if (
            basis["selection_revision"] <= 0
            or basis["contract_revision"] <= 0
            or not all(
                isinstance(value, str) and bool(value)
                for key, value in basis.items()
                if key
                not in {"selection_revision", "contract_revision"}
            )
        ):
            return None
        return basis

    @staticmethod
    def _matches_bible_basis(row, basis) -> bool:
        if row is None or basis is None:
            return False
        return all(
            (
                int(row.get(key) or 0) == expected
                if isinstance(expected, int)
                else row.get(key) == expected
            )
            for key, expected in basis.items()
        )

    @classmethod
    def _bible_status(cls, snapshot, contract_result) -> str:
        basis = cls._contract_basis(contract_result)
        head = snapshot.get("bible_head")
        draft = snapshot.get("bible_draft")
        head_revision = int((head or {}).get("head_revision") or 0)
        head_is_current = (
            head_revision > 0
            and int((head or {}).get("revision") or 0) == head_revision
            and (head or {}).get("head_bible_revision_id")
            == (head or {}).get("revision_id")
            and (head or {}).get("head_content_hash")
            == (head or {}).get("content_hash")
            and cls._matches_bible_basis(head, basis)
        )
        draft_is_current = (
            draft is not None
            and bool(draft.get("draft_id"))
            and int(draft.get("base_head_revision") or 0) == head_revision
            and cls._matches_bible_basis(draft, basis)
        )
        if draft_is_current:
            return "draft"
        if head_is_current:
            return "current"
        if head_revision > 0 or draft is not None:
            return "superseded"
        return "missing"

    @staticmethod
    def _project_path(project_id: str, module: str) -> str:
        return f"/projects/{quote(str(project_id), safe='')}/{module}"

    async def preparation(self, project_id: str) -> ProjectPreparationResult:
        if self.contract_service is None:
            raise RuntimeError("contract service is not configured")
        async with self.transaction_factory() as session:
            snapshot = await self.repository.read_preparation_snapshot(
                session, project_id
            )
            if snapshot is None:
                raise ProjectNotFound()
            contract_result = await self.contract_service.get_head(
                project_id,
                session=session,
                for_update=False,
            )

        lifecycle = (
            "archived"
            if snapshot["project"].get("archived_at") is not None
            else "active"
        )
        active_selection = (
            "current" if snapshot.get("selection") is not None else "missing"
        )
        contract = self._contract_status(snapshot, contract_result)
        bible = self._bible_status(snapshot, contract_result)
        model_tasks = self._model_tasks(snapshot.get("model_tasks"))
        planning_ready = next(
            item.readiness == "ready"
            for item in model_tasks
            if item.task_key == "planning"
        )

        edit_contract = lifecycle == "active" and active_selection == "current"
        edit_bible = lifecycle == "active" and contract == "current"
        generate_bible = edit_bible and planning_ready
        reasons = []
        if lifecycle == "archived":
            next_action = "archived_read_only"
            target_path = None
            reasons.append("project_archived")
        elif active_selection == "missing":
            next_action = "select_seed"
            target_path = self._project_path(project_id, "seeds")
            reasons.append("selection_missing")
        elif contract != "current":
            next_action = "continue_contract"
            target_path = self._project_path(project_id, "contract")
            reasons.append(f"contract_{contract}")
        elif bible != "current":
            next_action = "continue_bible"
            target_path = self._project_path(project_id, "bible")
            reasons.append(f"bible_{bible}")
        else:
            next_action = "phase_boundary_planning"
            target_path = None
            reasons.append("phase_boundary_planning")
        if lifecycle == "active" and not planning_ready:
            reasons.append("planning_model_not_ready")

        return ProjectPreparationResult(
            lifecycle=lifecycle,
            active_selection=active_selection,
            contract=contract,
            bible=bible,
            model_tasks=model_tasks,
            capabilities=ProjectPreparationCapabilities(
                view_preparation=True,
                edit_contract=edit_contract,
                edit_bible=edit_bible,
                generate_bible=generate_bible,
            ),
            next_action=next_action,
            target_path=target_path,
            reasons=tuple(reasons),
        )

    async def rename(self, project_id: str, title: str) -> ProjectResult:
        async with self.transaction_factory() as session:
            row = await self.repository.lock_active_project(session, project_id)
            if row is None:
                row = await self.repository.lock_any(session, project_id)
                if row is None:
                    raise ProjectNotFound()
                raise ProjectArchived()
            if row["title"] == title:
                return ProjectResult.from_row(row)
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
