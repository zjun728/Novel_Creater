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


def current_bootstrap_payload() -> dict:
    return {
        "project_id": "project-1",
        "requested_chapter": 3,
        "authoritative_chapter": 3,
        "mode": "current",
        "volume": volume(),
        "session": None,
        "final_chapter": None,
        "outline": outline(),
        "available_actions": (),
        "blocked_reasons": (),
        "canon_revision": 2,
        "projection_revision": 2,
        "canon_projection_synchronized": True,
    }


@pytest.mark.parametrize(
    ("volume_ref", "outline_ref"),
    ((volume(), None), (None, outline())),
)
def test_current_bootstrap_rejects_partial_authority_bundle(
    volume_ref: WorkbenchVolumeReference | None,
    outline_ref: WorkbenchOutlineReference | None,
) -> None:
    payload = current_bootstrap_payload()
    payload.update(volume=volume_ref, outline=outline_ref)

    with pytest.raises(ValidationError, match="authority bundle"):
        WorkbenchBootstrap.model_validate(payload)


def test_current_session_requires_confirmed_outline_and_volume() -> None:
    payload = current_bootstrap_payload()
    payload.update(
        volume=None,
        outline=None,
        session=WorkbenchSessionReference(id="session-3", chapter_number=3),
        available_actions=("edit_draft",),
    )

    with pytest.raises(ValidationError, match="session.*authority bundle"):
        WorkbenchBootstrap.model_validate(payload)


def test_create_session_requires_confirmed_outline_and_volume() -> None:
    payload = current_bootstrap_payload()
    payload.update(
        volume=None,
        outline=None,
        available_actions=("create_session",),
        blocked_reasons=(WorkbenchBlockedReason(
            code="outline_required", message="需要先确认章节大纲。",
        ),),
    )

    with pytest.raises(ValidationError, match="create_session.*authority bundle"):
        WorkbenchBootstrap.model_validate(payload)


def test_current_without_confirmed_authority_remains_blocked_and_unassigned() -> None:
    payload = current_bootstrap_payload()
    payload.update(
        volume=None,
        outline=None,
        blocked_reasons=(WorkbenchBlockedReason(
            code="outline_required", message="需要先确认章节大纲。",
        ),),
    )

    value = WorkbenchBootstrap.model_validate(payload)

    assert value.volume is None
    assert value.outline is None
    assert value.available_actions == ()


@pytest.mark.parametrize(
    ("canon_revision", "projection_revision", "synchronized", "blocked_reasons"),
    (
        (3, 2, False, ()),
        (2, 2, True, (WorkbenchBlockedReason(
            code="canon_projection_unsynchronized",
            message="Canon 与当前状态尚未同步。",
        ),)),
    ),
)
def test_sync_blocker_must_match_head_synchronization(
    canon_revision: int,
    projection_revision: int,
    synchronized: bool,
    blocked_reasons: tuple[WorkbenchBlockedReason, ...],
) -> None:
    payload = current_bootstrap_payload()
    payload.update(
        canon_revision=canon_revision,
        projection_revision=projection_revision,
        canon_projection_synchronized=synchronized,
        blocked_reasons=blocked_reasons,
    )

    with pytest.raises(ValidationError, match="blocked reason"):
        WorkbenchBootstrap.model_validate(payload)


def test_unsynchronized_heads_cannot_offer_session_creation() -> None:
    payload = current_bootstrap_payload()
    payload.update(
        canon_revision=3,
        projection_revision=2,
        canon_projection_synchronized=False,
        available_actions=("create_session",),
        blocked_reasons=(WorkbenchBlockedReason(
            code="canon_projection_unsynchronized",
            message="Canon 与当前状态尚未同步。",
        ),),
    )

    with pytest.raises(ValidationError, match="create_session.*synchronized"):
        WorkbenchBootstrap.model_validate(payload)


def test_active_session_remains_valid_after_global_heads_diverge() -> None:
    payload = current_bootstrap_payload()
    payload.update(
        session=WorkbenchSessionReference(id="session-3", chapter_number=3),
        available_actions=("edit_draft",),
        canon_revision=3,
        projection_revision=2,
        canon_projection_synchronized=False,
        blocked_reasons=(WorkbenchBlockedReason(
            code="canon_projection_unsynchronized",
            message="Canon 与当前状态尚未同步。",
        ),),
    )

    value = WorkbenchBootstrap.model_validate(payload)

    assert value.session is not None
    assert value.available_actions == ("edit_draft",)


