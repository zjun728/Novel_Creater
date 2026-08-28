"""Build deterministic Phase 8A manuscript browser fixtures in one owned schema."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import os
import re
import time

from backend.database import close_pool, connection, transaction
from backend.config import (
    clear_runtime_configuration,
    install_runtime_configuration,
    load_runtime_configuration,
)
from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.domain.finalization import FinalizationChangeSet
from backend.repositories.canon import CanonRepository
from backend.repositories.chapter_outlines import ChapterOutlineRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.finalization import FinalizationRepository
from backend.repositories.planning import PlanningRepository
from backend.scripts import prepare_phase6a_browser_db as base
from backend.services.canon import CanonService
from backend.services.chapter_outlines import (
    ChapterOutlineService,
    ConfirmChapterOutlineDraft,
    CreateChapterOutlineDraft,
    SaveChapterOutlineDraft,
)
from backend.services.chapter_sessions import (
    ChapterSessionService,
    CreateChapterSession,
    SaveDraftCandidate,
    SaveWorkingDraft,
)
from backend.services.finalization import (
    ConfirmFinalization,
    FinalizationService,
    PrepareFinalization,
)
from backend.services.finalization_commit import AtomicFinalizationService, CommitFinalization
from backend.services.planning import PlanningService


PROJECTS = {
    "complete": "8a000000-0000-4000-8000-000000000001",
    "awaiting-author": "8a000000-0000-4000-8000-000000000002",
    "corrupt": "8a000000-0000-4000-8000-000000000003",
}
PROJECT_TITLES = {
    "complete": "织机赌局 · 完整稿件",
    "awaiting-author": "织机赌局 · 待作者确认",
    "corrupt": "织机赌局 · 完整性演练",
}
CHAPTER_TITLES = ("泔水醒来，三日织机赌局", "废料改机", "复验定局")
FINAL_PROSE = (
    "泔水桶的酸气先醒了过来。林砚睁眼时，三日后的织机赌局已经写在墙上。",
    "他把废铜齿轮磨薄半分，让报废的织机重新咬住经线。众人第一次听见机器平稳的回声。",
    "复验钟响过三遍，新织机没有断线。林砚交出账册，赌局至此有了无可争辩的定局。",
    "第四章只用于待作者确认的可见审查，不得触发任何 Provider。",
)
WORKING_SENTINEL = "PHASE8A_WORKING_SENTINEL_MUST_NOT_DOWNLOAD"
CANDIDATE_SENTINEL = "PHASE8A_CANDIDATE_SENTINEL_MUST_NOT_DOWNLOAD"
_DISPOSABLE = re.compile(r"novel_creator_test_[a-f0-9]{32}\Z")


@dataclass(frozen=True)
class OutlineTemplate:
    chapter_goal: str
    expected_characters: tuple[str, ...]
    continuation: tuple[str, ...]
    planned_tasks: tuple[str, ...]
    scenes: tuple[str, ...]
    forbidden_early_events: tuple[str, ...]


PINNED_OUTLINES = (
    OutlineTemplate("在三日织机赌局中取得一次可验证的喘息", ("林砚", "阿绫"), ("承接泔水桶醒来",), ("确认赌局期限",), ("染坊后院醒来", "账房立赌约"), ("不可提前赢下终局",)),
    OutlineTemplate("用废料完成不依赖新零件的织机改造", ("林砚", "阿绫", "周掌柜"), ("承接三日赌约",), ("拆检废机", "完成试织"), ("废料棚选件", "夜间改机"), ("不可跳过失败试织",)),
    OutlineTemplate("让公开复验形成不可抵赖的结果", ("林砚", "周掌柜"), ("承接废料改机",), ("完成三轮复验", "公开账册"), ("工坊复验", "众人见证"), ("不可引入外力代胜",)),
    OutlineTemplate("追查赌局背后的旧织机账目", ("林砚", "阿绫"), ("承接复验定局",), ("核对旧账",), ("库房查账",), ("不可提前揭示幕后主使",)),
)


class ProviderMustNotRun:
    async def __call__(self, *_args, **_kwargs):
        raise RuntimeError("Phase8A Provider invocation is forbidden")


class _Quality:
    async def audit(self, **_kwargs):
        return ()


class _Extraction:
    def __init__(self, title: str):
        self.title = title

    async def extract(self, *, manifest, **_kwargs):
        return FinalizationChangeSet.model_validate({
            "schemaVersion": "finalization-changeset-v1",
            "title": self.title,
            "summary": f"第{manifest.chapter_number}章已定稿。",
            "existingEntityIds": [], "entities": [], "aliases": [],
            "canonEvents": [], "storyProgressEvents": [],
            "planningPatches": [], "planningSuggestions": [],
        })


def assert_database_name(value: str) -> str:
    if not isinstance(value, str) or _DISPOSABLE.fullmatch(value) is None:
        raise RuntimeError("Phase8A fixture requires a disposable database")
    return value


def fixture_signature() -> dict[str, object]:
    return {"projectIds": list(PROJECTS.values()), "finalCounts": [3, 3, 3]}


def postcondition_signature() -> dict[str, object]:
    return {
        "projectIds": list(PROJECTS.values()),
        "finalCounts": [3, 4, 3],
        "lifecycles": ["archived", "active", "active"],
    }


async def assert_owned_database(database_name: str) -> None:
    database_name = assert_database_name(database_name)
    if os.environ.get("MYSQL_DB") != database_name:
        raise RuntimeError("Phase8A fixture database authority mismatch")
    async with connection() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
    if selected != {"database_name": database_name}:
        raise RuntimeError("Phase8A fixture selected a non-owned database")


async def read_fixture_signature() -> dict[str, object] | None:
    async with connection() as session:
        rows = await session.fetchall(
            "SELECT id FROM projects WHERE id IN (%s,%s,%s) ORDER BY id",
            tuple(PROJECTS.values()),
        )
        total = await session.fetchone("SELECT COUNT(*) AS count FROM projects")
        if int(total["count"] or 0) == 0:
            return None
        counts = []
        for project_id in PROJECTS.values():
            row = await session.fetchone(
                "SELECT COUNT(*) AS count FROM final_chapters WHERE project_id=%s",
                (project_id,),
            )
            counts.append(int(row["count"] or 0))
    return {"projectIds": [row["id"] for row in rows], "finalCounts": counts}


async def read_postcondition_signature() -> dict[str, object] | None:
    observed = await read_fixture_signature()
    if observed is None:
        return None
    lifecycles = []
    async with connection() as session:
        for project_id in PROJECTS.values():
            row = await session.fetchone(
                "SELECT archived_at FROM projects WHERE id=%s", (project_id,),
            )
            lifecycles.append("archived" if row and row["archived_at"] is not None else "active")
    return {**observed, "lifecycles": lifecycles}


def _outline(planning, template: OutlineTemplate) -> EditableChapterOutlineContent:
    volume, block = planning.volumes[0], planning.story_blocks[0]
    stage, task = block.stages[0], block.stages[0].scene_tasks[0]
    ref = lambda item: {"id": item.id, "revision": item.revision, "contentHash": item.content_hash}
    return EditableChapterOutlineContent.model_validate({
        "schemaVersion": "chapter-outline-draft-v1", "volumeRef": ref(volume),
        "storyBlockRef": ref(block), "stageRefs": (ref(stage),), "sceneTaskRefs": (ref(task),),
        "chapterGoal": template.chapter_goal,
        "expectedCharacters": template.expected_characters,
        "continuation": template.continuation,
        "plannedTasks": template.planned_tasks,
        "scenes": template.scenes,
        "forbiddenEarlyEvents": template.forbidden_early_events,
    })


def _services(title: str):
    sessions = ChapterSessionService(
        ChapterSessionRepository(), transaction_factory=transaction, connection_factory=connection,
    )
    finalization = FinalizationService(
        transaction_factory=transaction, repository=FinalizationRepository(),
        quality_provider=_Quality(), extraction_provider=_Extraction(title),
        clock=lambda: int(time.time() * 1000),
    )
    atomic = AtomicFinalizationService(
        transaction_factory=transaction, repository=FinalizationRepository(),
        planning_repository=PlanningRepository(),
        canon_committer=CanonService(CanonRepository(), transaction_factory=transaction),
        clock=lambda: int(time.time() * 1000),
    )
    return sessions, finalization, atomic


async def _finalize_third(project_id: str) -> None:
    sessions, finalization, atomic = _services(CHAPTER_TITLES[2])
    workspace = await sessions.get(project_id, 3)
    if workspace is None:
        raise RuntimeError("Phase8A chapter three workspace is missing")
    saved = await sessions.save_working_draft(SaveWorkingDraft(
        project_id, workspace.session.id, workspace.working_draft.revision,
        workspace.working_draft.content_hash, FINAL_PROSE[2],
    ))
    candidate = await sessions.save_candidate(SaveDraftCandidate(
        project_id, workspace.session.id, saved.working_draft.revision,
        saved.working_draft.content_hash,
        f"8a000000-0000-4000-8000-{project_id[-12:-1]}3",
    ))
    prepared = await finalization.prepare(PrepareFinalization(
        project_id, workspace.session.id, candidate.saved_candidate_id,
        saved.working_draft.content_hash, workspace.session.expected_canon_revision,
        workspace.session.planning_hash, workspace.session.chapter_outline_hash,
        (project_id[-1] * 64),
    ))
    confirmed = await finalization.confirm(ConfirmFinalization(
        project_id, workspace.session.id, prepared.current_revision, prepared.current_revision_hash,
    ))
    await atomic.commit(CommitFinalization(
        project_id, workspace.session.id, ((project_id[-1] + "f") * 32),
        confirmed.current_revision, confirmed.current_revision_hash,
    ))


async def _planning(project_id: str):
    repository = PlanningRepository()
    async with transaction() as session:
        head = await repository.lock_planning_head(session, project_id)
    if head is None:
        raise RuntimeError("Phase8A planning authority is missing")
    content = PlanningService(repository, transaction_factory=transaction)._planning_from_json(head["content_json"])
    return int(head["revision"]), str(head["content_hash"]), content


async def _create_fourth(project_id: str, *, awaiting_author: bool) -> None:
    planning_revision, planning_hash, planning = await _planning(project_id)
    outlines = ChapterOutlineService(
        ChapterOutlineRepository(), ChapterSessionRepository(),
        transaction_factory=transaction, planning_repository=PlanningRepository(),
    )
    draft = await outlines.create_draft(CreateChapterOutlineDraft(project_id, 4))
    saved = await outlines.save_draft(SaveChapterOutlineDraft(
        project_id, 4, draft.draft_id, draft.draft_revision, draft.content_hash,
        _outline(planning, PINNED_OUTLINES[3]),
    ))
    outline = await outlines.confirm_draft(ConfirmChapterOutlineDraft(
        project_id, 4, saved.draft_id, saved.draft_revision, saved.content_hash, 0,
        f"phase8a-outline-4-{project_id[-1]}",
    ))
    if not awaiting_author:
        return
    sessions, finalization, _atomic = _services("旧账浮出水面")
    workspace = await sessions.create_session(CreateChapterSession(
        project_id, 4, planning_revision, planning_hash,
        outline.revision, outline.content_hash, 3,
    ))
    saved_working = await sessions.save_working_draft(SaveWorkingDraft(
        project_id, workspace.session.id, workspace.working_draft.revision,
        workspace.working_draft.content_hash, FINAL_PROSE[3],
    ))
    candidate = await sessions.save_candidate(SaveDraftCandidate(
        project_id, workspace.session.id, saved_working.working_draft.revision,
        saved_working.working_draft.content_hash,
        "8a000000-0000-4000-8000-000000000024",
    ))
    prepared = await finalization.prepare(PrepareFinalization(
        project_id, workspace.session.id, candidate.saved_candidate_id,
        saved_working.working_draft.content_hash, 3, planning_hash, outline.content_hash,
        "a" * 64,
    ))
    if prepared.status != "awaiting_author":
        raise RuntimeError("Phase8A chapter four review is not awaiting_author")


async def _seed_project(kind: str, project_id: str) -> None:
    original_project = base.PROJECT
    original_final_one, original_final_two = base.FINAL_ONE, base.FINAL_TWO
    original_outline, original_extraction = base._outline_payload, base._Extraction
    outline_index = 0

    def next_outline(planning):
        nonlocal outline_index
        value = _outline(planning, PINNED_OUTLINES[outline_index])
        outline_index += 1
        return value

    class ExactExtraction:
        async def extract(self, *, manifest, **kwargs):
            return await _Extraction(CHAPTER_TITLES[manifest.chapter_number - 1]).extract(
                manifest=manifest, **kwargs,
            )

    try:
        base.PROJECT = project_id
        base.FINAL_ONE, base.FINAL_TWO = FINAL_PROSE[:2]
        base._outline_payload = next_outline
        base._Extraction = ExactExtraction
        await base.prepare(os.environ["MYSQL_DB"])
    finally:
        base.PROJECT = original_project
        base.FINAL_ONE, base.FINAL_TWO = original_final_one, original_final_two
        base._outline_payload, base._Extraction = original_outline, original_extraction
    async with connection() as session:
        await session.execute(
            "UPDATE projects SET title=%s WHERE id=%s",
            (PROJECT_TITLES[kind], project_id),
        )
    await _finalize_third(project_id)
    await _create_fourth(project_id, awaiting_author=kind == "awaiting-author")
    if kind == "corrupt":
        async with connection() as session:
            await session.execute(
                "UPDATE final_chapters SET content=CONCAT(content,%s) WHERE project_id=%s AND chapter_num=3",
                (" CORRUPT_BODY_MUST_NEVER_ESCAPE", project_id),
            )


async def seed_fixture() -> None:
    for kind, project_id in PROJECTS.items():
        await _seed_project(kind, project_id)


async def prepare(database_name: str) -> None:
    await assert_owned_database(database_name)
    observed = await read_fixture_signature()
    expected = fixture_signature()
    if observed == expected:
        return
    if observed is not None:
        raise RuntimeError("Phase8A fixture schema must be empty or exact")
    await seed_fixture()
    if await read_fixture_signature() != expected:
        raise RuntimeError("Phase8A fixture postcondition failed")


async def verify_postconditions(database_name: str) -> None:
    await assert_owned_database(database_name)
    if await read_postcondition_signature() != postcondition_signature():
        raise RuntimeError("Phase8A fixture authority changed")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--verify-postconditions", action="store_true")
    args = parser.parse_args()
    snapshot = load_runtime_configuration()
    install_runtime_configuration(snapshot)
    try:
        await (verify_postconditions(args.database) if args.verify_postconditions else prepare(args.database))
    finally:
        try:
            await close_pool()
        finally:
            clear_runtime_configuration(snapshot)


if __name__ == "__main__":
    asyncio.run(main())
