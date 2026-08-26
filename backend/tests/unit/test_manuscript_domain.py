from __future__ import annotations

from importlib.util import find_spec

import pytest
from pydantic import TypeAdapter, ValidationError

from backend.domain import manuscripts as domain
from backend.domain.chapter_outlines import ChapterOutline


def test_manuscript_domain_module_exists() -> None:
    assert find_spec("backend.domain.manuscripts") is not None


def _chapter(**overrides: object):
    values = {
        "number": 3,
        "title": "渡口夜雨",
        "scalar_count": 2_801,
        "finalized_at_ms": 1_724_544_000_000,
    }
    values.update(overrides)
    return domain.ManuscriptChapterMeta.model_validate(values)


def _volume(**overrides: object):
    values = {
        "id": "volume-1",
        "order": 1,
        "title": "山雨欲来",
        "chapters": (_chapter(),),
    }
    values.update(overrides)
    return domain.ManuscriptVolume.model_validate(values)


def _chapter_outline() -> ChapterOutline:
    return ChapterOutline.model_validate(
        {
            "schemaVersion": "chapter-outline-v1",
            "chapterNumber": 1,
            "planningRevisionId": "planning-revision-1",
            "planningRevision": 1,
            "planningHash": "a" * 64,
            "volumeRef": {
                "id": "volume-1",
                "revision": 1,
                "contentHash": "b" * 64,
            },
            "storyBlockRef": {
                "id": "story-block-1",
                "revision": 1,
                "contentHash": "c" * 64,
            },
            "stageRefs": (
                {
                    "id": "stage-1",
                    "revision": 1,
                    "contentHash": "d" * 64,
                },
            ),
            "sceneTaskRefs": (
                {
                    "id": "scene-task-1",
                    "revision": 1,
                    "contentHash": "e" * 64,
                },
            ),
            "chapterGoal": "找到穿越封锁线的可行缺口。",
            "expectedCharacters": ("沈砚", "陆昭"),
            "continuation": ("承接二人被困封锁区的局面",),
            "plannedTasks": ("观察换岗", "试探暗渠"),
            "scenes": ("废弃驿站的夜间侦察", "暗渠入口的试探"),
            "forbiddenEarlyEvents": ("不可提前揭示内应",),
            "capacityPolicy": {
                "targetMin": 2_500,
                "targetMax": 3_200,
                "softCeiling": 3_800,
            },
            "canonRevision": 0,
            "projectionRevision": 0,
            "projectionHash": "f" * 64,
            "contentHash": "0" * 64,
        }
    )


def test_volume_contract_has_exactly_four_fields_and_rejects_lifecycle() -> None:
    payload = {
        "id": "volume-1",
        "order": 1,
        "title": "山雨欲来",
        "chapters": (_chapter(),),
    }

    volume = domain.ManuscriptVolume.model_validate(payload)

    assert set(domain.ManuscriptVolume.model_fields) == {
        "id",
        "order",
        "title",
        "chapters",
    }
    assert volume.id == payload["id"]
    assert volume.order == payload["order"]
    assert volume.title == payload["title"]
    assert volume.chapters == payload["chapters"]
    with pytest.raises(ValidationError):
        domain.ManuscriptVolume.model_validate(
            {**payload, "lifecycle": "active"}
        )


@pytest.mark.parametrize(
    "volume_id",
    (
        "   ",
        "\n",
        "a\nb",
        "\x00",
        "a\x1fb",
        "a\x85b",
        "a\u200bb",
        "a\ud800b",
    ),
)
def test_volume_id_rejects_blank_or_unicode_category_c_text(
    volume_id: str,
) -> None:
    with pytest.raises(ValidationError):
        _volume(id=volume_id)


def test_manuscript_values_are_strict_frozen_and_forbid_extra_fields() -> None:
    chapter = _chapter()
    volume = _volume(chapters=(chapter,))

    with pytest.raises(ValidationError):
        domain.ManuscriptChapterMeta.model_validate(
            {
                **chapter.model_dump(),
                "unexpected": "not part of the domain",
            }
        )
    with pytest.raises(ValidationError):
        chapter.title = "被篡改"
    with pytest.raises(ValidationError):
        volume.chapters[0].title = "被篡改"
    assert isinstance(volume.chapters, tuple)