@pytest.mark.parametrize(
    ("authoritative_chapter", "unassigned_chapter", "contains_authority"),
    (
        (None, None, True),
        (None, 3, False),
        (3, None, False),
        (3, 3, True),
    ),
)
def test_volume_summary_list_rejects_inexact_authority_location(
    authoritative_chapter: int | None,
    unassigned_chapter: int | None,
    contains_authority: bool,
) -> None:
    with pytest.raises(ValidationError, match="authority"):
        WorkbenchVolumeSummaryList(
            project_id="project-1",
            volumes=(WorkbenchVolumeSummary(
                volume=volume(), finalized_chapter_count=2,
                first_finalized_chapter=1, last_finalized_chapter=2,
                contains_authoritative_chapter=contains_authority,
            ),),
            authoritative_chapter=authoritative_chapter,
            unassigned_authoritative_chapter=unassigned_chapter,
        )


def test_volume_summary_list_accepts_exactly_one_located_authority() -> None:
    value = WorkbenchVolumeSummaryList(
        project_id="project-1",
        volumes=(WorkbenchVolumeSummary(
            volume=volume(), finalized_chapter_count=2,
            first_finalized_chapter=1, last_finalized_chapter=2,
            contains_authoritative_chapter=True,
        ),),
        authoritative_chapter=2,
        unassigned_authoritative_chapter=None,
    )

    assert value.volumes[0].contains_authoritative_chapter is True


def test_current_chapter_must_be_last_in_volume_index() -> None:
    with pytest.raises(ValidationError, match="current.*last"):
        WorkbenchChapterIndexPage(
            project_id="project-1",
            volume=volume(),
            chapters=(
                WorkbenchChapterIndexItem(
                    chapter_number=2, title="第二章", mode="current",
                    scalar_count=None, finalized_at_ms=None,
                    final_chapter_id=None, session_id="session-2",
                ),
                WorkbenchChapterIndexItem(
                    chapter_number=3, title="第三章", mode="historical",
                    scalar_count=3200, finalized_at_ms=1000,
                    final_chapter_id="final-3", session_id=None,
                ),
            ),
            next_cursor=None,
            limit=100,
        )


@pytest.mark.parametrize(
    ("count", "first", "last"),
    ((1, 1, 2), (2, 1, 1), (3, 1, 2)),
)
def test_volume_summary_rejects_inconsistent_count_and_range(
    count: int,
    first: int,
    last: int,
) -> None:
    with pytest.raises(ValidationError, match="finalized"):
        WorkbenchVolumeSummary(
            volume=volume(),
            finalized_chapter_count=count,
            first_finalized_chapter=first,
            last_finalized_chapter=last,
            contains_authoritative_chapter=False,
        )


def test_volume_summary_allows_gaps_inside_finalized_range() -> None:
    value = WorkbenchVolumeSummary(
        volume=volume(),
        finalized_chapter_count=2,
        first_finalized_chapter=1,
        last_finalized_chapter=3,
        contains_authoritative_chapter=False,
    )

    assert value.finalized_chapter_count == 2


def test_current_without_bundle_requires_outline_blocker() -> None:
    payload = current_bootstrap_payload()
    payload.update(volume=None, outline=None)

    with pytest.raises(ValidationError, match="outline_required"):
        WorkbenchBootstrap.model_validate(payload)


@pytest.mark.parametrize(
    "blocked_reasons",
    (
        (),
        (WorkbenchBlockedReason(
            code="session_not_created", message="尚未创建章节会话。",
        ),),
    ),
)
def test_ready_current_without_session_requires_explicit_create_action(
    blocked_reasons: tuple[WorkbenchBlockedReason, ...],
) -> None:
    payload = current_bootstrap_payload()
    payload.update(blocked_reasons=blocked_reasons)

    with pytest.raises(ValidationError, match="create_session"):
        WorkbenchBootstrap.model_validate(payload)


