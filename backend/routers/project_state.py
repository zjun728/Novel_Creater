"""Project state readiness persistence adapters.

These endpoints are contracts for migrated production schemas. They are not
invoked by the Phase 2.5 dry-run tests against a real database.
"""
import json
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.database import execute, fetchall, fetchone
from .helpers import convert_row, convert_rows
from .provenance_support import normalize_state_provenance

router = APIRouter(tags=["project-state"])

FINALIZATION_STATUSES = {
    "staged",
    "validated",
    "committed",
    "pending",
    "in_progress",
    "failed_pre_commit",
    "failed_after_chapter_commit",
    "half_success",
}

HEALTH_STATUSES = {
    "dry_run",
    "ready",
    "blocked",
    "warning",
    "failed",
    "unknown",
}


class FinalizationMarkerSave(BaseModel):
    sourceChapterNum: Optional[int] = None
    sourceVersionId: str = ""
    runId: str = ""
    finalizationId: str = ""
    commitStatus: str = "pending"
    reason: str = ""
    startedAt: Optional[int] = None
    provenance: Optional[dict] = None


class ProjectHealthCheckSave(BaseModel):
    sourceChapterNum: Optional[int] = None
    sourceVersionId: str = ""
    runId: str = ""
    finalizationId: str = ""
    commitStatus: str = "dry_run"
    blocked: bool = False
    blockingCount: int = 0
    warningCount: int = 0
    result: Optional[dict] = None
    issueSummary: Optional[list] = None
    provenance: Optional[dict] = None


@router.get("/projects/{pid}/finalization-markers")
async def list_finalization_markers(pid: str):
    try:
        rows = await fetchall(
            """SELECT * FROM finalization_markers
               WHERE project_id=%s
               ORDER BY chapter_num ASC, updated_at DESC""",
            (pid,),
        )
    except Exception as error:
        if _is_missing_project_state_table_error(error):
            return []
        raise
    return convert_rows(rows)


@router.put("/projects/{pid}/finalization-markers/{chapter_num}")
async def save_finalization_marker(pid: str, chapter_num: int, data: FinalizationMarkerSave):
    now = int(time.time() * 1000)
    status = _normalize_status(data.commitStatus, FINALIZATION_STATUSES, "pending")
    provenance = normalize_state_provenance(
        data,
        {
            "sourceChapterNum": data.sourceChapterNum or chapter_num,
            "sourceVersionId": data.sourceVersionId,
            "runId": data.runId,
            "finalizationId": data.finalizationId,
            "commitStatus": status,
        },
    )
    marker_id = _stable_marker_id(pid, chapter_num, provenance)
    try:
        await execute(
            """INSERT INTO finalization_markers
               (id, project_id, chapter_num, source_chapter_num, source_version_id,
                run_id, finalization_id, commit_status, reason, provenance,
                started_at, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE
                 source_chapter_num=VALUES(source_chapter_num),
                 source_version_id=VALUES(source_version_id),
                 run_id=VALUES(run_id),
                 finalization_id=VALUES(finalization_id),
                 commit_status=VALUES(commit_status),
                 reason=VALUES(reason),
                 provenance=VALUES(provenance),
                 started_at=COALESCE(started_at, VALUES(started_at)),
                 updated_at=VALUES(updated_at)""",
            (
                marker_id,
                pid,
                chapter_num,
                provenance.get("sourceChapterNum") or chapter_num,
                provenance.get("sourceVersionId") or "",
                provenance.get("runId") or "",
                provenance.get("finalizationId") or "",
                status,
                data.reason or "",
                json.dumps(provenance, ensure_ascii=False),
                data.startedAt or now,
                now,
                now,
            ),
        )
        row = await fetchone("SELECT * FROM finalization_markers WHERE id=%s", (marker_id,))
    except Exception as error:
        if _is_missing_project_state_table_error(error):
            return _migration_unavailable_response(
                "finalization_markers",
                pid,
                chapter_num,
                status,
                provenance,
                data.reason,
            )
        raise
    return convert_row(row)


@router.get("/projects/{pid}/health-checks")
async def list_project_health_checks(pid: str):
    try:
        rows = await fetchall(
            """SELECT * FROM project_health_checks
               WHERE project_id=%s
               ORDER BY chapter_num ASC, updated_at DESC""",
            (pid,),
        )
    except Exception as error:
        if _is_missing_project_state_table_error(error):
            return []
        raise
    return convert_rows(rows)


