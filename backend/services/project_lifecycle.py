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
from backend.repositories.chapter_sessions import ActiveChapterSessionConflict
from backend.services.bibles import BIBLE_POLICY_VERSION
from backend.services.projections import build_projection_bundle


class CreateProject(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    genre: str = ""
    description: str = ""
    target_words: int = 2_400_000
    target_chapters: int = 720


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


class ProjectPreparationOperation(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
    )

    operation_id: str = Field(min_length=1, serialization_alias="operationId")
    status: Literal["pending"]


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
    planning: Literal["missing", "draft", "current", "superseded"]
    planning_operation: ProjectPreparationOperation | None = Field(
        serialization_alias="planningOperation"
    )
    outline: Literal["missing", "draft", "current", "superseded"]
    outline_operation: ProjectPreparationOperation | None = Field(
        serialization_alias="outlineOperation"
    )
    authoritative_chapter_number: int = Field(
        ge=1,
        serialization_alias="authoritativeChapterNumber",
    )
    model_tasks: tuple[ProjectPreparationModelTask, ...] = Field(
        serialization_alias="modelTasks"
    )
    capabilities: ProjectPreparationCapabilities
    next_action: Literal[
        "select_seed",
        "continue_contract",
        "continue_bible",
        "recover_planning_operation",
        "continue_writing",
        "establish_planning",
        "continue_planning",
        "recover_chapter_outline_operation",
        "prepare_chapter_outline",
        "continue_chapter_outline",
        "start_chapter_session",
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
        async with self.transaction_factory() as session:
            return await self.create_in_session(session, command)

    async def create_in_session(
        self,
        session,
        command: CreateProject,
    ) -> ProjectResult:
        """Create the standard project foundation in a caller-owned transaction."""

        if self.model_binding_service is None:
            raise RuntimeError("model binding service is not configured")
        empty_hash = build_projection_bundle(0, ()).content_hash
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
        await self.model_binding_service.initialize_project(session, command.id)
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
        if cls._confirmed_contract_basis(snapshot, contract_result) is not None:
            return "current"
        if head_revision > 0 or _value(contract_result, "has_contract") is True:
            return "superseded"
        if cls._contract_draft_is_current(snapshot, head_revision):
            return "draft"
        return "missing"

    @staticmethod
    def _confirmed_contract_basis(snapshot, contract_result):
        selection = snapshot.get("selection")
        reasons = _value(contract_result, "reasons", ()) or ()
        if selection is None or "contract_head_drift" in reasons:
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
            or basis["selection_revision"]
            != int(selection.get("selection_revision") or 0)
            or basis["seed_id"] != selection.get("seed_id")
            or basis["seed_revision_id"] != selection.get("seed_revision_id")
            or basis["seed_hash"] != selection.get("seed_hash")
            or not all(
                isinstance(value, str) and bool(value)
                for key, value in basis.items()
                if key
                not in {"selection_revision", "contract_revision"}
            )
        ):
            return None
        return basis

    @classmethod
    def _contract_basis(cls, snapshot, contract_result):
        return cls._confirmed_contract_basis(snapshot, contract_result)

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
        basis = cls._contract_basis(snapshot, contract_result)
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
        if head_is_current:
            return "current"
        if head_revision > 0:
            return "superseded"
        if draft_is_current:
            return "draft"
        if draft is not None:
            return "superseded"
        return "missing"

    @classmethod
    def _planning_basis(cls, snapshot, contract_result):
        contract_basis = cls._contract_basis(snapshot, contract_result)
        bible_head = snapshot.get("bible_head")
        if contract_basis is None or bible_head is None:
            return None
        head_revision = int(bible_head.get("head_revision") or 0)
        if (
            head_revision <= 0
            or int(bible_head.get("revision") or 0) != head_revision
            or bible_head.get("head_bible_revision_id")
            != bible_head.get("revision_id")
            or bible_head.get("head_content_hash")
            != bible_head.get("content_hash")
            or not cls._matches_bible_basis(bible_head, contract_basis)
        ):
            return None
        return {
            key: value
            for key, value in contract_basis.items()
            if key != "policy_version"
        } | {
            "bible_revision": head_revision,
            "bible_revision_id": bible_head["revision_id"],
            "bible_hash": bible_head["content_hash"],
        }

    @classmethod
    def _planning_status(cls, snapshot, contract_result) -> str:
        basis = cls._planning_basis(snapshot, contract_result)
        head = snapshot.get("planning_head")
        draft = snapshot.get("planning_draft")
        head_revision = int((head or {}).get("head_revision") or 0)
        draft_is_current = (
            draft is not None
            and bool(draft.get("draft_id"))
            and draft.get("status") == "active"
            and int(draft.get("base_head_revision") or 0) == head_revision
            and cls._matches_bible_basis(draft, basis)
        )
        head_is_current = (
            head_revision > 0
            and int((head or {}).get("revision") or 0) == head_revision
            and (head or {}).get("planning_revision_id")
            == (head or {}).get("revision_id")
            and (head or {}).get("head_content_hash")
            == (head or {}).get("content_hash")
            and cls._matches_bible_basis(head, basis)
        )
        if draft_is_current:
            return "draft"
        if head_is_current:
            return "current"
        if head_revision > 0 or draft is not None:
            return "superseded"
        return "missing"

    @staticmethod
    def _planning_operation(snapshot) -> ProjectPreparationOperation | None:
        row = snapshot.get("planning_operation")
        if (
            row is None
            or row.get("status") != "pending"
            or not isinstance(row.get("operation_id"), str)
            or not row["operation_id"]
        ):
            return None
        return ProjectPreparationOperation(
            operation_id=row["operation_id"],
            status="pending",
        )

    @staticmethod
    def _outline_operation(snapshot) -> ProjectPreparationOperation | None:
        row = snapshot.get("outline_operation")
        if (
            row is None
            or row.get("status") != "pending"
            or not isinstance(row.get("operation_id"), str)
            or not row["operation_id"]
        ):
            return None
        return ProjectPreparationOperation(
            operation_id=row["operation_id"],
            status="pending",
        )

    @staticmethod
    def _active_chapter_number(snapshot) -> int | None:
        row = snapshot.get("active_session")
        if (
            row is None
            or not isinstance(row.get("id"), str)
            or not row["id"]
        ):
            return None
        try:
            chapter_number = int(row.get("chapter_num"))
        except (TypeError, ValueError):
            return None
        return chapter_number if chapter_number > 0 else None

    @staticmethod
    def _outline_row_id(row, *, head: bool) -> object:
        if row is None:
            return None
        if head:
            return row.get(
                "revision_id",
                row.get("id", row.get("outline_revision_id")),
            )
        return row.get("draft_id", row.get("id"))

    @staticmethod
    def _projection_hash(row) -> object:
        if row is None:
            return None
        return row.get("projection_hash", row.get("content_hash"))

    @classmethod
    def _outline_basis_is_current(cls, row, snapshot) -> bool:
        planning = snapshot.get("planning_head") or {}
        projection = snapshot.get("canon_projection") or {}
        return (
            row.get("planning_revision_id")
            == planning.get("planning_revision_id")
            and int(row.get("planning_revision") or 0)
            == int(planning.get("head_revision") or 0)
            and row.get("planning_hash")
            == planning.get("head_content_hash")
            and int(row.get("canon_revision") or 0)
            == int(projection.get("canon_revision") or 0)
            and int(row.get("projection_revision") or 0)
            == int(projection.get("projection_revision") or 0)
            and row.get("projection_hash")
            == cls._projection_hash(projection)
            and int(projection.get("canon_revision") or 0)
            == int(projection.get("projection_revision") or 0)
            and bool(cls._projection_hash(projection))
        )

    @classmethod
    def _outline_status(cls, snapshot, planning: str) -> str:
        head = snapshot.get("outline_head")
        draft = snapshot.get("outline_draft")
        chapter_number = int(
            snapshot.get("authoritative_chapter_number") or 1
        )
        head_revision = int(
            (head or {}).get("head_revision", (head or {}).get("revision"))
            or 0
        )
        draft_is_current = (
            planning == "current"
            and draft is not None
            and bool(cls._outline_row_id(draft, head=False))
            and draft.get("status") == "active"
            and int(draft.get("chapter_num") or 0) == chapter_number
            and int(draft.get("base_head_revision") or 0) == head_revision
            and cls._outline_basis_is_current(draft, snapshot)
        )
        head_id = (head or {}).get(
            "head_outline_revision_id",
            (head or {}).get("outline_revision_id"),
        )
        head_hash = (head or {}).get(
            "head_content_hash",
            (head or {}).get("content_hash"),
        )
        head_is_current = (
            planning == "current"
            and head is not None
            and head_revision > 0
            and int(head.get("revision") or 0) == head_revision
            and head_id == cls._outline_row_id(head, head=True)
            and head_hash == head.get("content_hash")
            and int(head.get("chapter_num") or 0) == chapter_number
            and cls._outline_basis_is_current(head, snapshot)
        )
        if draft_is_current:
            return "draft"
        if head_is_current:
            return "current"
        if head is not None or draft is not None:
            return "superseded"
        return "missing"

    @staticmethod
    def _project_path(project_id: str, module: str) -> str:
        return f"/projects/{quote(str(project_id), safe='')}/{module}"

    async def preparation(self, project_id: str) -> ProjectPreparationResult:
        if self.contract_service is None:
            raise RuntimeError("contract service is not configured")
        try:
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
        except ActiveChapterSessionConflict:
            raise ProjectLifecycleConflict() from None

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
        contract_head_revision = int(
            _value(contract_result, "revision", 0) or 0
        )
        bible_head = snapshot.get("bible_head") or {}
        bible_head_revision = int(
            bible_head.get("head_revision", bible_head.get("revision", 0)) or 0
        )
        planning = self._planning_status(snapshot, contract_result)
        planning_operation = self._planning_operation(snapshot)
        outline = self._outline_status(snapshot, planning)
        outline_operation = self._outline_operation(snapshot)
        authoritative_chapter_number = int(
            snapshot.get("authoritative_chapter_number") or 1
        )
        active_chapter_number = self._active_chapter_number(snapshot)
        model_tasks = self._model_tasks(snapshot.get("model_tasks"))
        planning_ready = next(
            item.readiness == "ready"
            for item in model_tasks
            if item.task_key == "planning"
        )

        edit_contract = (
            lifecycle == "active"
            and active_selection == "current"
            and contract in {"missing", "draft"}
            and contract_head_revision == 0
        )
        edit_bible = (
            lifecycle == "active"
            and contract == "current"
            and bible in {"missing", "draft"}
            and bible_head_revision == 0
        )
        generate_bible = edit_bible and planning_ready
        reasons = []
        if lifecycle == "archived":
            next_action = "archived_read_only"
            target_path = (
                self._project_path(project_id, "planning/volumes")
                if planning != "missing"
                else None
            )
            reasons.append("project_archived")
        elif active_chapter_number is not None:
            next_action = "continue_writing"
            target_path = self._project_path(
                project_id,
                f"write/chapters/{active_chapter_number}",
            )
            reasons.append("chapter_session_active")
        elif planning_operation is not None:
            next_action = "recover_planning_operation"
            target_path = self._project_path(project_id, "planning/volumes")
            reasons.append("planning_operation_pending")
        elif outline_operation is not None:
            next_action = "recover_chapter_outline_operation"
            target_path = self._project_path(
                project_id, "planning/story-blocks"
            )
            reasons.append("outline_operation_pending")
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
        elif planning == "draft":
            next_action = "continue_planning"
            target_path = self._project_path(project_id, "planning/volumes")
            reasons.append("planning_draft")
        elif planning != "current":
            next_action = "establish_planning"
            target_path = self._project_path(project_id, "planning/volumes")
            reasons.append(f"planning_{planning}")
        elif outline == "draft":
            next_action = "continue_chapter_outline"
            target_path = self._project_path(
                project_id, "planning/story-blocks"
            )
            reasons.append("chapter_outline_draft")
        elif outline != "current":
            next_action = "prepare_chapter_outline"
            target_path = self._project_path(
                project_id, "planning/story-blocks"
            )
            reasons.append(f"chapter_outline_{outline}")
        else:
            next_action = "start_chapter_session"
            target_path = self._project_path(
                project_id,
                f"write/chapters/{authoritative_chapter_number}",
            )
            reasons.append("chapter_outline_current")
        if lifecycle == "active" and not planning_ready:
            reasons.append("planning_model_not_ready")

        return ProjectPreparationResult(
            lifecycle=lifecycle,
            active_selection=active_selection,
            contract=contract,
            bible=bible,
            planning=planning,
            planning_operation=planning_operation,
            outline=outline,
            outline_operation=outline_operation,
            authoritative_chapter_number=authoritative_chapter_number,
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