def test_current_bundle_rejects_outline_blocker_with_create_action() -> None:
    payload = current_bootstrap_payload()
    payload.update(
        available_actions=("create_session",),
        blocked_reasons=(WorkbenchBlockedReason(
            code="outline_required", message="需要先确认章节大纲。",
        ),),
    )

    with pytest.raises(ValidationError, match="outline_required"):
        WorkbenchBootstrap.model_validate(payload)


def test_current_session_bundle_rejects_outline_blocker() -> None:
    payload = current_bootstrap_payload()
    payload.update(
        session=WorkbenchSessionReference(id="session-3", chapter_number=3),
        available_actions=("edit_draft",),
        blocked_reasons=(WorkbenchBlockedReason(
            code="outline_required", message="需要先确认章节大纲。",
        ),),
    )

    with pytest.raises(ValidationError, match="outline_required"):
        WorkbenchBootstrap.model_validate(payload)


@pytest.mark.parametrize(
    ("block_code", "canon_revision", "projection_revision", "synchronized"),
    (
        ("project_archived", 2, 2, True),
        ("canon_projection_unsynchronized", 3, 2, False),
    ),
)
def test_real_creation_blocker_suppresses_create_action(
    block_code: str,
    canon_revision: int,
    projection_revision: int,
    synchronized: bool,
) -> None:
    payload = current_bootstrap_payload()
    payload.update(
        canon_revision=canon_revision,
        projection_revision=projection_revision,
        canon_projection_synchronized=synchronized,
        blocked_reasons=(WorkbenchBlockedReason(
            code=block_code,
            message="当前状态暂不可创建章节会话。",
        ),),
    )

    value = WorkbenchBootstrap.model_validate(payload)

    assert "create_session" not in value.available_actions


def test_session_not_created_keeps_create_action_explicit() -> None:
    payload = current_bootstrap_payload()
    payload.update(
        available_actions=("create_session",),
        blocked_reasons=(WorkbenchBlockedReason(
            code="session_not_created", message="尚未创建章节会话。",
        ),),
    )

    value = WorkbenchBootstrap.model_validate(payload)

    assert "create_session" in value.available_actions


def test_current_last_item_cannot_have_next_cursor() -> None:
    with pytest.raises(ValidationError, match="current.*cursor"):
        WorkbenchChapterIndexPage(
            project_id="project-1",
            volume=volume(),
            chapters=(WorkbenchChapterIndexItem(
                chapter_number=2, title="第二章", mode="current",
                scalar_count=None, finalized_at_ms=None,
                final_chapter_id=None, session_id="session-2",
            ),),
            next_cursor="cursor-2",
            limit=100,
        )


def test_historical_only_page_may_have_next_cursor() -> None:
    page = WorkbenchChapterIndexPage(
        project_id="project-1",
        volume=volume(),
        chapters=(WorkbenchChapterIndexItem(
            chapter_number=1, title="第一章", mode="historical",
            scalar_count=3200, finalized_at_ms=1000,
            final_chapter_id="final-1", session_id=None,
        ),),
        next_cursor="cursor-1",
        limit=100,
    )

    assert page.next_cursor == "cursor-1"


def test_current_session_rejects_session_not_created_blocker() -> None:
    payload = current_bootstrap_payload()
    payload.update(
        session=WorkbenchSessionReference(id="session-3", chapter_number=3),
        available_actions=("edit_draft",),
        blocked_reasons=(WorkbenchBlockedReason(
            code="session_not_created", message="尚未创建章节会话。",
        ),),
    )

    with pytest.raises(ValidationError, match="session_not_created"):
        WorkbenchBootstrap.model_validate(payload)


@pytest.mark.parametrize(
    "forbidden_action",
    (
        "edit_draft",
        "run_ai_operation",
        "save_candidate",
        "audit_candidate",
        "finalize_candidate",
    ),
)
def test_archived_current_session_rejects_mutating_actions(
    forbidden_action: str,
) -> None:
    payload = current_bootstrap_payload()
    payload.update(
        session=WorkbenchSessionReference(id="session-3", chapter_number=3),
        available_actions=(forbidden_action,),
        blocked_reasons=(WorkbenchBlockedReason(
            code="project_archived", message="项目已归档。",
        ),),
    )

    with pytest.raises(ValidationError, match="project_archived"):
        WorkbenchBootstrap.model_validate(payload)


