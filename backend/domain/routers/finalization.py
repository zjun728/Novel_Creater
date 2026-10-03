from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.database import read_only_transaction, transaction
from backend.domain.finalization import FinalizationChangeSet
from backend.gateways.finalization_provider import (
    FinalizationExtractionGateway,
    FinalizationQualityGateway,
)
from backend.http_errors import PublicDomainError
from backend.repositories.finalization import (
    FinalizationDataCorruption,
    FinalizationRepository,
)
from backend.repositories.canon import CanonRepository
from backend.repositories.continuity import ContinuityRepository
from backend.repositories.planning import PlanningRepository
from backend.services.canon import CanonService
from backend.services.finalization import (
    CancelFinalization,
    ConfirmFinalization,
    CorrectFinalization,
    DecideFinding,
    DisputeFinding,
    FinalizationConflict,
    FinalizationPreflightConflict,
    FinalizationService,
    PrepareFinalization,
    RevokeFinalization,
)
from backend.services.finalization_commit import (
    AtomicFinalizationService,
    CommitFinalization,
    FinalizationCommitInvalid,
)
from backend.services.finalization_history import FinalizationHistoryReader, ReadFinalizationHistory


router = APIRouter(tags=["finalization"])
finalization_quality_gateway = FinalizationQualityGateway()
finalization_extraction_gateway = FinalizationExtractionGateway()
_service = FinalizationService(
    transaction_factory=transaction,
    repository=FinalizationRepository(),
    quality_provider=finalization_quality_gateway,
    extraction_provider=finalization_extraction_gateway,
    clock=lambda: int(time.time() * 1000),
)
_canon_repository = CanonRepository()
_atomic_service = AtomicFinalizationService(
    transaction_factory=transaction,
    repository=FinalizationRepository(),
    planning_repository=PlanningRepository(),
    canon_committer=CanonService(_canon_repository),
    clock=lambda: int(time.time() * 1000),
)


def get_finalization_service() -> FinalizationService:
    return _service


def get_finalization_history_reader() -> FinalizationHistoryReader:
    return FinalizationHistoryReader(FinalizationRepository(), ContinuityRepository(), read_only_transaction)


def get_atomic_finalization_service() -> AtomicFinalizationService:
    return _atomic_service


class FinalizationRequestInvalid(PublicDomainError):
    status_code = 422
    code = "FinalizationRequestInvalid"
    message = "Finalization request is invalid"


class FinalizationNotFound(PublicDomainError):
    status_code = 404
    code = "FinalizationNotFound"
    message = "Finalization or chapter session was not found"


class FinalizationStateConflict(PublicDomainError):
    status_code = 409
    code = "FinalizationConflict"
    message = "Finalization state changed; refresh and retry"


class FinalizationPlanningConflict(PublicDomainError):
    status_code = 409
    code = "FinalizationPreflightConflict"
    message = "Planning review is no longer applicable; cancel an unconfirmed review and prepare again"


class _StrictBody(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
    )


class PrepareFinalizationBody(_StrictBody):
    candidateHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedCanonRevision: int = Field(ge=0)
    expectedPlanningHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedOutlineHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotencyKey: str = Field(pattern=r"^[0-9a-f]{64}$")


class CorrectFinalizationBody(_StrictBody):
    expectedRevision: int = Field(ge=1)
    expectedRevisionHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    changeSet: FinalizationChangeSet


class ConfirmFinalizationBody(_StrictBody):
    expectedRevision: int = Field(ge=1)
    expectedRevisionHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedDecisionsRevisionPin: int | None = Field(default=None, ge=0)


class CommitFinalizationBody(ConfirmFinalizationBody):
    idempotencyKey: str = Field(pattern=r"^[0-9a-f]{64}$")


class FindingDecisionBody(ConfirmFinalizationBody):
    attemptId: str = Field(min_length=1, max_length=36)
    qualityReportHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedDecisionsRevision: int = Field(ge=0)
    findingId: str = Field(min_length=1, max_length=100)
    ignored: bool


@router.post('/projects/{project_id}/chapter-sessions/{session_id}/finalization/finding-decisions')
async def decide_finding(project_id: str, session_id: str, body: FindingDecisionBody,
                         service: FinalizationService = Depends(get_finalization_service)):
    try:
        return await service.decide_finding(DecideFinding(
            project_id=project_id, chapter_session_id=session_id,
            expected_revision=body.expectedRevision, expected_revision_hash=body.expectedRevisionHash,
            attempt_id=body.attemptId, report_hash=body.qualityReportHash,
            expected_decisions_revision=body.expectedDecisionsRevision,
            finding_id=body.findingId, ignored=body.ignored,
        ))
    except (FinalizationConflict, FinalizationDataCorruption, TypeError, ValueError) as error:
        _raise_public(error)


class DisputeEvidenceBody(_StrictBody):
    id: str = Field(pattern=r'^[0-9a-f]{64}$')
    quote: str = Field(min_length=1, max_length=10000)


