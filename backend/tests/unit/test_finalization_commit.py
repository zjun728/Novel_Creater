from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import sha256

import pytest

from backend.domain.finalization import FinalizationChangeSet, change_set_hash
from backend.domain.json_contracts import canonical_hash
from backend.domain.planning import (
    DraftPlanningAggregate,
    normalize_planning_aggregate,
)
from backend.services.finalization_commit import (
    AtomicFinalizationService,
    CommitFinalization,
    FinalizationCommitInvalid,
    apply_planning_patches,
    build_canon_commit,
)
from backend.services.canon import CommitCanonResult


HASH_A = "a" * 64
HASH_B = "b" * 64


def _planning():
    draft = DraftPlanningAggregate.model_validate({
        "activeStoryBlockRef": "block",
        "volumes": [{
            "clientNodeKey": "volume", "order": 1, "title": "第一卷",
            "coreChange": "逃亡转为立足。", "mainPressure": "追兵逼近。",
            "ensembleFocus": ["主角"], "forbiddenEvents": [],
        }],
        "plots": [{
            "clientNodeKey": "plot", "order": 1, "title": "追查",
            "plotType": "mystery", "storyQuestion": "幕后人是谁？",
            "futureDirection": "寻找线索。", "expectedPayoff": "揭示内应。",
            "relatedCharacters": ["主角"],
        }],
        "storyBlocks": [{
            "clientNodeKey": "block", "order": 1, "title": "入城",
            "volumeRef": "volume", "plotRefs": ["plot"],
            "entrySituation": "城门封锁。", "blockGoal": "进入城中。",
            "mainPressure": "追兵将至。", "expectedChange": "取得身份。",
            "openQuestions": [], "involvedCharacters": ["主角"],
            "stages": [{
                "clientNodeKey": "stage", "order": 1, "title": "过门",
                "purpose": "通过盘查。", "dramaticQuestion": "会暴露吗？",
                "sceneTasks": [{
                    "clientNodeKey": "task", "order": 1,
                    "task": "应对盘查。", "completionEvidence": "成功入城。",
                }],
            }],
        }],
    })
    ids = iter(("volume-1", "plot-1", "block-1", "stage-1", "task-1"))
    return normalize_planning_aggregate(
        draft, previous_confirmed=None, previous_draft=None,
        id_factory=ids.__next__,
    )


def _evidence(content="正文证据"):
    return {
        "startScalar": 0, "endScalar": 2,
        "excerptHash": sha256(content[:2].encode()).hexdigest(),
        "confidence": 1.0, "rationale": "正文直接证据。",
    }


def _change_set(planning, *, patch_target="plot-1"):
    plot = planning.plots[0]
    return FinalizationChangeSet.model_validate({
        "schemaVersion": "finalization-changeset-v1",
        "title": "第一章", "summary": "主角成功入城。",
        "existingEntityIds": [],
        "entities": [{
            "id": "entity-new", "entityType": "person",
            "canonicalName": "守门人",
        }],
        "aliases": [{
            "id": "alias-new", "entityId": "entity-new", "alias": "老卒",
        }],
        "canonEvents": [{
            "id": "event-new", "entityId": "entity-new",
            "factKind": "dynamic_event", "fieldPath": "location",
            "value": "城门", "evidence": _evidence(),
            "effectiveStartChapter": 1, "effectiveEndChapter": None,
            "assertionOperator": "equals", "valueCardinality": "single",
        }],
        "storyProgressEvents": [{
            "id": "progress-new", "targetType": "story_block",
            "targetId": "block-1", "status": "advanced",
            "evidence": _evidence(),
        }],
        "planningPatches": [{
            "id": "patch-new", "targetType": "plot",
            "targetId": patch_target, "expectedRevision": plot.revision,
            "expectedHash": plot.content_hash,
            "fieldPath": "futureDirection", "replacement": "追查城内接头人。",
            "evidence": _evidence(),
        }],
        "planningSuggestions": [],
    })


def test_build_canon_commit_reuses_closed_events_and_projects_progress():
    planning = _planning()
    request = build_canon_commit(
        _change_set(planning),
        project_id="project-1", expected_head=0,
        idempotency_key=HASH_A, source_id="attempt-1", chapter_number=1,
    )

    assert request.project_id == "project-1"
    assert request.source_type == "finalization"
    assert request.entities[0].id == "entity-new"
    assert request.aliases[0].entity_id == "entity-new"
    assert request.events[0].event.field_path == "location"
    progress = request.events[1].event
    assert progress.field_path == "plot.progress.story_block.block-1"
    assert progress.value == {
        "chapterNumber": 1, "status": "advanced",
        "targetId": "block-1", "targetType": "story_block",
    }


