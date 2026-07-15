"""Connection-explicit SQL for the atomic draft-pair transaction."""

from __future__ import annotations

import json
from typing import Iterable

from aiomysql import DictCursor

from .draft_write_models import DraftCandidateWrite, DraftWriteResult


async def lock_project(conn, project_id: str):
    async with conn.cursor(DictCursor) as cursor:
        await cursor.execute(
            "SELECT id FROM projects WHERE id=%s FOR UPDATE",
            (project_id,),
        )
        return await cursor.fetchone()


async def insert_pending_batch(
    conn,
    *,
    batch_id: str,
    project_id: str,
    idempotency_key: str,
    manifest_sha256: str,
    created_at: int,
) -> None:
    async with conn.cursor() as cursor:
        await cursor.execute(
            """INSERT INTO draft_write_batches
               (id, project_id, idempotency_key, manifest_sha256,
                result_json, created_at, committed_at)
               VALUES (%s,%s,%s,%s,NULL,%s,NULL)""",
            (
                batch_id,
                project_id,
                idempotency_key.encode("ascii"),
                manifest_sha256,
                created_at,
            ),
        )


async def read_batch(conn, *, project_id: str, idempotency_key: str):
    """Perform a READ COMMITTED current read without a locking modifier."""

    async with conn.cursor(DictCursor) as cursor:
        await cursor.execute(
            """SELECT id, project_id, manifest_sha256, result_json, committed_at
               FROM draft_write_batches
               WHERE project_id=%s AND idempotency_key=%s
               LIMIT 1""",
            (project_id, idempotency_key.encode("ascii")),
        )
        return await cursor.fetchone()


async def lock_chapters(conn, chapter_ids: Iterable[str]):
    ordered_ids = tuple(sorted(chapter_ids))
    if len(ordered_ids) != 2:
        raise ValueError("exactly two chapter IDs are required")
    async with conn.cursor(DictCursor) as cursor:
        await cursor.execute(
            """SELECT id, project_id, chapter_num, status, final_version_id
               FROM chapters
               WHERE id IN (%s,%s)
               ORDER BY chapter_num ASC, id ASC FOR UPDATE""",
            ordered_ids,
        )
        return list(await cursor.fetchall())


async def lock_source_versions(conn, source_version_ids: Iterable[str]):
    ordered_ids = tuple(sorted(source_version_ids))
    if len(ordered_ids) != 2:
        raise ValueError("exactly two source version IDs are required")
    async with conn.cursor(DictCursor) as cursor:
        await cursor.execute(
            """SELECT id, project_id, chapter_id, content
               FROM chapter_versions
               WHERE id IN (%s,%s)
               ORDER BY id ASC FOR UPDATE""",
            ordered_ids,
        )
        return list(await cursor.fetchall())


async def insert_candidate_version(
    conn,
    *,
    candidate_version_id: str,
    project_id: str,
    batch_id: str,
    write: DraftCandidateWrite,
    timestamp_ms: int,
) -> None:
    prompt_brief = f"[control-plane:{batch_id}] {write.prompt_brief}"
    async with conn.cursor() as cursor:
        await cursor.execute(
            """INSERT INTO chapter_versions
               (id, project_id, chapter_id, chapter_num, title, content,
                version_type, source_model_id, prompt_brief, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                candidate_version_id,
                project_id,
                write.chapter_id,
                write.chapter_num,
                write.title,
                write.content,
                "qa_draft_candidate",
                None,
                prompt_brief,
                timestamp_ms,
                timestamp_ms,
            ),
        )


async def complete_batch(conn, *, batch_id: str, result: DraftWriteResult) -> None:
    result_json = json.dumps(
        result.to_wire(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    async with conn.cursor() as cursor:
        await cursor.execute(
            """UPDATE draft_write_batches
               SET result_json=%s, committed_at=%s
               WHERE id=%s""",
            (result_json, result.committed_at, batch_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("ledger completion did not update exactly one row")
