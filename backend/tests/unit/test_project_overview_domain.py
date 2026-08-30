import pytest
from pydantic import ValidationError

from backend.domain.project_overview import (
    OverviewAchievement,
    OverviewContinuity,
    OverviewFinalChapter,
    OverviewModuleStates,
    OverviewProgress,
    OverviewProject,
    OverviewVolume,
    OverviewWriterCore,
    ProjectOverview,
)


def _project(**changes: object) -> OverviewProject:
    values: dict[str, object] = {
        "id": "project-1",
        "title": "The Glass Archive",
        "genre": "Science Fiction",
        "logline": "A memory keeper discovers that her own past was forged.",
        "target_words": 90_000,
        "target_chapters": 36,
        "updated_at_ms": 1_787_990_400_000,
        "lifecycle": "active",
    }
    values.update(changes)
    return OverviewProject(**values)  # type: ignore[arg-type]


def _progress(**changes: object) -> OverviewProgress:
    values: dict[str, object] = {
        "authoritative_chapter_number": 4,
        "current_volume": OverviewVolume(
            id="volume-1",
            order=1,
            title="The Stolen Past",
        ),
        "latest_final_chapter": OverviewFinalChapter(
            number=3,
            title="The Locked Room",
            finalized_at_ms=1_787_990_300_000,
        ),
        "finalized_chapter_count": 3,
        "finalized_scalar_count": 18_240,
    }
    values.update(changes)
    return OverviewProgress(**values)  # type: ignore[arg-type]


def _modules() -> OverviewModuleStates:
    return OverviewModuleStates(
        seed="current",
        contract="current",
        bible="needs_review",
        planning="pending_confirmation",
        outline="working_draft",
        writing="current",
    )


def _achievement(**changes: object) -> OverviewAchievement:
    values: dict[str, object] = {
        "kind": "final_chapter",
        "label": "Finalized Chapter 3",
        "occurred_at_ms": 1_787_990_300_000,
    }
    values.update(changes)
    return OverviewAchievement(**values)  # type: ignore[arg-type]


def _overview(**changes: object) -> ProjectOverview:
    values: dict[str, object] = {
        "project": _project(),
        "progress": _progress(),
        "modules": _modules(),
        "writer_core": OverviewWriterCore(
            canon_revision=17,
            projection_revision=17,
            synchronized=True,
        ),
        "continuity": OverviewContinuity(
            availability="available",
            pending_count=0,
        ),
        "recent_achievements": (_achievement(),),
    }
    values.update(changes)
    return ProjectOverview(**values)  # type: ignore[arg-type]


def test_complete_overview_serializes_to_exact_camel_case_response_shape():
    assert _overview().model_dump(mode="json", by_alias=True) == {
        "project": {
            "id": "project-1",
            "title": "The Glass Archive",
            "genre": "Science Fiction",
            "logline": "A memory keeper discovers that her own past was forged.",
            "targetWords": 90_000,
            "targetChapters": 36,
            "updatedAtMs": 1_787_990_400_000,
            "lifecycle": "active",
        },
        "progress": {
            "authoritativeChapterNumber": 4,
            "currentVolume": {
                "id": "volume-1",
                "order": 1,
                "title": "The Stolen Past",
            },
            "latestFinalChapter": {
                "number": 3,
                "title": "The Locked Room",
                "finalizedAtMs": 1_787_990_300_000,
            },
            "finalizedChapterCount": 3,
            "finalizedScalarCount": 18_240,
        },
        "modules": {
            "seed": "current",
            "contract": "current",
            "bible": "needs_review",
            "planning": "pending_confirmation",
            "outline": "working_draft",
            "writing": "current",
        },
        "writerCore": {
            "canonRevision": 17,
            "projectionRevision": 17,
            "synchronized": True,
        },
        "continuity": {
            "availability": "available",
            "pendingCount": 0,
        },
        "recentAchievements": [
            {
                "kind": "final_chapter",
                "label": "Finalized Chapter 3",
                "occurredAtMs": 1_787_990_300_000,
            }
        ],
    }


def test_overview_rejects_frontend_inferred_or_raw_authority_fields():
    forbidden = {
        "next_action",
        "target_path",
        "raw_json",
        "content_hash",
        "planning_json",
        "canon_events",
    }
    assert forbidden.isdisjoint(ProjectOverview.model_fields)
    with pytest.raises(ValidationError):
        ProjectOverview.model_validate(
            _overview().model_dump() | {"next_action": "write"}
        )


@pytest.mark.parametrize(
    ("canon_revision", "projection_revision", "synchronized"),
    ((3, 3, False), (3, 2, True)),
)
def test_sync_flag_must_equal_revision_comparison(
    canon_revision: int,
    projection_revision: int,
    synchronized: bool,
):
    with pytest.raises(ValidationError):
        OverviewWriterCore(
            canon_revision=canon_revision,
            projection_revision=projection_revision,
            synchronized=synchronized,
        )


def test_pending_continuity_module_cannot_claim_zero_issues():
    with pytest.raises(ValidationError):
        OverviewContinuity(availability="pending_module", pending_count=0)


def test_available_continuity_requires_a_pending_count():
    with pytest.raises(ValidationError):
        OverviewContinuity(availability="available", pending_count=None)