class DisputeBody(ConfirmFinalizationBody):
    attemptId: str = Field(min_length=1, max_length=36)
    qualityReportHash: str = Field(pattern=r'^[0-9a-f]{64}$')
    expectedDecisionsRevision: int = Field(ge=0)
    findingId: str = Field(min_length=1, max_length=100)
    action: str = Field(pattern=r'^(note|retain|revoke)$')
    category: str = Field(pattern=r'^(attribution|state_change|custody|style|other)$')
    reason: str = Field(min_length=1, max_length=2000)
    evidence: list[DisputeEvidenceBody] = Field(max_length=8)
    eventId: str = Field(pattern=r'^[0-9a-f]{64}$')


@router.post('/projects/{project_id}/chapter-sessions/{session_id}/finalization/dispute-evidence')
async def dispute_evidence(project_id: str, session_id: str, body: ConfirmFinalizationBody,
                           service: FinalizationService = Depends(get_finalization_service)):
    try:
        return await service.dispute_evidence(ConfirmFinalization(project_id, session_id, body.expectedRevision, body.expectedRevisionHash))
    except (FinalizationConflict, FinalizationDataCorruption, TypeError, ValueError) as error:
        _raise_public(error)


@router.post('/projects/{project_id}/chapter-sessions/{session_id}/finalization/disputes')
async def dispute_finding(project_id: str, session_id: str, body: DisputeBody,
                          service: FinalizationService = Depends(get_finalization_service)):
    try:
        return await service.dispute_finding(DisputeFinding(
            project_id, session_id, body.expectedRevision, body.expectedRevisionHash,
            body.attemptId, body.qualityReportHash, body.expectedDecisionsRevision,
            body.findingId, body.action, body.category, body.reason,
            tuple(item.model_dump() for item in body.evidence), body.eventId))
    except (FinalizationConflict, FinalizationDataCorruption, TypeError, ValueError) as error:
        _raise_public(error)


def _raise_public(error: Exception) -> None:
    if isinstance(error, FinalizationPreflightConflict):
        raise FinalizationPlanningConflict() from None
    if isinstance(error, FinalizationConflict) and str(error).startswith(
        "FINALIZATION_NOT_FOUND"
    ):
        raise FinalizationNotFound() from None
    if isinstance(error, (
        FinalizationConflict, FinalizationDataCorruption,
        FinalizationCommitInvalid,
    )):
        raise FinalizationStateConflict() from None
    raise FinalizationRequestInvalid() from None


def _prepared(value) -> dict[str, object]:
    return {
        "attemptId": value.attempt_id,
        "status": value.status,
        "qualityStatus": value.quality_status,
        "currentRevision": value.current_revision,
        "currentRevisionHash": value.current_revision_hash,
        "hardBlocks": [
            item.model_dump(by_alias=True, mode="json")
            for item in value.hard_blocks
        ],
        "replayed": value.replayed,
    }


def _reviewed(value) -> dict[str, object]:
    return {
        "attemptId": value.attempt_id,
        "status": value.status,
        "currentRevision": value.current_revision,
        "currentRevisionHash": value.current_revision_hash,
        "confirmedRevision": value.confirmed_revision,
        "confirmedRevisionHash": value.confirmed_revision_hash,
    }


@router.post(
    "/projects/{project_id}/chapter-sessions/{session_id}/candidates/"
    "{candidate_id}/finalization/prepare",
    status_code=201,
)
async def prepare_finalization(
    project_id: str,
    session_id: str,
    candidate_id: str,
    body: PrepareFinalizationBody,
    service: FinalizationService = Depends(get_finalization_service),
):
    try:
        value = await service.prepare(PrepareFinalization(
            project_id=project_id,
            chapter_session_id=session_id,
            candidate_id=candidate_id,
            candidate_hash=body.candidateHash,
            expected_canon_revision=body.expectedCanonRevision,
            expected_planning_hash=body.expectedPlanningHash,
            expected_outline_hash=body.expectedOutlineHash,
            idempotency_key=body.idempotencyKey,
        ))
    except (FinalizationConflict, FinalizationDataCorruption, TypeError, ValueError) as error:
        _raise_public(error)
    return _prepared(value)


@router.get("/projects/{project_id}/chapter-sessions/{session_id}/finalization")
async def get_finalization(
    project_id: str,
    session_id: str,
    service: FinalizationService = Depends(get_finalization_service),
):
    try:
        return await service.get_review(project_id, session_id)
    except (FinalizationConflict, FinalizationDataCorruption, TypeError, ValueError) as error:
        _raise_public(error)


@router.get("/projects/{project_id}/chapter-sessions/{session_id}/finalization/history-reference")
async def get_finalization_history(
    project_id: str,
    session_id: str,
    attempt_id: str = Query(alias="attemptId", min_length=1, max_length=100),
    candidate_id: str = Query(alias="candidateId", min_length=1, max_length=100),
    candidate_hash: str = Query(alias="candidateHash", pattern=r"^[0-9a-f]{64}$"),
    canon_revision: int = Query(alias="canonRevision", ge=0),
    expected_revision: int = Query(alias="expectedRevision", ge=1),
    expected_revision_hash: str = Query(alias="expectedRevisionHash", pattern=r"^[0-9a-f]{64}$"),
    reader: FinalizationHistoryReader = Depends(get_finalization_history_reader),
):
    try:
        return await reader.read(ReadFinalizationHistory(
            project_id, session_id, attempt_id, candidate_id, candidate_hash,
            canon_revision, expected_revision, expected_revision_hash,
        ))
    except (FinalizationConflict, FinalizationDataCorruption, TypeError, ValueError) as error:
        _raise_public(error)


