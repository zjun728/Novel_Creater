"""Fail-closed mapping for the author-facing project overview."""

from __future__ import annotations

from collections.abc import Mapping
import json
import unicodedata

from pydantic import ValidationError

from backend.domain.project_overview import (
    OverviewAchievement,
    OverviewArtifactStatus,
    OverviewContinuity,
    OverviewFinalChapter,
    OverviewModuleStates,
    OverviewProgress,
    OverviewProject,
    OverviewVolume,
    OverviewWriterCore,
    ProjectOverview,
)
from backend.http_errors import ProjectNotFound


class ProjectOverviewConsistencyError(RuntimeError):
    """An authority snapshot cannot safely satisfy the public DTO."""

    def __init__(self, authority: str) -> None:
        super().__init__(f"Project overview {authority} is inconsistent")


def _mapping(value: object) -> dict[object, object] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return dict(value)
    except Exception:
        return None


def _json_object(value: object) -> dict[object, object] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
            return None
    return _mapping(value)


def _exact_int(value: object, *, minimum: int = 0) -> int | None:
    if type(value) is not int or value < minimum:
        return None
    return value


def _safe_text(value: object, *, trim: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip() if trim else value
    if not candidate or candidate != candidate.strip():
        return None
    if any(
        unicodedata.category(character).startswith("C")
        for character in candidate
    ):
        return None
    return candidate


def _has_draft(head: dict[object, object] | None, draft: object) -> bool:
    if draft is not None:
        return True
    if head is None:
        return False
    flag = head.get("has_draft")
    return (type(flag) is bool and flag) or (type(flag) is int and flag == 1)


def map_artifact_status(
    *,
    head: object,
    draft: object = None,
    required_json: tuple[str, ...] = (),
) -> OverviewArtifactStatus:
    """Map one revision head without guessing supersession or frontend state."""

    row = _mapping(head)
    if row is None:
        if head is not None:
            return "needs_review"
        return "working_draft" if draft is not None else "missing"

    revision_value = row.get("revision")
    revision = _exact_int(revision_value, minimum=0)
    if revision is None:
        return "needs_review" if revision_value is not None else (
            "working_draft" if _has_draft(row, draft) else "missing"
        )
    if revision == 0:
        return "working_draft" if _has_draft(row, draft) else "missing"
    if any(_json_object(row.get(field)) is None for field in required_json):
        return "needs_review"
    return "current"


def _seed_status(selected_seed: object) -> OverviewArtifactStatus:
    if selected_seed is None:
        return "missing"
    row = _mapping(selected_seed)
    if (
        row is None
        or _exact_int(row.get("selection_revision"), minimum=1) is None
        or _exact_int(row.get("selected_at")) is None
        or _json_object(row.get("payload_json")) is None
    ):
        return "needs_review"
    return "current"


def _confirmed_revision(row: object) -> bool:
    mapping = _mapping(row)
    return mapping is not None and _exact_int(
        mapping.get("revision"), minimum=1
    ) is not None


def _outline_pin_metadata_is_complete(outline: object) -> bool:
    row = _mapping(outline)
    if row is None:
        return False
    return (
        _safe_text(row.get("planning_revision_id")) is not None
        and _exact_int(row.get("planning_revision"), minimum=1) is not None
        and _safe_text(row.get("planning_hash")) is not None
    )


def _unique_mapping_with_id(
    values: object,
    expected_id: str,
) -> dict[object, object] | None:
    if not isinstance(values, (list, tuple)):
        return None
    matches: list[dict[object, object]] = []
    for value in values:
        row = _mapping(value)
        if row is not None and row.get("id") == expected_id:
            matches.append(row)
    return matches[0] if len(matches) == 1 else None


def _resolve_current_volume(outline: object) -> OverviewVolume | None:
    row = _mapping(outline)
    if row is None or not _outline_pin_metadata_is_complete(row):
        return None
    outline_content = _json_object(row.get("content_json"))
    pinned_planning = _json_object(row.get("pinned_planning_content_json"))
    if outline_content is None or pinned_planning is None:
        return None
    story_block_ref = _mapping(outline_content.get("storyBlockRef"))
    if story_block_ref is None:
        return None
    story_block_id = _safe_text(story_block_ref.get("id"))
    if story_block_id is None:
        return None
    story_block = _unique_mapping_with_id(
        pinned_planning.get("storyBlocks"),
        story_block_id,
    )
    if story_block is None:
        return None
    volume_id = _safe_text(story_block.get("volumeId"))
    if volume_id is None:
        return None
    volume = _unique_mapping_with_id(
        pinned_planning.get("volumes"),
        volume_id,
    )
    if volume is None or volume.get("lifecycle") != "active":
        return None
    order = _exact_int(volume.get("order"), minimum=1)
    title = _safe_text(volume.get("title"))
    if order is None or title is None:
        return None
    try:
        return OverviewVolume(id=volume_id, order=order, title=title)
    except ValidationError:
        return None


def _project(
    snapshot: dict[object, object],
    *,
    seed_status: OverviewArtifactStatus,
) -> OverviewProject:
    row = _mapping(snapshot.get("project"))
    if row is None:
        raise ProjectOverviewConsistencyError("project authority")
    project_id = _safe_text(row.get("id"))
    title = _safe_text(row.get("title"))
    target_words = _exact_int(row.get("target_words"), minimum=1)
    target_chapters = _exact_int(row.get("target_chapters"), minimum=1)
    updated_at = _exact_int(row.get("updated_at"))
    if None in (
        project_id,
        title,
        target_words,
        target_chapters,
        updated_at,
    ):
        raise ProjectOverviewConsistencyError("project authority")

    selected = (
        _mapping(snapshot.get("selected_seed"))
        if seed_status == "current"
        else None
    )
    payload = (
        _json_object(selected.get("payload_json"))
        if selected is not None
        else None
    )
    genre = _safe_text(payload.get("genre"), trim=True) if payload else None
    logline = (
        _safe_text(payload.get("logline"), trim=True) if payload else None
    )
    genre = genre or _safe_text(row.get("genre"), trim=True) or "题材尚未填写"
    logline = (
        logline
        or _safe_text(row.get("description"), trim=True)
        or "一句话创意尚未填写"
    )
    try:
        return OverviewProject(
            id=project_id,
            title=title,
            genre=genre,
            logline=logline,
            target_words=target_words,
            target_chapters=target_chapters,
            updated_at_ms=updated_at,
            lifecycle=(
                "archived" if row.get("archived_at") is not None else "active"
            ),
        )
    except ValidationError as error:
        raise ProjectOverviewConsistencyError("project authority") from None


def _progress(
    snapshot: dict[object, object],
    *,
    current_volume: OverviewVolume | None,
) -> tuple[OverviewProgress, OverviewFinalChapter | None]:
    authoritative = _exact_int(
        snapshot.get("authoritative_chapter_number"),
        minimum=1,
    )
    aggregate = _mapping(snapshot.get("final_aggregate"))
    if authoritative is None or aggregate is None:
        raise ProjectOverviewConsistencyError("final chapter authority")
    chapter_count = _exact_int(aggregate.get("chapter_count"))
    scalar_count = _exact_int(aggregate.get("scalar_count"))
    if chapter_count is None or scalar_count is None:
        raise ProjectOverviewConsistencyError("final chapter authority")

    latest: OverviewFinalChapter | None = None
    latest_number_value = aggregate.get("latest_number")
    latest_title_value = aggregate.get("latest_title")
    latest_at_value = aggregate.get("latest_finalized_at")
    if chapter_count == 0:
        if scalar_count != 0 or any(
            value is not None
            for value in (
                latest_number_value,
                latest_title_value,
                latest_at_value,
            )
        ):
            raise ProjectOverviewConsistencyError("final chapter authority")
    else:
        latest_number = _exact_int(latest_number_value, minimum=1)
        latest_title = _safe_text(latest_title_value)
        latest_at = _exact_int(latest_at_value)
        if (
            latest_number is None
            or latest_title is None
            or latest_at is None
            or chapter_count > latest_number
            or latest_number >= authoritative
        ):
            raise ProjectOverviewConsistencyError("final chapter authority")
        latest = OverviewFinalChapter(
            number=latest_number,
            title=latest_title,
            finalized_at_ms=latest_at,
        )
    try:
        return (
            OverviewProgress(
                authoritative_chapter_number=authoritative,
                current_volume=current_volume,
                latest_final_chapter=latest,
                finalized_chapter_count=chapter_count,
                finalized_scalar_count=scalar_count,
            ),
            latest,
        )
    except ValidationError:
        raise ProjectOverviewConsistencyError("final chapter authority") from None


def _writer_core(snapshot: dict[object, object]) -> OverviewWriterCore:
    row = _mapping(snapshot.get("writer_core"))
    if row is None:
        raise ProjectOverviewConsistencyError("writer core authority")
    canon = _exact_int(row.get("canon_revision"))
    projection = _exact_int(row.get("projection_revision"))
    if canon is None or projection is None:
        raise ProjectOverviewConsistencyError("writer core authority")
    return OverviewWriterCore(
        canon_revision=canon,
        projection_revision=projection,
        synchronized=canon == projection,
    )


def _achievement_timestamp(row: object, field: str) -> int | None:
    mapping = _mapping(row)
    if mapping is None:
        return None
    return _exact_int(mapping.get(field))


def _achievements(
    snapshot: dict[object, object],
    latest: OverviewFinalChapter | None,
    *,
    seed_status: OverviewArtifactStatus,
    planning_status: OverviewArtifactStatus,
) -> tuple[OverviewAchievement, ...]:
    candidates: list[tuple[int, int, OverviewAchievement]] = []

    def add(index: int, kind: str, label: str, occurred_at: int | None) -> None:
        if occurred_at is None:
            return
        candidates.append(
            (
                -occurred_at,
                index,
                OverviewAchievement(
                    kind=kind,
                    label=label,
                    occurred_at_ms=occurred_at,
                ),
            )
        )

    selected_seed = snapshot.get("selected_seed")
    if seed_status == "current":
        add(
            0,
            "seed",
            "创意种子已确认",
            _achievement_timestamp(selected_seed, "selected_at"),
        )
    for index, (field, kind, label) in enumerate(
        (
            ("contract", "contract", "创作契约已确认"),
            ("bible", "bible", "创作圣经已确认"),
            ("planning", "planning", "故事规划已确认"),
        ),
        start=1,
    ):
        row = snapshot.get(field)
        if _confirmed_revision(row) and (
            field != "planning" or planning_status == "current"
        ):
            add(index, kind, label, _achievement_timestamp(row, "updated_at"))
    if latest is not None:
        add(
            4,
            "final_chapter",
            f"第 {latest.number} 章《{latest.title}》已定稿",
            latest.finalized_at_ms,
        )

    candidates.sort(key=lambda item: (item[0], item[1]))
    unique: list[OverviewAchievement] = []
    identities: set[tuple[str, int, str]] = set()
    for _, _, achievement in candidates:
        identity = (
            achievement.kind,
            achievement.occurred_at_ms,
            achievement.label,
        )
        if identity in identities:
            continue
        identities.add(identity)
        unique.append(achievement)
        if len(unique) == 5:
            break
    return tuple(unique)


def build_project_overview(snapshot: object) -> ProjectOverview:
    """Validate one repository snapshot and map only approved author facts."""

    source = _mapping(snapshot)
    if source is None:
        raise ProjectOverviewConsistencyError("snapshot")

    seed_status = _seed_status(source.get("selected_seed"))
    contract_status = map_artifact_status(head=source.get("contract"))
    bible_status = map_artifact_status(head=source.get("bible"))
    planning_status = map_artifact_status(
        head=source.get("planning"),
        required_json=("content_json",),
    )
    outline = source.get("outline")
    outline_status = map_artifact_status(
        head=outline,
        required_json=("content_json", "pinned_planning_content_json"),
    )
    current_volume = None
    if outline_status == "current":
        current_volume = _resolve_current_volume(outline)
        if current_volume is None:
            outline_status = "needs_review"

    progress, latest = _progress(source, current_volume=current_volume)
    session = source.get("session")
    writing_status: OverviewArtifactStatus
    if session is not None:
        session_row = _mapping(session)
        if session_row is None or session_row.get("status") != "drafting":
            raise ProjectOverviewConsistencyError("writing session")
        writing_status = "working_draft"
    elif progress.finalized_chapter_count > 0:
        writing_status = "current"
    else:
        writing_status = "missing"

    try:
        return ProjectOverview(
            project=_project(source, seed_status=seed_status),
            progress=progress,
            modules=OverviewModuleStates(
                seed=seed_status,
                contract=contract_status,
                bible=bible_status,
                planning=planning_status,
                outline=outline_status,
                writing=writing_status,
            ),
            writer_core=_writer_core(source),
            continuity=OverviewContinuity(
                availability="pending_module",
                pending_count=None,
            ),
            recent_achievements=_achievements(
                source,
                latest,
                seed_status=seed_status,
                planning_status=planning_status,
            ),
        )
    except ValidationError:
        raise ProjectOverviewConsistencyError("authority") from None


class ProjectOverviewService:
    def __init__(self, repository, *, connection_factory) -> None:
        self.repository = repository
        self.connection_factory = connection_factory

    async def get(self, project_id: str) -> ProjectOverview:
        async with self.connection_factory() as session:
            snapshot = await self.repository.read_snapshot(session, project_id)
        if snapshot is None:
            raise ProjectNotFound()
        return build_project_overview(snapshot)


__all__ = (
    "ProjectOverviewConsistencyError",
    "ProjectOverviewService",
    "build_project_overview",
    "map_artifact_status",
)
