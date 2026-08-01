from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.database import connection, transaction
from backend.http_errors import PublicDomainError
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.services.chapter_draft_generation import (
    ChapterDraftGenerationConflict,
    ChapterDraftGenerationFailed,
    ChapterDraftGenerationPreconditionFailed,
    ChapterDraftGenerationService,
    GenerateWorkingDraft,
)
from backend.services.chapter_sessions import (
    ChapterSessionConflict,
    ChapterSessionNotFound,
    ChapterSessionPreconditionFailed,
    ChapterSessionRequestInvalid as ServiceRequestInvalid,
    ChapterSessionService,
    CreateChapterSession,
    SaveDraftCandidate,
    SaveWorkingDraft,
)


router = APIRouter(tags=["chapter-sessions"])
_service = ChapterSessionService(
    ChapterSessionRepository(), transaction_factory=transaction,
    connection_factory=connection,
)
_generation_service = ChapterDraftGenerationService(
    ChapterSessionRepository(), transaction_factory=transaction,
)


def get_chapter_session_service() -> ChapterSessionService:
    return _service


def get_chapter_draft_generation_service() -> ChapterDraftGenerationService:
    return _generation_service


class ChapterSessionRequestInvalid(PublicDomainError):
    status_code = 422
    code = "ChapterSessionRequestInvalid"
    message = "Chapter session request is invalid"


class ChapterSessionResourceNotFound(PublicDomainError):
    status_code = 404
    code = "ChapterSessionNotFound"
    message = "Chapter session or project was not found"


class ChapterSessionStateConflict(PublicDomainError):
    status_code = 409
    code = "ChapterSessionConflict"
    message = "Chapter session state changed; refresh and retry"


class ChapterSessionPreconditionUnavailable(PublicDomainError):
    status_code = 422
    code = "ChapterSessionPreconditionFailed"
    message = "Chapter session prerequisites are unavailable"


class ChapterDraftGenerationUnavailable(PublicDomainError):
    status_code = 502
    code = "ChapterDraftGenerationFailed"
    message = "Chapter draft generation failed"


class _StrictBody(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
    )


class CreateSessionBody(_StrictBody):
    chapterNumber: int = Field(ge=1)
    expectedPlanningRevision: int = Field(ge=1)
    expectedPlanningHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedOutlineRevision: int = Field(ge=1)
    expectedOutlineHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedCanonRevision: int = Field(ge=0)


class SaveWorkingDraftBody(_StrictBody):
    expectedRevision: int = Field(ge=1)
    expectedContentHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: str = Field(max_length=100_000)


class SaveCandidateBody(_StrictBody):
    expectedWorkingDraftRevision: int = Field(ge=1)


class GenerateWorkingDraftBody(_StrictBody):
    expectedWorkingDraftRevision: int = Field(ge=1)
    authorInstruction: str = Field(default="", max_length=2000)


def _raise_public(error: Exception):
    if isinstance(error, ChapterSessionNotFound):
        raise ChapterSessionResourceNotFound() from None
    if isinstance(error, ServiceRequestInvalid):
        raise ChapterSessionRequestInvalid() from None
    if isinstance(error, ChapterSessionConflict):
        raise ChapterSessionStateConflict() from None
    if isinstance(error, ChapterSessionPreconditionFailed):
        raise ChapterSessionPreconditionUnavailable() from None
    if isinstance(error, ChapterDraftGenerationConflict):
        raise ChapterSessionStateConflict() from None
    if isinstance(error, ChapterDraftGenerationPreconditionFailed):
        raise ChapterSessionPreconditionUnavailable() from None
    if isinstance(error, ChapterDraftGenerationFailed):
        raise ChapterDraftGenerationUnavailable() from None
    raise error


