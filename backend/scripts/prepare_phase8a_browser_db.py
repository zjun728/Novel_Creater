"""Build deterministic Phase 8A manuscript browser fixtures in one owned schema."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from hashlib import sha256
import json
import os
import re
import time

from backend.database import close_pool, connection, transaction
from backend.config import (
    clear_runtime_configuration,
    install_runtime_configuration,
    load_runtime_configuration,
)
from backend.domain.chapter_outlines import (
    ChapterOutline,
    DraftChapterOutline,
    EditableChapterOutlineContent,
    OutlineCapacityPolicy,
    normalize_chapter_outline,
)
from backend.domain.finalization import FinalizationChangeSet
from backend.domain.json_contracts import canonical_hash
from backend.domain.planning import DraftPlanningAggregate, normalize_planning_aggregate
from backend.repositories.canon import CanonRepository
from backend.repositories.chapter_outlines import ChapterOutlineRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.finalization import FinalizationRepository
from backend.repositories.planning import PlanningRepository
from backend.schema_manifest import manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
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
from backend.services.projections import build_projection_bundle


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
_SAFE_TABLE = re.compile(r"[A-Za-z0-9_]+\Z")
_METADATA_TABLE = "phase8a_fixture_metadata"
_FIXTURE_KEY = "phase8a-manuscript-productization"
_FIXTURE_VERSION = "phase8a-v1"


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


def _planning_id(project_id: str, index: int) -> str:
    return f"8a2{project_id[-1]}0000-0000-4000-8000-{index:012d}"


def _planning_id_factory(project_id: str):
    index = 0

    def next_id() -> str:
        nonlocal index
        index += 1
        return _planning_id(project_id, index)

    return next_id


def _deterministic_planning(project_id: str):
    index = 1  # Planning Draft consumes the first service-issued identity.

    def next_node_id() -> str:
        nonlocal index
        index += 1
        return _planning_id(project_id, index)

    return normalize_planning_aggregate(
        DraftPlanningAggregate.model_validate(base._planning_payload()),
        previous_confirmed=None,
        previous_draft=None,
        id_factory=next_node_id,
    )


def _pinned_refs(planning) -> dict[str, object]:
    volume, block = planning.volumes[0], planning.story_blocks[0]
    stage, task = block.stages[0], block.stages[0].scene_tasks[0]
    ref = lambda item: {
        "id": item.id, "revision": item.revision, "contentHash": item.content_hash,
    }
    return {
        "volumeRef": ref(volume), "storyBlockRef": ref(block),
        "stageRefs": [ref(stage)], "sceneTaskRefs": [ref(task)],
    }


def _outline_signature(
    project_id: str, chapter_number: int, template: OutlineTemplate,
) -> dict[str, object]:
    planning = _deterministic_planning(project_id)
    editable = EditableChapterOutlineContent.model_validate({
        "schemaVersion": "chapter-outline-draft-v1", **_pinned_refs(planning),
        "chapterGoal": template.chapter_goal,
        "expectedCharacters": template.expected_characters,
        "continuation": template.continuation,
        "plannedTasks": template.planned_tasks,
        "scenes": template.scenes,
        "forbiddenEarlyEvents": template.forbidden_early_events,
    })
    capacity = OutlineCapacityPolicy(targetMin=2000, targetMax=3000, softCeiling=3000)
    draft = DraftChapterOutline.model_validate({
        "schemaVersion": "chapter-outline-v1", "chapterNumber": chapter_number,
        "planningRevisionId": _planning_id(project_id, 8), "planningRevision": 1,
        "planningHash": planning.content_hash,
        **editable.model_dump(mode="json", by_alias=True, exclude={"schema_version"}),
        "capacityPolicy": capacity.model_dump(mode="json", by_alias=True),
    })
    revision = chapter_number - 1
    projection_hash = build_projection_bundle(revision, ()).content_hash
    confirmed = normalize_chapter_outline(
        draft, planning=planning, authoritative_chapter_number=chapter_number,
        planning_revision_id=_planning_id(project_id, 8), planning_revision=1,
        capacity_policy=capacity, canon_revision=revision, projection_revision=revision,
        projection_hash=projection_hash,
    )
    content = confirmed.model_dump(mode="json", by_alias=True)
    return {"content": content, "hashMatches": True}


def outline_hash_matches(content: dict[str, object], stored_hash: str) -> bool:
    hash_payload = {key: value for key, value in content.items() if key != "contentHash"}
    return content.get("contentHash") == stored_hash and canonical_hash(hash_payload) == stored_hash


def _final_signature(kind: str, count: int) -> list[dict[str, object]]:
    finals = []
    for chapter in range(1, count + 1):
        authoritative_content = FINAL_PROSE[chapter - 1]
        content = authoritative_content
        title = CHAPTER_TITLES[chapter - 1] if chapter <= 3 else "旧账浮出水面"
        if kind == "corrupt" and chapter == 3:
            content += " CORRUPT_BODY_MUST_NEVER_ESCAPE"
        finals.append({
            "chapter": chapter, "title": title, "content": content,
            "storedHash": sha256(authoritative_content.encode("utf-8")).hexdigest(),
            "hashMatches": not (kind == "corrupt" and chapter == 3),
        })
    return finals


def _signature(*, postconditions: bool) -> dict[str, object]:
    counts = [3, 4 if postconditions else 3, 3]
    return {
        "projects": [
            {"id": project_id, "title": PROJECT_TITLES[kind],
             "lifecycle": "archived" if postconditions and kind == "complete" else "active"}
            for kind, project_id in PROJECTS.items()
        ],
        "finalCounts": counts,
        "finalChapters": [
            _final_signature(kind, count)
            for (kind, _project_id), count in zip(PROJECTS.items(), counts, strict=True)
        ],
        "outlineGoals": [[item.chapter_goal for item in PINNED_OUTLINES]] * 3,
        "outlines": [
            [_outline_signature(project_id, chapter, item)
             for chapter, item in enumerate(PINNED_OUTLINES, start=1)]
            for project_id in PROJECTS.values()
        ],
        "authoritativeChapters": [4, 5 if postconditions else 4, 4],
        "awaitingAuthorReviews": [] if postconditions else [{
            "projectId": PROJECTS["awaiting-author"], "chapter": 4,
            "status": "awaiting_author",
        }],
        "sentinelCounts": {"working": 3, "candidate": 3},
        "corruptHashMismatch": True,
    }


def fixture_signature() -> dict[str, object]:
    return _signature(postconditions=False)


def postcondition_signature() -> dict[str, object]:
    signature = _signature(postconditions=True)
    return {**signature, "lifecycles": [item["lifecycle"] for item in signature["projects"]]}


async def assert_owned_database(database_name: str) -> None:
    database_name = assert_database_name(database_name)
    if os.environ.get("MYSQL_DB") != database_name:
        raise RuntimeError("Phase8A fixture database authority mismatch")
    async with connection() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
    if selected != {"database_name": database_name}:
        raise RuntimeError("Phase8A fixture selected a non-owned database")


def _fingerprint_value(value):
    if isinstance(value, (bytes, bytearray)):
        return {"bytes": bytes(value).hex()}
    if isinstance(value, dict):
        return {str(key): _fingerprint_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_fingerprint_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


async def read_business_fingerprint() -> str:
    inventory = []
    async with connection() as session:
        tables = await session.fetchall(
            "SELECT TABLE_NAME AS table_name FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
        )
        for item in tables:
            table = str(item["table_name"])
            if table == _METADATA_TABLE:
                continue
            if _SAFE_TABLE.fullmatch(table) is None:
                raise RuntimeError("Phase8A fixture table inventory is invalid")
            rows = [_fingerprint_value(row) for row in await session.fetchall(f"SELECT * FROM `{table}`")]
            rows.sort(key=lambda row: json.dumps(
                row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
            ))
            inventory.append({"table": table, "rows": rows})
    encoded = json.dumps(
        inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


async def read_fixture_marker() -> dict[str, str] | None:
    async with connection() as session:
        exists = await session.fetchone(
            "SELECT TABLE_NAME AS table_name FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND TABLE_TYPE='BASE TABLE'",
            (_METADATA_TABLE,),
        )
        if exists is None:
            return None
        rows = await session.fetchall(
            f"SELECT fixture_key,schema_version,business_fingerprint FROM `{_METADATA_TABLE}`"
        )
    if len(rows) != 1:
        return {"invalid": "marker-row-count"}
    return {key: str(rows[0][key]) for key in (
        "fixture_key", "schema_version", "business_fingerprint",
    )}


def _is_pristine_setup_rows(table: str, rows: list[dict[str, object]]) -> bool:
    if table == "application_settings":
        return rows == [{
            "singleton_id": 1, "fallback_provider_id": None,
            "revision": 0, "updated_at": 0,
        }]
    if table == "schema_metadata":
        return (
            len(rows) == 1
            and rows[0].get("singleton_id") == 1
            and rows[0].get("schema_version") == EXPECTED_SCHEMA_VERSION
            and rows[0].get("manifest_hash") == manifest_hash()
            and type(rows[0].get("initialized_at")) is int
            and int(rows[0]["initialized_at"]) > 0
        )
    return not rows


async def business_tables_are_empty() -> bool:
    async with connection() as session:
        tables = await session.fetchall(
            "SELECT TABLE_NAME AS table_name FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
        )
        for item in tables:
            table = str(item["table_name"])
            if table == _METADATA_TABLE:
                continue
            if _SAFE_TABLE.fullmatch(table) is None:
                return False
            rows = await session.fetchall(f"SELECT * FROM `{table}`")
            if not _is_pristine_setup_rows(table, rows):
                return False
    return True


async def write_fixture_marker(fingerprint: str) -> None:
    async with connection() as session:
        await session.execute(
            f"""CREATE TABLE `{_METADATA_TABLE}` (
                fixture_key VARCHAR(64) PRIMARY KEY,
                schema_version VARCHAR(32) NOT NULL,
                business_fingerprint CHAR(64) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
        )
        await session.execute(
            f"INSERT INTO `{_METADATA_TABLE}` (fixture_key,schema_version,business_fingerprint) VALUES (%s,%s,%s)",
            (_FIXTURE_KEY, _FIXTURE_VERSION, fingerprint),
        )


