from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
import json

import pytest

from backend.domain.json_contracts import canonical_hash
from backend.http_errors import ProjectArchived as RepositoryProjectArchived
from backend.services.planning import (
    ConfirmPlanningDraft,
    PlanningArchived,
    CreatePlanningDraft,
    PlanningConflict,
    PlanningPreconditionFailed,
    PlanningService,
    SavePlanningDraft,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64


def basis(**changes):
    value = {
        "selection_revision": 1,
        "seed_id": "seed-a",
        "seed_revision_id": "seed-revision-a",
        "seed_hash": HASH_A,
        "contract_revision": 1,
        "creation_contract_id": "creation-a",
        "creation_hash": HASH_B,
        "style_contract_id": "style-a",
        "style_hash": HASH_C,
        "bible_revision": 1,
        "bible_revision_id": "bible-a",
        "bible_hash": HASH_D,
        "chapter_capacity_policy": json.dumps(
            {
                "expectedVolumeCount": 3,
                "expectedChapterCount": 60,
                "chapterWordRangePreference": [3000, 5000],
            }
        ),
    }
    value.update(changes)
    return value


def planning_payload(title: str = "第一卷"):
    return {
        "activeStoryBlockRef": "block",
        "volumes": [
            {
                "clientNodeKey": "volume",
                "order": 1,
                "title": title,
                "coreChange": "主角建立第一个可靠据点。",
                "mainPressure": "追兵逼近。",
                "ensembleFocus": ["主角", "同伴"],
                "forbiddenEvents": ["不可提前揭示幕后人"],
            }
        ],
        "plots": [
            {
                "clientNodeKey": "plot",
                "order": 1,
                "title": "立足主线",
                "plotType": "main",
                "storyQuestion": "主角如何活下来？",
                "futureDirection": "从逃亡转为主动布局。",
                "expectedPayoff": "建立据点。",
                "relatedCharacters": ["主角"],
            }
        ],
        "storyBlocks": [
            {
                "clientNodeKey": "block",
                "order": 1,
                "title": "夜渡封锁线",
                "volumeRef": "volume",
                "plotRefs": ["plot"],
                "entrySituation": "二人被困。",
                "blockGoal": "穿过封锁线。",
                "mainPressure": "追兵压缩路线。",
                "expectedChange": "二人建立信任。",
                "openQuestions": ["内应是谁"],
                "involvedCharacters": ["主角", "同伴"],
                "stages": [
                    {
                        "clientNodeKey": "stage",
                        "order": 1,
                        "title": "寻找缺口",
                        "purpose": "确认封锁薄弱处。",
                        "dramaticQuestion": "能否在暴露前找到缺口？",
                        "sceneTasks": [
                            {
                                "clientNodeKey": "task",
                                "order": 1,
                                "task": "观察换岗。",
                                "completionEvidence": "取得换岗间隔。",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def editable_payload(content, *, title: str):
    payload = content.model_dump(mode="json", by_alias=True)
    payload["activeStoryBlockRef"] = payload.pop("activeStoryBlockId")
    payload.pop("schemaVersion")
    payload.pop("contentHash")
    payload["volumes"][0]["title"] = title
    for block in payload["storyBlocks"]:
        block["volumeRef"] = block.pop("volumeId")
        block["plotRefs"] = block.pop("plotIds")
        for stage in block["stages"]:
            stage.pop("storyBlockId")
            for task in stage["sceneTasks"]:
                task.pop("stageId")
    return payload


class MemoryPlanningRepository:
    def __init__(self):
        self.projects = {
            "p1": {
                "id": "p1",
                "archived_at": None,
            }
        }
        self.basis = {"p1": basis()}
        self.heads = {
            "p1": {
                "project_id": "p1",
                "revision": 0,
                "planning_revision_id": None,
                "content_hash": None,
                "content_json": None,
            }
        }
        self.drafts: dict[tuple[str, str], dict] = {}
        self.revisions: dict[tuple[str, int], dict] = {}
        self.requests: dict[tuple[str, str], dict] = {}
        self.projections = {
            "p1": {
                "project_id": "p1",
                "canon_revision_number": 0,
                "projection_revision_number": 0,
                "content_hash": HASH_E,
            }
        }
        self.binding = {
            "p1": {
                "binding_revision_id": "binding-revision-1",
                "binding_revision": 1,
                "binding_hash": HASH_E,
                "binding_task_key": "planning",
                "resolution_status": "bound",
                "provider_id": "provider-1",
                "model_name_snapshot": "deepseek-v4-flash",
                "id": "provider-1",
                "provider_type": "openai-compatible",
                "model_name": "deepseek-v4-flash",
                "base_url": "https://provider.example/v1",
                "api_key": "unit-test-secret",
                "enabled": 1,
                "lifecycle_status": "active",
                "revision": 1,
                "temperature": 0.7,
                "max_context_tokens": 100000,
                "max_output_tokens": 8000,
            }
        }
        self.calls: list[str] = []
        self.projection_write_count = 0
        self.raise_archived_on_lock = False

    async def lock_active_project(self, _session, project_id):
        self.calls.append("lock_active_project")
        if self.raise_archived_on_lock:
            raise RepositoryProjectArchived()
        project = self.projects.get(project_id)
        return (
            project
            if project and project["archived_at"] is None
            else None
        )

    async def read_project_any(self, _session, project_id):
        self.calls.append("read_project_any")
        return self.projects.get(project_id)

    async def read_current_basis(self, _session, project_id):
        self.calls.append("read_current_basis")
        return deepcopy(self.basis.get(project_id))

    async def lock_planning_head(self, _session, project_id):
        self.calls.append("lock_planning_head")
        row = deepcopy(self.heads.get(project_id))
        if row and row["revision"]:
            revision = self.revisions[(project_id, row["revision"])]
            row["content_json"] = revision["content_json"]
            for key in (
                "selection_revision",
                "seed_id",
                "seed_revision_id",
                "seed_hash",
                "contract_revision",
                "creation_contract_id",
                "creation_hash",
                "style_contract_id",
                "style_hash",
                "bible_revision",
                "bible_revision_id",
                "bible_hash",
            ):
                row[key] = revision[key]
        return row

    async def read_active_draft(self, _session, project_id):
        self.calls.append("read_active_draft")
        for (pid, _), row in self.drafts.items():
            if pid == project_id and row["status"] == "active":
                return deepcopy(row)
        return None

    async def read_draft(self, _session, project_id, draft_id):
        self.calls.append("read_draft")
        row = self.drafts.get((project_id, draft_id))
        return deepcopy(row) if row else None

    async def insert_draft(self, _session, row):
        self.calls.append("insert_draft")
        self.drafts[(row["project_id"], row["id"])] = deepcopy(row)
        return True

    async def update_draft_cas(
        self, _session, row, *, expected_revision, expected_hash
    ):
        self.calls.append("update_draft_cas")
        current = self.drafts.get((row["project_id"], row["id"]))
        if (
            current is None
            or current["status"] != "active"
            or current["draft_revision"] != expected_revision
            or current["content_hash"] != expected_hash
        ):
            return False
        current.update(deepcopy(row))
        current["active_slot"] = 1 if row["status"] == "active" else None
        return True

    async def supersede_draft(self, _session, project_id, draft_id, updated_at):
        self.calls.append("supersede_draft")
        row = self.drafts.get((project_id, draft_id))
        if row is None or row["status"] != "active":
            return False
        row.update(status="superseded", active_slot=None, updated_at=updated_at)
        return True

    async def find_confirmation(self, _session, project_id, idempotency_key):
        self.calls.append("find_confirmation")
        row = self.requests.get((project_id, idempotency_key))
        return deepcopy(row) if row else None

    async def insert_confirmation_pending(self, _session, row):
        self.calls.append("insert_confirmation_pending")
        self.requests[(row["project_id"], row["idempotency_key"])] = deepcopy(row)
        return True

    async def insert_revision(self, _session, row):
        self.calls.append("insert_revision")
        self.revisions[(row["project_id"], row["revision"])] = deepcopy(row)
        return True

    async def advance_head_cas(self, _session, row, expected_head):
        self.calls.append("advance_head_cas")
        current = self.heads[row["project_id"]]
        if any(
            current.get(key) != expected_head.get(key)
            for key in (
                "revision",
                "planning_revision_id",
                "content_hash",
            )
        ):
            return False
        current.update(deepcopy(row))
        return True

    async def finish_confirmation(self, _session, row):
        self.calls.append("finish_confirmation")
        current = self.requests[(row["project_id"], row["idempotency_key"])]
        current.update(deepcopy(row))
        return True

    async def list_revisions(self, _session, project_id):
        return tuple(
            deepcopy(row)
            for (pid, _), row in sorted(
                self.revisions.items(), key=lambda item: item[0][1], reverse=True
            )
            if pid == project_id
        )

    async def read_projection_head(self, _session, project_id):
        return deepcopy(self.projections.get(project_id))

    async def lock_projection_head(self, _session, project_id):
        self.calls.append("lock_projection_head")
        return deepcopy(self.projections.get(project_id))

    async def lock_planning_binding(self, _session, project_id):
        self.calls.append("lock_planning_binding")
        return deepcopy(self.binding.get(project_id))


class Harness:
    def __init__(self, *, failpoint=None):
        self.transaction_entries = 0
        self.connection_entries = 0
        self.repository = MemoryPlanningRepository()
        ids = iter(
            f"00000000-0000-0000-0000-{number:012d}"
            for number in range(101, 200)
        )
        repository = self.repository

        @asynccontextmanager
        async def transaction():
            self.transaction_entries += 1
            snapshot = deepcopy(repository.__dict__)
            try:
                yield object()
            except BaseException:
                repository.__dict__.clear()
                repository.__dict__.update(snapshot)
                raise

        @asynccontextmanager
        async def connection():
            self.connection_entries += 1
            yield object()

        self.service = PlanningService(
            repository,
            transaction_factory=transaction,
            connection_factory=connection,
            id_factory=ids.__next__,
            clock=lambda: 1_900_000_000_000,
            failpoint=failpoint,
        )


@pytest.mark.asyncio
async def test_create_requires_current_bible_and_head_zero_is_one_empty_draft():
    harness = Harness()
    harness.repository.basis["p1"] = None

    with pytest.raises(PlanningPreconditionFailed, match="Bible"):
        await harness.service.create_draft(CreatePlanningDraft("p1", "create-1"))

    harness.repository.basis["p1"] = basis()
    first = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-1")
    )
    second = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-2")
    )

    assert second == first
    assert first.base_head_revision == 0
    assert first.draft_revision == 1
    assert first.content.active_story_block_id is None
    assert first.content.volumes == first.content.plots == ()
    assert first.content.story_blocks == ()
    assert first.capacity_policy == {
        "targetMin": 3000,
        "targetMax": 5000,
        "softCeiling": 5000,
    }
    serialized = json.dumps(
        first.content.model_dump(mode="json", by_alias=True), ensure_ascii=False
    )
    for forbidden in ("典籍", "第一卷", "3500", "4500", "5200"):
        assert forbidden not in serialized
    assert len(harness.repository.drafts) == 1


@pytest.mark.parametrize(
    "invalid_range",
    (
        None,
        [],
        [3000],
        [3000, 5000, 6000],
        [True, 5000],
        [3000.0, 5000],
        ["3000", 5000],
        [0, 5000],
        [5000, 3000],
    ),
)
@pytest.mark.asyncio
async def test_create_rejects_noncanonical_contract_capacity_without_writes(
    invalid_range,
):
    harness = Harness()
    harness.repository.basis["p1"]["chapter_capacity_policy"] = json.dumps(
        {
            "expectedVolumeCount": 3,
            "expectedChapterCount": 60,
            "chapterWordRangePreference": invalid_range,
        }
    )

    with pytest.raises(PlanningPreconditionFailed, match="capacity"):
        await harness.service.create_draft(
            CreatePlanningDraft("p1", "invalid-capacity")
        )

    assert harness.repository.drafts == {}


@pytest.mark.asyncio
async def test_create_rejects_target_shape_as_a_second_capacity_contract():
    harness = Harness()
    harness.repository.basis["p1"]["chapter_capacity_policy"] = json.dumps(
        {"targetMin": 3000, "targetMax": 5000, "softCeiling": 6000}
    )

    with pytest.raises(PlanningPreconditionFailed, match="capacity"):
        await harness.service.create_draft(
            CreatePlanningDraft("p1", "second-shape")
        )

    assert harness.repository.drafts == {}


@pytest.mark.asyncio
async def test_save_is_cas_and_allocates_new_node_ids_only_on_the_server():
    harness = Harness()
    draft = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-1")
    )

    saved = await harness.service.save_draft(
        SavePlanningDraft(
            "p1",
            draft.draft_id,
            draft.draft_revision,
            draft.content_hash,
            planning_payload(),
            "save-1",
        )
    )

    assert saved.draft_revision == 2
    assert saved.content.volumes[0].id.startswith("00000000-")
    assert saved.content.volumes[0].id != "volume"
    server_before = deepcopy(
        harness.repository.drafts[("p1", draft.draft_id)]
    )
    with pytest.raises(PlanningConflict, match="draft revision"):
        await harness.service.save_draft(
            SavePlanningDraft(
                "p1",
                draft.draft_id,
                draft.draft_revision,
                draft.content_hash,
                planning_payload("不应覆盖服务端"),
                "save-stale",
            )
        )
    assert harness.repository.drafts[("p1", draft.draft_id)] == server_before


@pytest.mark.asyncio
async def test_confirm_rejects_empty_then_is_atomic_and_idempotent():
    harness = Harness()
    empty = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-1")
    )
    with pytest.raises(PlanningPreconditionFailed, match="not confirmable"):
        await harness.service.confirm_draft(
            ConfirmPlanningDraft(
                "p1",
                empty.draft_id,
                empty.draft_revision,
                empty.content_hash,
                "confirm-empty",
            )
        )
    assert harness.repository.revisions == {}

    saved = await harness.service.save_draft(
        SavePlanningDraft(
            "p1",
            empty.draft_id,
            empty.draft_revision,
            empty.content_hash,
            planning_payload(),
            "save-1",
        )
    )
    command = ConfirmPlanningDraft(
        "p1",
        saved.draft_id,
        saved.draft_revision,
        saved.content_hash,
        "confirm-1",
    )
    harness.repository.calls.clear()
    first = await harness.service.confirm_draft(command)
    first_confirm_calls = tuple(harness.repository.calls)
    replay = await harness.service.confirm_draft(command)

    assert replay == first
    assert first.revision == 1
    assert harness.repository.heads["p1"]["revision"] == 1
    assert harness.repository.drafts[("p1", saved.draft_id)]["status"] == "confirmed"
    assert harness.repository.requests[("p1", "confirm-1")]["status"] == "succeeded"
    assert harness.repository.projection_write_count == 0
    assert first_confirm_calls == (
        "read_project_any",
        "lock_active_project",
        "read_current_basis",
        "lock_planning_head",
        "read_draft",
        "lock_projection_head",
        "find_confirmation",
        "insert_confirmation_pending",
        "insert_revision",
        "advance_head_cas",
        "update_draft_cas",
        "finish_confirmation",
    )
    with pytest.raises(PlanningConflict, match="idempotency"):
        await harness.service.confirm_draft(
            ConfirmPlanningDraft(
                "p1",
                saved.draft_id,
                saved.draft_revision + 1,
                saved.content_hash,
                "confirm-1",
            )
        )


@pytest.mark.asyncio
async def test_successful_confirmation_replay_returns_pinned_history_after_basis_changes():
    harness = Harness()
    draft = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-historical-replay")
    )
    saved = await harness.service.save_draft(
        SavePlanningDraft(
            "p1",
            draft.draft_id,
            draft.draft_revision,
            draft.content_hash,
            planning_payload(),
            "save-historical-replay",
        )
    )
    command = ConfirmPlanningDraft(
        "p1",
        saved.draft_id,
        saved.draft_revision,
        saved.content_hash,
        "confirm-historical-replay",
    )
    confirmed = await harness.service.confirm_draft(command)
    harness.repository.basis["p1"] = basis(
        selection_revision=2,
        seed_id="seed-b",
        seed_revision_id="seed-revision-b",
        seed_hash=HASH_E,
        contract_revision=2,
        creation_contract_id="creation-b",
        creation_hash=HASH_D,
        style_contract_id="style-b",
        style_hash=HASH_A,
        bible_revision=2,
        bible_revision_id="bible-b",
        bible_hash=HASH_B,
    )
    before = deepcopy(
        {
            "heads": harness.repository.heads,
            "drafts": harness.repository.drafts,
            "revisions": harness.repository.revisions,
            "requests": harness.repository.requests,
            "projection_write_count": harness.repository.projection_write_count,
        }
    )

    replay = await harness.service.confirm_draft(command)

    assert replay == confirmed
    assert replay.revision == 1
    assert replay.content_hash == confirmed.content_hash
    assert {
        "heads": harness.repository.heads,
        "drafts": harness.repository.drafts,
        "revisions": harness.repository.revisions,
        "requests": harness.repository.requests,
        "projection_write_count": harness.repository.projection_write_count,
    } == before


@pytest.mark.asyncio
async def test_head_one_create_clones_every_stable_identity_and_history_is_immutable():
    harness = Harness()
    draft = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-1")
    )
    saved = await harness.service.save_draft(
        SavePlanningDraft(
            "p1",
            draft.draft_id,
            draft.draft_revision,
            draft.content_hash,
            planning_payload(),
            "save-1",
        )
    )
    revision = await harness.service.confirm_draft(
        ConfirmPlanningDraft(
            "p1",
            saved.draft_id,
            saved.draft_revision,
            saved.content_hash,
            "confirm-1",
        )
    )

    cloned = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-adjustment")
    )
    history_before = await harness.service.history("p1")

    assert cloned.base_head_revision == 1
    assert cloned.content == revision.content
    assert cloned.content_hash == revision.content_hash
    assert history_before == (revision,)

    formal = cloned.content.model_dump(mode="json", by_alias=True)
    formal["activeStoryBlockRef"] = formal.pop("activeStoryBlockId")
    for block in formal["storyBlocks"]:
        block["volumeRef"] = block.pop("volumeId")
        block["plotRefs"] = block.pop("plotIds")
        for stage in block["stages"]:
            stage.pop("storyBlockId")
            for task in stage["sceneTasks"]:
                task.pop("stageId")
    formal.pop("schemaVersion")
    formal.pop("contentHash")
    adjusted = await harness.service.save_draft(
        SavePlanningDraft(
            "p1",
            cloned.draft_id,
            cloned.draft_revision,
            cloned.content_hash,
            formal,
            "save-adjustment",
        )
    )
    await harness.service.confirm_draft(
        ConfirmPlanningDraft(
            "p1",
            adjusted.draft_id,
            adjusted.draft_revision,
            adjusted.content_hash,
            "confirm-2",
        )
    )
    history_after = await harness.service.history("p1")

    assert tuple(item.revision for item in history_after) == (2, 1)
    assert history_after[1].content == revision.content
    assert history_after[1].content_hash == revision.content_hash
    assert history_after[1].planning_revision_id == revision.planning_revision_id
    assert history_after[1].display_status == "superseded"


@pytest.mark.asyncio
async def test_basis_drift_supersedes_and_a_to_b_to_a_never_reactivates():
    harness = Harness()
    first = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-a")
    )
    harness.repository.basis["p1"] = basis(
        selection_revision=2,
        seed_id="seed-b",
        seed_revision_id="seed-revision-b",
        seed_hash=HASH_E,
        contract_revision=2,
        creation_contract_id="creation-b",
        creation_hash=HASH_D,
        style_contract_id="style-b",
        style_hash=HASH_A,
        bible_revision=2,
        bible_revision_id="bible-b",
        bible_hash=HASH_B,
    )

    with pytest.raises(PlanningPreconditionFailed, match="superseded"):
        await harness.service.save_draft(
            SavePlanningDraft(
                "p1",
                first.draft_id,
                first.draft_revision,
                first.content_hash,
                planning_payload(),
                "stale-a",
            )
        )
    assert harness.repository.drafts[("p1", first.draft_id)]["status"] == "superseded"

    second = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-b")
    )
    harness.repository.basis["p1"] = basis(
        selection_revision=3,
        contract_revision=3,
        creation_contract_id="creation-a3",
        creation_hash=HASH_E,
        style_contract_id="style-a3",
        style_hash=HASH_A,
        bible_revision=3,
        bible_revision_id="bible-a3",
        bible_hash=HASH_B,
    )
    with pytest.raises(PlanningPreconditionFailed, match="superseded"):
        await harness.service.save_draft(
            SavePlanningDraft(
                "p1",
                second.draft_id,
                second.draft_revision,
                second.content_hash,
                planning_payload(),
                "stale-b",
            )
        )
    third = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-a3")
    )
    assert third.draft_id not in {first.draft_id, second.draft_id}
    assert harness.repository.drafts[("p1", first.draft_id)]["status"] == "superseded"


