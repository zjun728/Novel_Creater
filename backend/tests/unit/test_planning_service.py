from __future__ import annotations

import pytest

from backend.domain.json_contracts import canonical_hash


class FakePlanningRepository:
    def __init__(self):
        self.project = {"id": "p1", "title": "永乐大典"}
        self.contract_head = {
            "revision": 1,
            "creation_contract_id": "creation-1",
            "style_contract_id": "style-1",
            "creation_hash": "c" * 64,
            "contract_ready": True,
            "reasons": (),
        }
        self.creation_contract = {
            "id": "creation-1",
            "revision": 1,
            "seed_id": "seed-1",
            "seed_revision_id": "seed-rev-1",
            "content_json": {
                "storyEngine": {
                    "name": "典籍入山河",
                    "storyPromise": "主角以永乐大典残页为引，在乱世中把知识变成可见的秩序和代价。",
                },
                "chapterCapacityPolicy": {
                    "targetMin": 3500,
                    "targetMax": 4500,
                    "softCeiling": 5200,
                },
            },
            "content_hash": "c" * 64,
        }
        self.selected_seed = {
            "selection_revision": 3,
            "seed_id": "seed-1",
            "seed_revision_id": "seed-rev-1",
            "seed_hash": "s" * 64,
            "title": "典镇山河",
            "payload_json": {
                "protagonist": "沈砚",
                "coreConflict": "典籍知识能救人，也会招来权力与贪欲。",
                "openingHook": "他在大典残页中看见一个即将被洪水吞没的县城。",
            },
        }
        self.bible_head = {
            "revision": 2,
            "bible_revision_id": "bible-2",
            "content_hash": "b" * 64,
            "selection_revision": 3,
            "contract_revision": 1,
            "contract_hash": "c" * 64,
        }
        self.plan = None
        self.inserted = None

    async def lock_project(self, session, project_id):
        return self.project if project_id == "p1" else None

    async def read_current_plan(self, session, project_id):
        return self.plan

    async def read_contract_head(self, session, project_id):
        return self.contract_head

    async def read_creation_contract(self, session, creation_contract_id):
        return self.creation_contract if creation_contract_id == "creation-1" else None

    async def read_selected_seed(self, session, project_id):
        return self.selected_seed

    async def read_bible_head(self, session, project_id):
        return self.bible_head

    async def insert_initial_plan(self, session, bundle):
        self.inserted = bundle
        self.plan = bundle
        return True


class FakeTx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def tx_factory():
    return FakeTx()


@pytest.mark.asyncio
async def test_current_plan_query_compares_full_contract_and_bible_generation():
    from backend.repositories.planning import PlanningRepository

    class EmptyPlanSession:
        def __init__(self):
            self.sql = ""

        async def fetchone(self, sql, _args):
            self.sql = sql
            return None

    session = EmptyPlanSession()
    assert await PlanningRepository().read_current_plan(session, "p1") is None
    compact = " ".join(session.sql.split())
    assert "JOIN creation_contracts current_contract" in compact
    assert "current_contract.selection_revision=volume.selection_revision" in compact
    assert "JOIN creation_bible_revisions current_bible" in compact
    assert "current_bible.selection_revision=volume.selection_revision" in compact
    assert "current_bible.contract_revision=volume.contract_revision" in compact
    assert "current_bible.creation_hash=volume.contract_hash" in compact
    assert "current_bible.contract_hash" not in compact


@pytest.mark.asyncio
async def test_bible_head_query_aliases_creation_hash_for_the_existing_dto():
    from backend.repositories.planning import PlanningRepository

    class BibleHeadSession:
        def __init__(self):
            self.sql = ""

        async def fetchone(self, sql, _args):
            self.sql = sql
            return None

    session = BibleHeadSession()
    assert await PlanningRepository().read_bible_head(session, "p1") is None
    compact = " ".join(session.sql.split())
    assert "bible.creation_hash AS contract_hash" in compact
    assert "bible.contract_hash" not in compact


def test_chapter_session_generation_fence_uses_bible_creation_hash():
    from backend.repositories.chapter_sessions import _EFFECTIVE_STATUS

    compact = " ".join(_EFFECTIVE_STATUS.split())
    assert "current_bible.creation_hash=session.contract_hash" in compact
    assert "current_bible.contract_hash" not in compact