@pytest.mark.parametrize("field", ("number", "scalar_count", "finalized_at_ms"))
@pytest.mark.parametrize("value", (True, 1.0, "1"))
def test_chapter_integer_fields_reject_bool_and_coercion(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _chapter(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("number", 0),
        ("number", -1),
        ("scalar_count", -1),
        ("finalized_at_ms", -1),
    ),
)
def test_chapter_numbers_and_counts_enforce_their_lower_bounds(
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        _chapter(**{field: value})


@pytest.mark.parametrize(
    "title",
    ("", "   ", " 前后空白 ", "换行\n标题", "坏\ud800标题"),
)
def test_chapter_title_must_be_safe_nonempty_text(title: str) -> None:
    with pytest.raises(ValidationError):
        _chapter(title=title)


@pytest.mark.parametrize("order", (0, -1, True, 1.0, "1"))
def test_volume_order_is_a_strict_positive_integer(order: object) -> None:
    with pytest.raises(ValidationError):
        _volume(order=order)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("id", ""),
        ("title", ""),
        ("title", "  "),
        ("title", " 前后空白 "),
        ("title", "卷名\u0000"),
    ),
)
def test_volume_identity_and_title_are_closed(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _volume(**{field: value})


def test_project_lifecycle_type_is_closed_to_active_and_archived() -> None:
    adapter = TypeAdapter(domain.ManuscriptLifecycle)

    assert adapter.validate_python("active") == "active"
    assert adapter.validate_python("archived") == "archived"
    with pytest.raises(ValidationError):
        adapter.validate_python("retired")


def test_outline_projection_is_strict_frozen_and_nested_immutable() -> None:
    projection = domain.FinalOutlineProjection.model_validate(
        {
            "chapter_goal": "潜入渡口，找到失踪账册。",
            "expected_characters": ("沈砚", "陆昭"),
            "continuation": ("承接追踪水路的线索",),
            "planned_tasks": ("观察守卫换岗",),
            "scenes": ("雨夜渡口", "废弃仓房"),
            "forbidden_early_events": ("不可揭示幕后主使",),
        }
    )

    assert projection.scenes == ("雨夜渡口", "废弃仓房")
    with pytest.raises(ValidationError):
        projection.chapter_goal = "被篡改"
    with pytest.raises(ValidationError):
        domain.FinalOutlineProjection.model_validate(
            {**projection.model_dump(), "scenes": ["列表不能被宽松转换"]}
        )
    with pytest.raises(ValidationError):
        domain.FinalOutlineProjection.model_validate(
            {**projection.model_dump(), "extra": "internal"}
        )


@pytest.mark.parametrize(
    ("error_name", "message"),
    (
        ("ManuscriptProjectMissing", "manuscript project was not found"),
        ("FinalChapterMissing", "finalized chapter was not found"),
        ("ManuscriptCorrupt", "manuscript integrity validation failed"),
        ("ManuscriptUnavailable", "manuscript is temporarily unavailable"),
    ),
)
def test_manuscript_errors_have_fixed_safe_messages(
    error_name: str,
    message: str,
) -> None:
    error_type = getattr(domain, error_name)
    error = error_type()

    assert isinstance(error, domain.ManuscriptDomainError)
    assert str(error) == message
    with pytest.raises(TypeError):
        error_type("storage-id hash JSON SQL prose raw exception")


def test_canonicalizes_by_actual_final_chapter_number_and_allows_gaps() -> None:
    later = _volume(
        id="volume-2",
        order=2,
        title="暗潮汹涌",
        chapters=(_chapter(number=8), _chapter(number=5)),
    )
    earlier = _volume(
        id="volume-1",
        order=1,
        title="山雨欲来",
        chapters=(_chapter(number=3), _chapter(number=1)),
    )

    canonical = domain.canonicalize_manuscript_volumes((later, earlier))

    assert [volume.id for volume in canonical] == ["volume-1", "volume-2"]
    assert [
        chapter.number
        for volume in canonical
        for chapter in volume.chapters
    ] == [1, 3, 5, 8]
    assert [chapter.number for chapter in later.chapters] == [8, 5]


def test_canonicalization_merges_consistent_fragments_of_one_volume() -> None:
    first_fragment = _volume(chapters=(_chapter(number=1),))
    second_fragment = _volume(chapters=(_chapter(number=4),))

    canonical = domain.canonicalize_manuscript_volumes(
        (second_fragment, first_fragment)
    )

    assert len(canonical) == 1
    assert [chapter.number for chapter in canonical[0].chapters] == [1, 4]


def test_canonicalization_rejects_duplicate_final_chapter_numbers() -> None:
    volume = _volume(chapters=(_chapter(number=2), _chapter(number=2)))

    with pytest.raises(domain.ManuscriptCorrupt):
        domain.canonicalize_manuscript_volumes((volume,))


def test_canonicalization_rejects_volume_order_regression_along_chapters() -> None:
    first_chapter = _volume(
        id="volume-2",
        order=2,
        title="后卷",
        chapters=(_chapter(number=1),),
    )
    later_chapter = _volume(
        id="volume-1",
        order=1,
        title="前卷",
        chapters=(_chapter(number=2),),
    )

    with pytest.raises(domain.ManuscriptCorrupt):
        domain.canonicalize_manuscript_volumes((first_chapter, later_chapter))


def test_canonicalization_rejects_a_volume_split_into_multiple_runs() -> None:
    volume_one_start = _volume(chapters=(_chapter(number=1),))
    volume_two = _volume(
        id="volume-2",
        order=2,
        title="第二卷",
        chapters=(_chapter(number=2),),
    )
    volume_one_return = _volume(chapters=(_chapter(number=3),))

    with pytest.raises(domain.ManuscriptCorrupt):
        domain.canonicalize_manuscript_volumes(
            (volume_one_start, volume_two, volume_one_return)
        )


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    (("order", 2), ("title", "冲突卷名")),
)
def test_canonicalization_rejects_inconsistent_details_for_one_volume_id(
    changed_field: str,
    changed_value: object,
) -> None:
    first = _volume(chapters=(_chapter(number=1),))
    second = _volume(
        **{
            changed_field: changed_value,
            "chapters": (_chapter(number=2),),
        }
    )

    with pytest.raises(domain.ManuscriptCorrupt):
        domain.canonicalize_manuscript_volumes((first, second))