@pytest.mark.asyncio
async def test_confirmed_head_is_history_only_after_generation_changes():
    harness = Harness()
    draft_a = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-a-confirmed")
    )
    saved_a = await harness.service.save_draft(
        SavePlanningDraft(
            "p1",
            draft_a.draft_id,
            draft_a.draft_revision,
            draft_a.content_hash,
            planning_payload("A 第一卷"),
            "save-a-confirmed",
        )
    )
    revision_a = await harness.service.confirm_draft(
        ConfirmPlanningDraft(
            "p1",
            saved_a.draft_id,
            saved_a.draft_revision,
            saved_a.content_hash,
            "confirm-a",
        )
    )
    old_node_ids = {
        revision_a.content.volumes[0].id,
        revision_a.content.plots[0].id,
        revision_a.content.story_blocks[0].id,
        revision_a.content.story_blocks[0].stages[0].id,
        revision_a.content.story_blocks[0].stages[0].scene_tasks[0].id,
    }
    harness.repository.basis["p1"] = basis(
        selection_revision=2,
        seed_id="seed-b",
        seed_revision_id="seed-revision-b",
        seed_hash=HASH_E,
        contract_revision=2,
        creation_contract_id="creation-b",
        creation_hash=HASH_D,
        style_contract_id="style-b",
        style_hash=HASH_A,
        bible_revision=2,
        bible_revision_id="bible-b",
        bible_hash=HASH_B,
    )

    state_b = await harness.service.get_state("p1")
    assert state_b.basis_status == "current"
    assert state_b.future_plan is None
    draft_b = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-b-empty")
    )
    assert draft_b.base_head_revision == 1
    assert draft_b.content.volumes == ()
    assert draft_b.content.story_blocks == ()
    assert not old_node_ids.intersection(
        node.id
        for node in (
            *draft_b.content.volumes,
            *draft_b.content.plots,
            *draft_b.content.story_blocks,
        )
    )
    saved_b = await harness.service.save_draft(
        SavePlanningDraft(
            "p1",
            draft_b.draft_id,
            draft_b.draft_revision,
            draft_b.content_hash,
            planning_payload("B 第一卷"),
            "save-b",
        )
    )
    harness.repository.basis["p1"] = basis(
        selection_revision=2,
        seed_id="seed-b",
        seed_revision_id="seed-revision-b",
        seed_hash=HASH_E,
        contract_revision=2,
        creation_contract_id="creation-b",
        creation_hash=HASH_D,
        style_contract_id="style-b",
        style_hash=HASH_A,
        bible_revision=3,
        bible_revision_id="bible-b3",
        bible_hash=HASH_C,
    )
    with pytest.raises(PlanningPreconditionFailed, match="superseded"):
        await harness.service.confirm_draft(
            ConfirmPlanningDraft(
                "p1",
                saved_b.draft_id,
                saved_b.draft_revision,
                saved_b.content_hash,
                "confirm-stale-b",
            )
        )

    draft_b3 = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-b3-empty")
    )
    assert draft_b3.content.volumes == ()
    saved_b3 = await harness.service.save_draft(
        SavePlanningDraft(
            "p1",
            draft_b3.draft_id,
            draft_b3.draft_revision,
            draft_b3.content_hash,
            planning_payload("B3 第一卷"),
            "save-b3",
        )
    )
    revision_b = await harness.service.confirm_draft(
        ConfirmPlanningDraft(
            "p1",
            saved_b3.draft_id,
            saved_b3.draft_revision,
            saved_b3.content_hash,
            "confirm-b3",
        )
    )
    assert revision_b.revision == 2
    harness.repository.basis["p1"] = basis(
        selection_revision=3,
        contract_revision=3,
        creation_contract_id="creation-a3",
        creation_hash=HASH_E,
        style_contract_id="style-a3",
        style_hash=HASH_A,
        bible_revision=4,
        bible_revision_id="bible-a4",
        bible_hash=HASH_B,
    )

    state_a3 = await harness.service.get_state("p1")
    assert state_a3.basis_status == "current"
    assert state_a3.future_plan is None
    draft_a3 = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-a3-empty")
    )
    assert draft_a3.content.volumes == ()
    assert draft_a3.content.story_blocks == ()
    assert tuple(
        item.revision for item in await harness.service.history("p1")
    ) == (2, 1)


