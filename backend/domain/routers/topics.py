"""Strict global Topic Center HTTP routes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.database import connection, transaction
from backend.domain.topics import (
    TopicCandidatePayload,
    TopicDirectionPayload,
    TopicEvidenceRef,
    TopicMessage,
    TopicSubjectRef,
)
from backend.gateways import topic_discussion_provider
from backend.repositories.chapter_outlines import ChapterOutlineRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.projects import ProjectRepository
from backend.repositories.seeds import SeedRepository
from backend.repositories.topics import TopicRepository
from backend.services.model_bindings import ModelBindingService
from backend.services.project_lifecycle import ProjectLifecycleService
from backend.services.seeds import SeedService
from backend.services.topic_discussions import DiscussTopic, TopicDiscussionService
from backend.services.topic_library import (
    ArchiveTopicCandidate,
    SaveTopicCandidate,
    SaveTopicDirection,
    TopicLibraryService,
)
from backend.services.topic_project_handoffs import (
    HandoffTopicCandidate,
    TopicProjectHandoffService,
)


router = APIRouter(tags=["topics"])
BoundedId = Annotated[str, Path(min_length=1, max_length=36)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]

_topic_repository = TopicRepository()
_discussion_service = TopicDiscussionService(
    _topic_repository,
    transaction_factory=transaction,
    connection_factory=connection,
    provider_gateway=(
        topic_discussion_provider.topic_discussion_provider_gateway
    ),
)
_library_service = TopicLibraryService(
    _topic_repository,
    transaction_factory=transaction,
    connection_factory=connection,
)
_binding_service = ModelBindingService(
    ModelBindingRepository(),
    transaction_factory=transaction,
    connection_factory=connection,
)
_project_service = ProjectLifecycleService(
    ProjectRepository(
        chapter_session_repository=ChapterSessionRepository(),
        chapter_outline_repository=ChapterOutlineRepository(),
    ),
    transaction,
    connection,
    model_binding_service=_binding_service,
)
_seed_service = SeedService(
    SeedRepository(),
    transaction_factory=transaction,
    connection_factory=connection,
)
_handoff_service = TopicProjectHandoffService(
    _topic_repository,
    project_service=_project_service,
    seed_service=_seed_service,
    transaction_factory=transaction,
)


def get_topic_discussion_service() -> TopicDiscussionService:
    return _discussion_service


def get_topic_library_service() -> TopicLibraryService:
    return _library_service


def get_topic_handoff_service() -> TopicProjectHandoffService:
    return _handoff_service


class _StrictBody(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class CreateDiscussionBody(_StrictBody):
    title: str = Field(min_length=1, max_length=300)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return TopicMessage(role="user", content=value).content


class SendDiscussionMessageBody(_StrictBody):
    content: str = Field(min_length=1, max_length=20_000)
    idempotencyKey: str = Field(pattern=r"^[A-Za-z0-9_-]{64}$")
    evidence: tuple[TopicEvidenceRef, ...] = Field(default=(), max_length=4)
    subject: TopicSubjectRef | None = None

    @field_validator("evidence", mode="before")
    @classmethod
    def freeze_evidence(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return TopicMessage(role="user", content=value).content

    @field_validator("evidence")
    @classmethod
    def unique_evidence(cls, value):
        identities = tuple(item.snapshot_id for item in value)
        if len(identities) != len(set(identities)):
            raise ValueError("topic evidence IDs must be unique")
        return value


class SaveDirectionBody(_StrictBody):
    messageId: str = Field(min_length=1, max_length=36)
    payload: TopicDirectionPayload
    evidence: tuple[TopicEvidenceRef, ...] = Field(default=(), max_length=4)
    idempotencyKey: str = Field(pattern=r"^[A-Za-z0-9_-]{64}$")
    directionId: str | None = Field(default=None, min_length=1, max_length=36)
    expectedVersion: int | None = Field(default=None, gt=0)

    @field_validator("evidence", mode="before")
    @classmethod
    def freeze_evidence(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @field_validator("evidence")
    @classmethod
    def unique_evidence(cls, value):
        identities = tuple(item.snapshot_id for item in value)
        if len(identities) != len(set(identities)):
            raise ValueError("topic evidence IDs must be unique")
        return value

    @model_validator(mode="after")
    def matching_version_target(self):
        if (self.directionId is None) != (self.expectedVersion is None):
            raise ValueError("direction ID and expected version must match")
        return self


class SaveCandidateBody(_StrictBody):
    messageId: str = Field(min_length=1, max_length=36)
    payload: TopicCandidatePayload
    evidence: tuple[TopicEvidenceRef, ...] = Field(default=(), max_length=4)
    idempotencyKey: str = Field(pattern=r"^[A-Za-z0-9_-]{64}$")
    candidateId: str | None = Field(default=None, min_length=1, max_length=36)
    expectedVersion: int | None = Field(default=None, gt=0)

    @field_validator("evidence", mode="before")
    @classmethod
    def freeze_evidence(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @field_validator("evidence")
    @classmethod
    def unique_evidence(cls, value):
        identities = tuple(item.snapshot_id for item in value)
        if len(identities) != len(set(identities)):
            raise ValueError("topic evidence IDs must be unique")
        return value

    @model_validator(mode="after")
    def matching_version_target(self):
        if (self.candidateId is None) != (self.expectedVersion is None):
            raise ValueError("candidate ID and expected version must match")
        return self


class ArchiveCandidateBody(_StrictBody):
    expectedVersion: int = Field(gt=0)


class HandoffCandidateBody(_StrictBody):
    candidateHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    projectTitle: str = Field(min_length=1, max_length=200)
    idempotencyKey: str = Field(pattern=r"^[A-Za-z0-9_-]{64}$")


def _discussion_view(row: Mapping) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "createdAt": int(row["created_at"]),
        "updatedAt": int(row["updated_at"]),
    }


def _discussion_detail_view(value: Mapping) -> dict:
    return {
        "discussion": _discussion_view(value["discussion"]),
        "messages": [
            {
                "id": row["id"],
                "sequenceNumber": int(row["sequence_number"]),
                "role": row["role"],
                "content": row["content_text"],
                "contentHash": row["content_hash"],
                "createdAt": int(row["created_at"]),
            }
            for row in value["messages"]
        ],
        "requests": [
            {
                "id": row["id"],
                "status": row["status"],
                "userMessageId": row["user_message_id"],
                "assistantMessageId": row.get("assistant_message_id"),
                "result": row.get("result"),
                "resultHash": row.get("result_hash"),
                "publicErrorCode": row.get("public_error_code"),
                "createdAt": int(row["created_at"]),
                "completedAt": row.get("completed_at"),
            }
            for row in value["requests"]
        ],
    }


def _version_view(row: Mapping, kind: str, *, current: bool = False) -> dict:
    version = int(row["current_version"] if current else row["version"])
    return {
        "id": row["version_id"] if current else row["id"],
        "version": version,
        "payload": row["payload"],
        "contentHash": row["content_hash"],
        "discussionId": row["discussion_id"],
        "basis": row["basis"],
        "createdAt": int(
            row["version_created_at"] if current else row["created_at"]
        ),
    }


def _direction_list_view(row: Mapping) -> dict:
    return {
        "id": row["id"],
        "currentVersion": int(row["current_version"]),
        "createdAt": int(row["created_at"]),
        "updatedAt": int(row["updated_at"]),
        "current": _version_view(row, "direction", current=True),
    }


def _candidate_list_view(row: Mapping) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "currentVersion": int(row["current_version"]),
        "createdAt": int(row["created_at"]),
        "updatedAt": int(row["updated_at"]),
        "current": _version_view(row, "candidate", current=True),
    }


@router.get("/topic-discussions")
async def list_topic_discussions(
    offset: Offset = 0,
    limit: Limit = 50,
    service: TopicDiscussionService = Depends(get_topic_discussion_service),
):
    return [
        _discussion_view(row)
        for row in await service.list(offset=offset, limit=limit)
    ]


@router.get("/topic-discussions/{discussion_id}")
async def get_topic_discussion(
    discussion_id: BoundedId,
    service: TopicDiscussionService = Depends(get_topic_discussion_service),
):
    return _discussion_detail_view(await service.read(discussion_id))


@router.post("/topic-discussions")
async def create_topic_discussion(
    body: CreateDiscussionBody,
    service: TopicDiscussionService = Depends(get_topic_discussion_service),
):
    return _discussion_view(await service.create(body.title))


@router.post("/topic-discussions/{discussion_id}/messages")
async def send_topic_message(
    discussion_id: BoundedId,
    body: SendDiscussionMessageBody,
    service: TopicDiscussionService = Depends(get_topic_discussion_service),
):
    value = await service.send(DiscussTopic(
        discussionId=discussion_id,
        content=body.content,
        idempotencyKey=body.idempotencyKey,
        evidence=body.evidence,
        subject=body.subject,
    ))
    return {
        **{key: item for key, item in value.items() if key != "result"},
        "result": value["result"].model_dump(mode="json", by_alias=True),
    }


@router.get("/topic-directions")
async def list_topic_directions(
    offset: Offset = 0,
    limit: Limit = 50,
    service: TopicLibraryService = Depends(get_topic_library_service),
):
    return [
        _direction_list_view(row)
        for row in await service.list_directions(offset=offset, limit=limit)
    ]


@router.get("/topic-directions/{direction_id}")
async def get_topic_direction(
    direction_id: BoundedId,
    service: TopicLibraryService = Depends(get_topic_library_service),
):
    value = await service.read_direction(direction_id)
    identity = value["direction"]
    return {
        "id": identity["id"],
        "currentVersion": int(identity["current_version"]),
        "createdAt": int(identity["created_at"]),
        "updatedAt": int(identity["updated_at"]),
        "versions": [
            _version_view(row, "direction") for row in value["versions"]
        ],
    }


@router.post("/topic-discussions/{discussion_id}/directions")
async def save_topic_direction(
    discussion_id: BoundedId,
    body: SaveDirectionBody,
    service: TopicLibraryService = Depends(get_topic_library_service),
):
    return await service.save_direction(SaveTopicDirection(
        discussionId=discussion_id,
        messageId=body.messageId,
        payload=body.payload,
        evidence=body.evidence,
        idempotencyKey=body.idempotencyKey,
        directionId=body.directionId,
        expectedVersion=body.expectedVersion,
    ))


@router.get("/topic-candidates")
async def list_topic_candidates(
    status: Literal["active", "archived"] = "active",
    offset: Offset = 0,
    limit: Limit = 50,
    service: TopicLibraryService = Depends(get_topic_library_service),
):
    return [
        _candidate_list_view(row)
        for row in await service.list_candidates(
            status=status,
            offset=offset,
            limit=limit,
        )
    ]


@router.get("/topic-candidates/{candidate_id}")
async def get_topic_candidate(
    candidate_id: BoundedId,
    service: TopicLibraryService = Depends(get_topic_library_service),
):
    value = await service.read_candidate(candidate_id)
    identity = value["candidate"]
    return {
        "id": identity["id"],
        "status": identity["status"],
        "currentVersion": int(identity["current_version"]),
        "createdAt": int(identity["created_at"]),
        "updatedAt": int(identity["updated_at"]),
        "versions": [
            _version_view(row, "candidate") for row in value["versions"]
        ],
    }


@router.post("/topic-discussions/{discussion_id}/candidates")
async def save_topic_candidate(
    discussion_id: BoundedId,
    body: SaveCandidateBody,
    service: TopicLibraryService = Depends(get_topic_library_service),
):
    return await service.save_candidate(SaveTopicCandidate(
        discussionId=discussion_id,
        messageId=body.messageId,
        payload=body.payload,
        evidence=body.evidence,
        idempotencyKey=body.idempotencyKey,
        candidateId=body.candidateId,
        expectedVersion=body.expectedVersion,
    ))


@router.post("/topic-candidates/{candidate_id}/archive")
async def archive_topic_candidate(
    candidate_id: BoundedId,
    body: ArchiveCandidateBody,
    service: TopicLibraryService = Depends(get_topic_library_service),
):
    return await service.archive_candidate(ArchiveTopicCandidate(
        candidateId=candidate_id,
        expectedVersion=body.expectedVersion,
    ))


@router.post("/topic-candidates/{candidate_id}/versions/{version}/projects")
async def create_project_from_topic_candidate(
    candidate_id: BoundedId,
    version: Annotated[int, Path(gt=0)],
    body: HandoffCandidateBody,
    service: TopicProjectHandoffService = Depends(get_topic_handoff_service),
):
    value = await service.create_project(HandoffTopicCandidate(
        candidateId=candidate_id,
        candidateVersion=version,
        candidateHash=body.candidateHash,
        projectTitle=body.projectTitle,
        idempotencyKey=body.idempotencyKey,
    ))
    return {
        "project": {"id": value["projectId"], "title": body.projectTitle},
        "seed": {
            "id": value["seedId"],
            "revision": value["seedRevision"],
            "isSelected": False,
            "selectionRevision": 0,
        },
        "handoff": {
            "candidateId": value["candidateId"],
            "version": value["candidateVersion"],
        },
    }


__all__ = (
    "get_topic_discussion_service",
    "get_topic_handoff_service",
    "get_topic_library_service",
    "router",
)