def test_canonicalization_rejects_one_order_mapped_to_different_volumes() -> None:
    first = _volume(chapters=(_chapter(number=1),))
    conflicting = _volume(
        id="volume-other",
        order=1,
        title="另一卷",
        chapters=(_chapter(number=2),),
    )

    with pytest.raises(domain.ManuscriptCorrupt):
        domain.canonicalize_manuscript_volumes((first, conflicting))


def test_unicode_scalar_count_counts_astral_characters_once() -> None:
    assert domain.unicode_scalar_count("A😀𠀀e\u0301") == 5
    assert domain.unicode_scalar_count("") == 0


@pytest.mark.parametrize("value", (None, b"text", 1, True, 1.5))
def test_unicode_scalar_count_strictly_rejects_non_strings(value: object) -> None:
    with pytest.raises(TypeError):
        domain.unicode_scalar_count(value)


@pytest.mark.parametrize("value", ("\ud800", "\udfff", "\ud83d\ude00"))
def test_unicode_scalar_count_rejects_malformed_surrogates(value: str) -> None:
    with pytest.raises(ValueError, match="Unicode scalar"):
        domain.unicode_scalar_count(value)


@pytest.mark.parametrize("value", (0, 1, 4_096))
def test_database_scalar_count_accepts_only_nonnegative_exact_ints(value: int) -> None:
    result = domain.validate_database_scalar_count(value)

    assert result == value
    assert type(result) is int


@pytest.mark.parametrize("value", (True, False, -1, 1.0, "1", None))
def test_database_scalar_count_maps_invalid_storage_values_to_corruption(
    value: object,
) -> None:
    with pytest.raises(
        domain.ManuscriptCorrupt,
        match="manuscript integrity validation failed",
    ):
        domain.validate_database_scalar_count(value)


def test_projects_exact_author_fields_from_a_real_chapter_outline() -> None:
    outline = _chapter_outline()
    assert isinstance(outline, ChapterOutline)

    projection = domain.project_final_outline(outline)

    assert projection.model_dump() == {
        "chapter_goal": "找到穿越封锁线的可行缺口。",
        "expected_characters": ("沈砚", "陆昭"),
        "continuation": ("承接二人被困封锁区的局面",),
        "planned_tasks": ("观察换岗", "试探暗渠"),
        "scenes": ("废弃驿站的夜间侦察", "暗渠入口的试探"),
        "forbidden_early_events": ("不可提前揭示内应",),
    }
    assert set(projection.model_dump()).isdisjoint(
        {
            "id",
            "schema_version",
            "chapter_number",
            "planning_revision_id",
            "planning_revision",
            "planning_hash",
            "volume_ref",
            "story_block_ref",
            "stage_refs",
            "scene_task_refs",
            "capacity_policy",
            "canon_revision",
            "projection_revision",
            "projection_hash",
            "content_hash",
            "basis",
            "status",
        }
    )


@pytest.mark.parametrize("value", (None, {}, object()))
def test_outline_projection_strictly_rejects_non_chapter_outline_inputs(
    value: object,
) -> None:
    with pytest.raises(TypeError, match="ChapterOutline"):
        domain.project_final_outline(value)
