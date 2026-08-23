"""Pure mappings used by the atomic chapter-finalization transaction."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
from typing import Callable
from uuid import uuid4

from backend.domain.canon import (
    AssertionOperator,
    CanonEventInput,
    ConfirmationStatus,
    FactKind,
    ValueCardinality,
    thaw_json,
)
from backend.domain.chapter_outlines import ChapterOutline
from backend.domain.finalization import (
    FinalizationAuthority,
    FinalizationChangeSet,
    PlanningPatch,
    PlanningTargetType,
)
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.planning import (
    DraftPlanningAggregate,
    PlanningAggregate,
    PlanningDomainError,
    normalize_planning_aggregate,
)
from backend.services.canon import (
    AliasCreate,
    CanonEntityCreate,
    CanonEventCreate,
    CommitCanonRevision,
)
from backend.services.finalization import FinalizationService, PrepareFinalization
from backend.services.finalization_checks import (
    run_finalization_prechecks,
    validate_change_set_context,
)


class FinalizationCommitInvalid(ValueError):
    """The confirmed finalization payload is no longer safe to commit."""


def _hash(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("finalization commit hash is invalid")


@dataclass(frozen=True, slots=True)
class CommitFinalization:
    project_id: str
    chapter_session_id: str
    idempotency_key: str
    expected_revision: int
    expected_revision_hash: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.project_id, self.chapter_session_id)
        ):
            raise ValueError("finalization commit identity is invalid")
        _hash(self.idempotency_key)
        _hash(self.expected_revision_hash)
        if type(self.expected_revision) is not int or self.expected_revision < 1:
            raise ValueError("finalization commit revision is invalid")


@dataclass(frozen=True, slots=True)
class CommittedFinalization:
    record_id: str
    final_chapter_id: str
    canon_revision: int
    projection_hash: str
    planning_revision_id: str
    planning_revision: int
    planning_hash: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.record_id, self.final_chapter_id,
                self.planning_revision_id,
            )
        ):
            raise ValueError("finalization result identity is invalid")
        if type(self.canon_revision) is not int or self.canon_revision < 1:
            raise ValueError("finalization Canon revision is invalid")
        if type(self.planning_revision) is not int or self.planning_revision < 1:
            raise ValueError("finalization Planning revision is invalid")
        _hash(self.projection_hash)
        _hash(self.planning_hash)
        if type(self.replayed) is not bool:
            raise ValueError("finalization replay flag is invalid")


def commit_request_fingerprint(command: CommitFinalization) -> str:
    return canonical_hash({
        "schemaVersion": "finalization-commit-request-v1",
        "projectId": command.project_id,
        "chapterSessionId": command.chapter_session_id,
        "expectedRevision": command.expected_revision,
        "expectedRevisionHash": command.expected_revision_hash,
    })


def _evidence(value) -> dict[str, object]:
    return value.model_dump(by_alias=True, mode="json")


def build_canon_commit(
    change_set: FinalizationChangeSet,
    *,
    project_id: str,
    expected_head: int,
    idempotency_key: str,
    source_id: str,
    chapter_number: int,
) -> CommitCanonRevision:
    """Translate one confirmed ChangeSet into the existing Canon command."""

    entities = tuple(
        CanonEntityCreate(
            id=item.id,
            entity_type=item.entity_type,
            canonical_name=item.canonical_name,
        )
        for item in change_set.entities
    )
    aliases = tuple(
        AliasCreate(id=item.id, entity_id=item.entity_id, alias=item.alias)
        for item in change_set.aliases
    )
    events = [
        CanonEventCreate(
            id=item.id,
            event=CanonEventInput(
                entity_id=item.entity_id,
                fact_kind=item.fact_kind,
                field_path=item.field_path,
                value=thaw_json(item.value),
                evidence=_evidence(item.evidence),
                effective_start_chapter=item.effective_start_chapter,
                effective_end_chapter=item.effective_end_chapter,
                confirmation_status=ConfirmationStatus.CONFIRMED,
                assertion_operator=item.assertion_operator,
                value_cardinality=item.value_cardinality,
            ),
        )
        for item in change_set.canon_events
    ]
    events.extend(
        CanonEventCreate(
            id=item.id,
            event=CanonEventInput(
                entity_id=None,
                fact_kind=FactKind.DYNAMIC_EVENT,
                field_path=f"plot.progress.{item.target_type.value}.{item.target_id}",
                value={
                    "chapterNumber": chapter_number,
                    "status": item.status.value,
                    "targetId": item.target_id,
                    "targetType": item.target_type.value,
                },
                evidence=_evidence(item.evidence),
                effective_start_chapter=chapter_number,
                effective_end_chapter=None,
                confirmation_status=ConfirmationStatus.CONFIRMED,
                assertion_operator=AssertionOperator.EQUALS,
                value_cardinality=ValueCardinality.SINGLE,
            ),
        )
        for item in change_set.story_progress_events
    )
    return CommitCanonRevision(
        project_id=project_id,
        expected_head=expected_head,
        idempotency_key=idempotency_key,
        source_type="finalization",
        source_id=source_id,
        entities=entities,
        aliases=aliases,
        events=tuple(events),
    )


def _editable_payload(value: PlanningAggregate) -> dict[str, object]:
    payload = value.model_dump(mode="json", by_alias=True)
    payload["activeStoryBlockRef"] = payload.pop("activeStoryBlockId")
    payload.pop("schemaVersion")
    payload.pop("contentHash")
    for block in payload["storyBlocks"]:
        block["volumeRef"] = block.pop("volumeId")
        block["plotRefs"] = block.pop("plotIds")
        for stage in block["stages"]:
            stage.pop("storyBlockId")
            for task in stage["sceneTasks"]:
                task.pop("stageId")
    return payload


def _nodes_by_type(payload: dict[str, object]):
    nodes: dict[tuple[PlanningTargetType, str], dict[str, object]] = {}
    for item in payload["volumes"]:
        nodes[(PlanningTargetType.VOLUME, item["id"])] = item
    for item in payload["plots"]:
        nodes[(PlanningTargetType.PLOT, item["id"])] = item
    for block in payload["storyBlocks"]:
        nodes[(PlanningTargetType.STORY_BLOCK, block["id"])] = block
        for stage in block["stages"]:
            nodes[(PlanningTargetType.STAGE, stage["id"])] = stage
            for task in stage["sceneTasks"]:
                nodes[(PlanningTargetType.SCENE_TASK, task["id"])] = task
    return nodes


def apply_planning_patches(
    planning: PlanningAggregate,
    patches: Iterable[PlanningPatch],
    *,
    implemented_ids: frozenset[str],
) -> PlanningAggregate:
    """Apply confirmed, whitelisted patches only to unimplemented nodes."""

    patches = tuple(patches)
    if not patches:
        return planning
    payload = _editable_payload(planning)
    nodes = _nodes_by_type(payload)
    for patch in patches:
        if patch.target_id in implemented_ids:
            raise FinalizationCommitInvalid(
                "planning patch targets an implemented node"
            )
        node = nodes.get((patch.target_type, patch.target_id))
        if node is None:
            raise FinalizationCommitInvalid("planning patch target is missing")
        if (
            node["revision"] != patch.expected_revision
            or node["contentHash"] != patch.expected_hash
        ):
            raise FinalizationCommitInvalid("planning patch target is stale")
        node[patch.field_path] = thaw_json(patch.replacement)

    try:
        draft = DraftPlanningAggregate.model_validate(payload, strict=True)
        return normalize_planning_aggregate(
            draft,
            previous_confirmed=planning,
            previous_draft=None,
            id_factory=lambda: _unexpected_id_allocation(),
        )
    except PlanningDomainError as exc:
        raise FinalizationCommitInvalid("planning patch is invalid") from exc


def _unexpected_id_allocation() -> str:
    raise FinalizationCommitInvalid("planning patch cannot create nodes")


def _json_object(value: object, label: str) -> dict[str, object]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        raise FinalizationCommitInvalid(f"{label} is invalid") from None
    if not isinstance(decoded, dict):
        raise FinalizationCommitInvalid(f"{label} is invalid")
    return dict(decoded)


def _implemented_ids(outline_values: Iterable[object]) -> frozenset[str]:
    result: set[str] = set()
    for value in outline_values:
        try:
            outline = ChapterOutline.model_validate(
                _json_object(value, "chapter outline"), strict=True,
            )
        except (TypeError, ValueError):
            raise FinalizationCommitInvalid("chapter outline is invalid") from None
        result.add(outline.volume_ref.id)
        result.add(outline.story_block_ref.id)
        result.update(item.id for item in outline.stage_refs)
        result.update(item.id for item in outline.scene_task_refs)
    return frozenset(result)


class AtomicFinalizationService:
    """Commit one confirmed chapter using a single caller-owned transaction."""

    def __init__(
        self,
        *,
        transaction_factory,
        repository,
        planning_repository,
        canon_committer,
        clock: Callable[[], int],
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.transaction_factory = transaction_factory
        self.repository = repository
        self.planning_repository = planning_repository
        self.canon_committer = canon_committer
        self._clock = clock
        self._id = id_factory or (lambda: str(uuid4()))

    @staticmethod
    def _replayed(record: dict[str, object]) -> CommittedFinalization:
        result = record.get("result")
        if not isinstance(result, dict):
            raise FinalizationCommitInvalid("finalization receipt is invalid")
        try:
            return CommittedFinalization(
                record_id=record["id"],
                final_chapter_id=result["finalChapterId"],
                canon_revision=result["canonRevision"],
                projection_hash=result["projectionHash"],
                planning_revision_id=result["planningRevisionId"],
                planning_revision=result["planningRevision"],
                planning_hash=result["planningHash"],
                replayed=True,
            )
        except (KeyError, TypeError, ValueError):
            raise FinalizationCommitInvalid("finalization receipt is invalid") from None

    @staticmethod
    def _require_attempt(attempt, command: CommitFinalization) -> None:
        if (
            not isinstance(attempt, dict)
            or attempt.get("status") != "awaiting_author"
            or attempt.get("active_slot") != 1
            or attempt.get("current_revision") != command.expected_revision
            or attempt.get("current_revision_hash") != command.expected_revision_hash
            or attempt.get("confirmed_revision") != command.expected_revision
            or attempt.get("confirmed_revision_hash") != command.expected_revision_hash
        ):
            raise FinalizationCommitInvalid("finalization confirmation changed")

    @staticmethod
    def _planning_row(
        head: dict[str, object], updated: PlanningAggregate, revision_id: str,
        now: int, project_id: str,
    ) -> dict[str, object]:
        return {
            "id": revision_id,
            "project_id": project_id,
            "revision": head["revision"] + 1,
            "parent_revision": head["revision"],
            **{key: head[key] for key in (
                "selection_revision", "seed_id", "seed_revision_id", "seed_hash",
                "contract_revision", "creation_contract_id", "creation_hash",
                "style_contract_id", "style_hash", "bible_revision",
                "bible_revision_id", "bible_hash",
            )},
            "content_json": canonical_json(
                updated.model_dump(by_alias=True, mode="json")
            ),
            "content_hash": updated.content_hash,
            "created_at": now,
        }

    async def commit(self, command: CommitFinalization) -> CommittedFinalization:
        if type(command) is not CommitFinalization:
            raise TypeError("command must be CommitFinalization")
        fingerprint = commit_request_fingerprint(command)
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, command.project_id) is None:
                raise FinalizationCommitInvalid("finalization was not found")
            canon_head = await self.canon_committer.repository.lock_head(
                session, command.project_id,
            )
            chapter_session = await self.repository.lock_session(
                session, command.project_id, command.chapter_session_id,
            )
            planning_head = await self.planning_repository.lock_planning_head(
                session, command.project_id,
            )
            attempt = await self.repository.lock_latest_attempt(
                session, command.project_id, command.chapter_session_id,
            )
            candidate_id = attempt.get("draft_candidate_id") if isinstance(attempt, dict) else None
            candidate = None
            if isinstance(candidate_id, str):
                candidate = await self.repository.lock_candidate(
                    session, command.project_id, command.chapter_session_id,
                    candidate_id,
                )
            by_key = await self.repository.lock_commit_by_key(
                session, command.project_id, command.idempotency_key,
            )
            by_session = await self.repository.lock_commit_by_session(
                session, command.project_id, command.chapter_session_id,
            )
            if by_key is not None:
                if (
                    by_key.get("chapter_session_id") != command.chapter_session_id
                    or by_key.get("request_fingerprint") != fingerprint
                ):
                    raise FinalizationCommitInvalid("finalization idempotency conflict")
                return self._replayed(by_key)
            if by_session is not None:
                raise FinalizationCommitInvalid("chapter is already final")
            if chapter_session is None or planning_head is None or candidate is None:
                raise FinalizationCommitInvalid("finalization was not found")
            self._require_attempt(attempt, command)

            chapter_number = chapter_session.get("chapter_num")
            if type(chapter_number) is not int or chapter_number < 1:
                raise FinalizationCommitInvalid("chapter authority is invalid")
            current = await self.repository.lock_current_authority(
                session, command.project_id, chapter_number,
            )
            snapshot = await self.repository.load_preparation_context(
                session, command.project_id, chapter_number,
            )
            if current is None or not isinstance(snapshot, dict):
                raise FinalizationCommitInvalid("finalization authority is invalid")
            try:
                frozen = PrepareFinalization(
                    project_id=command.project_id,
                    chapter_session_id=command.chapter_session_id,
                    candidate_id=attempt["draft_candidate_id"],
                    candidate_hash=attempt["candidate_hash"],
                    expected_canon_revision=attempt["expected_canon_revision"],
                    expected_planning_hash=attempt["expected_planning_hash"],
                    expected_outline_hash=attempt["expected_outline_hash"],
                    idempotency_key=attempt["idempotency_key"],
                )
                manifest_hash = canonical_hash(
                    FinalizationService._context_manifest(
                        frozen, chapter_number, snapshot,
                    )
                )
                authority = FinalizationAuthority.model_validate({
                    "projectId": command.project_id,
                    "chapterSessionId": command.chapter_session_id,
                    "candidateId": attempt["draft_candidate_id"],
                    "candidateHash": attempt["candidate_hash"],
                    "expectedCanonRevision": attempt["expected_canon_revision"],
                    "expectedPlanningHash": attempt["expected_planning_hash"],
                    "expectedOutlineHash": attempt["expected_outline_hash"],
                    "contextManifestHash": attempt["context_manifest_hash"],
                    "idempotencyKey": attempt["idempotency_key"],
                    "requestFingerprint": attempt["request_fingerprint"],
                })
            except (KeyError, TypeError, ValueError):
                raise FinalizationCommitInvalid("finalization authority is invalid") from None
            if manifest_hash != attempt.get("context_manifest_hash"):
                raise FinalizationCommitInvalid("finalization authority changed")
            blocks = run_finalization_prechecks(
                authority,
                session=chapter_session,
                candidate=candidate,
                current_authority=current,
                reference_sources=snapshot.get("reference_sources", ()),
                copy_check_completed=True,
            )
            if blocks:
                raise FinalizationCommitInvalid("finalization precheck failed")

            if await self.canon_committer.repository.find_idempotent(
                session, command.project_id, command.idempotency_key,
            ) is not None:
                raise FinalizationCommitInvalid("finalization idempotency conflict")

            revision = await self.repository.lock_change_set_revision(
                session, command.project_id, attempt["id"],
                command.expected_revision, command.expected_revision_hash,
            )
            if revision is None:
                raise FinalizationCommitInvalid("confirmed finalization revision is missing")
            change_set = revision.get("change_set")
            if type(change_set) is not FinalizationChangeSet:
                raise FinalizationCommitInvalid("confirmed finalization revision is invalid")
            try:
                validate_change_set_context(
                    change_set,
                    candidate_content=candidate["content"],
                    canon_context=snapshot["canon_context"],
                    planning_context=snapshot["planning_context"],
                )
                planning = PlanningAggregate.model_validate(
                    _json_object(planning_head.get("content_json"), "Planning"),
                    strict=True,
                )
            except (KeyError, TypeError, ValueError):
                raise FinalizationCommitInvalid("finalization payload is invalid") from None
            if (
                planning_head.get("revision") != chapter_session.get("planning_revision")
                or planning_head.get("planning_revision_id") != chapter_session.get("planning_revision_id")
                or planning.content_hash != chapter_session.get("planning_hash")
                or canon_head != attempt.get("expected_canon_revision")
            ):
                raise FinalizationCommitInvalid("finalization authority changed")

            previous_outlines = await self.repository.list_finalized_outline_contents(
                session, command.project_id,
            )
            current_outline = snapshot.get("outline_context", {}).get("content")
            implemented = _implemented_ids((*previous_outlines, current_outline))
            updated_planning = apply_planning_patches(
                planning, change_set.planning_patches,
                implemented_ids=implemented,
            )

            now = self._clock()
            if not await self.repository.mark_committing(
                session, project_id=command.project_id,
                session_id=command.chapter_session_id,
                change_set_id=attempt["id"], updated_at=now,
            ):
                raise FinalizationCommitInvalid("finalization state changed")
            canon_request = build_canon_commit(
                change_set,
                project_id=command.project_id,
                expected_head=canon_head,
                idempotency_key=command.idempotency_key,
                source_id=attempt["id"],
                chapter_number=chapter_number,
            )
            try:
                canon_result = await self.canon_committer.commit_locked(
                    session, canon_request,
                )
            except Exception as exc:
                raise FinalizationCommitInvalid("Canon commit failed") from exc

            planning_revision_id = planning_head["planning_revision_id"]
            planning_revision = planning_head["revision"]
            planning_hash = planning.content_hash
            if updated_planning is not planning:
                planning_revision_id = self._id()
                planning_row = self._planning_row(
                    planning_head, updated_planning, planning_revision_id,
                    now, command.project_id,
                )
                if not await self.planning_repository.insert_revision(session, planning_row):
                    raise FinalizationCommitInvalid("Planning revision was not inserted")
                planning_revision = planning_row["revision"]
                planning_hash = planning_row["content_hash"]
                if not await self.planning_repository.advance_head_cas(
                    session,
                    {
                        "project_id": command.project_id,
                        "revision": planning_revision,
                        "planning_revision_id": planning_revision_id,
                        "content_hash": planning_hash,
                        "updated_at": now,
                    },
                    planning_head,
                ):
                    raise FinalizationCommitInvalid("Planning head changed")

            record_id = self._id()
            final_chapter_id = self._id()
            result_payload = {
                "finalChapterId": final_chapter_id,
                "canonRevision": canon_result.revision_number,
                "projectionHash": canon_result.projection_hash,
                "planningRevisionId": planning_revision_id,
                "planningRevision": planning_revision,
                "planningHash": planning_hash,
            }
            await self.repository.insert_finalization_record(session, {
                "id": record_id, "project_id": command.project_id,
                "chapter_session_id": command.chapter_session_id,
                "draft_candidate_id": candidate["id"],
                "change_set_id": attempt["id"],
                "change_set_revision": command.expected_revision,
                "idempotency_key": command.idempotency_key,
                "request_fingerprint": fingerprint,
                "candidate_hash": candidate["content_hash"],
                "change_set_hash": command.expected_revision_hash,
                "expected_canon_revision": canon_head,
                "committed_canon_revision": canon_result.revision_number,
                "result": result_payload, "finalized_at": now,
            })
            await self.repository.insert_final_chapter(session, {
                "id": final_chapter_id, "project_id": command.project_id,
                "chapter_session_id": command.chapter_session_id,
                "draft_candidate_id": candidate["id"],
                "finalization_record_id": record_id,
                "chapter_num": chapter_number, "title": change_set.title,
                "content": candidate["content"],
                "content_hash": candidate["content_hash"],
                "canon_revision": canon_result.revision_number,
                "planning_revision_id": chapter_session["planning_revision_id"],
                "planning_revision": chapter_session["planning_revision"],
                "planning_hash": chapter_session["planning_hash"],
                "chapter_outline_revision_id": chapter_session["chapter_outline_revision_id"],
                "chapter_outline_revision": chapter_session["chapter_outline_revision"],
                "chapter_outline_hash": chapter_session["chapter_outline_hash"],
                "finalized_at": now,
            })
            if not await self.repository.finalize_session(
                session, project_id=command.project_id,
                session_id=command.chapter_session_id, finalized_at=now,
            ):
                raise FinalizationCommitInvalid("chapter session changed")
            if not await self.repository.advance_project_chapter(
                session,
                project_id=command.project_id,
                chapter_number=chapter_number,
                updated_at=now,
            ):
                raise FinalizationCommitInvalid("project progress changed")
            if not await self.repository.mark_committed(
                session, project_id=command.project_id,
                session_id=command.chapter_session_id,
                change_set_id=attempt["id"], updated_at=now,
            ):
                raise FinalizationCommitInvalid("finalization state changed")
            return CommittedFinalization(
                record_id=record_id,
                final_chapter_id=final_chapter_id,
                canon_revision=canon_result.revision_number,
                projection_hash=canon_result.projection_hash,
                planning_revision_id=planning_revision_id,
                planning_revision=planning_revision,
                planning_hash=planning_hash,
            )


__all__ = [
    "AtomicFinalizationService",
    "CommitFinalization",
    "CommittedFinalization",
    "FinalizationCommitInvalid",
    "apply_planning_patches",
    "build_canon_commit",
    "commit_request_fingerprint",
]
