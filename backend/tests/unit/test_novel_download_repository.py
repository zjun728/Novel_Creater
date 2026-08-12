from __future__ import annotations

import json
from hashlib import sha256
import traceback

import pytest

from backend.domain.chapter_outlines import (
    DraftChapterOutline,
    OutlineCapacityPolicy,
    normalize_chapter_outline,
)
from backend.domain.planning import (
    DraftPlanningAggregate,
    normalize_planning_aggregate,
)
from backend.repositories.novel_downloads import (
    NovelDownloadDataCorruption,
    NovelDownloadRepository,
)


class CapturingSession:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    async def fetchall(self, sql, args=None):
        self.calls.append((sql, args))
        return self.rows


def _compact(sql: str) -> str:
    return " ".join(sql.split())


def _planning():
    draft = DraftPlanningAggregate.model_validate({
        "activeStoryBlockRef": "block",
        "volumes": [{
            "clientNodeKey": "volume", "order": 1, "title": "第一卷",
            "coreChange": "改变", "mainPressure": "压力",
            "ensembleFocus": [], "forbiddenEvents": [],
        }],
        "plots": [{
            "clientNodeKey": "plot", "order": 1, "title": "主线",
            "plotType": "mystery", "storyQuestion": "问题？",
            "futureDirection": "方向", "expectedPayoff": "回报",
            "relatedCharacters": [],
        }],
        "storyBlocks": [{
            "clientNodeKey": "block", "order": 1, "title": "故事块",
            "volumeRef": "volume", "plotRefs": ["plot"],
            "entrySituation": "开端", "blockGoal": "目标", "mainPressure": "压力",
            "expectedChange": "改变", "openQuestions": [],
            "involvedCharacters": [],
            "stages": [{
                "clientNodeKey": "stage", "order": 1, "title": "阶段",
                "purpose": "目的", "dramaticQuestion": "悬念？",
                "sceneTasks": [{
                    "clientNodeKey": "task", "order": 1, "task": "任务",
                    "completionEvidence": "证据",
                }],
            }],
        }],
    })
    return normalize_planning_aggregate(
        draft, previous_confirmed=None, previous_draft=None,
        id_factory=iter(("volume-id", "plot-id", "block-id", "stage-id", "task-id")).__next__,
    )


def _ref(value):
    return {"id": value.id, "revision": value.revision, "contentHash": value.content_hash}


def _outline(planning):
    block = planning.story_blocks[0]
    policy = OutlineCapacityPolicy.model_validate({
        "targetMin": 1, "targetMax": 2, "softCeiling": 3,
    })
    return normalize_chapter_outline(
        DraftChapterOutline.model_validate({
            "schemaVersion": "chapter-outline-v1", "chapterNumber": 1,
            "planningRevisionId": "planning-id", "planningRevision": 1,
            "planningHash": planning.content_hash,
            "volumeRef": _ref(planning.volumes[0]), "storyBlockRef": _ref(block),
            "stageRefs": [_ref(block.stages[0])],
            "sceneTaskRefs": [_ref(block.stages[0].scene_tasks[0])],
            "chapterGoal": "目标", "expectedCharacters": [], "continuation": [],
            "plannedTasks": ["任务"], "scenes": ["场景"],
            "forbiddenEarlyEvents": [],
            "capacityPolicy": policy.model_dump(by_alias=True, mode="json"),
        }),
        planning=planning, authoritative_chapter_number=1,
        planning_revision_id="planning-id", planning_revision=1,
        capacity_policy=policy, canon_revision=0, projection_revision=0,
        projection_hash="c" * 64,
    )