def test_archived_current_session_allows_safe_read_actions() -> None:
    payload = current_bootstrap_payload()
    safe_actions = ("view_chapter", "view_outline", "compare_candidates")
    payload.update(
        session=WorkbenchSessionReference(id="session-3", chapter_number=3),
        available_actions=safe_actions,
        blocked_reasons=(WorkbenchBlockedReason(
            code="project_archived", message="项目已归档。",
        ),),
    )

    value = WorkbenchBootstrap.model_validate(payload)

    assert value.available_actions == safe_actions


@pytest.mark.parametrize(
    "forbidden_action",
    ("run_ai_operation", "audit_candidate", "finalize_candidate"),
)
def test_unsynchronized_current_session_rejects_head_sensitive_actions(
    forbidden_action: str,
) -> None:
    payload = current_bootstrap_payload()
    payload.update(
        session=WorkbenchSessionReference(id="session-3", chapter_number=3),
        available_actions=(forbidden_action,),
        canon_revision=3,
        projection_revision=2,
        canon_projection_synchronized=False,
        blocked_reasons=(WorkbenchBlockedReason(
            code="canon_projection_unsynchronized",
            message="Canon 与当前状态尚未同步。",
        ),),
    )

    with pytest.raises(
        ValidationError, match="canon_projection_unsynchronized",
    ):
        WorkbenchBootstrap.model_validate(payload)


def test_unsynchronized_current_session_preserves_pinned_safe_actions() -> None:
    payload = current_bootstrap_payload()
    safe_actions = (
        "view_chapter",
        "view_outline",
        "edit_draft",
        "save_candidate",
        "compare_candidates",
    )
    payload.update(
        session=WorkbenchSessionReference(id="session-3", chapter_number=3),
        available_actions=safe_actions,
        canon_revision=3,
        projection_revision=2,
        canon_projection_synchronized=False,
        blocked_reasons=(WorkbenchBlockedReason(
            code="canon_projection_unsynchronized",
            message="Canon 与当前状态尚未同步。",
        ),),
    )

    value = WorkbenchBootstrap.model_validate(payload)

    assert value.available_actions == safe_actions


def test_finalization_in_progress_requires_current_session() -> None:
    payload = current_bootstrap_payload()
    payload.update(blocked_reasons=(WorkbenchBlockedReason(
        code="finalization_in_progress", message="定稿流程正在进行。",
    ),))

    with pytest.raises(ValidationError, match="finalization_in_progress"):
        WorkbenchBootstrap.model_validate(payload)


def test_finalization_in_progress_rejects_new_audit_action() -> None:
    payload = current_bootstrap_payload()
    payload.update(
        session=WorkbenchSessionReference(id="session-3", chapter_number=3),
        available_actions=("audit_candidate",),
        blocked_reasons=(WorkbenchBlockedReason(
            code="finalization_in_progress", message="定稿流程正在进行。",
        ),),
    )

    with pytest.raises(ValidationError, match="audit_candidate"):
        WorkbenchBootstrap.model_validate(payload)


def test_finalization_in_progress_preserves_existing_session_actions() -> None:
    payload = current_bootstrap_payload()
    allowed_actions = (
        "view_chapter",
        "view_outline",
        "edit_draft",
        "run_ai_operation",
        "save_candidate",
        "compare_candidates",
        "finalize_candidate",
    )
    payload.update(
        session=WorkbenchSessionReference(id="session-3", chapter_number=3),
        available_actions=allowed_actions,
        blocked_reasons=(WorkbenchBlockedReason(
            code="finalization_in_progress", message="定稿流程正在进行。",
        ),),
    )

    value = WorkbenchBootstrap.model_validate(payload)

    assert value.available_actions == allowed_actions


@pytest.mark.parametrize(
    "changes",
    (
        {
            "available_actions": ("create_session",),
            "blocked_reasons": (WorkbenchBlockedReason(
                code="future_chapter", message="该章节尚未成为当前权威章节。",
            ),),
        },
        {
            "session": WorkbenchSessionReference(
                id="session-3", chapter_number=3,
            ),
            "available_actions": ("edit_draft",),
            "blocked_reasons": (WorkbenchBlockedReason(
                code="future_chapter", message="该章节尚未成为当前权威章节。",
            ),),
        },
        {
            "volume": None,
            "outline": None,
            "blocked_reasons": (
                WorkbenchBlockedReason(
                    code="outline_required", message="需要先确认章节大纲。",
                ),
                WorkbenchBlockedReason(
                    code="future_chapter", message="该章节尚未成为当前权威章节。",
                ),
            ),
        },
    ),
)
def test_current_mode_rejects_future_chapter_blocker(changes: dict) -> None:
    payload = current_bootstrap_payload()
    payload.update(changes)

    with pytest.raises(ValidationError, match="future_chapter"):
        WorkbenchBootstrap.model_validate(payload)