@pytest.mark.asyncio
async def test_confirmation_requires_synchronized_projection_and_rolls_back_every_write():
    harness = Harness(
        failpoint=lambda stage: (
            (_ for _ in ()).throw(RuntimeError("rollback sentinel"))
            if stage == "after_head_advance"
            else None
        )
    )
    draft = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-1")
    )
    saved = await harness.service.save_draft(
        SavePlanningDraft(
            "p1",
            draft.draft_id,
            draft.draft_revision,
            draft.content_hash,
            planning_payload(),
            "save-1",
        )
    )
    before = deepcopy(harness.repository.__dict__)
    with pytest.raises(RuntimeError, match="rollback sentinel"):
        await harness.service.confirm_draft(
            ConfirmPlanningDraft(
                "p1",
                saved.draft_id,
                saved.draft_revision,
                saved.content_hash,
                "confirm-failpoint",
            )
        )
    assert harness.repository.__dict__ == before

    harness.service.failpoint = None
    harness.repository.projections["p1"]["canon_revision_number"] = 1
    mismatch_before = deepcopy(harness.repository.__dict__)
    with pytest.raises(PlanningPreconditionFailed, match="Projection"):
        await harness.service.confirm_draft(
            ConfirmPlanningDraft(
                "p1",
                saved.draft_id,
                saved.draft_revision,
                saved.content_hash,
                "confirm-mismatch",
            )
        )
    assert harness.repository.__dict__ == mismatch_before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "drifted_value"),
    (
        ("revision", 7),
        ("planning_revision_id", "foreign-planning-revision"),
        ("content_hash", HASH_A),
    ),
)
async def test_confirmation_rolls_back_when_any_previous_head_pin_drifts(
    field,
    drifted_value,
):
    harness = Harness()
    draft = await harness.service.create_draft(
        CreatePlanningDraft("p1", f"create-cas-{field}")
    )
    saved = await harness.service.save_draft(
        SavePlanningDraft(
            "p1",
            draft.draft_id,
            draft.draft_revision,
            draft.content_hash,
            planning_payload(),
            f"save-cas-{field}",
        )
    )
    before = deepcopy(harness.repository.__dict__)

    def drift_head(stage):
        if stage == "after_revision_insert":
            harness.repository.heads["p1"][field] = drifted_value

    harness.service.failpoint = drift_head
    with pytest.raises(PlanningConflict, match="head revision conflict"):
        await harness.service.confirm_draft(
            ConfirmPlanningDraft(
                "p1",
                saved.draft_id,
                saved.draft_revision,
                saved.content_hash,
                f"confirm-cas-{field}",
            )
        )

    assert harness.repository.__dict__ == before