def _row(*, title="章节标题", prose="最终正文", planning_json=True, outline_json=True):
    planning = _planning()
    outline = _outline(planning)
    return {
        "book_title": "书名", "final_id": "final-id", "final_project_id": "project-id",
        "final_session_id": "session-id", "final_chapter_num": 1,
        "final_title": title, "final_content": prose,
        "final_content_hash": sha256(prose.encode()).hexdigest(),
        "final_planning_id": "planning-id", "final_planning_revision": 1,
        "final_planning_hash": planning.content_hash, "final_outline_id": "outline-id",
        "final_outline_revision": 1, "final_outline_hash": outline.content_hash,
        "session_id": "session-id", "session_project_id": "project-id",
        "session_chapter_num": 1, "session_planning_id": "planning-id",
        "session_planning_revision": 1, "session_planning_hash": planning.content_hash,
        "session_story_block_id": planning.story_blocks[0].id,
        "session_story_block_revision": planning.story_blocks[0].revision,
        "session_story_block_hash": planning.story_blocks[0].content_hash,
        "session_outline_id": "outline-id", "session_outline_revision": 1,
        "session_outline_hash": outline.content_hash,
        "outline_id": "outline-id", "outline_project_id": "project-id",
        "outline_chapter_num": 1, "outline_revision": 1,
        "outline_planning_id": "planning-id", "outline_planning_revision": 1,
        "outline_planning_hash": planning.content_hash,
        "outline_content_hash": outline.content_hash,
        "outline_content_json": (
            json.dumps(outline.model_dump(by_alias=True, mode="json"))
            if outline_json else outline.model_dump(by_alias=True, mode="json")
        ),
        "planning_id": "planning-id", "planning_project_id": "project-id",
        "planning_revision": 1, "planning_content_hash": planning.content_hash,
        "planning_content_json": (
            json.dumps(planning.model_dump(by_alias=True, mode="json"))
            if planning_json else planning.model_dump(by_alias=True, mode="json")
        ),
    }


@pytest.mark.asyncio
async def test_load_snapshot_selects_only_pinned_authorities_and_accepts_active_or_archived():
    session = CapturingSession([_row()])

    snapshot = await NovelDownloadRepository().load_finalized_snapshot(session, "project-id")

    assert snapshot.book_title == "书名"
    assert snapshot.chapters[0].volume_title == "第一卷"
    sql, args = session.calls[0]
    compact = _compact(sql).lower()
    assert args == ("project-id",)
    assert "select *" not in compact
    assert "project_planning_heads" not in compact
    assert "working_drafts" not in compact and "draft_candidates" not in compact
    assert "provider" not in compact
    assert "left join final_chapters" in compact
    assert "chapter.story_block_id as session_story_block_id" in compact


@pytest.mark.asyncio
async def test_load_snapshot_distinguishes_unknown_project_from_empty_project():
    repository = NovelDownloadRepository()

    assert await repository.load_finalized_snapshot(CapturingSession([]), "project-id") is None
    empty = await repository.load_finalized_snapshot(
        CapturingSession([{"book_title": "书名", "final_id": None}]), "project-id",
    )
    assert empty.book_title == "书名" and empty.chapters == ()


@pytest.mark.asyncio
async def test_load_snapshot_accepts_dict_json_and_rejects_unclosed_persisted_rows():
    snapshot = await NovelDownloadRepository().load_finalized_snapshot(
        CapturingSession([_row(planning_json=False, outline_json=False)]), "project-id",
    )
    assert snapshot.chapters[0].chapter_title == "章节标题"

    cases = [
        ("session_id", None), ("outline_id", None), ("planning_id", None),
        ("session_planning_hash", "b" * 64),
        ("outline_content_json", "RAW_JSON_SENTINEL"),
        ("planning_content_json", "RAW_JSON_SENTINEL"),
        ("final_content_hash", "a" * 64),
    ]
    for key, value in cases:
        row = _row()
        row[key] = value
        with pytest.raises(NovelDownloadDataCorruption) as raised:
            await NovelDownloadRepository().load_finalized_snapshot(
                CapturingSession([row]), "project-id",
            )
        assert "RAW_JSON_SENTINEL" not in str(raised.value)


