from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.http_errors import ProjectArchived
from backend.repositories.chapter_sessions import ActiveChapterSessionConflict
from backend.services.chapter_outlines import (
    ChapterOutlineConflict,
    ChapterOutlineService,
    CreateChapterOutlineDraft,
    authoritative_chapter,
)

HASH = "a" * 64


def test_editable_chapter_outline_is_closed_and_contains_only_author_fields():
    content = EditableChapterOutlineContent()

    assert content.model_dump(mode="json", by_alias=True) == {
        "schemaVersion": "chapter-outline-draft-v1",
        "volumeRef": None,
        "storyBlockRef": None,
        "stageRefs": [],
        "sceneTaskRefs": [],
        "chapterGoal": "",
        "expectedCharacters": [],
        "continuation": [],
        "plannedTasks": [],
        "scenes": [],
        "forbiddenEarlyEvents": [],
    }
    with pytest.raises(ValidationError):
        EditableChapterOutlineContent.model_validate(
            {
                "schemaVersion": "chapter-outline-draft-v1",
                "chapterNumber": 7,
            }
        )


@pytest.mark.parametrize(
    ("active_session", "max_final", "expected"),
    (
        (None, None, 1),
        (None, 7, 8),
        ({"chapter_num": 4}, 7, 4),
    ),
)
def test_authoritative_chapter_uses_session_then_final_history(
    active_session,
    max_final,
    expected,
):
    assert authoritative_chapter(active_session, max_final) == expected


def test_create_command_has_no_client_authority_or_idempotency_fields():
    command = CreateChapterOutlineDraft("project-1", 3)

    assert command.project_id == "project-1"
    assert command.chapter_number == 3
    assert set(command.__dataclass_fields__) == {
        "project_id",
        "chapter_number",
    }


def test_current_target_path_is_the_url_encoded_authoritative_writer_route():
    assert ChapterOutlineService._writer_path("project / 一", 8) == (
        "/projects/project%20%2F%20%E4%B8%80/write/chapters/8"
    )


class _Transaction:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _ReadableProjectRepository:
    async def lock_project(self, session, project_id):
        return {"id": project_id, "archived_at": None}

    async def read_project_any(self, session, project_id):
        return {"id": project_id, "archived_at": None}


class _SplitActiveSessionRepository:
    async def read_active_session(self, session, project_id):
        raise ActiveChapterSessionConflict(
            "raw SQL rows contain AUTHORITY-SPLIT-SENTINEL"
        )


@pytest.mark.asyncio
async def test_current_read_maps_split_active_session_to_outline_conflict():
    service = ChapterOutlineService(
        _ReadableProjectRepository(),
        _SplitActiveSessionRepository(),
        transaction_factory=_Transaction,
    )

    with pytest.raises(
        ChapterOutlineConflict,
        match="active ChapterSession authority is inconsistent",
    ) as caught:
        await service.get_current("project-1")

    assert "AUTHORITY-SPLIT-SENTINEL" not in str(caught.value)
    assert caught.value.__cause__ is None


class _OutlineStateRepository:
    def __init__(self, calls):
        self.calls = calls
        self.project = {"id": "project-1", "archived_at": None}
        self.authorities = {
            "planning_revision_id": "planning-1",
            "planning_revision": 1,
            "planning_hash": HASH,
            "planning_content": {},
            "canon_revision": 0,
            "projection_revision": 0,
            "projection_hash": HASH,
        }
        content = EditableChapterOutlineContent().model_dump(
            mode="json",
            by_alias=True,
        )
        self.draft = {
            "id": "outline-draft-1",
            "project_id": "project-1",
            "chapter_num": 1,
            "base_head_revision": 0,
            "draft_revision": 1,
            "content_hash": HASH,
            "content": content,
            "status": "active",
            "active_slot": 1,
            "planning_revision_id": "planning-1",
            "planning_revision": 1,
            "planning_hash": HASH,
            "canon_revision": 0,
            "projection_revision": 0,
            "projection_hash": HASH,
        }
        self.pending_attempt = None

    async def lock_project(self, _session, project_id):
        self.calls.append("project-lock")
        if self.project["archived_at"] is not None:
            raise ProjectArchived()
        return self.project if project_id == "project-1" else None

    async def read_project_any(self, _session, project_id):
        self.calls.append("project-read")
        return self.project if project_id == "project-1" else None

    async def read_current_authorities(self, _session, project_id):
        return self.authorities if project_id == "project-1" else None

    async def read_outline_head(self, _session, _project_id, _chapter_number):
        return None

    async def read_active_draft(
        self,
        _session,
        _project_id,
        _chapter_number,
    ):
        return self.draft

    async def read_active_attempt(self, _session, _draft_id):
        return self.pending_attempt


class _OutlineStateChapterRepository:
    def __init__(self, calls):
        self.calls = calls
        self.active_session = None
        self.session = None

    async def read_active_session(self, _session, _project_id):
        self.calls.append("active-session-read")
        return self.active_session

    async def read_max_final_chapter_number(self, _session, _project_id):
        self.calls.append("final-chapter-read")
        return None

    async def read_chapter_session(
        self,
        _session,
        _project_id,
        _chapter_number,
    ):
        return self.session