def historical_bootstrap_payload() -> dict:
    return {
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


@pytest.mark.parametrize(
    "block_code",
    (
        "future_chapter",
        "outline_required",
        "session_not_created",
        "finalization_in_progress",
    ),
)
def test_historical_mode_rejects_incompatible_blocker(block_code: str) -> None:
    payload = historical_bootstrap_payload()
    payload.update(blocked_reasons=(WorkbenchBlockedReason(
        code=block_code, message="该阻塞原因不适用于历史章节。",
    ),))

    with pytest.raises(ValidationError, match="historical.*blocked reason"):
        WorkbenchBootstrap.model_validate(payload)


@pytest.mark.parametrize(
    ("blocked_reasons", "canon_revision", "projection_revision", "synchronized"),
    (
        (
            (WorkbenchBlockedReason(
                code="project_archived", message="项目已归档。",
            ),),
            2, 2, True,
        ),
        (
            (WorkbenchBlockedReason(
                code="canon_projection_unsynchronized",
                message="Canon 与当前状态尚未同步。",
            ),),
            3, 2, False,
        ),
    ),
)
def test_historical_mode_accepts_compatible_blockers(
    blocked_reasons: tuple[WorkbenchBlockedReason, ...],
    canon_revision: int,
    projection_revision: int,
    synchronized: bool,
) -> None:
    payload = historical_bootstrap_payload()
    payload.update(
        blocked_reasons=blocked_reasons,
        canon_revision=canon_revision,
        projection_revision=projection_revision,
        canon_projection_synchronized=synchronized,
    )

    value = WorkbenchBootstrap.model_validate(payload)

    assert value.blocked_reasons == blocked_reasons


def future_bootstrap_payload() -> dict:
    return {
        "project_id": "project-1",
        "requested_chapter": 5,
        "authoritative_chapter": 3,
        "mode": "future",
        "volume": None,
        "session": None,
        "final_chapter": None,
        "outline": None,
        "available_actions": (),
        "blocked_reasons": (WorkbenchBlockedReason(
            code="future_chapter", message="该章节尚未成为当前权威章节。",
        ),),
        "canon_revision": 2,
        "projection_revision": 2,
        "canon_projection_synchronized": True,
    }


@pytest.mark.parametrize(
    "block_code",
    ("outline_required", "session_not_created", "finalization_in_progress"),
)
def test_future_mode_rejects_incompatible_blocker(block_code: str) -> None:
    payload = future_bootstrap_payload()
    payload.update(blocked_reasons=(
        *payload["blocked_reasons"],
        WorkbenchBlockedReason(
            code=block_code, message="该阻塞原因不适用于未来章节。",
        ),
    ))

    with pytest.raises(ValidationError, match="future.*blocked reason"):
        WorkbenchBootstrap.model_validate(payload)


@pytest.mark.parametrize(
    ("extra_reason", "canon_revision", "projection_revision", "synchronized"),
    (
        (
            WorkbenchBlockedReason(
                code="project_archived", message="项目已归档。",
            ),
            2, 2, True,
        ),
        (
            WorkbenchBlockedReason(
                code="canon_projection_unsynchronized",
                message="Canon 与当前状态尚未同步。",
            ),
            3, 2, False,
        ),
    ),
)
def test_future_mode_accepts_compatible_optional_blocker(
    extra_reason: WorkbenchBlockedReason,
    canon_revision: int,
    projection_revision: int,
    synchronized: bool,
) -> None:
    payload = future_bootstrap_payload()
    payload.update(
        blocked_reasons=(*payload["blocked_reasons"], extra_reason),
        canon_revision=canon_revision,
        projection_revision=projection_revision,
        canon_projection_synchronized=synchronized,
    )

    value = WorkbenchBootstrap.model_validate(payload)

    assert value.blocked_reasons[-1] == extra_reason