@pytest.mark.asyncio
async def test_load_snapshot_rejects_domain_decode_and_outline_volume_story_block_mismatches():
    invalid = _row()
    invalid["planning_content_json"] = {"schemaVersion": "planning-v1"}
    with pytest.raises(NovelDownloadDataCorruption):
        await NovelDownloadRepository().load_finalized_snapshot(CapturingSession([invalid]), "project-id")

    for field, replacement in (("volumeRef", {"id": "missing", "revision": 1, "contentHash": "a" * 64}),
                               ("storyBlockRef", {"id": "missing", "revision": 1, "contentHash": "a" * 64})):
        row = _row()
        payload = json.loads(row["outline_content_json"])
        payload[field] = replacement
        row["outline_content_json"] = payload
        with pytest.raises(NovelDownloadDataCorruption):
            await NovelDownloadRepository().load_finalized_snapshot(CapturingSession([row]), "project-id")


@pytest.mark.asyncio
async def test_load_snapshot_rejects_tampered_canonical_planning_or_outline_payloads():
    planning_mutations = (
        ("volumes", 0, "title"),
        ("plots", 0, "title"),
        ("storyBlocks", 0, "title"),
        ("storyBlocks", 0, "stages", 0, "title"),
        ("storyBlocks", 0, "stages", 0, "sceneTasks", 0, "task"),
    )
    for path in planning_mutations:
        row = _row()
        payload = json.loads(row["planning_content_json"])
        target = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = "TAMPERED_CONTENT_SENTINEL"
        row["planning_content_json"] = payload
        with pytest.raises(NovelDownloadDataCorruption) as raised:
            await NovelDownloadRepository().load_finalized_snapshot(CapturingSession([row]), "project-id")
        assert "TAMPERED_CONTENT_SENTINEL" not in str(raised.value)

    for field in ("chapterGoal", "scenes"):
        row = _row()
        payload = json.loads(row["outline_content_json"])
        payload[field] = "TAMPERED_CONTENT_SENTINEL" if field == "chapterGoal" else ["TAMPERED_CONTENT_SENTINEL"]
        row["outline_content_json"] = payload
        with pytest.raises(NovelDownloadDataCorruption) as raised:
            await NovelDownloadRepository().load_finalized_snapshot(CapturingSession([row]), "project-id")
        assert "TAMPERED_CONTENT_SENTINEL" not in str(raised.value)


@pytest.mark.asyncio
async def test_load_snapshot_requires_session_story_block_pin_to_match_outline_and_planning():
    for key, value in (
        ("session_story_block_id", "other-block"),
        ("session_story_block_revision", 2),
        ("session_story_block_hash", "a" * 64),
    ):
        row = _row()
        row[key] = value
        with pytest.raises(NovelDownloadDataCorruption):
            await NovelDownloadRepository().load_finalized_snapshot(CapturingSession([row]), "project-id")


@pytest.mark.asyncio
async def test_load_snapshot_suppresses_sensitive_exception_causes_and_tracebacks():
    cases = []
    invalid_json = _row()
    invalid_json["outline_content_json"] = "RAW_JSON_SENTINEL"
    cases.append((invalid_json, "RAW_JSON_SENTINEL"))

    invalid_model = _row()
    outline_payload = json.loads(invalid_model["outline_content_json"])
    outline_payload["chapterNumber"] = "PYDANTIC_PAYLOAD_SENTINEL"
    invalid_model["outline_content_json"] = outline_payload
    cases.append((invalid_model, "PYDANTIC_PAYLOAD_SENTINEL"))

    invalid_snapshot = _row()
    invalid_snapshot["final_title"] = None
    cases.append((invalid_snapshot, "INTERNAL_ID_SENTINEL"))

    for row, sentinel in cases:
        with pytest.raises(NovelDownloadDataCorruption) as raised:
            await NovelDownloadRepository().load_finalized_snapshot(
                CapturingSession([row]), "INTERNAL_ID_SENTINEL",
            )
        error = raised.value
        rendered = "".join(traceback.format_exception(error))
        assert error.__cause__ is None
        assert sentinel not in rendered
        assert "INTERNAL_ID_SENTINEL" not in rendered
