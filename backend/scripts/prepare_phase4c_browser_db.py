"""Prepare and verify the disposable Phase 4C browser fixture."""

from __future__ import annotations

import argparse
import asyncio
import os
from types import SimpleNamespace

from backend.database import close_pool, connection
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.scripts.prepare_phase4b2_browser_db import (
    PROJECT,
    assert_database_name,
)
from backend.services.chapter_sessions import ChapterSessionService
from backend.tests.integration.test_authoritative_chapter_session import (
    _confirmed_outline,
    _create_command,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


def _configuration(database_name: str) -> dict[str, object]:
    required = ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD")
    if any(not os.environ.get(name) for name in required):
        raise RuntimeError("Phase4C fixture requires explicit disposable MySQL authority")
    return {
        "host": os.environ["MYSQL_HOST"],
        "port": int(os.environ["MYSQL_PORT"]),
        "user": os.environ["MYSQL_USER"],
        "password": os.environ["MYSQL_PASSWORD"],
        "db": database_name,
        "charset": "utf8mb4",
        "autocommit": True,
    }


async def prepare_canonical_workspace(database_name: str) -> None:
    """Create the real confirmed-outline-to-working-draft chain without Provider setup."""
    database_name = assert_database_name(database_name)
    if os.environ.get("MYSQL_DB") != database_name:
        raise RuntimeError("Phase4C fixture database authority mismatch")
    config = _configuration(database_name)
    async with connection() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        if selected != {"database_name": database_name}:
            raise RuntimeError("Phase4C fixture selected a non-owned database")
        fixture = SimpleNamespace(
            session=session,
            database_name=database_name,
            connection_config=config,
        )
        _, planning, outline = await _confirmed_outline(fixture)
        service = ChapterSessionService(
            ChapterSessionRepository(),
            transaction_factory=transaction_factory_for(config),
        )
        workspace = await service.create_session(_create_command(planning, outline))
        if workspace.session.project_id != PROJECT:
            raise RuntimeError("Phase4C fixture project authority mismatch")


async def verify_postconditions(database_name: str) -> None:
    database_name = assert_database_name(database_name)
    if os.environ.get("MYSQL_DB") != database_name:
        raise RuntimeError("Phase4C verifier database authority mismatch")
    async with connection() as session:
        await session.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        await session.execute("START TRANSACTION READ ONLY, WITH CONSISTENT SNAPSHOT")
        try:
            selected = await session.fetchone("SELECT DATABASE() AS database_name")
            chapter = await session.fetchone(
                """SELECT id,active_draft_operation_id
                     FROM chapter_sessions
                    WHERE project_id=%s AND chapter_num=1""",
                (PROJECT,),
            )
            session_id = chapter["id"] if chapter else None
            candidates = await session.fetchall(
                """SELECT id,working_draft_revision,content_hash
                     FROM draft_candidates
                    WHERE project_id=%s AND chapter_session_id=%s
                    ORDER BY created_at,id""",
                (PROJECT, session_id),
            )
            attempts = await session.fetchone(
                """SELECT COUNT(*) AS total FROM draft_operation_attempts
                    WHERE project_id=%s AND chapter_session_id=%s""",
                (PROJECT, session_id),
            )
            draft = await session.fetchone(
                """SELECT revision,content_hash FROM working_drafts
                    WHERE project_id=%s AND chapter_session_id=%s""",
                (PROJECT, session_id),
            )
            recovery = await session.fetchall(
                """SELECT working_draft_revision,snapshot_role,replacement_reason,
                          source_operation_id,source_candidate_id,content_hash
                     FROM working_draft_revisions
                    WHERE project_id=%s AND chapter_session_id=%s
                    ORDER BY working_draft_revision,snapshot_role""",
                (PROJECT, session_id),
            )
        finally:
            await session.raw.rollback()

    if (
        selected != {"database_name": database_name}
        or not chapter
        or chapter.get("active_draft_operation_id") is not None
        or attempts != {"total": 0}
        or not draft
        or len(candidates) != 2
    ):
        raise RuntimeError("Phase4C canonical postcondition is invalid")
    if [row.get("working_draft_revision") for row in candidates] != [2, 3]:
        raise RuntimeError("Phase4C candidate revision chain is invalid")
    if len({row.get("content_hash") for row in candidates}) != 2:
        raise RuntimeError("Phase4C immutable candidate identities are invalid")
    if draft != {"revision": 4, "content_hash": candidates[0]["content_hash"]}:
        raise RuntimeError("Phase4C loaded draft is not the first candidate")
    if (
        len(recovery) != 2
        or [row.get("working_draft_revision") for row in recovery] != [3, 4]
        or [row.get("snapshot_role") for row in recovery] != ["before", "after"]
        or {row.get("replacement_reason") for row in recovery} != {"candidate_load"}
        or {row.get("source_operation_id") for row in recovery} != {None}
        or {row.get("source_candidate_id") for row in recovery} != {candidates[0]["id"]}
        or recovery[1].get("content_hash") != candidates[0].get("content_hash")
    ):
        raise RuntimeError("Phase4C append-only candidate-load evidence is invalid")


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
