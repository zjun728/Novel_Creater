from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.services.chapter_outlines import (
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
