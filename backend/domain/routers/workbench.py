"""Bounded, read-only workbench entrypoint."""

import aiomysql
from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse

from backend.database import DatabaseUnavailable, read_only_transaction
from backend.domain.manuscripts import ManuscriptCorrupt
from backend.http_errors import PublicDomainError
from backend.repositories.chapter_sessions import ActiveChapterSessionConflict
from backend.repositories.workbench import WorkbenchRepository
from backend.repositories.workbench_reviews import WorkbenchReviewRepository
from backend.services.workbench import WorkbenchReader, WorkbenchProjectMissing
from backend.services.workbench_reviews import WorkbenchReviewReader, WorkbenchReviewMissing

router = APIRouter(tags=['workbench'])
reader = WorkbenchReader(WorkbenchRepository(), read_only_transaction)
review_reader = WorkbenchReviewReader(WorkbenchReviewRepository(), read_only_transaction)


class WorkbenchPublicError(PublicDomainError):
    def __init__(self, status, code, message):
        self.status_code, self.code, self.message = status, code, message
        super().__init__()


async def read_result(operation):
    try:
        result = await operation
        return JSONResponse(result.model_dump(mode='json'), headers={'Cache-Control': 'private, no-store'})
    except WorkbenchProjectMissing:
        raise WorkbenchPublicError(404, 'WorkbenchProjectMissing', '项目不存在。') from None
    except WorkbenchReviewMissing:
        raise WorkbenchPublicError(404, 'WorkbenchReviewMissing', '本章尚无定稿审查记录。') from None
    except (DatabaseUnavailable, aiomysql.OperationalError, aiomysql.InterfaceError):
        raise WorkbenchPublicError(503, 'WorkbenchUnavailable', '工作台暂时无法读取，请重试。') from None
    except (ValueError, ManuscriptCorrupt, ActiveChapterSessionConflict):
        raise WorkbenchPublicError(409, 'WorkbenchAuthorityInvalid', '章节依据暂时无法核对，请重新读取。') from None


@router.get('/projects/{project_id}/workbench/chapters/{number}')
async def bootstrap(project_id: str, number: int = Path(ge=1, le=2147483647)):
    return await read_result(reader.bootstrap(project_id, number))


@router.get('/projects/{project_id}/workbench/chapters/{number}/review')
async def review(project_id: str, number: int = Path(ge=1, le=2147483647)):
    return await read_result(review_reader.review(project_id, number))


@router.get('/projects/{project_id}/workbench/volumes')
async def volumes(project_id: str):
    return await read_result(reader.volumes(project_id))


@router.get('/projects/{project_id}/workbench/volumes/{volume_id}/chapters')
async def chapters(project_id: str, volume_id: str, cursor: str | None = Query(None, max_length=512),
                   limit: int = Query(50, ge=1, le=100)):
    return await read_result(reader.chapters(project_id, volume_id, cursor=cursor, limit=limit))