async def read_fixture_signature() -> dict[str, object] | None:
    async with connection() as session:
        rows = await session.fetchall("SELECT id,title,archived_at FROM projects ORDER BY id")
        if not rows:
            return None
        finals_by_project = []
        outlines_by_project = []
        authorities = []
        for project_id in PROJECTS.values():
            finals = await session.fetchall(
                "SELECT chapter_num,title,content,content_hash FROM final_chapters WHERE project_id=%s ORDER BY chapter_num",
                (project_id,),
            )
            finals_by_project.append([{
                "chapter": int(item["chapter_num"]), "title": item["title"], "content": item["content"],
                "storedHash": item["content_hash"],
                "hashMatches": item["content_hash"] == sha256(item["content"].encode("utf-8")).hexdigest(),
            } for item in finals])
            outline_rows = await session.fetchall(
                """SELECT revision.content_json,revision.content_hash FROM project_chapter_outline_heads head
                     JOIN chapter_outline_revisions revision
                       ON revision.project_id=head.project_id AND revision.chapter_num=head.chapter_num
                      AND revision.id=head.outline_revision_id AND revision.revision=head.revision
                      AND revision.content_hash=head.content_hash
                    WHERE head.project_id=%s ORDER BY head.chapter_num""",
                (project_id,),
            )
            outlines = []
            for item in outline_rows:
                content = item["content_json"]
                if isinstance(content, (bytes, bytearray)):
                    content = content.decode("utf-8")
                if isinstance(content, str):
                    content = json.loads(content)
                normalized_content = ChapterOutline.model_validate(content).model_dump(
                    mode="json", by_alias=True,
                )
                outlines.append({
                    "content": normalized_content,
                    "hashMatches": outline_hash_matches(content, item["content_hash"]),
                })
            outlines_by_project.append(outlines)
            active = await session.fetchone(
                "SELECT chapter_num FROM chapter_sessions WHERE project_id=%s AND status='drafting'",
                (project_id,),
            )
            authorities.append(int(active["chapter_num"]) if active else len(finals) + 1)
        reviews = await session.fetchall(
            """SELECT change_set.project_id,chapter.chapter_num,change_set.status
                 FROM finalization_change_sets change_set
                 JOIN chapter_sessions chapter
                   ON chapter.project_id=change_set.project_id AND chapter.id=change_set.chapter_session_id
                WHERE change_set.status='awaiting_author' AND change_set.active_slot=1
                ORDER BY change_set.project_id,chapter.chapter_num"""
        )
        sentinel = await session.fetchone(
            """SELECT SUM(content=%s) AS working_count,SUM(content=%s) AS candidate_count
                 FROM (SELECT content FROM working_drafts UNION ALL SELECT content FROM draft_candidates) values_""",
            (WORKING_SENTINEL, CANDIDATE_SENTINEL),
        )
    counts = [len(items) for items in finals_by_project]
    return {
        "projects": [{
            "id": row["id"], "title": row["title"],
            "lifecycle": "archived" if row["archived_at"] is not None else "active",
        } for row in rows],
        "finalCounts": counts,
        "finalChapters": finals_by_project,
        "outlineGoals": [[item["content"]["chapterGoal"] for item in outlines] for outlines in outlines_by_project],
        "outlines": outlines_by_project,
        "authoritativeChapters": authorities,
        "awaitingAuthorReviews": [{
            "projectId": item["project_id"], "chapter": int(item["chapter_num"]),
            "status": item["status"],
        } for item in reviews],
        "sentinelCounts": {
            "working": int(sentinel["working_count"] or 0),
            "candidate": int(sentinel["candidate_count"] or 0),
        },
        "corruptHashMismatch": bool(finals_by_project[2]) and not finals_by_project[2][-1]["hashMatches"],
    }


