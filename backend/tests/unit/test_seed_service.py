from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy

import pytest

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.seeds import SeedPayload
from backend.http_errors import SeedConflict, SeedLocked, SeedNotFound
from backend.services.seeds import (
    CreateSeed,
    DeleteSeed,
    EditSeed,
    SeedService,
    SelectSeed,
)


def payload(title: str = "雾城来信") -> SeedPayload:
    return SeedPayload(
        title=title,
        genre="悬疑",
        logline="失踪记者从未来寄回一封信。",
        protagonist="档案员林岚",
        desire="找回失踪的姐姐",
        coreConflict="公开真相会抹去姐姐存在的时间线",
        worldPressure="城市每天遗忘一段公共记忆",
        openingHook="林岚收到盖着明日邮戳的信",
        differentiation="以城市档案缺页表现时间被改写",
    )


class MemorySeedRepository:
    def __init__(self):
        self.projects = {"p1", "p2"}
        self.final_projects: set[str] = set()
        self.seeds: dict[str, dict] = {}
        self.revisions: dict[str, list[dict]] = {}
        self.selections: dict[str, dict] = {}
        self.selection_revisions: dict[str, list[dict]] = {}
        self.dependencies: set[str] = set()
        self.contracts: dict[str, dict] = {}
        self.events: list[str] = []

    async def lock_project(self, session, project_id):
        self.events.append("project")
        return {"id": project_id} if project_id in self.projects else None

    async def count_final_chapters(self, session, project_id):
        return int(project_id in self.final_projects)

    async def read_project(self, session, project_id):
        self.events.append("read-project")
        return {"id": project_id} if project_id in self.projects else None

    async def insert_identity(self, session, row):
        self.events.append("identity")
        self.seeds[row["id"]] = dict(row)
        self.revisions[row["id"]] = []

    async def insert_revision(self, session, row):
        self.events.append("revision")
        self.revisions[row["seed_id"]].append(dict(row))

    async def insert_head(self, session, row):
        self.events.append("head")
        self.seeds[row["seed_id"]]["head"] = dict(row)

    async def lock_seed_head(self, session, project_id, seed_id):
        self.events.append("seed")
        seed = self.seeds.get(seed_id)
        if seed is None or seed["project_id"] != project_id:
            return None
        revision = self.revisions[seed_id][-1]
        return {
            **seed, **revision, "id": seed_id, "revision_id": revision["id"]
        }

    async def lock_selection(self, session, project_id):
        self.events.append("selection")
        selection = self.selections.get(project_id)
        return dict(selection) if selection else None

    async def update_head(self, session, row):
        self.events.append("update-head")
        self.seeds[row["seed_id"]]["head"] = dict(row)

    async def insert_selection(self, session, row):
        self.events.append("insert-selection")
        self.selections[row["project_id"]] = dict(row)

    async def insert_selection_revision(self, session, row):
        self.events.append("selection-revision")
        self.selection_revisions.setdefault(row["project_id"], []).append(dict(row))

    async def advance_selected_revision(self, session, row):
        self.events.append("advance-selected-revision")
        self.selections[row["project_id"]].update(row)
        return True

    async def replace_selection(self, session, row):
        self.events.append("replace-selection")
        self.selections[row["project_id"]] = dict(row)
        return True

    async def dependency_count(self, session, project_id, seed_id):
        self.events.append("dependencies")
        return int(seed_id in self.dependencies)

    async def archive(self, session, project_id, seed_id, updated_at):
        self.events.append("archive")
        self.seeds[seed_id]["status"] = "archived"

    async def physical_delete(self, session, project_id, seed_id):
        self.events.append("physical-delete")
        del self.seeds[seed_id]
        del self.revisions[seed_id]

    async def list_heads(self, session, project_id):
        rows = []
        for seed_id, seed in self.seeds.items():
            if seed["project_id"] != project_id:
                continue
            revision = self.revisions[seed_id][-1]
            rows.append({
                **seed, **revision, "id": seed_id,
                "revision_id": revision["id"],
            })
        return rows

    async def read_selection(self, session, project_id):
        selection = self.selections.get(project_id)
        if selection is None:
            return None
        seed_id = selection["seed_id"]
        revision = next(
            row
            for row in self.revisions[seed_id]
            if row["id"] == selection["seed_revision_id"]
        )
        return {
            **self.seeds[seed_id], **revision, **selection, "id": seed_id,
            "revision_id": revision["id"], "is_selected": True,
        }

    async def read_contract_facts(self, session, project_id):
        return self.contracts.get(project_id)


class Harness:
    def __init__(self):
        self.repo = MemorySeedRepository()
        ids = iter(f"id-{index}" for index in range(1, 100))
        self.service = SeedService(
            self.repo,
            transaction_factory=self.transaction,
            connection_factory=self.connection,
            id_factory=lambda: next(ids),
            clock=lambda: 1234,
        )

    @asynccontextmanager
    async def transaction(self):
        snapshot = deepcopy(self.repo.__dict__)
        try:
            yield object()
        except BaseException:
            self.repo.__dict__.clear()
            self.repo.__dict__.update(snapshot)
            raise

    @asynccontextmanager
    async def connection(self):
        yield object()