class _OutlineStatePlanningRepository:
    def __init__(self, calls):
        self.calls = calls
        self.binding_reads = 0
        self.basis = {
            "selection_revision": 1,
            "seed_id": "seed-1",
            "seed_revision_id": "seed-revision-1",
            "seed_hash": HASH,
            "contract_revision": 1,
            "creation_contract_id": "contract-1",
            "creation_hash": HASH,
            "style_contract_id": "style-1",
            "style_hash": HASH,
            "bible_revision": 1,
            "bible_revision_id": "bible-1",
            "bible_hash": HASH,
            "chapter_capacity_policy": {
                "targetMin": 2_000,
                "targetMax": 3_000,
                "softCeiling": 3_000,
            },
        }
        self.head = {
            "revision": 1,
            "planning_revision_id": "planning-1",
            "content_hash": HASH,
            **{
                key: value
                for key, value in self.basis.items()
                if key != "chapter_capacity_policy"
            },
        }
        self.binding = {
            "binding_revision_id": "binding-1",
            "binding_revision": 1,
            "binding_hash": HASH,
            "binding_task_key": "planning",
            "resolution_status": "bound",
            "provider_id": "provider-1",
            "model_name_snapshot": "test-model",
            "id": "provider-1",
            "provider_type": "openai-compatible",
            "model_name": "test-model",
            "base_url": "https://provider.invalid/v1",
            "api_key": "TEST_ONLY_PRIVATE_KEY",
            "enabled": 1,
            "lifecycle_status": "active",
            "revision": 1,
            "temperature": 0.4,
            "max_context_tokens": 100_000,
            "max_output_tokens": 8_000,
        }

    async def read_current_basis(self, _session, _project_id):
        return self.basis

    async def lock_planning_head(self, _session, _project_id):
        self.calls.append("planning-head-lock")
        return self.head

    async def lock_planning_binding(self, _session, _project_id):
        self.calls.append("planning-binding-lock")
        self.binding_reads += 1
        return self.binding


def _outline_state_service():
    calls = []
    outline = _OutlineStateRepository(calls)
    chapter = _OutlineStateChapterRepository(calls)
    planning = _OutlineStatePlanningRepository(calls)
    service = ChapterOutlineService(
        outline,
        chapter,
        transaction_factory=_Transaction,
        planning_repository=planning,
    )
    return service, outline, chapter, planning, calls


def _active_session_row():
    node_ref = {"id": "node-1", "revision": 1, "contentHash": HASH}
    outline = {
        "schemaVersion": "chapter-outline-v1",
        "chapterNumber": 1,
        "planningRevisionId": "planning-1",
        "planningRevision": 1,
        "planningHash": HASH,
        "volumeRef": node_ref,
        "storyBlockRef": node_ref,
        "stageRefs": [node_ref],
        "sceneTaskRefs": [node_ref],
        "chapterGoal": "推进当前故事块。",
        "expectedCharacters": [],
        "continuation": [],
        "plannedTasks": [],
        "scenes": ["完成当前场景。"],
        "forbiddenEarlyEvents": [],
        "capacityPolicy": {
            "targetMin": 2_000,
            "targetMax": 3_000,
            "softCeiling": 3_000,
        },
        "canonRevision": 0,
        "projectionRevision": 0,
        "projectionHash": HASH,
        "contentHash": HASH,
    }
    return {
        "id": "session-1",
        "chapter_num": 1,
        "status": "active",
        "planning_revision_id": "planning-1",
        "planning_revision": 1,
        "planning_hash": HASH,
        "chapter_outline_revision_id": "outline-1",
        "chapter_outline_revision": 1,
        "chapter_outline_hash": HASH,
        "outline_canon_revision": 0,
        "outline_projection_revision": 0,
        "outline_projection_hash": HASH,
        "chapter_outline": outline,
    }


@pytest.mark.asyncio
async def test_current_draft_can_generate_when_planning_binding_is_ready():
    service, _outline, _chapter, planning, _calls = _outline_state_service()

    state = await service.get_current("project-1")

    assert state.draft is not None
    assert state.draft.status == "current"
    assert state.capabilities.generate is True
    assert planning.binding_reads == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "blocked_by",
    (
        "model-unready",
        "archived",
        "pending-operation",
        "active-session",
        "authority-invalid",
        "projection-mismatch",
    ),
)
async def test_generation_capability_fails_closed(blocked_by):
    service, outline, chapter, planning, _calls = _outline_state_service()
    if blocked_by == "model-unready":
        planning.binding["enabled"] = 0
    elif blocked_by == "archived":
        outline.project["archived_at"] = 123
    elif blocked_by == "pending-operation":
        outline.pending_attempt = {
            "operation_id": "operation-1",
            "status": "pending",
        }
    elif blocked_by == "active-session":
        chapter.active_session = {"chapter_num": 1}
        chapter.session = _active_session_row()
    elif blocked_by == "authority-invalid":
        planning.basis = None
    elif blocked_by == "projection-mismatch":
        outline.authorities["canon_revision"] = 1
        outline.draft["canon_revision"] = 1

    state = await service.get_current("project-1")

    assert state.capabilities.generate is False


@pytest.mark.asyncio
async def test_current_state_locks_project_before_planning_authorities():
    service, _outline, _chapter, _planning, calls = _outline_state_service()

    await service.get_current("project-1")

    assert calls == [
        "project-lock",
        "active-session-read",
        "final-chapter-read",
        "planning-head-lock",
        "planning-binding-lock",
    ]


@pytest.mark.asyncio
async def test_archived_state_falls_back_to_read_after_project_lock():
    service, outline, _chapter, _planning, calls = _outline_state_service()
    outline.project["archived_at"] = 123

    state = await service.get_current("project-1")

    assert calls[:2] == ["project-lock", "project-read"]
    assert state.lifecycle == "archived"
    assert state.capabilities.generate is False