async def read_postcondition_signature() -> dict[str, object] | None:
    observed = await read_fixture_signature()
    if observed is None:
        return None
    return {**observed, "lifecycles": [item["lifecycle"] for item in observed["projects"]]}


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
    await sessions.save_candidate(SaveDraftCandidate(
        project_id, workspace.session.id, workspace.working_draft.revision,
        workspace.working_draft.content_hash,
        f"8a100000-0000-4000-8000-00000000000{project_id[-1]}",
    ))
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
    original_working, original_candidate = base.WORKING_SENTINEL, base.CANDIDATE_SENTINEL
    original_outline, original_extraction = base._outline_payload, base._Extraction
    original_planning_service = base.PlanningService
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
        base.WORKING_SENTINEL, base.CANDIDATE_SENTINEL = WORKING_SENTINEL, CANDIDATE_SENTINEL
        base._outline_payload = next_outline
        base._Extraction = ExactExtraction
        base.PlanningService = lambda *args, **kwargs: original_planning_service(
            *args, **kwargs, id_factory=_planning_id_factory(project_id),
        )
        await base.prepare(os.environ["MYSQL_DB"])
    finally:
        base.PROJECT = original_project
        base.FINAL_ONE, base.FINAL_TWO = original_final_one, original_final_two
        base.WORKING_SENTINEL, base.CANDIDATE_SENTINEL = original_working, original_candidate
        base._outline_payload, base._Extraction = original_outline, original_extraction
        base.PlanningService = original_planning_service
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
    marker = await read_fixture_marker()
    observed = await read_fixture_signature()
    expected = fixture_signature()
    if marker is not None:
        if (
            observed == expected
            and marker.get("fixture_key") == _FIXTURE_KEY
            and marker.get("schema_version") == _FIXTURE_VERSION
            and await read_business_fingerprint() == marker.get("business_fingerprint")
        ):
            return
        raise RuntimeError("Phase8A fixture schema must be empty or exact")
    if observed is not None or not await business_tables_are_empty():
        raise RuntimeError("Phase8A fixture schema must be empty or exact")
    await seed_fixture()
    if await read_fixture_signature() != expected:
        raise RuntimeError("Phase8A fixture postcondition failed")
    await write_fixture_marker(await read_business_fingerprint())


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
