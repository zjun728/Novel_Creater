from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain.workbench import (
    WorkbenchBlockedReason,
    WorkbenchBootstrap,
    WorkbenchChapterIndexItem,
    WorkbenchChapterIndexPage,
    WorkbenchFinalChapterReference,
    WorkbenchOutlineReference,
    WorkbenchSessionReference,
    WorkbenchVolumeReference,
    WorkbenchVolumeSummary,
    WorkbenchVolumeSummaryList,
)


HASH = "a" * 64


def volume() -> WorkbenchVolumeReference:
    return WorkbenchVolumeReference(id="volume-1", order=1, title="第一卷")


def outline() -> WorkbenchOutlineReference:
    return WorkbenchOutlineReference(id="outline-1", revision=1, content_hash=HASH)


def test_historical_bootstrap_has_only_pinned_read_authorities() -> None:
    value = WorkbenchBootstrap(
        project_id="project-1",
        requested_chapter=2,
        authoritative_chapter=3,
        mode="historical",
        volume=volume(),
        session=None,
        final_chapter=WorkbenchFinalChapterReference(
            id="final-2", chapter_number=2, content_hash=HASH,
        ),
        outline=outline(),
        available_actions=("view_chapter", "view_outline"),
        blocked_reasons=(),
        canon_revision=2,
        projection_revision=2,
        canon_projection_synchronized=True,
    )

    assert value.mode == "historical"
    assert value.final_chapter.chapter_number == 2
    assert value.session is None


def test_current_bootstrap_may_offer_explicit_session_creation_only() -> None:
    value = WorkbenchBootstrap(
        project_id="project-1",
        requested_chapter=3,
        authoritative_chapter=3,
        mode="current",
        volume=volume(),
        session=None,
        final_chapter=None,
        outline=outline(),
        available_actions=("view_outline", "create_session"),
        blocked_reasons=(),
        canon_revision=2,
        projection_revision=2,
        canon_projection_synchronized=True,
    )

    assert value.available_actions == ("view_outline", "create_session")


def test_current_session_rejects_create_session_action() -> None:
    with pytest.raises(ValidationError, match="create_session"):
        WorkbenchBootstrap(
            project_id="project-1",
            requested_chapter=3,
            authoritative_chapter=3,
            mode="current",
            volume=volume(),
            session=WorkbenchSessionReference(id="session-3", chapter_number=3),
            final_chapter=None,
            outline=outline(),
            available_actions=("create_session", "edit_draft"),
            blocked_reasons=(),
            canon_revision=2,
            projection_revision=2,
            canon_projection_synchronized=True,
        )


def test_future_bootstrap_has_no_authority_refs_or_actions() -> None:
    value = WorkbenchBootstrap(
        project_id="project-1",
        requested_chapter=5,
        authoritative_chapter=3,
        mode="future",
        volume=None,
        session=None,
        final_chapter=None,
        outline=None,
        available_actions=(),
        blocked_reasons=(WorkbenchBlockedReason(
            code="future_chapter", message="该章节尚未成为当前权威章节。",
        ),),
        canon_revision=2,
        projection_revision=2,
        canon_projection_synchronized=True,
    )

    assert value.available_actions == ()


@pytest.mark.parametrize(
    "changes",
    (
        {"mode": "historical", "requested_chapter": 3},
        {"mode": "current", "requested_chapter": 2},
        {"mode": "future", "requested_chapter": 2},
    ),
)
def test_mode_must_match_server_authoritative_chapter(changes: dict) -> None:
    payload = {
        "project_id": "project-1",
        "requested_chapter": 2,
        "authoritative_chapter": 3,
        "mode": "historical",
        "volume": volume(),
        "session": None,
        "final_chapter": WorkbenchFinalChapterReference(
            id="final-2", chapter_number=2, content_hash=HASH,
        ),
        "outline": outline(),
        "available_actions": ("view_chapter",),
        "blocked_reasons": (),
        "canon_revision": 2,
        "projection_revision": 2,
        "canon_projection_synchronized": True,
    }
    payload.update(changes)

    with pytest.raises(ValidationError):
        WorkbenchBootstrap.model_validate(payload)


def test_sync_flag_is_derived_from_both_heads() -> None:
    with pytest.raises(ValidationError, match="synchronization"):
        WorkbenchBootstrap(
            project_id="project-1",
            requested_chapter=3,
            authoritative_chapter=3,
            mode="current",
            volume=None,
            session=None,
            final_chapter=None,
            outline=None,
            available_actions=(),
            blocked_reasons=(WorkbenchBlockedReason(
                code="canon_projection_unsynchronized",
                message="Canon 与当前状态尚未同步。",
            ),),
            canon_revision=3,
            projection_revision=2,
            canon_projection_synchronized=True,
        )


def test_volume_index_is_bounded_ordered_and_contains_at_most_one_current() -> None:
    page = WorkbenchChapterIndexPage(
        project_id="project-1",
        volume=volume(),
        chapters=(
            WorkbenchChapterIndexItem(
                chapter_number=1, title="第一章", mode="historical",
                scalar_count=3200, finalized_at_ms=1000,
                final_chapter_id="final-1", session_id=None,
            ),
            WorkbenchChapterIndexItem(
                chapter_number=2, title="第二章", mode="current",
                scalar_count=None, finalized_at_ms=None,
                final_chapter_id=None, session_id="session-2",
            ),
        ),
        next_cursor=None,
        limit=100,
    )

    assert [item.chapter_number for item in page.chapters] == [1, 2]
    assert set(WorkbenchChapterIndexItem.model_fields).isdisjoint(
        {"content", "planning", "outline"}
    )
    with pytest.raises(ValidationError):
        WorkbenchChapterIndexPage.model_validate(
            {**page.model_dump(), "limit": 101}, strict=True,
        )
    with pytest.raises(ValidationError, match="current"):
        WorkbenchChapterIndexPage(
            project_id="project-1", volume=volume(),
            chapters=(page.chapters[1], page.chapters[1].model_copy(
                update={"chapter_number": 3, "session_id": "session-3"}
            )),
            next_cursor=None, limit=100,
        )


def test_volume_summary_list_keeps_unassigned_authority_explicit() -> None:
    value = WorkbenchVolumeSummaryList(
        project_id="project-1",
        volumes=(WorkbenchVolumeSummary(
            volume=volume(), finalized_chapter_count=2,
            first_finalized_chapter=1, last_finalized_chapter=2,
            contains_authoritative_chapter=False,
        ),),
        authoritative_chapter=3,
        unassigned_authoritative_chapter=3,
    )

    assert value.unassigned_authoritative_chapter == 3