def _public_workspace(workspace):
    return {
        "projectId": workspace.project_id,
        "session": {
            "id": workspace.session.id,
            "projectId": workspace.session.project_id,
            "planningRevisionId": workspace.session.planning_revision_id,
            "planningRevision": workspace.session.planning_revision,
            "planningHash": workspace.session.planning_hash,
            "storyBlockId": workspace.session.story_block_id,
            "storyBlockRevision": workspace.session.story_block_revision,
            "storyBlockHash": workspace.session.story_block_hash,
            "chapterOutlineRevisionId": (
                workspace.session.chapter_outline_revision_id
            ),
            "chapterOutlineRevision": (
                workspace.session.chapter_outline_revision
            ),
            "chapterOutlineHash": workspace.session.chapter_outline_hash,
            "chapterNum": workspace.session.chapter_num,
            "expectedCanonRevision": workspace.session.expected_canon_revision,
            "status": workspace.session.status,
        },
        "workingDraft": {
            "id": workspace.working_draft.id,
            "projectId": workspace.working_draft.project_id,
            "chapterSessionId": workspace.working_draft.chapter_session_id,
            "revision": workspace.working_draft.revision,
            "content": workspace.working_draft.content,
            "contentHash": workspace.working_draft.content_hash,
        },
        "candidates": [{
            "id": candidate.id,
            "projectId": candidate.project_id,
            "chapterSessionId": candidate.chapter_session_id,
            "workingDraftRevision": candidate.working_draft_revision,
            "content": candidate.content,
            "contentHash": candidate.content_hash,
            "outlineRevisionId": candidate.outline_revision_id,
            "outlineRevision": candidate.outline_revision,
            "outlineHash": candidate.outline_hash,
            "planningRevisionId": candidate.planning_revision_id,
            "planningRevision": candidate.planning_revision,
            "planningHash": candidate.planning_hash,
            "canonRevision": candidate.canon_revision,
            "projectionRevision": candidate.projection_revision,
            "projectionHash": candidate.projection_hash,
            "basisStatus": candidate.basis_status,
        } for candidate in workspace.candidates],
    }


@router.get("/projects/{pid}/chapter-sessions/{chapter_number}")
async def get_chapter_session(
    pid: str,
    chapter_number: int,
    service=Depends(get_chapter_session_service),
):
    try:
        workspace = await service.get(pid, chapter_number)
        return None if workspace is None else _public_workspace(workspace)
    except Exception as error:
        _raise_public(error)


@router.post(
    "/projects/{pid}/chapter-sessions/{chapter_number}",
    status_code=201,
)
async def create_chapter_session(
    pid: str,
    chapter_number: int,
    raw_body: object = Body(...),
    service=Depends(get_chapter_session_service),
):
    try:
        body = CreateSessionBody.model_validate(raw_body)
        if body.chapterNumber != chapter_number:
            raise ChapterSessionRequestInvalid()
        workspace = await service.create_session(CreateChapterSession(
            project_id=pid,
            chapter_number=body.chapterNumber,
            expected_planning_revision=body.expectedPlanningRevision,
            expected_planning_hash=body.expectedPlanningHash,
            expected_outline_revision=body.expectedOutlineRevision,
            expected_outline_hash=body.expectedOutlineHash,
            expected_canon_revision=body.expectedCanonRevision,
        ))
    except ValidationError:
        raise ChapterSessionRequestInvalid() from None
    except Exception as error:
        _raise_public(error)
    return _public_workspace(workspace)


@router.put("/projects/{pid}/chapter-sessions/{session_id}/working-draft")
async def save_working_draft(
    pid: str, session_id: str, raw_body: object = Body(...),
    service=Depends(get_chapter_session_service),
):
    try:
        body = SaveWorkingDraftBody.model_validate(raw_body)
        workspace = await service.save_working_draft(SaveWorkingDraft(
            project_id=pid,
            chapter_session_id=session_id,
            expected_revision=body.expectedRevision,
            expected_content_hash=body.expectedContentHash,
            content=body.content,
        ))
    except ValidationError:
        raise ChapterSessionRequestInvalid() from None
    except Exception as error:
        _raise_public(error)
    return _public_workspace(workspace)


@router.post("/projects/{pid}/chapter-sessions/{session_id}/generate-working-draft", status_code=201)
async def generate_working_draft(
    pid: str, session_id: str, raw_body: object = Body(...),
    service=Depends(get_chapter_draft_generation_service),
):
    try:
        body = GenerateWorkingDraftBody.model_validate(raw_body)
        workspace = await service.generate_working_draft(GenerateWorkingDraft(
            project_id=pid,
            chapter_session_id=session_id,
            expected_working_draft_revision=body.expectedWorkingDraftRevision,
            author_instruction=body.authorInstruction,
        ))
    except ValidationError:
        raise ChapterSessionRequestInvalid() from None
    except Exception as error:
        _raise_public(error)
    return _public_workspace(workspace)


@router.post("/projects/{pid}/chapter-sessions/{session_id}/candidates", status_code=201)
async def save_candidate(
    pid: str, session_id: str, raw_body: object = Body(...),
    service=Depends(get_chapter_session_service),
):
    try:
        body = SaveCandidateBody.model_validate(raw_body)
        workspace = await service.save_candidate(SaveDraftCandidate(
            project_id=pid,
            chapter_session_id=session_id,
            expected_working_draft_revision=body.expectedWorkingDraftRevision,
        ))
    except ValidationError:
        raise ChapterSessionRequestInvalid() from None
    except Exception as error:
        _raise_public(error)
    return _public_workspace(workspace)
