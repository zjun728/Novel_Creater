"""Read-only continuity author endpoints."""

from typing import Literal
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from backend.http_errors import PublicDomainError
from backend.database import read_only_transaction
from backend.repositories.continuity import ContinuityRepository
from backend.services.continuity import ContinuityReader, ContinuityReadError

router = APIRouter(tags=["continuity"])
reader = ContinuityReader(ContinuityRepository(), read_only_transaction)

class ContinuityPublicError(PublicDomainError):
    def __init__(self, code):
        codes = {
            'project_missing': (404, '项目不存在。'),
            'entity_missing': (404, '当前项目中没有这项设定。'),
            'evidence_missing': (404, '当前项目中没有这条来源记录。'),
            'snapshot_changed': (409, '事实版本已变化，请重新读取。'),
            'projection_out_of_sync': (409, '事实正在同步，请稍后重试。'),
            'invalid_request': (422, '读取条件无效。'),
            'invalid_content': (500, '连续性记录暂时无法读取。'),
        }
        self.code = code if code in codes else 'invalid_content'
        self.status_code, self.message = codes[self.code]
        super().__init__()


async def read_result(operation):
    try:
        return JSONResponse(await operation, headers={'Cache-Control': 'private, no-store'})
    except ContinuityReadError as error:
        raise ContinuityPublicError(str(error)) from None


@router.get("/projects/{project_id}/continuity/entities")
async def entities(project_id: str, offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=50),
                   query: str = Query("", max_length=100),
                   entity_type: Literal["person", "organization", "place", "item"] | None = None,
                   revision: int | None = Query(None, ge=0)):
    return await read_result(reader.entities(project_id, offset=offset, limit=limit, query=query,
                                             entity_type=entity_type, revision=revision))


@router.get("/projects/{project_id}/continuity/records")
async def records(project_id: str, kind: Literal["facts", "state", "memory", "arcs", "clues", "progress"],
                  entity_id: str | None = Query(None, max_length=100), offset: int = Query(0, ge=0),
                  limit: int = Query(30, ge=1, le=50), revision: int | None = Query(None, ge=0),
                  field_path: str | None = Query(None, min_length=1, max_length=200),
                  global_only: bool = False):
    return await read_result(reader.records(project_id, kind=kind, entity_id=entity_id,
                                            offset=offset, limit=limit, revision=revision,
                                            field_path=field_path, global_only=global_only))


@router.get("/projects/{project_id}/continuity/evidence/{event_id}")
async def evidence(project_id: str, event_id: str):
    return await read_result(reader.evidence(project_id, event_id))


@router.get("/projects/{project_id}/continuity/future-design")
async def future_design(project_id: str, revision: int | None = Query(None, ge=0),
                        entity_id: str | None = Query(None, min_length=1, max_length=100)):
    return await read_result(reader.future_design(project_id, revision=revision, entity_id=entity_id))
