from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
import importlib
import json

import pytest

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.seeds import SeedPayload
from backend.http_errors import (
    ProjectBusy,
    SeedAlreadyConfirmed,
    SeedConflict,
    SeedLocked,
    SeedNotFound,
)
from backend.repositories.seeds import SeedRepository
from backend.services.seeds import (
    ArchiveSeed,
    CreateSeed,
    DeleteSeed,
    EditSeed,
    RestoreSeed,
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
        self.archived_projects: set[str] = set()
        self.final_projects: set[str] = set()
        self.seeds: dict[str, dict] = {}
        self.revisions: dict[str, list[dict]] = {}
        self.selections: dict[str, dict] = {}
        self.selection_revisions: dict[str, list[dict]] = {}
        self.dependencies: set[str] = set()
        self.contracts: dict[str, dict] = {}
        self.events: list[str] = []
        self.project_lock_error: BaseException | None = None
        self.provenance_inputs = {
            "snapshots": (
                {
                    "id": "snapshot-1",
                    "source_id": "source-1",
                    "content_hash": "a" * 64,
                    "manifest_hash": "b" * 64,
                    "source_url": "https://www.qidian.com/rank/newsign/",
                    "captured_at": 1_721_000_000_000,
                },
            ),
            "analysis": {
                "id": "analysis-1",
                "result_hash": "c" * 64,
                "status": "succeeded",
                "input_manifest_json": {
                    "snapshots": [
                        {
                            "id": "snapshot-1",
                            "hash": "a" * 64,
                            "manifestHash": "b" * 64,
                            "sourceId": "source-1",
                        }
                    ]
                },
            },
            "attempt": {
                "id": "attempt-1",
                "result_hash": "d" * 64,
                "status": "succeeded",
                "market_snapshot_id": "snapshot-1",
                "market_snapshot_hash": "a" * 64,
                "market_analysis_id": "analysis-1",
                "market_analysis_hash": "c" * 64,
                "input_manifest_json": {
                    "snapshots": [
                        {"id": "snapshot-1", "hash": "a" * 64}
                    ]
                },
            },
        }

    async def lock_project(self, session, project_id):
        self.events.append("project")
        if self.project_lock_error is not None:
            raise self.project_lock_error
        return {"id": project_id} if project_id in self.projects else None

    async def count_final_chapters(self, session, project_id):
        return int(project_id in self.final_projects)

    async def read_project(self, session, project_id):
        self.events.append("read-project")
        if project_id not in self.projects:
            return None
        return {
            "id": project_id,
            "archived_at": 2 if project_id in self.archived_projects else None,
        }

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
        selected_before = any(
            row["seed_id"] == seed_id
            for row in self.selection_revisions.get(project_id, ())
        )
        return int(seed_id in self.dependencies or selected_before)

    async def archive(self, session, project_id, seed_id, updated_at):
        self.events.append("archive")
        self.seeds[seed_id]["status"] = "archived"

    async def restore(self, session, project_id, seed_id, updated_at):
        self.events.append("restore")
        self.seeds[seed_id]["status"] = "candidate"

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

    async def lock_seed_provenance_inputs(self, session, project_id, selection):
        self.events.append("provenance")
        return deepcopy(self.provenance_inputs)


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
async def test_ai_chat_provenance_uses_attempt_first_global_lock_order():
    domain = importlib.import_module("backend.domain.seeds")

    class RecordingSession:
        events = []

        async def fetchone(self, sql, _args):
            if "seed_inspiration_attempts" in sql:
                self.events.append("attempt")
                return {
                    "id": "attempt-1",
                    "status": "succeeded",
                    "result_hash": "d" * 64,
                    "market_snapshot_id": "snapshot-1",
                    "market_snapshot_hash": "a" * 64,
                    "market_analysis_id": "analysis-1",
                    "market_analysis_hash": "c" * 64,
                    "input_manifest_json": {
                        "snapshots": [
                            {"id": "snapshot-1", "hash": "a" * 64}
                        ]
                    },
                }
            self.events.append("analysis")
            return {
                "id": "analysis-1",
                "status": "succeeded",
                "result_hash": "c" * 64,
                "input_manifest_json": {
                    "snapshots": [
                        {
                            "id": "snapshot-1",
                            "hash": "a" * 64,
                            "manifestHash": "b" * 64,
                            "sourceId": "source-1",
                        }
                    ]
                },
            }

        async def fetchall(self, _sql, _args):
            self.events.append("snapshots")
            return [
                {
                    "id": "snapshot-1",
                    "source_id": "source-1",
                    "source_url": "https://example.com/rank",
                    "captured_at": 1,
                    "content_hash": "a" * 64,
                    "manifest_hash": "b" * 64,
                }
            ]

    session = RecordingSession()
    await SeedRepository().lock_seed_provenance_inputs(
        session,
        "p1",
        domain.SeedProvenanceSelection(
            kind="ai_chat",
            snapshotIds=("snapshot-1",),
            analysisId="analysis-1",
            inspirationAttemptId="attempt-1",
        ),
    )

    assert session.events == ["attempt", "snapshots", "analysis"]


@pytest.mark.asyncio
async def test_create_maps_retryable_provenance_deadlock_to_project_busy():
    domain = importlib.import_module("backend.domain.seeds")
    harness = Harness()

    async def deadlocked_provenance(_session, _project_id, _selection):
        raise RuntimeError(1213, "PRIVATE_DATABASE_DETAIL")

    harness.repo.lock_seed_provenance_inputs = deadlocked_provenance
    with pytest.raises(ProjectBusy):
        await harness.service.create(
            CreateSeed(
                project_id="p1",
                payload=payload(),
                provenance=domain.SeedProvenanceSelection(
                    kind="market_snapshot",
                    snapshotIds=("snapshot-1",),
                ),
            )
        )


@pytest.mark.asyncio
async def test_dependency_count_includes_immutable_selection_history():
    class RecordingSession:
        sql = ""
        args = ()

        async def fetchone(self, sql, args):
            self.sql = sql
            self.args = args
            return {"count": 1}

    session = RecordingSession()

    assert await SeedRepository().dependency_count(session, "p1", "seed-a") == 1
    assert "FROM project_seed_selection_revisions" in session.sql
    assert session.args == (
        "p1", "seed-a",
        "p1", "seed-a",
        "p1", "seed-a",
        "p1", "seed-a",
    )


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
async def test_explicit_save_is_idempotent_and_freezes_safe_provenance_without_changing_seed_hash():
    domain = importlib.import_module("backend.domain.seeds")
    harness = Harness()
    selection = domain.SeedProvenanceSelection(
        kind="ai_chat",
        snapshotIds=("snapshot-1",),
        analysisId="analysis-1",
        inspirationAttemptId="attempt-1",
        publicNotes=("作者采用了对话方案，但重新编辑了九字段。",),
    )
    command = CreateSeed(
        project_id="p1",
        payload=payload("作者最终编辑"),
        provenance=selection,
        idempotency_key="s" * 64,
    )

    first = await harness.service.create(command)
    replay = await harness.service.create(command)

    assert replay == first
    assert len(harness.repo.seeds) == 1
    assert len(harness.repo.revisions[first.id]) == 1
    stored = json.loads(harness.repo.revisions[first.id][0]["payload_json"])
    assert {key for key in stored if key != "_provenance"} == set(
        SeedPayload.model_fields
    )
    assert stored["_provenance"]["kind"] == "ai_chat"
    assert stored["_provenance"]["snapshots"] == [
        {
            "id": "snapshot-1",
            "hash": "a" * 64,
            "sourceId": "source-1",
            "sourceURL": "https://www.qidian.com/rank/newsign/",
            "capturedAt": 1_721_000_000_000,
        }
    ]
    assert stored["_provenance"]["analysis"] == {
        "id": "analysis-1",
        "hash": "c" * 64,
    }
    assert stored["_provenance"]["inspirationAttempt"] == {
        "id": "attempt-1",
        "resultHash": "d" * 64,
    }
    assert len(stored["_provenance"]["provenanceHash"]) == 64
    assert first.payload == payload("作者最终编辑")
    assert first.content_hash == canonical_hash(payload("作者最终编辑"))
    assert first.provenance == replay.provenance

    with pytest.raises(SeedConflict):
        await harness.service.create(
            command.model_copy(update={"payload": payload("同键异请求")})
        )
    assert len(harness.repo.seeds) == 1

    edited = await harness.service.edit(
        EditSeed(
            project_id="p1",
            seed_id=first.id,
            payload=payload("后续人工编辑"),
            expected_seed_revision=1,
            expected_selection_revision=0,
        )
    )
    assert edited.provenance == first.provenance
    assert (
        json.loads(harness.repo.revisions[first.id][1]["payload_json"])[
            "_provenance"
        ]
        == stored["_provenance"]
    )


@pytest.mark.asyncio
async def test_explicit_save_rejects_analysis_or_attempt_outside_frozen_snapshot_manifest():
    domain = importlib.import_module("backend.domain.seeds")
    harness = Harness()
    harness.repo.provenance_inputs["analysis"]["input_manifest_json"][
        "snapshots"
    ][0]["hash"] = "f" * 64
    command = CreateSeed(
        project_id="p1",
        payload=payload("不得保存"),
        provenance=domain.SeedProvenanceSelection(
            kind="ai_chat",
            snapshotIds=("snapshot-1",),
            analysisId="analysis-1",
            inspirationAttemptId="attempt-1",
        ),
        idempotency_key="m" * 64,
    )

    with pytest.raises(SeedConflict):
        await harness.service.create(command)

    assert harness.repo.seeds == {}


@pytest.mark.asyncio
async def test_create_rejects_a_new_candidate_after_project_selection_is_confirmed():
    harness = Harness()
    selected_seed = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("已选"))
    )
    selection = await harness.service.select(
        SelectSeed(
            project_id="p1", seed_id=selected_seed.id,
            expected_seed_revision=1, expected_selection_revision=0,
        )
    )
    harness.repo.events.clear()

    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.create(CreateSeed(project_id="p1", payload=payload("新候选")))

    assert selection.selection_revision == 1
    assert len(harness.repo.seeds) == 1