@pytest.mark.asyncio
async def test_initial_planning_requires_confirmed_contract_head():
    from backend.services.planning import CreateInitialPlan, PlanningPreconditionFailed, PlanningService

    repo = FakePlanningRepository()
    repo.contract_head = None
    service = PlanningService(repo, transaction_factory=tx_factory)

    with pytest.raises(PlanningPreconditionFailed, match="confirmed contract"):
        await service.create_initial_plan(CreateInitialPlan(
            project_id="p1",
            expected_contract_revision=1,
            idempotency_key="m3-test",
        ))


@pytest.mark.asyncio
async def test_initial_planning_creates_one_active_story_block_without_chapter_counts():
    from backend.services.planning import CreateInitialPlan, PlanningService

    repo = FakePlanningRepository()
    service = PlanningService(repo, transaction_factory=tx_factory)

    result = await service.create_initial_plan(CreateInitialPlan(
        project_id="p1",
        expected_contract_revision=1,
        idempotency_key="m3-test",
    ))

    assert result.has_planning is True
    assert result.contract_revision == 1
    assert result.selection_revision == 3
    assert result.contract_hash == "c" * 64
    assert result.bible_revision == 2
    assert result.bible_hash == "b" * 64
    assert result.active_volume.status == "active"
    assert result.active_block.status == "active"
    assert result.active_block.goal["chapterCapacity"] == {
        "targetMin": 3500,
        "targetMax": 4500,
        "softCeiling": 5200,
    }
    assert "targetChapterCount" not in result.active_block.goal
    assert "continuationCount" not in result.active_block.goal
    assert [stage.status for stage in result.stages] == [
        "in_progress", "pending", "pending",
    ]
    assert all(task.status == "pending" for task in result.scene_tasks)
    assert repo.inserted["manifest_hash"] == canonical_hash({
        "selectionRevision": 3,
        "contractRevision": 1,
        "contractHash": "c" * 64,
        "bibleRevision": 2,
        "bibleHash": "b" * 64,
        "volume": repo.inserted["volume"]["payload"],
        "block": repo.inserted["block"]["payload"],
        "stages": [stage["payload"] for stage in repo.inserted["stages"]],
        "sceneTasks": [task["payload"] for task in repo.inserted["scene_tasks"]],
    })
    assert repo.inserted["volume"]["selection_revision"] == 3
    assert repo.inserted["volume"]["contract_hash"] == "c" * 64
    assert repo.inserted["volume"]["bible_revision"] == 2
    assert repo.inserted["volume"]["bible_hash"] == "b" * 64


@pytest.mark.asyncio
async def test_initial_planning_requires_confirmed_bible_head():
    from backend.services.planning import (
        CreateInitialPlan,
        PlanningPreconditionFailed,
        PlanningService,
    )

    repo = FakePlanningRepository()
    repo.bible_head = {"revision": 0, "bible_revision_id": None, "content_hash": None}

    with pytest.raises(PlanningPreconditionFailed, match="Bible"):
        await PlanningService(repo, transaction_factory=tx_factory).create_initial_plan(
            CreateInitialPlan(
                project_id="p1",
                expected_contract_revision=1,
                idempotency_key="m3-test",
            )
        )


@pytest.mark.asyncio
async def test_initial_planning_is_idempotent_when_plan_already_exists():
    from backend.services.planning import CreateInitialPlan, PlanningService

    repo = FakePlanningRepository()
    service = PlanningService(repo, transaction_factory=tx_factory)
    first = await service.create_initial_plan(CreateInitialPlan(
        project_id="p1",
        expected_contract_revision=1,
        idempotency_key="m3-test",
    ))
    inserted = repo.inserted

    second = await service.create_initial_plan(CreateInitialPlan(
        project_id="p1",
        expected_contract_revision=1,
        idempotency_key="m3-test",
    ))

    assert second == first
    assert repo.inserted is inserted


@pytest.mark.asyncio
async def test_initial_planning_reads_current_creation_contract_selected_engine_shape():
    from backend.services.planning import CreateInitialPlan, PlanningService

    repo = FakePlanningRepository()
    repo.creation_contract["content_json"] = {
        "selectedEngine": {
            "name": "典籍入山河",
            "storyPromise": "穿越知识、典籍残卷、山河治理和群像成长绑定成长期发动机。",
        },
        "chapterCapacityPolicy": {
            "targetMin": 3500,
            "targetMax": 4500,
            "softCeiling": 5200,
        },
    }
    service = PlanningService(repo, transaction_factory=tx_factory)

    result = await service.create_initial_plan(CreateInitialPlan(
        project_id="p1",
        expected_contract_revision=1,
        idempotency_key="m3-test",
    ))

    assert result.active_block.title == "典籍入山河"
    assert "典籍入山河" in result.active_volume.direction["direction"]
