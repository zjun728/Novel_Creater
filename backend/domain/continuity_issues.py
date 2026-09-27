"""Minimal author-owned continuity debt; never a Canon or Planning authority."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.http_errors import PublicDomainError


IssueCategory = Literal['time', 'location', 'character_state', 'rule', 'fact']
IssueSeverity = Literal['low', 'medium', 'high']
IssueStatus = Literal['pending', 'resolved', 'ignored']
IssueText = Annotated[str, Field(min_length=1, max_length=4000)]
MAX_TIMESTAMP = 9223372036854775807


class ContinuityIssueNotFound(PublicDomainError):
    status_code = 404
    code = 'ContinuityIssueNotFound'
    message = '当前项目中没有这条连续性问题。'


class ContinuityIssueConflict(PublicDomainError):
    status_code = 409
    code = 'ContinuityIssueConflict'
    message = '连续性问题已变化，请刷新后重试。'


class ContinuityIssueSourceInvalid(PublicDomainError):
    status_code = 422
    code = 'ContinuityIssueSourceInvalid'
    message = '来源章节没有有效的正式定稿记录。'


class ContinuityIssueInvalid(PublicDomainError):
    status_code = 422
    code = 'ContinuityIssueInvalid'
    message = '连续性问题的填写内容或读取条件无效。'


class ContinuityIssueUnavailable(PublicDomainError):
    status_code = 503
    code = 'ContinuityIssueUnavailable'
    message = '连续性问题暂时无法读取或保存，请稍后重试。'


class _StrictBody(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')

    @field_validator('description', 'suggestion', 'futureTarget', 'resolutionNote', check_fields=False)
    @classmethod
    def nonblank_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError('Text must not be blank')
        return value


class CreateContinuityIssue(_StrictBody):
    id: str = Field(min_length=36, max_length=36)
    category: IssueCategory
    severity: IssueSeverity
    description: IssueText
    suggestion: IssueText | None = None
    futureTarget: IssueText | None = None
    sourceChapterNumber: int | None = Field(default=None, ge=1, le=2147483647)

    @field_validator('id')
    @classmethod
    def stable_uuid(cls, value):
        canonical = str(UUID(value))
        if value.lower() != canonical:
            raise ValueError('A UUID is required')
        return canonical


class UpdateContinuityIssue(_StrictBody):
    status: IssueStatus
    resolutionNote: IssueText | None = None
    expectedUpdatedAt: int = Field(ge=0, le=MAX_TIMESTAMP)

    @model_validator(mode='after')
    def handling_requires_note(self):
        if self.status in ('resolved', 'ignored') and self.resolutionNote is None:
            raise ValueError('A resolution note is required')
        return self


def public_issue(row, *, lifecycle):
    """Closed DTO prevents newly added storage fields leaking into the API."""
    return {
        'id': row['id'], 'projectId': row['project_id'], 'category': row['category'],
        'severity': row['severity'], 'status': row['status'], 'description': row['description'],
        'suggestion': row['suggestion'], 'futureTarget': row['future_target'],
        'resolutionNote': row['resolution_note'], 'sourceChapterNumber': row['source_chapter'],
        'sourceFinalizationId': row['source_finalization_id'],
        'sourceCanonRevision': row['source_canon_revision'],
        'createdAt': row['created_at'], 'updatedAt': row['updated_at'], 'lifecycle': lifecycle,
    }