@pytest.mark.asyncio
async def test_archived_mutations_reject_but_state_remains_readable_and_separated():
    harness = Harness()
    state = await harness.service.get_state("p1")

    assert state.future_plan is None
    assert state.actual_progress == ()
    assert state.canon_projection_status == {
        "canonRevision": 0,
        "projectionRevision": 0,
        "contentHash": HASH_E,
        "synchronized": True,
    }
    assert state.basis_status == "current"
    assert state.project_lifecycle == "active"
    assert state.capabilities.view is True
    assert state.capabilities.edit is True
    assert state.capabilities.confirm is False
    assert state.capabilities.generate is False

    harness.repository.projects["p1"]["archived_at"] = 123
    archived = await harness.service.get_state("p1")
    assert archived.archived is True
    assert archived.project_lifecycle == "archived"
    assert archived.basis_status == "current"
    assert archived.capabilities.view is True
    assert archived.capabilities.edit is False
    assert archived.capabilities.confirm is False
    assert archived.capabilities.generate is False
    for operation in (
        harness.service.create_draft(CreatePlanningDraft("p1", "archived-create")),
        harness.service.save_draft(
            SavePlanningDraft("p1", "missing", 1, HASH_A, planning_payload(), "x")
        ),
        harness.service.confirm_draft(
            ConfirmPlanningDraft("p1", "missing", 1, HASH_A, "y")
        ),
    ):
        with pytest.raises(PlanningArchived):
            await operation