def test_apply_planning_patches_revisions_only_changed_future_node():
    planning = _planning()
    change_set = _change_set(planning)

    updated = apply_planning_patches(
        planning, change_set.planning_patches, implemented_ids=frozenset(),
    )

    assert updated is not planning
    assert updated.content_hash != planning.content_hash
    assert updated.plots[0].future_direction == "追查城内接头人。"
    assert updated.plots[0].revision == planning.plots[0].revision + 1
    assert updated.volumes[0] == planning.volumes[0]
    assert updated.story_blocks[0] == planning.story_blocks[0]


def test_planning_patch_rejects_implemented_or_stale_target():
    planning = _planning()
    payload = _change_set(planning).model_dump(by_alias=True, mode="json")
    block = planning.story_blocks[0]
    payload["planningPatches"][0].update({
        "targetType": "story_block", "targetId": block.id,
        "expectedRevision": block.revision, "expectedHash": block.content_hash,
        "fieldPath": "expectedChange", "replacement": "违规回改。",
    })
    patch = FinalizationChangeSet.model_validate(payload).planning_patches

    with pytest.raises(FinalizationCommitInvalid):
        apply_planning_patches(
            planning, patch, implemented_ids=frozenset({block.id}),
        )

    stale = payload
    stale["planningPatches"][0]["expectedRevision"] += 1
    with pytest.raises(FinalizationCommitInvalid):
        apply_planning_patches(
            planning,
            FinalizationChangeSet.model_validate(stale).planning_patches,
            implemented_ids=frozenset(),
        )


class _Transactions:
    def __init__(self):
        self.sessions = []

    @asynccontextmanager
    async def __call__(self):
        session = object()
        self.sessions.append(session)
        yield session


