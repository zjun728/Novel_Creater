"""Prepare and verify the disposable Phase 4B3 browser fixture."""

from __future__ import annotations

import argparse
import asyncio
import os

from backend.database import close_pool, connection
from backend.scripts.prepare_phase4b2_browser_db import (
    PROJECT,
    assert_database_name,
    prepare as prepare_canonical_workspace,
)


LOCAL_TYPES = (
    "rewrite_selection",
    "polish_selection",
    "expand_selection",
    "compress_selection",
)


async def verify_postconditions(database_name: str) -> None:
    database_name = assert_database_name(database_name)
    if os.environ.get("MYSQL_DB") != database_name:
        raise RuntimeError("Phase4B3 verifier database authority mismatch")
    async with connection() as session:
        await session.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        await session.execute("START TRANSACTION READ ONLY, WITH CONSISTENT SNAPSHOT")
        try:
            selected = await session.fetchone("SELECT DATABASE() AS database_name")
            if selected != {"database_name": database_name}:
                raise RuntimeError("Phase4B3 verifier selected a non-owned database")
            chapter = await session.fetchone(
                """SELECT id,active_draft_operation_id
                     FROM chapter_sessions
                    WHERE project_id=%s AND chapter_num=1""",
                (PROJECT,),
            )
            candidates = await session.fetchone(
                "SELECT COUNT(*) AS total FROM draft_candidates WHERE project_id=%s",
                (PROJECT,),
            )
            attempts = await session.fetchall(
                """SELECT id,operation_type,status,base_working_draft_revision,
                          result_working_draft_revision,result_content_hash
                     FROM draft_operation_attempts
                    WHERE project_id=%s AND chapter_session_id=%s
                    ORDER BY created_at,id""",
                (PROJECT, chapter["id"] if chapter else None),
            )
            draft = await session.fetchone(
                """SELECT revision,content_hash
                     FROM working_drafts
                    WHERE project_id=%s AND chapter_session_id=%s""",
                (PROJECT, chapter["id"] if chapter else None),
            )
            recovery = await session.fetchall(
                """SELECT working_draft_revision,snapshot_role,replacement_reason,
                          source_operation_id
                     FROM working_draft_revisions
                    WHERE project_id=%s AND chapter_session_id=%s""",
                (PROJECT, chapter["id"] if chapter else None),
            )
        finally:
            await session.raw.rollback()

    if (
        not chapter
        or chapter.get("active_draft_operation_id") is not None
        or candidates != {"total": 0}
        or len(attempts) != 4
        or not draft
    ):
        raise RuntimeError("Phase4B3 canonical postcondition is invalid")
    if [row.get("operation_type") for row in attempts] != list(LOCAL_TYPES):
        raise RuntimeError("Phase4B3 local operation order is invalid")
    if [row.get("status") for row in attempts] != [
        "completed", "completed", "cancelled", "completed",
    ]:
        raise RuntimeError("Phase4B3 local terminal statuses are invalid")
    if [row.get("base_working_draft_revision") for row in attempts] != [2, 3, 4, 4]:
        raise RuntimeError("Phase4B3 local revision chain is invalid")
    if [row.get("result_working_draft_revision") for row in attempts] != [3, 4, None, 5]:
        raise RuntimeError("Phase4B3 local result revisions are invalid")
    if (
        draft.get("revision") != 6
        or draft.get("content_hash") != attempts[1].get("result_content_hash")
    ):
        raise RuntimeError("Phase4B3 undo did not restore the prior authoritative prose")
    undo_rows = [row for row in recovery if row.get("replacement_reason") == "undo_local"]
    if (
        len(recovery) != 7
        or len(undo_rows) != 1
        or undo_rows[0].get("snapshot_role") != "before"
        or undo_rows[0].get("working_draft_revision") != 5
        or undo_rows[0].get("source_operation_id") != attempts[3].get("id")
    ):
        raise RuntimeError("Phase4B3 append-only undo evidence is invalid")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--verify-postconditions", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify_postconditions:
            await verify_postconditions(args.database)
        else:
            await prepare_canonical_workspace(args.database)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