@pytest.mark.asyncio
async def test_repository_archive_race_is_translated_without_snapshot_reread():
    harness = Harness()
    harness.repository.raise_archived_on_lock = True

    with pytest.raises(PlanningArchived):
        await harness.service.create_draft(
            CreatePlanningDraft("p1", "archive-race")
        )


@pytest.mark.asyncio
async def test_state_exposes_service_owned_basis_and_confirmation_capabilities():
    harness = Harness()
    empty = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-capabilities")
    )
    before_save = await harness.service.get_state("p1")

    assert before_save.basis_status == "current"
    assert before_save.capabilities.confirm is False
    assert before_save.capabilities.generate is True

    await harness.service.save_draft(
        SavePlanningDraft(
            "p1",
            empty.draft_id,
            empty.draft_revision,
            empty.content_hash,
            planning_payload(),
            "save-capabilities",
        )
    )
    after_save = await harness.service.get_state("p1")

    assert after_save.capabilities.confirm is True
    assert after_save.capabilities.generate is True

    harness.repository.binding["p1"]["enabled"] = 0
    model_unready = await harness.service.get_state("p1")
    assert model_unready.capabilities.generate is False
    assert model_unready.capabilities.edit is True
    assert model_unready.capabilities.confirm is True

    harness.repository.binding["p1"]["enabled"] = 1
    harness.repository.binding["p1"]["model_name_snapshot"] = (
        "unit-test-secret"
    )
    harness.repository.binding["p1"]["model_name"] = "unit-test-secret"
    unsafe_summary = await harness.service.get_state("p1")
    assert unsafe_summary.capabilities.generate is False
    assert unsafe_summary.capabilities.edit is True
    assert unsafe_summary.capabilities.confirm is True

    harness.repository.projections["p1"]["canon_revision_number"] = 1
    unsynchronized = await harness.service.get_state("p1")
    assert unsynchronized.capabilities.confirm is False

    harness.repository.basis["p1"] = None
    unavailable = await harness.service.get_state("p1")
    assert unavailable.basis_status == "unavailable"
    assert unavailable.capabilities.edit is False
    assert unavailable.capabilities.confirm is False
    assert unavailable.capabilities.generate is False