class _FinalizationRepository:
    def __init__(self, planning, change_set):
        self.planning = planning
        self.change_set = change_set
        self.records = []
        self.chapters = []
        self.states = []
        self.project_chapters = []
        self.record_by_key = None
        self.record_by_session = None
        candidate_content = "正文证据。" * 20
        basis = {
            "schemaVersion": "draft-candidate-basis-v1",
            "outlineRevisionId": "outline-revision-1", "outlineRevision": 1,
            "outlineHash": HASH_B,
            "planningRevisionId": "planning-revision-1", "planningRevision": 1,
            "planningHash": planning.content_hash,
            "canonRevision": 0, "projectionRevision": 0,
            "projectionHash": HASH_A,
        }
        self.candidate = {
            "id": "candidate-1", "project_id": "project-1",
            "chapter_session_id": "session-1", "content": candidate_content,
            "content_hash": sha256(candidate_content.encode()).hexdigest(),
            "basis_hash": canonical_hash(basis), "provenance": basis,
        }
        self.session = {
            "id": "session-1", "project_id": "project-1", "chapter_num": 1,
            "status": "drafting", "active_draft_operation_id": None,
            "expected_canon_revision": 0,
            "planning_revision_id": "planning-revision-1",
            "planning_revision": 1, "planning_hash": planning.content_hash,
            "chapter_outline_revision_id": "outline-revision-1",
            "chapter_outline_revision": 1, "chapter_outline_hash": HASH_B,
            "working_draft_content_hash": self.candidate["content_hash"],
        }
        self.current = {
            "canon_revision": 0, "projection_revision": 0,
            "projection_hash": HASH_A,
            "planning_revision_id": "planning-revision-1",
            "planning_revision": 1, "planning_hash": planning.content_hash,
            "outline_revision_id": "outline-revision-1",
            "outline_revision": 1, "outline_hash": HASH_B,
        }
        self.outline = {
            "schemaVersion": "chapter-outline-v1", "chapterNumber": 1,
            "planningRevisionId": "planning-revision-1", "planningRevision": 1,
            "planningHash": planning.content_hash,
            "volumeRef": _ref(planning.volumes[0]),
            "storyBlockRef": _ref(planning.story_blocks[0]),
            "stageRefs": [_ref(planning.story_blocks[0].stages[0])],
            "sceneTaskRefs": [_ref(planning.story_blocks[0].stages[0].scene_tasks[0])],
            "chapterGoal": "进入城中。", "expectedCharacters": ["主角"],
            "continuation": [], "plannedTasks": ["应对盘查。"],
            "scenes": ["城门"], "forbiddenEarlyEvents": [],
            "capacityPolicy": {"targetMin": 1, "targetMax": 2, "softCeiling": 3},
            "canonRevision": 0, "projectionRevision": 0,
            "projectionHash": HASH_A, "contentHash": HASH_B,
        }
        self.snapshot = {
            "canon_context": {
                "revision": 0, "projectionHash": HASH_A, "entities": [],
                "currentState": [],
            },
            "planning_context": {
                "id": "planning-revision-1", "revision": 1,
                "contentHash": planning.content_hash,
                "content": planning.model_dump(by_alias=True, mode="json"),
            },
            "outline_context": {
                "id": "outline-revision-1", "revision": 1,
                "contentHash": HASH_B, "content": self.outline,
            },
            "contract_context": {"revision": 1, "contentHash": HASH_A, "content": {}, "style": {}},
            "bible_context": {"revision": 1, "contentHash": HASH_B, "content": {}},
            "policy_version": "quality-v1", "reference_sources": [],
            "audit_binding": None, "extraction_binding": None,
        }
        from backend.services.finalization import FinalizationService, PrepareFinalization
        frozen = PrepareFinalization(
            project_id="project-1", chapter_session_id="session-1",
            candidate_id="candidate-1", candidate_hash=self.candidate["content_hash"],
            expected_canon_revision=0, expected_planning_hash=planning.content_hash,
            expected_outline_hash=HASH_B, idempotency_key=HASH_A,
        )
        manifest = FinalizationService._context_manifest(frozen, 1, self.snapshot)
        self.attempt = {
            "id": "attempt-1", "project_id": "project-1",
            "chapter_session_id": "session-1", "draft_candidate_id": "candidate-1",
            "idempotency_key": HASH_A,
            "request_fingerprint": FinalizationService.request_fingerprint(frozen, self.snapshot, 1),
            "candidate_hash": self.candidate["content_hash"],
            "expected_canon_revision": 0,
            "expected_planning_hash": planning.content_hash,
            "expected_outline_hash": HASH_B,
            "context_manifest_hash": canonical_hash(manifest),
            "status": "awaiting_author", "active_slot": 1,
            "current_revision": 1, "current_revision_hash": change_set_hash(change_set),
            "confirmed_revision": 1, "confirmed_revision_hash": change_set_hash(change_set),
        }

    async def lock_project(self, session, project_id): return {"id": project_id}
    async def lock_session(self, session, project_id, session_id): return self.session
    async def lock_current_authority(self, session, project_id, chapter_number): return self.current
    async def load_preparation_context(self, session, project_id, chapter_number): return self.snapshot
    async def lock_candidate(self, session, project_id, session_id, candidate_id): return self.candidate
    async def lock_latest_attempt(self, session, project_id, session_id): return self.attempt
    async def lock_change_set_revision(self, session, project_id, attempt_id, revision, content_hash):
        if revision == 1 and content_hash == change_set_hash(self.change_set):
            return {"change_set": self.change_set, "content_hash": content_hash}
        return None
    async def lock_commit_by_key(self, session, project_id, key): return self.record_by_key
    async def lock_commit_by_session(self, session, project_id, session_id): return self.record_by_session
    async def list_finalized_outline_contents(self, session, project_id): return ()
    async def insert_finalization_record(self, session, row): self.records.append((session, row))
    async def insert_final_chapter(self, session, row): self.chapters.append((session, row))
    async def mark_committing(self, session, **row): self.states.append((session, "committing")); return True
    async def mark_committed(self, session, **row): self.states.append((session, "committed")); return True
    async def finalize_session(self, session, **row): self.states.append((session, "final")); return True
    async def advance_project_chapter(self, session, **row):
        self.project_chapters.append((session, row))
        return True


class _PlanningRepository:
    def __init__(self, planning):
        self.rows = []
        self.heads = []
        self.head = {
            "project_id": "project-1", "revision": 1,
            "planning_revision_id": "planning-revision-1",
            "content_hash": planning.content_hash,
            "content_json": planning.model_dump(by_alias=True, mode="json"),
            "selection_revision": 1, "seed_id": "seed-1",
            "seed_revision_id": "seed-revision-1", "seed_hash": HASH_A,
            "contract_revision": 1, "creation_contract_id": "contract-1",
            "creation_hash": HASH_A, "style_contract_id": "style-1",
            "style_hash": HASH_A, "bible_revision": 1,
            "bible_revision_id": "bible-1", "bible_hash": HASH_B,
        }

    async def lock_planning_head(self, session, project_id): return self.head
    async def insert_revision(self, session, row): self.rows.append((session, row)); return True
    async def advance_head_cas(self, session, row, expected_head): self.heads.append((session, row)); return True