@pytest.mark.asyncio
async def test_create_missing_project_leaves_zero_writes():
    harness = Harness()
    before = deepcopy(harness.repo.__dict__)
    with pytest.raises(SeedNotFound):
        await harness.service.create(CreateSeed(project_id="missing", payload=payload()))
    assert harness.repo.seeds == before["seeds"]

@pytest.mark.asyncio
async def test_confirmed_selection_locks_all_candidate_edits_even_after_final_chapter_creation():
    harness = Harness()
    referenced = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("已选"))
    )
    free = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("未引用"))
    )
    selection = await harness.service.select(
        SelectSeed(
            project_id="p1", seed_id=referenced.id,
            expected_seed_revision=1, expected_selection_revision=0,
        )
    )
    harness.repo.final_projects.add("p1")

    before = deepcopy(harness.repo.__dict__)
    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.edit(
            EditSeed(
                project_id="p1", seed_id=referenced.id,
                payload=payload("历史不得改写"), expected_seed_revision=1,
                expected_selection_revision=selection.selection_revision,
            )
        )
    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.select(
            SelectSeed(
                project_id="p1", seed_id=free.id,
                expected_seed_revision=free.revision,
                expected_selection_revision=selection.selection_revision,
            )
        )
    with pytest.raises(SeedLocked):
        await harness.service.delete(
            DeleteSeed(
                project_id="p1", seed_id=referenced.id,
                expected_seed_revision=1,
                expected_selection_revision=selection.selection_revision,
            )
        )
    assert harness.repo.seeds == before["seeds"]
    assert harness.repo.revisions == before["revisions"]
    assert harness.repo.selections == before["selections"]


