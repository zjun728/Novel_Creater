"""Build one owned, provider-free finalized-download fixture through services."""
from __future__ import annotations

import argparse
import asyncio
import os
from types import SimpleNamespace

from backend.database import close_pool, connection
from backend.domain.finalization import FinalizationChangeSet
from backend.repositories.chapter_outlines import ChapterOutlineRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.routers import finalization
from backend.scripts.prepare_phase4b2_browser_db import PROJECT, assert_database_name
from backend.services.chapter_outlines import (
    ChapterOutlineService, ConfirmChapterOutlineDraft, CreateChapterOutlineDraft,
    SaveChapterOutlineDraft,
)
from backend.services.chapter_sessions import (
    ChapterSessionService, CreateChapterSession, SaveDraftCandidate, SaveWorkingDraft,
)
from backend.services.finalization import ConfirmFinalization, PrepareFinalization
from backend.services.finalization_commit import CommitFinalization
from backend.tests.integration.test_authoritative_chapter_session import (
    _confirmed_outline, _create_command,
)
from backend.tests.integration.test_chapter_outline_lifecycle import _editable_outline
from backend.tests.support.disposable_mysql import transaction_factory_for

FINAL_ONE = "PHASE6A_FINAL_CHAPTER_ONE"
FINAL_TWO = "PHASE6A_FINAL_CHAPTER_TWO"
WORKING_SENTINEL = "PHASE6A_WORKING_SENTINEL"
CANDIDATE_SENTINEL = "PHASE6A_CANDIDATE_SENTINEL"


class _Quality:
    async def audit(self, **_kwargs):
        return ()


class _Extraction:
    async def extract(self, *, manifest, **_kwargs):
        number = manifest.chapter_number
        return FinalizationChangeSet.model_validate({
            "schemaVersion": "finalization-changeset-v1",
            "title": f"第{number}章 定稿",
            "summary": f"第{number}章已定稿。",
            "existingEntityIds": [], "entities": [], "aliases": [], "canonEvents": [],
            "storyProgressEvents": [], "planningPatches": [], "planningSuggestions": [],
        })


def _config(database: str) -> dict[str, object]:
    return {"host": os.environ["MYSQL_HOST"], "port": int(os.environ["MYSQL_PORT"]), "user": os.environ["MYSQL_USER"], "password": os.environ["MYSQL_PASSWORD"], "db": database, "charset": "utf8mb4", "autocommit": True}


async def _finalize(service, workspace, outline, prose: str, candidate_key: str, hash_key: str, expected_canon_revision: int) -> None:
    saved = await service.save_working_draft(SaveWorkingDraft(
        PROJECT, workspace.session.id, workspace.working_draft.revision,
        workspace.working_draft.content_hash, prose,
    ))
    candidate = await service.save_candidate(SaveDraftCandidate(
        PROJECT, workspace.session.id, saved.working_draft.revision,
        saved.working_draft.content_hash, candidate_key,
    ))
    prepared = await finalization._service.prepare(PrepareFinalization(
        PROJECT, workspace.session.id, candidate.saved_candidate_id,
        saved.working_draft.content_hash, expected_canon_revision, workspace.session.planning_hash,
        outline.content_hash, hash_key,
    ))
    if (
        prepared.status != "awaiting_author"
        or not isinstance(prepared.current_revision, int)
        or not isinstance(prepared.current_revision_hash, str)
    ):
        raise RuntimeError(
            "Phase6A finalization preparation did not become reviewable: "
            f"status={prepared.status}, hard_blocks={len(prepared.hard_blocks)}"
        )
    confirmed = await finalization._service.confirm(ConfirmFinalization(
        PROJECT, workspace.session.id, prepared.current_revision,
        prepared.current_revision_hash,
    ))
    await finalization._atomic_service.commit(CommitFinalization(
        PROJECT, workspace.session.id, hash_key[::-1],
        confirmed.current_revision, confirmed.current_revision_hash,
    ))