@pytest.mark.asyncio
async def test_create_persists_identity_revision_one_and_head_with_canonical_fact():
    harness = Harness()

    result = await harness.service.create(CreateSeed(project_id="p1", payload=payload()))

    revision = harness.repo.revisions[result.id][0]
    assert result.revision == 1
    assert revision["payload_json"] == canonical_json(payload())
    assert revision["content_hash"] == canonical_hash(payload()) == result.content_hash
    assert harness.repo.events == [
        "project", "selection", "identity", "revision", "head",
    ]


@pytest.mark.asyncio
async def test_create_reports_current_project_selection_revision_for_unselected_seed():
    harness = Harness()
    selected_seed = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("已选"))
    )
    for expected_selection_revision in range(7):
        await harness.service.select(
            SelectSeed(
                project_id="p1", seed_id=selected_seed.id,
                expected_seed_revision=1,
                expected_selection_revision=expected_selection_revision,
            )
        )
    harness.repo.events.clear()

    created = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("新候选"))
    )

    assert created.is_selected is False
    assert created.selection_revision == 7
    assert harness.repo.events == [
        "project", "selection", "identity", "revision", "head",
    ]


@pytest.mark.asyncio
async def test_create_missing_project_and_locked_project_leave_zero_writes():
    harness = Harness()
    before = deepcopy(harness.repo.__dict__)
    with pytest.raises(SeedNotFound):
        await harness.service.create(CreateSeed(project_id="missing", payload=payload()))
    assert harness.repo.seeds == before["seeds"]

    harness.repo.final_projects.add("p1")
    before = deepcopy(harness.repo.__dict__)
    with pytest.raises(SeedLocked):
        await harness.service.create(CreateSeed(project_id="p1", payload=payload()))
    assert harness.repo.seeds == before["seeds"]


@pytest.mark.parametrize("operation", ("create", "edit", "select", "delete"))
@pytest.mark.asyncio
async def test_every_mutation_is_locked_after_final_chapter_with_zero_writes(
    operation,
):
    harness = Harness()
    created = None
    if operation != "create":
        created = await harness.service.create(
            CreateSeed(project_id="p1", payload=payload("已存在"))
        )
    harness.repo.final_projects.add("p1")
    before = deepcopy(harness.repo.__dict__)

    if operation == "create":
        mutation = harness.service.create(
            CreateSeed(project_id="p1", payload=payload("新建"))
        )
    elif operation == "edit":
        mutation = harness.service.edit(
            EditSeed(
                project_id="p1", seed_id=created.id, payload=payload("改写"),
                expected_seed_revision=1, expected_selection_revision=0,
            )
        )
    elif operation == "select":
        mutation = harness.service.select(
            SelectSeed(
                project_id="p1", seed_id=created.id,
                expected_seed_revision=1, expected_selection_revision=0,
            )
        )
    else:
        mutation = harness.service.delete(
            DeleteSeed(
                project_id="p1", seed_id=created.id,
                expected_seed_revision=1, expected_selection_revision=0,
            )
        )

    with pytest.raises(SeedLocked):
        await mutation
    assert harness.repo.__dict__ == before


@pytest.mark.asyncio
async def test_edit_appends_revision_preserves_history_and_moves_selected_fact():
    harness = Harness()
    created = await harness.service.create(CreateSeed(project_id="p1", payload=payload()))
    selected = await harness.service.select(
        SelectSeed(
            project_id="p1",
            seed_id=created.id,
            expected_seed_revision=1,
            expected_selection_revision=0,
        )
    )
    old = deepcopy(harness.repo.revisions[created.id][0])

    edited = await harness.service.edit(
        EditSeed(
            project_id="p1",
            seed_id=created.id,
            payload=payload("雾城第二封信"),
            expected_seed_revision=1,
            expected_selection_revision=selected.selection_revision,
        )
    )

    assert edited.revision == 2
    assert harness.repo.revisions[created.id][0] == old
    assert harness.repo.selections["p1"]["seed_revision_id"] == edited.revision_id
    assert harness.repo.selections["p1"]["seed_hash"] == edited.content_hash
    assert harness.repo.selections["p1"]["selection_revision"] == 2
    assert [row["selection_revision"] for row in harness.repo.selection_revisions["p1"]] == [1, 2]
    assert harness.repo.selection_revisions["p1"][0]["seed_revision_id"] == created.revision_id
    assert harness.repo.events[-7:] == [
        "project", "seed", "selection", "revision", "update-head",
        "selection-revision", "advance-selected-revision",
    ]