@pytest.mark.asyncio
async def test_history_derives_current_superseded_and_archived_statuses():
    harness = Harness()
    first_draft = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-history-1")
    )
    first_saved = await harness.service.save_draft(
        SavePlanningDraft(
            "p1",
            first_draft.draft_id,
            first_draft.draft_revision,
            first_draft.content_hash,
            planning_payload("第一版"),
            "save-history-1",
        )
    )
    await harness.service.confirm_draft(
        ConfirmPlanningDraft(
            "p1",
            first_saved.draft_id,
            first_saved.draft_revision,
            first_saved.content_hash,
            "confirm-history-1",
        )
    )
    second_draft = await harness.service.create_draft(
        CreatePlanningDraft("p1", "create-history-2")
    )
    second_saved = await harness.service.save_draft(
        SavePlanningDraft(
            "p1",
            second_draft.draft_id,
            second_draft.draft_revision,
            second_draft.content_hash,
            editable_payload(second_draft.content, title="第二版"),
            "save-history-2",
        )
    )
    await harness.service.confirm_draft(
        ConfirmPlanningDraft(
            "p1",
            second_saved.draft_id,
            second_saved.draft_revision,
            second_saved.content_hash,
            "confirm-history-2",
        )
    )

    current = await harness.service.history("p1")
    assert [
        (item.display_status, item.display_reason) for item in current
    ] == [
        ("current", "currentPlanningHead"),
        ("superseded", "newerPlanningOrBasis"),
    ]

    harness.repository.projects["p1"]["archived_at"] = 1
    archived = await harness.service.history("p1")
    assert {
        (item.display_status, item.display_reason) for item in archived
    } == {("archived", "projectArchived")}


@pytest.mark.asyncio
async def test_history_and_state_use_transaction_snapshot_not_read_connection():
    harness = Harness()

    await harness.service.history("p1")
    await harness.service.get_state("p1")

    assert harness.transaction_entries == 2
    assert harness.connection_entries == 0