@pytest.mark.asyncio
async def test_project_mutation_lock_contention_maps_to_stable_project_busy():
    harness = Harness()
    harness.repo.project_lock_error = RuntimeError(
        3572, "Statement aborted because lock(s) could not be acquired immediately"
    )

    before = deepcopy(harness.repo.__dict__)
    with pytest.raises(ProjectBusy):
        await harness.service.create(
            CreateSeed(project_id="p1", payload=payload("不得等待"))
        )
    assert harness.repo.seeds == before["seeds"]
    assert harness.repo.revisions == before["revisions"]


@pytest.mark.asyncio
async def test_confirmed_selection_allows_only_unreferenced_candidate_cleanup():
    harness = Harness()
    selected_seed = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("已选候选"))
    )
    current = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("当前候选"))
    )
    selection = await harness.service.select(
        SelectSeed(
            project_id="p1", seed_id=selected_seed.id,
            expected_seed_revision=1, expected_selection_revision=0,
        )
    )
    await harness.service.archive(
        ArchiveSeed(
            project_id="p1", seed_id=current.id,
            expected_seed_revision=1,
            expected_selection_revision=selection.selection_revision,
        )
    )
    archived = next(item for item in await harness.service.list("p1") if item.id == current.id)
    assert archived.status == "archived"
    assert archived.capabilities.canRestore is False
    assert archived.capabilities.canPermanentlyDelete is True

    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.restore(
            RestoreSeed(
                project_id="p1", seed_id=current.id,
                expected_seed_revision=1,
                expected_selection_revision=selection.selection_revision,
            )
        )
    await harness.service.delete(
        DeleteSeed(
            project_id="p1", seed_id=current.id,
            expected_seed_revision=1,
            expected_selection_revision=selection.selection_revision,
        )
    )
    assert current.id not in harness.repo.seeds


