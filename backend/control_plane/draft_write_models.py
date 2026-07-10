"""Closed request and immutable domain models for draft-pair writes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .draft_write_errors import DraftWriteError
from .restricted_jcs import JCSCanonicalizationError, loads_rejecting_duplicates


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IDEMPOTENCY_PATTERN = re.compile(r"^[!-~]{1,120}$", flags=re.ASCII)
ROOT_FIELDS = frozenset({"manifestVersion", "purpose", "projectId", "writes"})
WRITE_FIELDS = frozenset(
    {
        "chapterId",
        "chapterNum",
        "sourceVersionId",
        "expectedSourceContentSha256",
        "title",
        "content",
        "contentSha256",
        "promptBrief",
    }
)


def _safe_error(code: str, status: int, message: str, retryable: bool = False) -> DraftWriteError:
    return DraftWriteError(code=code, http_status=status, message=message, retryable=retryable)


class DraftCandidateWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    chapterId: str
    chapterNum: int = Field(gt=0, le=2_147_483_647)
    sourceVersionId: str
    expectedSourceContentSha256: str
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    contentSha256: str
    promptBrief: str = Field(min_length=1, max_length=500)

    @field_validator("chapterId", "sourceVersionId")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("invalid identifier")
        return value

    @field_validator("expectedSourceContentSha256", "contentSha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("invalid hash")
        return value

    @field_validator("chapterId", "sourceVersionId", "title", "content", "promptBrief")
    @classmethod
    def reject_surrogates(cls, value: str) -> str:
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError("invalid string")
        return value


class DraftWriteBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    manifestVersion: Literal[1]
    purpose: Literal["draft_only_pair"]
    projectId: str
    writes: list[DraftCandidateWriteRequest]

    @field_validator("projectId")
    @classmethod
    def validate_project_id(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("invalid identifier")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError("invalid string")
        return value


@dataclass(frozen=True)
class DraftCandidateWrite:
    chapter_id: str
    chapter_num: int
    source_version_id: str
    expected_source_content_sha256: str
    title: str
    content: str
    content_sha256: str
    prompt_brief: str


@dataclass(frozen=True)
class DraftWriteCommand:
    project_id: str
    idempotency_key: str
    manifest_sha256: str
    writes: tuple[DraftCandidateWrite, DraftCandidateWrite]


@dataclass(frozen=True)
class DraftWriteResult:
    batch_id: str
    project_id: str
    manifest_sha256: str
    candidate_version_ids: tuple[str, str]
    committed_at: int

    def to_wire(self) -> dict[str, object]:
        return {
            "batchId": self.batch_id,
            "projectId": self.project_id,
            "manifestSha256": self.manifest_sha256,
            "candidateVersionIds": list(self.candidate_version_ids),
            "committedAt": self.committed_at,
        }


def parse_manifest_bytes(raw: bytes) -> tuple[DraftWriteBatchRequest, dict[str, object]]:
    try:
        value = loads_rejecting_duplicates(raw)
    except JCSCanonicalizationError as error:
        if error.kind == "duplicate":
            raise _safe_error(
                "duplicate_json_key",
                400,
                "Manifest contains a duplicate JSON key.",
            ) from None
        raise _safe_error("invalid_manifest", 400, "Manifest is invalid.") from None
    request = parse_manifest_value(value)
    return request, value


def parse_manifest_value(value: object) -> DraftWriteBatchRequest:
    """Validate the exact manifest fields and map failures to safe errors."""

    if type(value) is not dict:
        raise _safe_error("invalid_manifest", 400, "Manifest is invalid.")
    if any(type(key) is not str or key not in ROOT_FIELDS for key in value):
        raise _safe_error("unknown_field", 400, "Manifest contains an unknown field.")
    writes = value.get("writes")
    if type(writes) is not list:
        raise _safe_error("invalid_write_count", 400, "Manifest must contain exactly two writes.")
    if len(writes) != 2:
        raise _safe_error("invalid_write_count", 400, "Manifest must contain exactly two writes.")
    for item in writes:
        if type(item) is not dict:
            raise _safe_error("invalid_manifest", 400, "Manifest is invalid.")
        if any(type(key) is not str or key not in WRITE_FIELDS for key in item):
            raise _safe_error("unknown_field", 400, "Manifest contains an unknown field.")
        for hash_field in ("expectedSourceContentSha256", "contentSha256"):
            hash_value = item.get(hash_field)
            if type(hash_value) is not str or not SHA256_PATTERN.fullmatch(hash_value):
                raise _safe_error("invalid_hash", 400, "A SHA-256 value is invalid.")

    if (
        type(writes[0].get("chapterId")) is str
        and writes[0].get("chapterId") == writes[1].get("chapterId")
    ):
        raise _safe_error("duplicate_chapter_id", 400, "Writes must target distinct chapters.")
    if value.get("manifestVersion") != 1 or type(value.get("manifestVersion")) is not int:
        raise _safe_error("invalid_manifest", 400, "Manifest is invalid.")
    try:
        request = DraftWriteBatchRequest.model_validate(value)
    except ValidationError as error:
        if any(item["type"] == "extra_forbidden" for item in error.errors()):
            raise _safe_error("unknown_field", 400, "Manifest contains an unknown field.") from None
        raise _safe_error("invalid_manifest", 400, "Manifest is invalid.") from None
    if request.writes[0].chapterId == request.writes[1].chapterId:
        raise _safe_error("duplicate_chapter_id", 400, "Writes must target distinct chapters.")
    return request


def to_command(
    *,
    route_project_id: str,
    request: DraftWriteBatchRequest,
    idempotency_key: str,
    manifest_sha256: str,
) -> DraftWriteCommand:
    """Validate headers and identity, then produce an immutable command."""

    if request.projectId != route_project_id:
        raise _safe_error(
            "project_identity_conflict",
            409,
            "Route and manifest project identities do not match.",
        )
    if type(idempotency_key) is not str or not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        raise _safe_error(
            "invalid_idempotency_key",
            400,
            "Idempotency key is invalid.",
        )
    if type(manifest_sha256) is not str or not SHA256_PATTERN.fullmatch(manifest_sha256):
        raise _safe_error("invalid_manifest_hash", 400, "Manifest hash is invalid.")

    writes: list[DraftCandidateWrite] = []
    for item in request.writes:
        actual_hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
        if actual_hash != item.contentSha256:
            raise _safe_error(
                "candidate_content_hash_mismatch",
                422,
                "Candidate content hash does not match candidate content.",
            )
        writes.append(
            DraftCandidateWrite(
                chapter_id=item.chapterId,
                chapter_num=item.chapterNum,
                source_version_id=item.sourceVersionId,
                expected_source_content_sha256=item.expectedSourceContentSha256,
                title=item.title,
                content=item.content,
                content_sha256=item.contentSha256,
                prompt_brief=item.promptBrief,
            )
        )
    return DraftWriteCommand(
        project_id=request.projectId,
        idempotency_key=idempotency_key,
        manifest_sha256=manifest_sha256,
        writes=(writes[0], writes[1]),
    )
