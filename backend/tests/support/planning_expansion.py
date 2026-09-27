"""Controlled review fixture, real outline/session/finalization transactions.

Only for an explicitly guarded disposable database. This does not test model review.
"""
import time
from hashlib import sha256
from uuid import uuid4
from types import SimpleNamespace

from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.domain.finalization import FinalizationChangeSet, QualityReportPayload, change_set_hash
from backend.domain.json_contracts import canonical_hash
from backend.repositories.canon import CanonRepository
from backend.repositories.chapter_outlines import ChapterOutlineRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.finalization import FinalizationRepository
from backend.repositories.planning import PlanningRepository
from backend.services.canon import CanonService
from backend.services.chapter_outlines import ChapterOutlineService, CreateChapterOutlineDraft, SaveChapterOutlineDraft, ConfirmChapterOutlineDraft
from backend.services.chapter_sessions import ChapterSessionService, CreateChapterSession, SaveWorkingDraft, SaveDraftCandidate
from backend.services.finalization import FinalizationService, PrepareFinalization
from backend.services.finalization_commit import AtomicFinalizationService, CommitFinalization
from backend.services.planning import PlanningService
from backend.tests.support.disposable_mysql import assert_disposable_name


async def finalize_active_block_fixture(tx, project_id):
    async with tx() as session:
        assert_disposable_name((await session.fetchone("SELECT DATABASE() AS name"))["name"])
        authority = await PlanningRepository().read_expansion_authority(session, project_id)
        maximum = await ChapterSessionRepository().read_max_final_chapter_number(session, project_id)
    number = (maximum or 0) + 1
    canon = authority["projection"]["canon_revision_number"]
    state = await PlanningService(PlanningRepository(), transaction_factory=tx).get_state(project_id)
    planning = state.future_plan
    block = next(b for b in planning.story_blocks if b.id == planning.active_story_block_id)
    volume = next(v for v in planning.volumes if v.id == block.volume_id)
    stage = next(s for s in block.stages if s.lifecycle == "active")
    task = next(t for t in stage.scene_tasks if t.lifecycle == "active")
    ref = lambda n: {"id": n.id, "revision": n.revision, "contentHash": n.content_hash}
    outlines = ChapterOutlineService(ChapterOutlineRepository(), ChapterSessionRepository(), transaction_factory=tx)
    async with tx() as session:
        existing_outline = await ChapterOutlineRepository().read_outline_head(session, project_id, number)
    if existing_outline:
        outline = SimpleNamespace(revision=existing_outline["revision"], content_hash=existing_outline["content_hash"])
    else:
        draft = await outlines.create_draft(CreateChapterOutlineDraft(project_id, number))
        payload = EditableChapterOutlineContent.model_validate({
            "schemaVersion": "chapter-outline-draft-v1", "volumeRef": ref(volume), "storyBlockRef": ref(block),
            "stageRefs": [ref(stage)], "sceneTaskRefs": [ref(task)], "chapterGoal": block.block_goal,
            "expectedCharacters": list(block.involved_characters), "continuation": [],
            "plannedTasks": [task.task], "scenes": [stage.title], "forbiddenEarlyEvents": [],
        })
        saved = await outlines.save_draft(SaveChapterOutlineDraft(project_id, number, draft.draft_id, draft.draft_revision, draft.content_hash, payload))
        outline = await outlines.confirm_draft(ConfirmChapterOutlineDraft(project_id, number, saved.draft_id,
            saved.draft_revision, saved.content_hash, 0, str(uuid4())))
    writing = ChapterSessionService(ChapterSessionRepository(), transaction_factory=tx)
    workspace = await writing.create_session(CreateChapterSession(project_id, number, state.head.revision,
        state.head.content_hash, outline.revision, outline.content_hash, canon))
    content = "这是隔离验收用的受控正文。" + block.block_goal + "。作者确认这一故事块的任务已经完成。"
    workspace = await writing.save_working_draft(SaveWorkingDraft(project_id, workspace.session.id,
        workspace.working_draft.revision, workspace.working_draft.content_hash, content))
    candidate = await writing.save_candidate(SaveDraftCandidate(project_id, workspace.session.id,
        workspace.working_draft.revision, workspace.working_draft.content_hash, str(uuid4())))
    session_id = workspace.session.id
    now = int(time.time() * 1000)
    key, attempt_id, report_id = canonical_hash(str(uuid4())), str(uuid4()), str(uuid4())
    repository = FinalizationRepository()
    changes = FinalizationChangeSet.model_validate({
        "schemaVersion": "finalization-changeset-v1", "title": f"受控验收第{number}章", "summary": block.block_goal,
        "existingEntityIds": [], "entities": [], "aliases": [], "canonEvents": [],
        "storyProgressEvents": [{"id": str(uuid4()), "targetType": "story_block", "targetId": block.id,
            "status": "completed", "evidence": {"startScalar": 0, "endScalar": len(content),
                "excerptHash": sha256(content.encode()).hexdigest(), "confidence": 1.0, "rationale": "受控验收进度"}}],
        "planningPatches": [], "planningSuggestions": [],
    })
    payload = changes.model_dump(mode="json", by_alias=True)
    evidence = payload["storyProgressEvents"][0]["evidence"]
    for child_stage in block.stages:
        if child_stage.lifecycle != "active":
            continue
        payload["storyProgressEvents"].append({"id": str(uuid4()), "targetType": "stage",
            "targetId": child_stage.id, "status": "completed", "evidence": evidence})
        for child_task in child_stage.scene_tasks:
            if child_task.lifecycle == "active":
                payload["storyProgressEvents"].append({"id": str(uuid4()), "targetType": "scene_task",
                    "targetId": child_task.id, "status": "completed", "evidence": evidence})
    changes = FinalizationChangeSet.model_validate(payload)
    async with tx() as session:
        snapshot = await repository.load_preparation_context(session, project_id, number)
        prepare = PrepareFinalization(project_id=project_id, chapter_session_id=session_id,
            candidate_id=candidate.saved_candidate_id, candidate_hash=workspace.working_draft.content_hash,
            expected_canon_revision=canon, expected_planning_hash=planning.content_hash,
            expected_outline_hash=outline.content_hash, idempotency_key=key)
        manifest = FinalizationService._context_manifest(prepare, number, snapshot)
        manifest_hash = canonical_hash(manifest)
        await repository.insert_preparing_attempt(session, {
            "id": attempt_id, "project_id": project_id, "chapter_session_id": session_id,
            "draft_candidate_id": candidate.saved_candidate_id, "idempotency_key": key,
            "request_fingerprint": FinalizationService.request_fingerprint(prepare, snapshot, number),
            "candidate_hash": workspace.working_draft.content_hash, "expected_canon_revision": canon,
            "expected_planning_hash": planning.content_hash, "expected_outline_hash": outline.content_hash,
            "context_manifest": manifest, "context_manifest_hash": manifest_hash, "created_at": now, "updated_at": now,
        })
        report = QualityReportPayload.model_validate({"status": "completed", "deterministicBlocks": [], "findings": []})
        await repository.insert_quality_report(session, {
            "id": report_id, "project_id": project_id, "chapter_session_id": session_id,
            "draft_candidate_id": candidate.saved_candidate_id, "candidate_hash": workspace.working_draft.content_hash,
            "expected_canon_revision": canon, "expected_planning_hash": planning.content_hash,
            "expected_outline_hash": outline.content_hash, "policy_version": "quality-v1",
            "context_manifest_hash": manifest_hash, "provider_id": None, "provider_profile_revision": None,
            "model_name_snapshot": None, "status": "completed", "deterministic_blocks": [], "findings": [],
            "content_hash": canonical_hash(report.model_dump(mode="json", by_alias=True)), "created_at": now,
        })
        revision_hash = change_set_hash(changes)
        await repository.insert_change_set_revision(session, {"id": str(uuid4()), "project_id": project_id,
            "change_set_id": attempt_id, "revision": 1, "change_set": changes, "content_hash": revision_hash,
            "source": "extraction", "created_at": now})
        assert await repository.publish_awaiting_author(session, project_id=project_id, session_id=session_id,
            change_set_id=attempt_id, report_id=report_id, extraction_id="controlled-fixture", revision=1,
            revision_hash=revision_hash, updated_at=now)
        assert await repository.confirm_current_revision(session, project_id=project_id, session_id=session_id,
            change_set_id=attempt_id, revision=1, revision_hash=revision_hash, confirmed_at=now)
    finalizer = AtomicFinalizationService(transaction_factory=tx, repository=repository,
        planning_repository=PlanningRepository(), canon_committer=CanonService(CanonRepository(), transaction_factory=tx),
        clock=lambda: int(time.time() * 1000))
    return await finalizer.commit(CommitFinalization(project_id=project_id, chapter_session_id=session_id,
        idempotency_key=canonical_hash(str(uuid4())), expected_revision=1, expected_revision_hash=revision_hash))