@pytest.mark.asyncio
async def test_archived_project_read_capabilities_disable_every_seed_mutation():
    harness = Harness()
    free = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("可编辑候选"))
    )
    selected_seed = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("已选择候选"))
    )
    await harness.service.select(
        SelectSeed(
            project_id="p1",
            seed_id=selected_seed.id,
            expected_seed_revision=1,
            expected_selection_revision=0,
        )
    )
    harness.repo.final_projects.add("p1")
    harness.repo.archived_projects.add("p1")

    listed = {item.id: item for item in await harness.service.list("p1")}
    selected = await harness.service.get_selected("p1")

    assert (
        listed[free.id].capabilities.referenced,
        listed[free.id].capabilities.hasFinalChapters,
    ) == (False, True)
    assert (
        listed[selected_seed.id].capabilities.referenced,
        listed[selected_seed.id].capabilities.hasFinalChapters,
    ) == (True, True)
    for item in (*listed.values(), selected.active_selection.seed):
        assert (
            item.capabilities.canEdit,
            item.capabilities.canSelect,
            item.capabilities.canArchive,
            item.capabilities.canRestore,
            item.capabilities.canPermanentlyDelete,
        ) == (False, False, False, False, False)


@pytest.mark.asyncio
async def test_second_selection_preserves_the_first_confirmed_generation():
    harness = Harness()
    seed_a = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("A"))
    )
    seed_b = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("B"))
    )
    first_a = await harness.service.select(
        SelectSeed(
            project_id="p1", seed_id=seed_a.id,
            expected_seed_revision=1, expected_selection_revision=0,
        )
    )
    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.select(
            SelectSeed(
                project_id="p1", seed_id=seed_b.id,
                expected_seed_revision=1,
                expected_selection_revision=first_a.selection_revision,
            )
        )
    harness.repo.contracts["p1"] = {
        "revision": 1,
        "selection_revision": first_a.selection_revision,
        "seed_id": seed_a.id,
        "seed_revision_id": seed_a.revision_id,
        "seed_hash": seed_a.content_hash,
    }

    selected = await harness.service.get_selected("p1")

    assert selected.active_selection.selection_revision == 1
    assert selected.active_selection.seed_id == seed_a.id
    assert selected.active_selection.seed_revision_id == seed_a.revision_id
    assert selected.seed_ready is True
    assert len(harness.repo.selection_revisions["p1"]) == 1