@router.put("/projects/{pid}/health-checks/{chapter_num}")
async def save_project_health_check(pid: str, chapter_num: int, data: ProjectHealthCheckSave):
    now = int(time.time() * 1000)
    status = _normalize_status(
        data.commitStatus or ("blocked" if data.blocked else "ready"),
        HEALTH_STATUSES,
        "dry_run",
    )
    provenance = normalize_state_provenance(
        data,
        {
            "sourceChapterNum": data.sourceChapterNum or chapter_num,
            "sourceVersionId": data.sourceVersionId,
            "runId": data.runId or f"health-{pid}-{chapter_num}",
            "finalizationId": data.finalizationId,
            "commitStatus": status,
        },
    )
    run_id = provenance.get("runId") or f"health-{pid}-{chapter_num}"
    health_id = _stable_health_id(pid, chapter_num, run_id)
    try:
        await execute(
            """INSERT INTO project_health_checks
               (id, project_id, chapter_num, source_chapter_num, source_version_id,
                run_id, finalization_id, commit_status, blocked, blocking_count,
                warning_count, result_json, issue_summary, provenance, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE
                 source_chapter_num=VALUES(source_chapter_num),
                 source_version_id=VALUES(source_version_id),
                 run_id=VALUES(run_id),
                 finalization_id=VALUES(finalization_id),
                 commit_status=VALUES(commit_status),
                 blocked=VALUES(blocked),
                 blocking_count=VALUES(blocking_count),
                 warning_count=VALUES(warning_count),
                 result_json=VALUES(result_json),
                 issue_summary=VALUES(issue_summary),
                 provenance=VALUES(provenance),
                 updated_at=VALUES(updated_at)""",
            (
                health_id,
                pid,
                chapter_num,
                provenance.get("sourceChapterNum") or chapter_num,
                provenance.get("sourceVersionId") or "",
                run_id,
                provenance.get("finalizationId") or "",
                status,
                1 if data.blocked else 0,
                int(data.blockingCount or 0),
                int(data.warningCount or 0),
                json.dumps(data.result or {}, ensure_ascii=False),
                json.dumps(data.issueSummary or [], ensure_ascii=False),
                json.dumps(provenance, ensure_ascii=False),
                now,
                now,
            ),
        )
        row = await fetchone("SELECT * FROM project_health_checks WHERE id=%s", (health_id,))
    except Exception as error:
        if _is_missing_project_state_table_error(error):
            return _migration_unavailable_response(
                "project_health_checks",
                pid,
                chapter_num,
                status,
                provenance,
                "project health-check persistence unavailable before migration",
            )
        raise
    return convert_row(row)


def _normalize_status(value: str, allowed: set[str], default: str) -> str:
    status = str(value or default).strip().lower()
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported commitStatus: {status}")
    return status


def _stable_marker_id(project_id: str, chapter_num: int, provenance: dict) -> str:
    finalization_id = provenance.get("finalizationId") or "no-finalization"
    run_id = provenance.get("runId") or "no-run"
    return f"{project_id}_{chapter_num}_{run_id}_{finalization_id}"[:160]


def _stable_health_id(project_id: str, chapter_num: int, run_id: str) -> str:
    return f"{project_id}_{chapter_num}_{run_id}"[:160]


def _is_missing_project_state_table_error(error):
    message = str(error).lower()
    return (
        ("finalization_markers" in message or "project_health_checks" in message)
        and (
            "doesn't exist" in message
            or "does not exist" in message
            or "unknown table" in message
            or "no such table" in message
            or "undefinedtable" in message
        )
    )


def _migration_unavailable_response(
    table_name: str,
    project_id: str,
    chapter_num: int,
    commit_status: str,
    provenance: dict,
    reason: str,
):
    return {
        "id": f"migration_unavailable_{project_id}_{chapter_num}_{table_name}"[:160],
        "projectId": project_id,
        "chapterNum": chapter_num,
        "sourceChapterNum": provenance.get("sourceChapterNum") or chapter_num,
        "sourceVersionId": provenance.get("sourceVersionId") or "",
        "runId": provenance.get("runId") or "",
        "finalizationId": provenance.get("finalizationId") or "",
        "commitStatus": commit_status,
        "reason": reason or f"{table_name} table unavailable before approved migration",
        "migrationUnavailable": True,
        "tableName": table_name,
        "provenance": provenance,
    }
