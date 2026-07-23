from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.domain.bibles import BiblePayload, canonical_bible_hash
from backend.domain.json_contracts import canonical_hash
from backend.http_errors import ProjectArchived
from backend.services.bibles import (
    BibleConfirmationFailed,
    BibleConflict,
    BibleNotFound,
    BiblePreconditionFailed,
    BibleService,
    CloneBibleDraft,
    ConfirmBible,
    SaveBibleDraft,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64


def bible_payload(**overrides) -> BiblePayload:
    values = {
        "premiseAndPromise": "主角将在陌生秩序中寻找可持续的立足方式。",
        "worldRules": (
            {"id": "world-rule-1", "text": "力量使用将付出可追踪的代价。"},
        ),
        "powerOrProgressionSystem": "成长将依靠选择、训练和有限资源逐层推进。",
        "protagonist": "主角被设计为谨慎、能承担选择后果的人。",
        "coreCast": (
            {"id": "cast-1", "text": "同伴将以独立目标参与未来冲突。"},
        ),
        "factions": (
            {"id": "faction-1", "text": "地方势力将围绕秩序与利益形成竞争。"},
        ),
        "longTermConflicts": (
            {"id": "conflict-1", "text": "长期矛盾将围绕自由与稳定逐步升级。"},
        ),
        "relationshipDynamics": (
            {"id": "relationship-1", "text": "信任将通过共同选择缓慢建立。"},
        ),
        "toneAndNarrativeBoundaries": "叙事将克制直接说教，并保留行动余波。",
        "continuityGuardrails": (
            {"id": "guardrail-1", "text": "能力提升必须保留资源与训练依据。"},
        ),
        "openDesignQuestions": (
            {"id": "question-1", "text": "后续需要决定第一阶段的关键代价。"},
        ),
    }
    values.update(overrides)
    return BiblePayload(**values)


def contract_head(
    *,
    selection_revision=1,
    seed_id="seed-a",
    seed_revision_id="seed-revision-a",
    seed_hash=HASH_A,
    revision=1,
    creation_contract_id="creation-a",
    creation_hash=HASH_B,
    style_contract_id="style-a",
    style_hash=HASH_C,
    contract_ready=True,
    reasons=(),
):
    return SimpleNamespace(
        contract_ready=contract_ready,
        reasons=tuple(reasons),
        selection_revision=selection_revision,
        revision=revision,
        creation_contract_id=creation_contract_id,
        creation_hash=creation_hash,
        style_contract_id=style_contract_id,
        style_hash=style_hash,
        seed_ref=SimpleNamespace(
            id=seed_id,
            revision_id=seed_revision_id,
            content_hash=seed_hash,
        ),
    )


class FakeContractService:
    def __init__(self):
        self.heads = {"p1": contract_head(), "archived": contract_head()}
        self.calls = []

    async def get_head(self, project_id):
        self.calls.append(project_id)
        value = self.heads.get(project_id)
        if value is None:
            raise BibleNotFound()
        return deepcopy(value)


class MemoryBibleRepository:
    def __init__(self):
        self.contract_service = None
        self.locked_selection_override = None
        self.locked_contract_head_override = None
        self.projects = {
            "p1": {"id": "p1", "archived_at": None},
            "archived": {"id": "archived", "archived_at": 1_900_000_000_000},
        }
        self.drafts = {}
        self.heads = {
            "p1": {
                "project_id": "p1",
                "revision": 0,
                "bible_revision_id": None,
                "content_hash": None,
                "updated_at": 1,
            },
            "archived": {
                "project_id": "archived",
                "revision": 0,
                "bible_revision_id": None,
                "content_hash": None,
                "updated_at": 1,
            },
        }
        self.revisions = {}
        self.requests = {}
        self.write_count = 0
        self.events = []

    async def read_project(self, _session, project_id):
        return deepcopy(self.projects.get(project_id))

    async def lock_project(self, _session, project_id):
        self.events.append("lock-project")
        row = self.projects.get(project_id)
        if row is not None and row["archived_at"] is not None:
            raise ProjectArchived()
        return deepcopy(row)

    def _canonical_contract(self, project_id):
        assert self.contract_service is not None
        return self.contract_service.heads.get(project_id)

    async def lock_selected_seed(self, _session, project_id):
        self.events.append("lock-selected-seed")
        if self.locked_selection_override is not None:
            return deepcopy(self.locked_selection_override)
        head = self._canonical_contract(project_id)
        if head is None or isinstance(head, dict):
            return None
        return {
            "selection_revision": head.selection_revision,
            "seed_id": head.seed_ref.id,
            "seed_revision_id": head.seed_ref.revision_id,
            "seed_hash": head.seed_ref.content_hash,
        }

    async def lock_contract_head(self, _session, project_id):
        self.events.append("lock-contract-head")
        if self.locked_contract_head_override is not None:
            return deepcopy(self.locked_contract_head_override)
        head = self._canonical_contract(project_id)
        if head is None or isinstance(head, dict):
            return None
        return {
            "revision": head.revision,
            "creation_contract_id": head.creation_contract_id,
            "creation_hash": head.creation_hash,
            "style_contract_id": head.style_contract_id,
            "style_hash": head.style_hash,
        }

    async def read_active_draft(self, _session, project_id):
        rows = [
            row for row in self.drafts.values()
            if row["project_id"] == project_id and row["active_slot"] == 1
        ]
        assert len(rows) <= 1
        return deepcopy(rows[0]) if rows else None

    async def lock_active_draft(self, session, project_id):
        self.events.append("lock-active-draft")
        return await self.read_active_draft(session, project_id)

    async def read_draft(self, _session, project_id, draft_id):
        row = self.drafts.get((project_id, draft_id))
        return deepcopy(row)

    async def insert_draft(self, _session, row):
        key = (row["project_id"], row["id"])
        if key in self.drafts or any(
            existing["project_id"] == row["project_id"]
            and existing["active_slot"] == 1
            for existing in self.drafts.values()
        ):
            return False
        self.drafts[key] = deepcopy(row)
        self.write_count += 1
        return True

    async def deactivate_active_draft(
        self,
        _session,
        project_id,
        draft_id,
        expected_version,
        content_hash,
    ):
        row = self.drafts.get((project_id, draft_id))
        if (
            row is None
            or row["active_slot"] != 1
            or row["draft_version"] != expected_version
            or row["content_hash"] != content_hash
        ):
            return False
        row["active_slot"] = None
        self.write_count += 1
        return True

    async def cas_update_draft(self, _session, row, expected_version):
        key = (row["project_id"], row["id"])
        current = self.drafts.get(key)
        if (
            current is None
            or current["active_slot"] != 1
            or current["draft_version"] != expected_version
        ):
            return False
        self.drafts[key] = deepcopy(row)
        self.write_count += 1
        return True

    async def read_bible_head(self, _session, project_id):
        return deepcopy(self.heads.get(project_id))

    async def lock_bible_head(self, session, project_id):
        self.events.append("lock-bible-head")
        return await self.read_bible_head(session, project_id)

    async def read_confirmation_request(
        self, _session, project_id, idempotency_key
    ):
        return deepcopy(self.requests.get((project_id, idempotency_key)))

    async def insert_confirmation_request(self, _session, row):
        key = (row["project_id"], row["idempotency_key"])
        if key in self.requests:
            return False
        self.requests[key] = deepcopy(row) | {
            "status": "reserved",
            "bible_revision_id": None,
            "result_revision": None,
            "result_hash": None,
            "public_error_code": None,
            "completed_at": None,
        }
        self.write_count += 1
        return True

    async def insert_revision(self, _session, row):
        key = (row["project_id"], row["revision"])
        if key in self.revisions:
            return False
        self.revisions[key] = deepcopy(row)
        self.write_count += 1
        return True

    async def cas_bible_head(self, _session, row):
        current = self.heads.get(row["project_id"])
        if current is None or current["revision"] != row["base_revision"]:
            return False
        self.heads[row["project_id"]] = {
            "project_id": row["project_id"],
            "revision": row["revision"],
            "bible_revision_id": row["bible_revision_id"],
            "content_hash": row["content_hash"],
            "updated_at": row["updated_at"],
        }
        self.write_count += 1
        return True

    async def succeed_confirmation_request(self, _session, row):
        key = (row["project_id"], row["idempotency_key"])
        current = self.requests.get(key)
        if (
            current is None
            or current["status"] != "reserved"
            or current["request_hash"] != row["request_hash"]
        ):
            return False
        current.update(
            {
                "status": "succeeded",
                "bible_revision_id": row["bible_revision_id"],
                "result_revision": row["result_revision"],
                "result_hash": row["result_hash"],
                "public_error_code": None,
                "completed_at": row["completed_at"],
            }
        )
        self.write_count += 1
        return True

    async def read_revision(self, _session, project_id, revision):
        return deepcopy(self.revisions.get((project_id, revision)))

    async def list_revisions(
        self,
        _session,
        project_id,
        *,
        before_revision,
        limit,
    ):
        rows = [
            {"revision": revision}
            for (candidate_project, revision) in self.revisions
            if candidate_project == project_id
            and (before_revision is None or revision < before_revision)
        ]
        return sorted(
            rows,
            key=lambda item: item["revision"],
            reverse=True,
        )[: limit + 1]


class BibleHarness:
    def __init__(self, *, failpoint=lambda _stage: None):
        self.repository = MemoryBibleRepository()
        self.contract_service = FakeContractService()
        self.repository.contract_service = self.contract_service
        self._lock = asyncio.Lock()
        ids = iter(
            f"90000000-0000-0000-0000-{number:012d}"
            for number in range(1, 100)
        )
        self.service = BibleService(
            self.repository,
            contract_service=self.contract_service,
            transaction_factory=self.transaction,
            connection_factory=self.connection,
            id_factory=lambda: next(ids),
            clock=lambda: 1_900_000_000_500,
            failpoint=failpoint,
        )

    @asynccontextmanager
    async def transaction(self):
        async with self._lock:
            snapshot = deepcopy(self.repository.__dict__)
            observed_events = self.repository.events
            contract_service = self.repository.contract_service
            try:
                yield object()
            except BaseException:
                self.repository.__dict__.clear()
                self.repository.__dict__.update(snapshot)
                self.repository.events = observed_events
                self.repository.contract_service = contract_service
                raise

    @asynccontextmanager
    async def connection(self):
        yield object()


@pytest.mark.asyncio
async def test_missing_and_current_draft_use_only_the_canonical_contract_head_basis():
    harness = BibleHarness()

    missing = await harness.service.get_draft("p1")
    saved = await harness.service.save_draft(
        SaveBibleDraft("p1", 0, bible_payload())
    )

    assert missing.status == "missing"
    assert missing.can_edit is True
    assert missing.payload is None
    assert saved.status == "current"
    assert saved.draft_version == 1
    assert saved.can_edit is saved.can_confirm is True
    assert saved.basis.selection_revision == 1
    assert saved.basis.seed_id == "seed-a"
    assert saved.basis.creation_contract_id == "creation-a"
    assert saved.basis.style_contract_id == "style-a"
    assert saved.basis.binding_revision_id is None
    assert saved.basis.binding_hash is None
    assert harness.contract_service.calls == ["p1", "p1"]


@pytest.mark.asyncio
async def test_contract_not_ready_blocks_manual_save_without_model_readiness_rules():
    harness = BibleHarness()
    harness.contract_service.heads["p1"] = {
        "project_id": "p1",
        "revision": 0,
        "has_contract": False,
        "contract_ready": False,
        "reasons": ("contract_missing",),
    }

    with pytest.raises(BiblePreconditionFailed):
        await harness.service.save_draft(
            SaveBibleDraft("p1", 0, bible_payload())
        )

    assert harness.repository.write_count == 0


@pytest.mark.asyncio
async def test_mutation_rechecks_locked_selection_and_contract_head_after_canonical_read():
    harness = BibleHarness()
    harness.repository.locked_contract_head_override = {
        "revision": 1,
        "creation_contract_id": "creation-a",
        "creation_hash": HASH_B,
        "style_contract_id": "style-a",
        "style_hash": HASH_D,
    }

    with pytest.raises(BibleConflict):
        await harness.service.save_draft(
            SaveBibleDraft("p1", 0, bible_payload())
        )

    assert harness.repository.events[:3] == [
        "lock-project",
        "lock-selected-seed",
        "lock-contract-head",
    ]
    assert harness.repository.write_count == 0


@pytest.mark.asyncio
async def test_superseded_draft_is_read_only_and_expected_zero_creates_a_new_row():
    harness = BibleHarness()
    first = await harness.service.save_draft(
        SaveBibleDraft("p1", 0, bible_payload())
    )
    harness.contract_service.heads["p1"] = contract_head(
        selection_revision=2,
        seed_id="seed-b",
        seed_revision_id="seed-revision-b",
        seed_hash=HASH_D,
        revision=2,
        creation_contract_id="creation-b",
        creation_hash=HASH_E,
        style_contract_id="style-b",
        style_hash=HASH_A,
    )

    superseded = await harness.service.get_draft("p1")
    with pytest.raises(BibleConflict):
        await harness.service.save_draft(
            SaveBibleDraft("p1", first.draft_version, bible_payload())
        )
    second = await harness.service.save_draft(
        SaveBibleDraft(
            "p1",
            0,
            bible_payload(protagonist="新的当前分支将重新设计主角选择。"),
        )
    )
    visible_after_replacement = await harness.service.get_draft("p1")

    assert superseded.status == "superseded"
    assert superseded.can_edit is superseded.can_confirm is False
    assert superseded.can_clone is True
    assert "selection_revision_changed" in superseded.reasons
    assert first.draft_id != second.draft_id
    assert visible_after_replacement.draft_id == second.draft_id
    assert harness.repository.drafts[("p1", first.draft_id)]["active_slot"] is None
    assert harness.repository.drafts[("p1", second.draft_id)]["active_slot"] == 1


@pytest.mark.asyncio
async def test_a_to_b_to_a_never_reactivates_the_old_selection_generation():
    harness = BibleHarness()
    first = await harness.service.save_draft(
        SaveBibleDraft("p1", 0, bible_payload())
    )
    harness.contract_service.heads["p1"] = contract_head(
        selection_revision=2,
        seed_id="seed-b",
        seed_revision_id="seed-revision-b",
        seed_hash=HASH_D,
        revision=2,
        creation_contract_id="creation-b",
        creation_hash=HASH_E,
        style_contract_id="style-b",
        style_hash=HASH_A,
    )
    assert (await harness.service.get_draft("p1")).status == "superseded"
    harness.contract_service.heads["p1"] = contract_head(
        selection_revision=3,
        seed_id="seed-a",
        seed_revision_id="seed-revision-a",
        seed_hash=HASH_A,
        revision=3,
        creation_contract_id="creation-a3",
        creation_hash=HASH_B,
        style_contract_id="style-a3",
        style_hash=HASH_C,
    )

    returned = await harness.service.get_draft("p1")
    replacement = await harness.service.save_draft(
        SaveBibleDraft("p1", 0, bible_payload())
    )

    assert returned.status == "superseded"
    assert returned.basis.selection_revision == 1
    assert replacement.basis.selection_revision == 3
    assert replacement.draft_id != first.draft_id


@pytest.mark.asyncio
async def test_style_only_contract_drift_supersedes_without_deleting_the_source():
    harness = BibleHarness()
    first = await harness.service.save_draft(
        SaveBibleDraft("p1", 0, bible_payload())
    )
    harness.contract_service.heads["p1"] = contract_head(
        style_contract_id="style-a-adjusted",
        style_hash=HASH_D,
    )

    old = await harness.service.get_draft("p1")
    replacement = await harness.service.save_draft(
        SaveBibleDraft("p1", 0, bible_payload())
    )

    assert old.status == "superseded"
    assert "style_contract_changed" in old.reasons
    assert ("p1", first.draft_id) in harness.repository.drafts
    assert replacement.basis.style_contract_id == "style-a-adjusted"


@pytest.mark.asyncio
async def test_archived_project_reads_are_preserved_with_all_mutation_capabilities_false():
    harness = BibleHarness()
    harness.repository.projects["p1"]["archived_at"] = 123

    draft = await harness.service.get_draft("p1")
    head = await harness.service.get_head("p1")
    history = await harness.service.history("p1")

    assert draft.status == head.status == "missing"
    assert draft.can_edit is draft.can_confirm is draft.can_clone is False
    assert head.can_clone is False
    assert history.items == ()
    assert "project_archived" in draft.reasons
    for operation in (
        harness.service.save_draft(
            SaveBibleDraft("p1", 0, bible_payload())
        ),
        harness.service.clone_draft(
            CloneBibleDraft("p1", source_revision=1)
        ),
        harness.service.confirm(
            ConfirmBible("p1", "archived-confirm", 1, 0)
        ),
    ):
        with pytest.raises(ProjectArchived):
            await operation
    assert harness.repository.write_count == 0


@pytest.mark.asyncio
async def test_confirmation_is_atomic_immutable_and_same_request_replays():
    harness = BibleHarness()
    saved = await harness.service.save_draft(
        SaveBibleDraft("p1", 0, bible_payload())
    )
    command = ConfirmBible("p1", "confirm-1", saved.draft_version, 0)

    first = await harness.service.confirm(command)
    replay = await harness.service.confirm(command)

    assert replay == first
    assert first.revision == 1
    assert first.status == "current"
    assert first.content_hash == canonical_bible_hash(bible_payload())
    assert harness.repository.heads["p1"]["revision"] == 1
    assert harness.repository.drafts[("p1", saved.draft_id)]["active_slot"] is None
    assert harness.repository.requests[("p1", "confirm-1")]["status"] == "succeeded"
    assert len(harness.repository.revisions) == 1
    with pytest.raises(BibleConflict):
        await harness.service.confirm(
            ConfirmBible("p1", "confirm-1", saved.draft_version + 1, 0)
        )


@pytest.mark.asyncio
async def test_confirmation_enforces_head_cas_without_retrying():
    harness = BibleHarness()
    saved = await harness.service.save_draft(
        SaveBibleDraft("p1", 0, bible_payload())
    )

    with pytest.raises(BibleConflict):
        await harness.service.confirm(
            ConfirmBible("p1", "wrong-head", saved.draft_version, 1)
        )

    assert harness.repository.heads["p1"]["revision"] == 0
    assert harness.repository.drafts[("p1", saved.draft_id)]["active_slot"] == 1
    assert ("p1", "wrong-head") not in harness.repository.requests


@pytest.mark.asyncio
async def test_failed_confirmation_request_replays_the_same_safe_failure():
    harness = BibleHarness()
    saved = await harness.service.save_draft(
        SaveBibleDraft("p1", 0, bible_payload())
    )
    command = ConfirmBible("p1", "failed-1", saved.draft_version, 0)
    request_hash = canonical_hash(
        {
            "projectId": "p1",
            "draftId": saved.draft_id,
            "draftVersion": saved.draft_version,
            "draftHash": saved.content_hash,
            "expectedHeadRevision": 0,
        }
    )
    harness.repository.requests[("p1", "failed-1")] = {
        "id": "failed-request-id",
        "project_id": "p1",
        "selection_revision": saved.basis.selection_revision,
        "contract_revision": saved.basis.contract_revision,
        "creation_contract_id": saved.basis.creation_contract_id,
        "creation_hash": saved.basis.creation_hash,
        "style_contract_id": saved.basis.style_contract_id,
        "style_hash": saved.basis.style_hash,
        "draft_id": saved.draft_id,
        "draft_version": saved.draft_version,
        "draft_hash": saved.content_hash,
        "idempotency_key": "failed-1",
        "request_hash": request_hash,
        "status": "failed",
        "bible_revision_id": None,
        "result_revision": None,
        "result_hash": None,
        "public_error_code": "BibleConfirmationFailed",
        "created_at": 1,
        "completed_at": 2,
    }
    writes = harness.repository.write_count

    with pytest.raises(BibleConfirmationFailed):
        await harness.service.confirm(command)
    with pytest.raises(BibleConflict):
        await harness.service.confirm(
            ConfirmBible("p1", "failed-1", saved.draft_version, 1)
        )

    assert harness.repository.write_count == writes
    assert harness.repository.drafts[("p1", saved.draft_id)]["active_slot"] == 1


@pytest.mark.asyncio
async def test_confirmation_failpoint_rolls_back_revision_head_request_and_slot():
    harness = BibleHarness(
        failpoint=lambda stage: (
            (_ for _ in ()).throw(RuntimeError("rollback sentinel"))
            if stage == "after_head_advance"
            else None
        )
    )
    saved = await harness.service.save_draft(
        SaveBibleDraft("p1", 0, bible_payload())
    )

    with pytest.raises(RuntimeError, match="rollback sentinel"):
        await harness.service.confirm(
            ConfirmBible("p1", "rollback-1", saved.draft_version, 0)
        )

    assert harness.repository.heads["p1"]["revision"] == 0
    assert harness.repository.revisions == {}
    assert harness.repository.requests == {}
    assert harness.repository.drafts[("p1", saved.draft_id)]["active_slot"] == 1


@pytest.mark.asyncio
async def test_explicit_clone_supports_superseded_draft_and_confirmed_revision_sources():
    harness = BibleHarness()
    first = await harness.service.save_draft(
        SaveBibleDraft("p1", 0, bible_payload())
    )
    confirmed = await harness.service.confirm(
        ConfirmBible("p1", "clone-source-confirm", first.draft_version, 0)
    )

    cloned_revision = await harness.service.clone_draft(
        CloneBibleDraft("p1", source_revision=confirmed.revision)
    )
    assert cloned_revision.draft_id != first.draft_id
    assert cloned_revision.base_head_revision == 1
    assert cloned_revision.draft_version == 1
    assert cloned_revision.content_hash == confirmed.content_hash

    updated = await harness.service.save_draft(
        SaveBibleDraft(
            "p1",
            cloned_revision.draft_version,
            bible_payload(protagonist="下一版将让主角采取更审慎的未来策略。"),
        )
    )
    second = await harness.service.confirm(
        ConfirmBible("p1", "confirm-adjustment", updated.draft_version, 1)
    )
    history = await harness.service.history("p1")

    assert second.revision == 2
    assert tuple(item.revision for item in history.items) == (2, 1)
    assert history.items[0].status == "current"
    assert history.items[1].status == "superseded"
    assert harness.repository.revisions[("p1", 1)]["content_hash"] == (
        confirmed.content_hash
    )

    harness.contract_service.heads["p1"] = contract_head(
        selection_revision=2,
        seed_id="seed-b",
        seed_revision_id="seed-revision-b",
        seed_hash=HASH_D,
        revision=2,
        creation_contract_id="creation-b",
        creation_hash=HASH_E,
        style_contract_id="style-b",
        style_hash=HASH_A,
    )
    superseded = await harness.service.get_draft("p1")
    assert superseded.status == "missing"
    source = await harness.service.clone_draft(
        CloneBibleDraft("p1", source_revision=1)
    )
    harness.contract_service.heads["p1"] = contract_head(
        selection_revision=3,
        seed_id="seed-a",
        seed_revision_id="seed-revision-a",
        seed_hash=HASH_A,
        revision=3,
        creation_contract_id="creation-a3",
        creation_hash=HASH_B,
        style_contract_id="style-a3",
        style_hash=HASH_C,
    )
    source_view = await harness.service.get_draft("p1")
    cloned_draft = await harness.service.clone_draft(
        CloneBibleDraft("p1", source_draft_id=source.draft_id)
    )

    assert source_view.status == "superseded"
    assert cloned_draft.draft_id != source.draft_id
    assert cloned_draft.basis.selection_revision == 3
    assert cloned_draft.payload == source.payload


@pytest.mark.asyncio
async def test_missing_project_and_invalid_history_inputs_are_stable_domain_errors():
    harness = BibleHarness()

    with pytest.raises(BibleNotFound):
        await harness.service.get_head("missing")
    with pytest.raises(BiblePreconditionFailed):
        await harness.service.history("p1", limit=0)
    with pytest.raises(BiblePreconditionFailed):
        await harness.service.get_history_revision("p1", 0)