@pytest.mark.asyncio
async def test_edit_cannot_advance_a_confirmed_seed_revision_or_selection_ledger():
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

    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.edit(
            EditSeed(
                project_id="p1",
                seed_id=created.id,
                payload=payload("雾城第二封信"),
                expected_seed_revision=1,
                expected_selection_revision=selected.selection_revision,
            )
        )

    assert harness.repo.revisions[created.id][0] == old
    assert len(harness.repo.revisions[created.id]) == 1
    assert harness.repo.selections["p1"]["seed_revision_id"] == created.revision_id
    assert harness.repo.selections["p1"]["seed_hash"] == created.content_hash
    assert harness.repo.selections["p1"]["selection_revision"] == 1
    assert [row["selection_revision"] for row in harness.repo.selection_revisions["p1"]] == [1]
    assert harness.repo.selection_revisions["p1"][0]["seed_revision_id"] == created.revision_id


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

    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.edit(
            EditSeed(
                project_id="p1", seed_id=first.id, payload=payload("一改"),
                expected_seed_revision=1, expected_selection_revision=0,
            )
        )
    assert len(harness.repo.revisions[first.id]) == 1

    with pytest.raises(SeedAlreadyConfirmed):
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
    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.select(
            SelectSeed(
                project_id="p1", seed_id=first.id,
                expected_seed_revision=1, expected_selection_revision=0,
            )
        )
    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.select(
            SelectSeed(
                project_id="p1", seed_id=other.id,
                expected_seed_revision=1, expected_selection_revision=1,
            )
        )


@pytest.mark.asyncio
async def test_delete_physically_removes_only_unreferenced_seed():
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
    with pytest.raises(SeedLocked):
        await harness.service.delete(
            DeleteSeed(
                project_id="p1", seed_id=referenced.id,
                expected_seed_revision=1, expected_selection_revision=0,
            )
        )
    assert harness.repo.seeds[referenced.id]["status"] == "candidate"


@pytest.mark.asyncio
async def test_confirmed_selection_readiness_does_not_drift_after_rejected_edit():
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

    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.edit(
            EditSeed(
                project_id="p1", seed_id=created.id, payload=payload("漂移"),
                expected_seed_revision=1,
                expected_selection_revision=selection.selection_revision,
            )
        )
    unchanged = await harness.service.get_selected("p1")
    assert unchanged.seed_ready is True
    assert unchanged.reasons == ("binding_not_verified",)


@pytest.mark.asyncio
async def test_same_seed_reselection_is_rejected_without_superseding_contract_readiness():
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

    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.select(
            SelectSeed(
                project_id="p1",
                seed_id=created.id,
                expected_seed_revision=1,
                expected_selection_revision=selection_one.selection_revision,
            )
        )
    unchanged = await harness.service.get_selected("p1")

    assert len(harness.repo.selection_revisions["p1"]) == 1
    assert unchanged.seed_ready is True
    assert unchanged.contract_ready is False
    assert unchanged.reasons == ("binding_not_verified",)


@pytest.mark.asyncio
async def test_get_selected_rejects_unknown_project_before_reading_seed_facts():
    harness = Harness()

    with pytest.raises(SeedNotFound):
        await harness.service.get_selected("missing")
    assert harness.repo.events == ["read-project"]