async def prepare(database_name: str) -> None:
    database_name = assert_database_name(database_name)
    if os.environ.get("MYSQL_DB") != database_name:
        raise RuntimeError("Phase6A fixture database authority mismatch")
    config = _config(database_name)
    finalization._service.quality_provider = _Quality()
    finalization._service.extraction_provider = _Extraction()
    async with connection() as session:
        if await session.fetchone("SELECT DATABASE() AS database_name") != {"database_name": database_name}:
            raise RuntimeError("Phase6A fixture selected a non-owned database")
        fixture = SimpleNamespace(session=session, database_name=database_name, connection_config=config)
        _, planning, outline_one = await _confirmed_outline(fixture)
        sessions = ChapterSessionService(ChapterSessionRepository(), transaction_factory=transaction_factory_for(config))
        first = await sessions.create_session(_create_command(planning, outline_one, 1))
    await _finalize(sessions, first, outline_one, FINAL_ONE, "11111111-1111-4111-8111-111111111111", "1" * 64, 0)
    outlines = ChapterOutlineService(ChapterOutlineRepository(), ChapterSessionRepository(), transaction_factory=transaction_factory_for(config))
    draft = await outlines.create_draft(CreateChapterOutlineDraft(PROJECT, 2))
    saved_outline = await outlines.save_draft(SaveChapterOutlineDraft(PROJECT, 2, draft.draft_id, draft.draft_revision, draft.content_hash, _editable_outline(planning.content)))
    outline_two = await outlines.confirm_draft(ConfirmChapterOutlineDraft(PROJECT, 2, saved_outline.draft_id, saved_outline.draft_revision, saved_outline.content_hash, 0, "phase6a-outline-two"))
    second = await sessions.create_session(CreateChapterSession(
        PROJECT, 2, planning.revision, planning.content_hash,
        outline_two.revision, outline_two.content_hash, 1,
    ))
    await _finalize(sessions, second, outline_two, FINAL_TWO, "22222222-2222-4222-8222-222222222222", "2" * 64, 1)
    # A real third drafting session retains non-final content.  It is deliberately
    # never finalized, so the download reader must exclude both sentinels.
    third_draft = await outlines.create_draft(CreateChapterOutlineDraft(PROJECT, 3))
    third_saved = await outlines.save_draft(SaveChapterOutlineDraft(
        PROJECT, 3, third_draft.draft_id, third_draft.draft_revision,
        third_draft.content_hash, _editable_outline(planning.content),
    ))
    outline_three = await outlines.confirm_draft(ConfirmChapterOutlineDraft(
        PROJECT, 3, third_saved.draft_id, third_saved.draft_revision,
        third_saved.content_hash, 0, "phase6a-outline-three",
    ))
    third = await sessions.create_session(CreateChapterSession(
        PROJECT, 3, planning.revision, planning.content_hash,
        outline_three.revision, outline_three.content_hash, 2,
    ))
    third_saved_candidate = await sessions.save_working_draft(SaveWorkingDraft(
        PROJECT, third.session.id, third.working_draft.revision,
        third.working_draft.content_hash, CANDIDATE_SENTINEL,
    ))
    await sessions.save_candidate(SaveDraftCandidate(
        PROJECT, third.session.id, third_saved_candidate.working_draft.revision,
        third_saved_candidate.working_draft.content_hash,
        "33333333-3333-4333-8333-333333333333",
    ))
    await sessions.save_working_draft(SaveWorkingDraft(
        PROJECT, third.session.id, third_saved_candidate.working_draft.revision,
        third_saved_candidate.working_draft.content_hash, WORKING_SENTINEL,
    ))


async def verify_postconditions(database_name: str) -> None:
    database_name = assert_database_name(database_name)
    if os.environ.get("MYSQL_DB") != database_name:
        raise RuntimeError("Phase6A verifier database authority mismatch")
    async with connection() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        finals = await session.fetchall(
            "SELECT chapter_num,content FROM final_chapters WHERE project_id=%s ORDER BY chapter_num",
            (PROJECT,),
        )
        sentinels = await session.fetchone(
            """SELECT
                    SUM(content IN (%s,%s)) AS working_count
                 FROM working_drafts WHERE project_id=%s""",
            (WORKING_SENTINEL, "PHASE6A_UNSAVED_SENTINEL", PROJECT),
        )
        candidates = await session.fetchone(
            "SELECT SUM(content=%s) AS candidate_count FROM draft_candidates WHERE project_id=%s",
            (CANDIDATE_SENTINEL, PROJECT),
        )
    if selected != {"database_name": database_name}:
        raise RuntimeError("Phase6A verifier selected a non-owned database")
    if finals != [
        {"chapter_num": 1, "content": FINAL_ONE},
        {"chapter_num": 2, "content": FINAL_TWO},
    ]:
        raise RuntimeError("Phase6A final chapters are not the owned two-chapter authority")
    if int(sentinels.get("working_count") or 0) != 1 or int(candidates.get("candidate_count") or 0) != 1:
        raise RuntimeError(
            "Phase6A non-final sentinel authority is invalid: "
            f"working={sentinels}, candidate={candidates}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--database", required=True); parser.add_argument("--verify-postconditions", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify_postconditions:
            await verify_postconditions(args.database)
        else:
            await prepare(args.database)
    finally: await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