@router.post(
    "/projects/{project_id}/chapter-sessions/{session_id}/finalization/revisions",
    status_code=201,
)
async def correct_finalization(
    project_id: str,
    session_id: str,
    body: CorrectFinalizationBody,
    service: FinalizationService = Depends(get_finalization_service),
):
    try:
        value = await service.correct(CorrectFinalization(
            project_id=project_id,
            chapter_session_id=session_id,
            expected_revision=body.expectedRevision,
            expected_revision_hash=body.expectedRevisionHash,
            change_set=body.changeSet,
        ))
    except (FinalizationConflict, FinalizationDataCorruption, TypeError, ValueError) as error:
        _raise_public(error)
    return _reviewed(value)


@router.post(
    "/projects/{project_id}/chapter-sessions/{session_id}/finalization/confirm",
)
async def confirm_finalization(
    project_id: str,
    session_id: str,
    body: ConfirmFinalizationBody,
    service: FinalizationService = Depends(get_finalization_service),
):
    try:
        value = await service.confirm(ConfirmFinalization(
            project_id=project_id,
            chapter_session_id=session_id,
            expected_revision=body.expectedRevision,
            expected_revision_hash=body.expectedRevisionHash,
            expected_decisions_revision_pin=body.expectedDecisionsRevisionPin,
        ))
    except (FinalizationConflict, FinalizationDataCorruption, TypeError, ValueError) as error:
        _raise_public(error)
    return _reviewed(value)


@router.post(
    "/projects/{project_id}/chapter-sessions/{session_id}/finalization/cancel",
)
async def cancel_finalization(
    project_id: str,
    session_id: str,
    body: ConfirmFinalizationBody,
    service: FinalizationService = Depends(get_finalization_service),
):
    try:
        value = await service.cancel(CancelFinalization(
            project_id=project_id,
            chapter_session_id=session_id,
            expected_revision=body.expectedRevision,
            expected_revision_hash=body.expectedRevisionHash,
        ))
    except (FinalizationConflict, FinalizationDataCorruption, TypeError, ValueError) as error:
        _raise_public(error)
    return _reviewed(value)


@router.post(
    "/projects/{project_id}/chapter-sessions/{session_id}/finalization/commit",
)
async def commit_finalization(
    project_id: str,
    session_id: str,
    body: CommitFinalizationBody,
    service: AtomicFinalizationService = Depends(get_atomic_finalization_service),
):
    try:
        value = await service.commit(CommitFinalization(
            project_id=project_id,
            chapter_session_id=session_id,
            idempotency_key=body.idempotencyKey,
            expected_revision=body.expectedRevision,
            expected_revision_hash=body.expectedRevisionHash,
        ))
    except (
        FinalizationCommitInvalid, FinalizationDataCorruption,
        TypeError, ValueError,
    ) as error:
        _raise_public(error)
    return {
        "recordId": value.record_id,
        "finalChapterId": value.final_chapter_id,
        "canonRevision": value.canon_revision,
        "projectionHash": value.projection_hash,
        "planningRevisionId": value.planning_revision_id,
        "planningRevision": value.planning_revision,
        "planningHash": value.planning_hash,
        "replayed": value.replayed,
    }


@router.post("/projects/{project_id}/chapter-sessions/{session_id}/finalization/attempts/{attempt_id}/revoke")
async def revoke_finalization(
    project_id: str, session_id: str, attempt_id: str, body: ConfirmFinalizationBody,
    service: FinalizationService = Depends(get_finalization_service),
):
    try:
        value = await service.revoke(RevokeFinalization(
            project_id=project_id, chapter_session_id=session_id, attempt_id=attempt_id,
            expected_revision=body.expectedRevision, expected_revision_hash=body.expectedRevisionHash,
        ))
    except (FinalizationConflict, FinalizationDataCorruption, TypeError, ValueError) as error:
        _raise_public(error)
    return _reviewed(value)


@router.get("/projects/{project_id}/chapter-sessions/{session_id}/finalization/attempts/{attempt_id}")
async def get_finalization_attempt_state(
    project_id: str, session_id: str, attempt_id: str,
    service: FinalizationService = Depends(get_finalization_service),
):
    try:
        value = await service.get_attempt_state(project_id, session_id, attempt_id)
    except (FinalizationConflict, FinalizationDataCorruption, TypeError, ValueError) as error:
        _raise_public(error)
    return _reviewed(value)


__all__ = [
    "finalization_extraction_gateway",
    "finalization_quality_gateway",
    "get_atomic_finalization_service",
    "get_finalization_service",
    "router",
]