@pytest.mark.asyncio
async def test_first_selection_locks_every_candidate_except_unreferenced_cleanup():
    harness = Harness()
    seed_a = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("A"))
    )
    seed_b = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("B"))
    )
    selected_a = await harness.service.select(
        SelectSeed(
            project_id="p1",
            seed_id=seed_a.id,
            expected_seed_revision=1,
            expected_selection_revision=0,
        )
    )

    listed = {item.id: item for item in await harness.service.list("p1")}
    assert listed[seed_a.id].capabilities.canSelect is False
    assert listed[seed_b.id].capabilities.canSelect is False
    assert listed[seed_a.id].capabilities.canEdit is False
    assert listed[seed_b.id].capabilities.canEdit is False
    assert listed[seed_b.id].capabilities.canArchive is True
    assert listed[seed_b.id].capabilities.canPermanentlyDelete is True

    for seed_id in (seed_a.id, seed_b.id):
        with pytest.raises(SeedAlreadyConfirmed) as error:
            await harness.service.select(
                SelectSeed(
                    project_id="p1",
                    seed_id=seed_id,
                    expected_seed_revision=1,
                    expected_selection_revision=selected_a.selection_revision,
                )
            )
        assert error.value.status_code == 409
        assert error.value.code == "seed_already_confirmed"

    with pytest.raises(SeedAlreadyConfirmed) as error:
        await harness.service.create(
            CreateSeed(project_id="p1", payload=payload("C"))
        )
    assert error.value.code == "seed_already_confirmed"

    with pytest.raises(SeedAlreadyConfirmed) as error:
        await harness.service.edit(
            EditSeed(
                project_id="p1",
                seed_id=seed_a.id,
                payload=payload("A 改写"),
                expected_seed_revision=1,
                expected_selection_revision=selected_a.selection_revision,
            )
        )
    assert error.value.code == "seed_already_confirmed"

    archived_b = await harness.service.archive(
        ArchiveSeed(
            project_id="p1",
            seed_id=seed_b.id,
            expected_seed_revision=1,
            expected_selection_revision=selected_a.selection_revision,
        )
    )
    assert archived_b.status == "archived"
    with pytest.raises(SeedAlreadyConfirmed) as error:
        await harness.service.restore(
            RestoreSeed(
                project_id="p1",
                seed_id=seed_b.id,
                expected_seed_revision=1,
                expected_selection_revision=selected_a.selection_revision,
            )
        )
    assert error.value.code == "seed_already_confirmed"

    await harness.service.delete(
        DeleteSeed(
            project_id="p1",
            seed_id=seed_b.id,
            expected_seed_revision=1,
            expected_selection_revision=selected_a.selection_revision,
        )
    )
    assert seed_b.id not in harness.repo.seeds
    assert harness.repo.selections["p1"]["seed_id"] == seed_a.id
    assert len(harness.repo.selection_revisions["p1"]) == 1
    assert "replace-selection" not in harness.repo.events


@pytest.mark.asyncio
async def test_confirmed_selection_precedes_stale_seed_and_selection_cas_errors():
    harness = Harness()
    seed_a = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("A"))
    )
    seed_b = await harness.service.create(
        CreateSeed(project_id="p1", payload=payload("B"))
    )
    await harness.service.archive(
        ArchiveSeed(
            project_id="p1",
            seed_id=seed_b.id,
            expected_seed_revision=1,
            expected_selection_revision=0,
        )
    )
    await harness.service.select(
        SelectSeed(
            project_id="p1",
            seed_id=seed_a.id,
            expected_seed_revision=1,
            expected_selection_revision=0,
        )
    )

    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.edit(
            EditSeed(
                project_id="p1",
                seed_id=seed_a.id,
                payload=payload("A 改写"),
                expected_seed_revision=2,
                expected_selection_revision=0,
            )
        )
    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.select(
            SelectSeed(
                project_id="p1",
                seed_id=seed_b.id,
                expected_seed_revision=2,
                expected_selection_revision=0,
            )
        )
    with pytest.raises(SeedAlreadyConfirmed):
        await harness.service.restore(
            RestoreSeed(
                project_id="p1",
                seed_id=seed_b.id,
                expected_seed_revision=2,
                expected_selection_revision=0,
            )
        )


@pytest.mark.asyncio
async def test_delete_locks_project_selection_once():
    harness = Harness()
    seed = await harness.service.create(CreateSeed(project_id="p1", payload=payload()))
    harness.repo.events.clear()

    await harness.service.delete(
        DeleteSeed(
            project_id="p1",
            seed_id=seed.id,
            expected_seed_revision=1,
            expected_selection_revision=0,
        )
    )

    assert harness.repo.events.count("selection") == 1
