"""Transactional lifecycle for minimal author continuity issues."""

import time

import aiomysql

from backend.domain.continuity_issues import (
    MAX_TIMESTAMP, ContinuityIssueConflict, ContinuityIssueInvalid,
    ContinuityIssueNotFound, ContinuityIssueSourceInvalid, ContinuityIssueUnavailable,
    CreateContinuityIssue, UpdateContinuityIssue, public_issue,
)
from backend.http_errors import ProjectNotFound


class ContinuityIssueService:
    def __init__(self, repository, *, transaction_factory, connection_factory=None, clock=None):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory or transaction_factory
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)

    async def _project(self, session, project_id, *, write=False):
        method = self.repository.lock_active_project if write else self.repository.read_project
        row = await method(session, project_id)
        if row is None:
            raise ProjectNotFound()
        return 'archived' if row['archived_at'] is not None else 'active'

    def _now(self, previous=None):
        value = self.clock()
        if type(value) is not int or not 0 <= value <= MAX_TIMESTAMP:
            raise ContinuityIssueUnavailable()
        value = max(value, previous + 1) if previous is not None else value
        if value > MAX_TIMESTAMP:
            raise ContinuityIssueConflict()
        return value

    async def list(self, project_id, *, status=None, offset=0, limit=30):
        if (status not in (None, 'pending', 'resolved', 'ignored') or type(offset) is not int
                or type(limit) is not int or offset < 0 or not 1 <= limit <= 50):
            raise ContinuityIssueInvalid()
        async with self.connection_factory() as session:
            lifecycle = await self._project(session, project_id)
            rows = await self.repository.list(session, project_id, status=status, offset=offset, limit=limit + 1)
            return {'projectId': project_id, 'lifecycle': lifecycle,
                    'items': [public_issue(row, lifecycle=lifecycle) for row in rows[:limit]],
                    'nextOffset': offset + limit if len(rows) > limit else None}

    async def get(self, project_id, issue_id):
        async with self.connection_factory() as session:
            lifecycle = await self._project(session, project_id)
            row = await self.repository.get(session, project_id, issue_id)
            if row is None:
                raise ContinuityIssueNotFound()
            return public_issue(row, lifecycle=lifecycle)

    async def create(self, project_id, request: CreateContinuityIssue):
        if not isinstance(request, CreateContinuityIssue):
            raise ContinuityIssueInvalid()
        async with self.transaction_factory() as session:
            lifecycle = await self._project(session, project_id, write=True)
            original = {'category': request.category, 'severity': request.severity,
                        'description': request.description, 'suggestion': request.suggestion,
                        'future_target': request.futureTarget, 'source_chapter': request.sourceChapterNumber}
            existing = await self.repository.get(session, project_id, request.id, for_update=True)
            if existing is not None:
                if any(existing[key] != value for key, value in original.items()):
                    raise ContinuityIssueConflict()
                return public_issue(existing, lifecycle=lifecycle)
            source = {'source_finalization_id': None, 'source_canon_revision': None}
            if request.sourceChapterNumber is not None:
                resolved = await self.repository.source_for_chapter(session, project_id, request.sourceChapterNumber)
                if (resolved is None or resolved['project_id'] != project_id
                        or resolved['source_chapter'] != request.sourceChapterNumber
                        or not resolved['source_finalization_id']
                        or type(resolved['source_canon_revision']) is not int
                        or resolved['source_canon_revision'] < 1):
                    raise ContinuityIssueSourceInvalid()
                source = {key: resolved[key] for key in source}
            now = self._now()
            row = dict(id=request.id, project_id=project_id, status='pending', resolution_note=None,
                       created_at=now, updated_at=now, **original, **source)
            try:
                await self.repository.insert(session, row)
            except aiomysql.IntegrityError as error:
                if error.args and error.args[0] == 1062:
                    raise ContinuityIssueConflict() from None
                raise
            return public_issue(row, lifecycle=lifecycle)

    async def update(self, project_id, issue_id, request: UpdateContinuityIssue):
        if not isinstance(request, UpdateContinuityIssue):
            raise ContinuityIssueInvalid()
        async with self.transaction_factory() as session:
            lifecycle = await self._project(session, project_id, write=True)
            row = await self.repository.get(session, project_id, issue_id, for_update=True)
            if row is None:
                raise ContinuityIssueNotFound()
            if row['updated_at'] != request.expectedUpdatedAt:
                raise ContinuityIssueConflict()
            now = self._now(previous=row['updated_at'])
            affected = await self.repository.update(
                session, project_id, issue_id, status=request.status, resolution_note=request.resolutionNote,
                expected_updated_at=request.expectedUpdatedAt, updated_at=now)
            if affected != 1:
                raise ContinuityIssueConflict()
            row = {**row, 'status': request.status, 'resolution_note': request.resolutionNote, 'updated_at': now}
            return public_issue(row, lifecycle=lifecycle)
