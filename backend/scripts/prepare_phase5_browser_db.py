"""Prepare and verify the disposable Phase 5 browser fixture."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from backend.database import close_pool, connection
from backend.scripts.prepare_phase4b2_browser_db import PROJECT, assert_database_name
from backend.scripts.prepare_phase4c_browser_db import prepare_canonical_workspace


def _assert_authority(database_name: str, label: str) -> str:
    database_name = assert_database_name(database_name)
    if not database_name.startswith("novel_creator_test_"):
        raise RuntimeError(f"Phase5 {label} requires a disposable database")
    if os.environ.get("MYSQL_DB") != database_name:
        raise RuntimeError(f"Phase5 {label} database authority mismatch")
    return database_name


async def prepare(database_name: str) -> None:
    database_name = _assert_authority(database_name, "fixture")
    await prepare_canonical_workspace(database_name)
    async with connection() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        if selected != {"database_name": database_name}:
            raise RuntimeError("Phase5 fixture selected a non-owned database")
        await session.execute(
            "UPDATE provider_profiles SET api_key=%s WHERE id IS NOT NULL",
            (os.environ["BROWSER_SECRET_SENTINEL"],),
        )


async def verify_postconditions(database_name: str) -> None:
    database_name = _assert_authority(database_name, "verifier")
    async with connection() as session:
        await session.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        await session.execute("START TRANSACTION READ ONLY, WITH CONSISTENT SNAPSHOT")
        try:
            selected = await session.fetchone("SELECT DATABASE() AS database_name")
            final = await session.fetchone(
                """SELECT chapter.title,chapter.content_hash,chapter.canon_revision,
                          chapter.planning_revision,chapter.draft_candidate_id,
                          candidate.content_hash AS candidate_hash,session.status,
                          session.finalized_at,session.active_draft_operation_id,
                          attempt.status AS attempt_status,attempt.active_slot,
                          attempt.current_revision,attempt.current_revision_hash,
                          attempt.confirmed_revision,attempt.confirmed_revision_hash,
                          record.change_set_revision,record.committed_canon_revision,
                          head.canon_revision_number,head.projection_revision_number
                     FROM final_chapters chapter
                     JOIN draft_candidates candidate ON candidate.id=chapter.draft_candidate_id
                     JOIN chapter_sessions session ON session.id=chapter.chapter_session_id
                     JOIN finalization_records record ON record.id=chapter.finalization_record_id
                     JOIN finalization_change_sets attempt ON attempt.id=record.change_set_id
                     JOIN projection_heads head ON head.project_id=chapter.project_id
                    WHERE chapter.project_id=%s AND chapter.chapter_num=1
                      AND session.status='final'""",
                (PROJECT,),
            )
            counts = {}
            for table in (
                "draft_candidates", "candidate_quality_reports",
                "finalization_change_sets", "finalization_records",
                "final_chapters",
            ):
                counts[table] = (await session.fetchone(
                    f"SELECT COUNT(*) AS total FROM {table} WHERE project_id=%s",
                    (PROJECT,),
                ))["total"]
            revisions = await session.fetchall(
                """SELECT revision,source FROM finalization_change_set_revisions
                    WHERE project_id=%s ORDER BY revision""",
                (PROJECT,),
            )
            quality = await session.fetchone(
                """SELECT status,JSON_LENGTH(findings_json) AS finding_count
                     FROM candidate_quality_reports WHERE project_id=%s""",
                (PROJECT,),
            )
            canon_revision = await session.fetchone(
                """SELECT revision_number,parent_revision_number,source_type
                     FROM canon_revisions
                    WHERE project_id=%s AND revision_number=1""",
                (PROJECT,),
            )
            entity = await session.fetchone(
                """SELECT entity.canonical_name,alias.alias
                     FROM canon_entities entity
                     JOIN entity_aliases alias ON alias.entity_id=entity.id
                    WHERE entity.project_id=%s
                      AND entity.id='30000000-0000-4000-8000-000000000001'
                      AND alias.id='30000000-0000-4000-8000-000000000002'""",
                (PROJECT,),
            )
            canon_event = await session.fetchone(
                """SELECT revision_number,entity_id,fact_kind,field_path,
                          confirmation_status
                     FROM canon_events
                    WHERE project_id=%s
                      AND id='30000000-0000-4000-8000-000000000003'""",
                (PROJECT,),
            )
            progress = await session.fetchone(
                """SELECT field_path,payload_json FROM plot_thread_projections
                    WHERE project_id=%s AND field_path LIKE 'plot.progress.%%'""",
                (PROJECT,),
            )
            planning = await session.fetchone(
                """SELECT head.revision,revision.content_json
                     FROM project_planning_heads head
                     JOIN planning_revisions revision
                       ON revision.id=head.planning_revision_id
                    WHERE head.project_id=%s""",
                (PROJECT,),
            )
        finally:
            await session.raw.rollback()

    expected_counts = {
        "draft_candidates": 1, "candidate_quality_reports": 1,
        "finalization_change_sets": 1, "finalization_records": 1,
        "final_chapters": 1,
    }
    if selected != {"database_name": database_name} or counts != expected_counts:
        raise RuntimeError("Phase5 atomic record counts are invalid")
    if not final or not (
        final["title"] == "第一章：入城"
        and final["content_hash"] == final["candidate_hash"]
        and final["canon_revision"] == final["committed_canon_revision"] == 1
        and final["planning_revision"] == 1
        and final["status"] == "final"
        and final["finalized_at"] is not None
        and final["active_draft_operation_id"] is None
        and final["attempt_status"] == "committed"
        and final["active_slot"] is None
        and final["current_revision"] == final["confirmed_revision"] == 2
        and final["current_revision_hash"] == final["confirmed_revision_hash"]
        and final["change_set_revision"] == 2
        and final["canon_revision_number"] == final["projection_revision_number"] == 1
    ):
        raise RuntimeError("Phase5 atomic finalization state is invalid")
    if revisions != [
        {"revision": 1, "source": "extraction"},
        {"revision": 2, "source": "author_correction"},
    ]:
        raise RuntimeError("Phase5 author correction evidence is invalid")
    if quality != {"status": "completed", "finding_count": 1}:
        raise RuntimeError("Phase5 quality review evidence is invalid")
    if canon_revision != {
        "revision_number": 1,
        "parent_revision_number": 0,
        "source_type": "finalization",
    }:
        raise RuntimeError("Phase5 Canon revision is invalid")
    if entity != {"canonical_name": "守门人", "alias": "老卒"}:
        raise RuntimeError("Phase5 Canon entity projection is invalid")
    if canon_event != {
        "revision_number": 1,
        "entity_id": "30000000-0000-4000-8000-000000000001",
        "fact_kind": "dynamic_event",
        "field_path": "location",
        "confirmation_status": "confirmed",
    }:
        raise RuntimeError("Phase5 Canon event is invalid")
    progress_payload = json.loads(progress["payload_json"]) if progress else None
    if not progress or progress_payload.get("status") != "completed":
        raise RuntimeError("Phase5 story progress projection is invalid")
    planning_payload = json.loads(planning["content_json"]) if planning else None
    if (
        not planning or planning["revision"] != 2
        or planning_payload["plots"][0]["futureDirection"] != "追查城内接头人。"
    ):
        raise RuntimeError("Phase5 future planning projection is invalid")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--verify-postconditions", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify_postconditions:
            await verify_postconditions(args.database)
        else:
            await prepare(args.database)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
