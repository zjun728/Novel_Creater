from __future__ import annotations

from dataclasses import FrozenInstanceError
from importlib.util import find_spec

import pytest

from backend.domain import finalized_chapter_structure as structure


def test_finalized_chapter_structure_module_exists() -> None:
    assert find_spec("backend.domain.finalized_chapter_structure") is not None


def _link(
    chapter_number: int,
    *,
    volume_id: str = "volume-1",
    volume_order: int = 1,
    volume_title: str = "第一卷",
):
    return structure.FinalizedChapterLink(
        chapter_number=chapter_number,
        volume_id=volume_id,
        volume_order=volume_order,
        volume_title=volume_title,
    )


def test_link_value_is_frozen() -> None:
    link = _link(1)

    with pytest.raises(FrozenInstanceError):
        link.volume_id = "changed"


def test_validates_and_sorts_globally_while_allowing_chapter_and_order_gaps() -> None:
    links = (
        _link(
            8,
            volume_id="volume-2",
            volume_order=4,
            volume_title="第四卷",
        ),
        _link(3),
        _link(
            5,
            volume_id="volume-2",
            volume_order=4,
            volume_title="第四卷",
        ),
        _link(1),
    )

    ordered = structure.validate_and_sort_finalized_chapter_links(links)

    assert isinstance(ordered, tuple)
    assert [link.chapter_number for link in ordered] == [1, 3, 5, 8]
    assert links[0].chapter_number == 8


def test_rejects_duplicate_chapter_numbers() -> None:
    with pytest.raises(structure.FinalizedChapterStructureError):
        structure.validate_and_sort_finalized_chapter_links((_link(2), _link(2)))


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    (("volume_order", 2), ("volume_title", "冲突卷名")),
)
def test_rejects_inconsistent_id_to_order_title_mapping(
    changed_field: str,
    changed_value: object,
) -> None:
    changed = {
        "volume_id": "volume-1",
        "volume_order": 1,
        "volume_title": "第一卷",
        changed_field: changed_value,
    }

    with pytest.raises(structure.FinalizedChapterStructureError):
        structure.validate_and_sort_finalized_chapter_links(
            (_link(1), _link(2, **changed))
        )


def test_rejects_one_order_mapped_to_different_id_or_title() -> None:
    with pytest.raises(structure.FinalizedChapterStructureError):
        structure.validate_and_sort_finalized_chapter_links(
            (
                _link(1),
                _link(
                    2,
                    volume_id="volume-other",
                    volume_order=1,
                    volume_title="另一卷",
                ),
            )
        )


def test_rejects_volume_order_that_does_not_strictly_increase() -> None:
    with pytest.raises(structure.FinalizedChapterStructureError):
        structure.validate_and_sort_finalized_chapter_links(
            (
                _link(
                    1,
                    volume_id="volume-2",
                    volume_order=2,
                    volume_title="第二卷",
                ),
                _link(2),
            )
        )


def test_rejects_one_volume_split_across_multiple_runs() -> None:
    with pytest.raises(structure.FinalizedChapterStructureError):
        structure.validate_and_sort_finalized_chapter_links(
            (
                _link(1),
                _link(
                    2,
                    volume_id="volume-2",
                    volume_order=2,
                    volume_title="第二卷",
                ),
                _link(3),
            )
        )