@pytest.mark.asyncio
async def test_edit_requires_both_seed_and_project_selection_cas_even_when_unselected():
    harness = Harness()
    first = await harness.service.create(CreateSeed(project_id="p1", payload=payload("一")))
    second = await harness.service.create(CreateSeed(project_id="p1", payload=payload("二")))
    await harness.service.select(
        SelectSeed(
            project_id="p1", seed_id=second.id,
            expected_seed_revision=1, expected_selection_revision=0,
        )
    )

    with pytest.raises(SeedConflict):
        await harness.service.edit(
            EditSeed(
                project_id="p1", seed_id=first.id, payload=payload("一改"),
                expected_seed_revision=1, expected_selection_revision=0,
            )
        )
    assert len(harness.repo.revisions[first.id]) == 1

    with pytest.raises(SeedConflict):
        await harness.service.edit(
            EditSeed(
                project_id="p1", seed_id=first.id, payload=payload("一改"),
                expected_seed_revision=2, expected_selection_revision=1,
            )
        )


@pytest.mark.asyncio
async def test_select_is_project_scoped_and_cas_advances_one_revision():
    harness = Harness()
    first = await harness.service.create(CreateSeed(project_id="p1", payload=payload("一")))
    other = await harness.service.create(CreateSeed(project_id="p2", payload=payload("二")))

    selected = await harness.service.select(
        SelectSeed(
            project_id="p1", seed_id=first.id,
            expected_seed_revision=1, expected_selection_revision=0,
        )
    )
    assert selected.selection_revision == 1
    assert harness.repo.events[-2:] == [
        "selection-revision", "insert-selection",
    ]
    with pytest.raises(SeedConflict):
        await harness.service.select(
            SelectSeed(
                project_id="p1", seed_id=first.id,
                expected_seed_revision=1, expected_selection_revision=0,
            )
        )
    with pytest.raises(SeedNotFound):
        await harness.service.select(
            SelectSeed(
                project_id="p1", seed_id=other.id,
                expected_seed_revision=1, expected_selection_revision=1,
            )
        )


@pytest.mark.asyncio
async def test_delete_physically_removes_free_seed_and_archives_selected_or_referenced_seed():
    harness = Harness()
    free = await harness.service.create(CreateSeed(project_id="p1", payload=payload("自由")))
    await harness.service.delete(
        DeleteSeed(
            project_id="p1", seed_id=free.id,
            expected_seed_revision=1, expected_selection_revision=0,
        )
    )
    assert free.id not in harness.repo.seeds

    referenced = await harness.service.create(CreateSeed(project_id="p1", payload=payload("引用")))
    harness.repo.dependencies.add(referenced.id)
    await harness.service.delete(
        DeleteSeed(
            project_id="p1", seed_id=referenced.id,
            expected_seed_revision=1, expected_selection_revision=0,
        )
    )
    assert harness.repo.seeds[referenced.id]["status"] == "archived"


@pytest.mark.asyncio
async def test_selected_readiness_is_backend_fact_and_reports_seed_drift_after_edit():
    harness = Harness()
    created = await harness.service.create(CreateSeed(project_id="p1", payload=payload()))
    selection = await harness.service.select(
        SelectSeed(
            project_id="p1", seed_id=created.id,
            expected_seed_revision=1, expected_selection_revision=0,
        )
    )
    harness.repo.contracts["p1"] = {
        "revision": 1,
        "selection_revision": selection.selection_revision,
        "seed_id": created.id,
        "seed_revision_id": created.revision_id,
        "seed_hash": created.content_hash,
    }
    ready = await harness.service.get_selected("p1")
    assert ready.seed_ready is True
    assert ready.contract_ready is False
    assert ready.reasons == ("binding_not_verified",)

    await harness.service.edit(
        EditSeed(
            project_id="p1", seed_id=created.id, payload=payload("漂移"),
            expected_seed_revision=1,
            expected_selection_revision=selection.selection_revision,
        )
    )
    drifted = await harness.service.get_selected("p1")
    assert drifted.seed_ready is False
    assert drifted.contract_ready is False
    assert "selected_seed_drift" in drifted.reasons


@pytest.mark.asyncio
async def test_same_seed_reselection_supersedes_old_contract_readiness_generation():
    harness = Harness()
    created = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload())
    )
    selection_one = await harness.service.select(
        SelectSeed(
            project_id="p1",
            seed_id=created.id,
            expected_seed_revision=1,
            expected_selection_revision=0,
        )
    )
    harness.repo.contracts["p1"] = {
        "revision": 1,
        "selection_revision": selection_one.selection_revision,
        "seed_id": created.id,
        "seed_revision_id": created.revision_id,
        "seed_hash": created.content_hash,
    }
    assert (await harness.service.get_selected("p1")).seed_ready is True

    selection_two = await harness.service.select(
        SelectSeed(
            project_id="p1",
            seed_id=created.id,
            expected_seed_revision=1,
            expected_selection_revision=selection_one.selection_revision,
        )
    )
    superseded = await harness.service.get_selected("p1")

    assert selection_two.selection_revision == 2
    assert superseded.seed_ready is False
    assert superseded.contract_ready is False
    assert superseded.reasons == ("selected_seed_drift",)


@pytest.mark.asyncio
async def test_get_selected_rejects_unknown_project_before_reading_seed_facts():
    harness = Harness()

    with pytest.raises(SeedNotFound):
        await harness.service.get_selected("missing")

    assert harness.repo.events == ["read-project"]
