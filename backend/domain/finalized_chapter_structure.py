"""Neutral finalized-chapter structure validation shared by read surfaces."""

from __future__ import annotations

from dataclasses import dataclass


class FinalizedChapterStructureError(ValueError):
    """A finalized chapter collection has inconsistent structural links."""


@dataclass(frozen=True, slots=True)
class FinalizedChapterLink:
    chapter_number: int
    volume_id: str
    volume_order: int
    volume_title: str


def validate_and_sort_finalized_chapter_links(
    links: tuple[FinalizedChapterLink, ...],
) -> tuple[FinalizedChapterLink, ...]:
    """Validate bidirectional volume links and return global chapter order."""

    if len({link.chapter_number for link in links}) != len(links):
        raise FinalizedChapterStructureError(
            "duplicate finalized chapter number"
        )

    volume_details: dict[str, tuple[int, str]] = {}
    volume_order_details: dict[int, tuple[str, str]] = {}
    for link in links:
        details = (link.volume_order, link.volume_title)
        if volume_details.setdefault(link.volume_id, details) != details:
            raise FinalizedChapterStructureError(
                "finalized chapter volume link is inconsistent"
            )
        order_details = (link.volume_id, link.volume_title)
        if (
            volume_order_details.setdefault(link.volume_order, order_details)
            != order_details
        ):
            raise FinalizedChapterStructureError(
                "finalized chapter volume order is inconsistent"
            )

    ordered = tuple(sorted(links, key=lambda link: link.chapter_number))
    seen_volume_ids: set[str] = set()
    current_volume_id: str | None = None
    current_volume_order = 0
    for link in ordered:
        if link.volume_id == current_volume_id:
            continue
        if (
            link.volume_id in seen_volume_ids
            or link.volume_order <= current_volume_order
        ):
            raise FinalizedChapterStructureError(
                "finalized chapter volume run is inconsistent"
            )
        seen_volume_ids.add(link.volume_id)
        current_volume_id = link.volume_id
        current_volume_order = link.volume_order
    return ordered


__all__ = (
    "FinalizedChapterLink",
    "FinalizedChapterStructureError",
    "validate_and_sort_finalized_chapter_links",
)