def test_current_volume_requires_stable_identity_not_only_a_title():
    with pytest.raises(ValidationError):
        OverviewProgress(
            authoritative_chapter_number=1,
            current_volume={"order": 1, "title": "Volume One"},
            latest_final_chapter=None,
            finalized_chapter_count=0,
            finalized_scalar_count=0,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("target_words", "90000"),
        ("target_chapters", 36.0),
        ("updated_at_ms", True),
    ),
)
def test_strict_project_numbers_reject_coercion(field: str, value: object):
    with pytest.raises(ValidationError):
        _project(**{field: value})


def test_strict_boolean_rejects_numeric_coercion():
    with pytest.raises(ValidationError):
        OverviewWriterCore(
            canon_revision=1,
            projection_revision=1,
            synchronized=1,
        )


@pytest.mark.parametrize(
    ("factory", "field"),
    (
        (_project, "id"),
        (_project, "title"),
        (_project, "genre"),
        (_project, "logline"),
        (_achievement, "label"),
    ),
)
@pytest.mark.parametrize("bad_text", ("", " ", " padded", "padded ", "bad\ntext", "bad\u200btext"))
def test_identity_and_display_text_must_be_trimmed_nonempty_and_control_free(
    factory,
    field: str,
    bad_text: str,
):
    with pytest.raises(ValidationError):
        factory(**{field: bad_text})


@pytest.mark.parametrize(
    "changes",
    (
        {"authoritative_chapter_number": 0},
        {"finalized_chapter_count": -1},
        {"finalized_scalar_count": -1},
        {"finalized_chapter_count": 0},
        {"latest_final_chapter": None},
        {
            "authoritative_chapter_number": 3,
            "latest_final_chapter": OverviewFinalChapter(
                number=3,
                title="Not Historical",
                finalized_at_ms=1,
            ),
        },
        {
            "latest_final_chapter": OverviewFinalChapter(
                number=2,
                title="Latest",
                finalized_at_ms=1,
            ),
            "finalized_chapter_count": 3,
        },
    ),
)
def test_progress_rejects_invalid_counts_and_final_chapter_contradictions(changes):
    with pytest.raises(ValidationError):
        _progress(**changes)


def test_empty_progress_accepts_no_latest_final_chapter():
    progress = _progress(
        authoritative_chapter_number=1,
        latest_final_chapter=None,
        finalized_chapter_count=0,
        finalized_scalar_count=0,
    )
    assert progress.latest_final_chapter is None


def test_overview_rejects_more_than_five_recent_achievements():
    achievements = tuple(
        _achievement(label=f"Achievement {index}", occurred_at_ms=index)
        for index in range(6)
    )
    with pytest.raises(ValidationError):
        _overview(recent_achievements=achievements)


def test_overview_rejects_duplicate_achievement_identity():
    achievement = _achievement()
    with pytest.raises(ValidationError):
        _overview(recent_achievements=(achievement, achievement))


def test_same_kind_and_time_with_a_different_label_is_not_a_duplicate():
    overview = _overview(
        recent_achievements=(
            _achievement(label="Finalized Chapter 3"),
            _achievement(label="Reached Act One"),
        )
    )
    assert len(overview.recent_achievements) == 2


@pytest.mark.parametrize(
    "constructor",
    (
        lambda: _project(target_words=0),
        lambda: _project(target_chapters=0),
        lambda: _project(updated_at_ms=-1),
        lambda: OverviewVolume(id="v", order=0, title="Volume"),
        lambda: OverviewFinalChapter(number=0, title="Chapter", finalized_at_ms=0),
        lambda: OverviewWriterCore(
            canon_revision=-1,
            projection_revision=-1,
            synchronized=True,
        ),
        lambda: OverviewContinuity(availability="available", pending_count=-1),
        lambda: _achievement(occurred_at_ms=-1),
    ),
)
def test_numbers_obey_positive_and_nonnegative_bounds(constructor):
    with pytest.raises(ValidationError):
        constructor()


@pytest.mark.parametrize(
    "constructor",
    (
        lambda: _project(lifecycle="deleted"),
        lambda: OverviewContinuity(availability="unknown", pending_count=0),
        lambda: _achievement(kind="outline"),
        lambda: OverviewModuleStates(
            seed="ready",
            contract="current",
            bible="current",
            planning="current",
            outline="current",
            writing="current",
        ),
    ),
)
def test_literal_fields_reject_unknown_values(constructor):
    with pytest.raises(ValidationError):
        constructor()


def test_all_overview_models_are_immutable():
    models = (
        _project(),
        OverviewVolume(id="volume-1", order=1, title="Volume One"),
        OverviewFinalChapter(number=1, title="Chapter One", finalized_at_ms=0),
        _progress(),
        _modules(),
        OverviewWriterCore(
            canon_revision=1,
            projection_revision=1,
            synchronized=True,
        ),
        OverviewContinuity(availability="available", pending_count=0),
        _achievement(),
        _overview(),
    )
    for model in models:
        field = next(iter(type(model).model_fields))
        with pytest.raises(ValidationError):
            setattr(model, field, getattr(model, field))


def test_all_overview_models_forbid_extra_fields():
    with pytest.raises(ValidationError):
        OverviewVolume(id="v", order=1, title="Volume", unexpected="value")
