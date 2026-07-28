from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.repositories.chapter_sessions import ActiveChapterSessionConflict
from backend.services.chapter_outlines import (
    ChapterOutlineConflict,
    ChapterOutlineService,
    CreateChapterOutlineDraft,
    authoritative_chapter,
)


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
