"""Strict, private author endpoints for independent continuity issues."""

from uuid import uuid4

import aiomysql
from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from backend.database import DatabaseUnavailable, read_only_transaction, transaction
from backend.domain.continuity_issues import (
    ContinuityIssueInvalid, ContinuityIssueUnavailable, CreateContinuityIssue,
    IssueStatus, UpdateContinuityIssue,
)
from backend.http_errors import PublicDomainError
from backend.repositories.continuity_issues import ContinuityIssueRepository
from backend.services.continuity_issues import ContinuityIssueService


_PRIVATE = {'Cache-Control': 'private, no-store'}


class _PrivateIssueRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            error = None
            try:
                response = await original(request)
                response.headers.update(_PRIVATE)
                return response
            except RequestValidationError:
                error = ContinuityIssueInvalid()
            except PublicDomainError as caught:
                error = caught
            except (DatabaseUnavailable, aiomysql.Error):
                error = ContinuityIssueUnavailable()
            return JSONResponse(status_code=error.status_code, headers=_PRIVATE,
                                content={'code': error.code, 'message': error.message,
                                         'correlationId': str(uuid4())})

        return handler


router = APIRouter(tags=['continuity-issues'], route_class=_PrivateIssueRoute)
_service = ContinuityIssueService(ContinuityIssueRepository(), transaction_factory=transaction,
                                  connection_factory=read_only_transaction)


def get_continuity_issue_service():
    return _service


@router.get('/projects/{project_id}/continuity/issues')
async def list_issues(project_id: str, status: IssueStatus | None = None,
                      offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=50),
                      service: ContinuityIssueService = Depends(get_continuity_issue_service)):
    return await service.list(project_id, status=status, offset=offset, limit=limit)


@router.get('/projects/{project_id}/continuity/issues/{issue_id}')
async def get_issue(project_id: str, issue_id: str,
                    service: ContinuityIssueService = Depends(get_continuity_issue_service)):
    return await service.get(project_id, issue_id)


@router.post('/projects/{project_id}/continuity/issues')
async def create_issue(project_id: str, body: CreateContinuityIssue,
                       service: ContinuityIssueService = Depends(get_continuity_issue_service)):
    return await service.create(project_id, body)


@router.patch('/projects/{project_id}/continuity/issues/{issue_id}')
async def update_issue(project_id: str, issue_id: str, body: UpdateContinuityIssue,
                       service: ContinuityIssueService = Depends(get_continuity_issue_service)):
    return await service.update(project_id, issue_id, body)