class _CanonCommitter:
    def __init__(self):
        self.requests = []
        self.repository = self
        self.existing = None

    async def lock_head(self, session, project_id): return 0
    async def find_idempotent(self, session, project_id, key): return self.existing
    async def commit_locked(self, session, request):
        self.requests.append((session, request))
        return CommitCanonResult(
            revision_id="canon-revision-1", revision_number=1,
            projection_hash=HASH_B, idempotent=False,
        )


def _ref(node):
    return {"id": node.id, "revision": node.revision, "contentHash": node.content_hash}


def _commit_command(change_set):
    return CommitFinalization(
        project_id="project-1", chapter_session_id="session-1",
        idempotency_key=HASH_B, expected_revision=1,
        expected_revision_hash=change_set_hash(change_set),
    )


@pytest.mark.asyncio
async def test_atomic_commit_uses_one_transaction_and_persists_exact_candidate():
    planning = _planning()
    change_set = _change_set(planning)
    transactions = _Transactions()
    repository = _FinalizationRepository(planning, change_set)
    planning_repository = _PlanningRepository(planning)
    canon = _CanonCommitter()
    service = AtomicFinalizationService(
        transaction_factory=transactions, repository=repository,
        planning_repository=planning_repository, canon_committer=canon,
        id_factory=iter(("planning-revision-2", "record-1", "chapter-1")).__next__,
        clock=lambda: 123,
    )

    result = await service.commit(_commit_command(change_set))

    assert result.canon_revision == 1
    assert result.planning_revision == 2
    assert repository.chapters[0][1]["content"] == repository.candidate["content"]
    assert repository.chapters[0][1]["planning_revision"] == 1
    assert repository.project_chapters == [(
        transactions.sessions[0],
        {"project_id": "project-1", "chapter_number": 1, "updated_at": 123},
    )]
    assert planning_repository.rows[0][1]["content_hash"] != planning.content_hash
    assert {item[0] for item in repository.records + repository.chapters + repository.states} == {transactions.sessions[0]}
    assert canon.requests[0][0] is transactions.sessions[0]
    assert planning_repository.rows[0][0] is transactions.sessions[0]


@pytest.mark.asyncio
async def test_atomic_commit_replays_same_receipt_without_writes_and_rejects_session_rekey():
    planning = _planning()
    change_set = _change_set(planning)
    repository = _FinalizationRepository(planning, change_set)
    receipt = {
        "id": "record-1", "project_id": "project-1",
        "chapter_session_id": "session-1", "idempotency_key": HASH_B,
        "request_fingerprint": canonical_hash({
            "schemaVersion": "finalization-commit-request-v1",
            "projectId": "project-1", "chapterSessionId": "session-1",
            "expectedRevision": 1,
            "expectedRevisionHash": change_set_hash(change_set),
        }),
        "result": {
            "finalChapterId": "chapter-1", "canonRevision": 1,
            "projectionHash": HASH_B, "planningRevisionId": "planning-revision-2",
            "planningRevision": 2, "planningHash": HASH_A,
        },
    }
    repository.record_by_key = receipt
    repository.record_by_session = receipt
    service = AtomicFinalizationService(
        transaction_factory=_Transactions(), repository=repository,
        planning_repository=_PlanningRepository(planning),
        canon_committer=_CanonCommitter(), id_factory=lambda: "unused",
        clock=lambda: 123,
    )

    replay = await service.commit(_commit_command(change_set))
    assert replay.replayed is True
    assert repository.records == []

    repository.record_by_key = None
    with pytest.raises(FinalizationCommitInvalid):
        await service.commit(_commit_command(change_set))


@pytest.mark.asyncio
async def test_atomic_commit_rejects_unowned_canon_idempotency_collision_before_writes():
    planning = _planning()
    change_set = _change_set(planning)
    repository = _FinalizationRepository(planning, change_set)
    canon = _CanonCommitter()
    canon.existing = {
        "id": "unrelated", "revision_number": 1, "content_hash": HASH_A,
    }
    service = AtomicFinalizationService(
        transaction_factory=_Transactions(), repository=repository,
        planning_repository=_PlanningRepository(planning),
        canon_committer=canon, id_factory=lambda: "unused", clock=lambda: 123,
    )

    with pytest.raises(FinalizationCommitInvalid):
        await service.commit(_commit_command(change_set))

    assert repository.records == []
    assert canon.requests == []
