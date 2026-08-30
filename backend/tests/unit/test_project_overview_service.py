from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from backend.http_errors import ProjectNotFound
from backend.services.project_overview import (
    ProjectOverviewConsistencyError,
    ProjectOverviewService,
    build_project_overview,
    map_artifact_status,
)


class RecordingRepository:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []

    async def read_snapshot(self, session, project_id):
        self.calls.append((session, project_id))
        return self.snapshot


class RecordingConnections:
    def __init__(self):
        self.session = object()
        self.calls = 0
        self.exits = 0

    @asynccontextmanager
    async def __call__(self):
        self.calls += 1
        try:
            yield self.session
        finally:
            self.exits += 1


def _snapshot(**changes):
    pinned_planning = {
        "schemaVersion": "planning-v1",
        "storyBlocks": [
            {
                "id": "block-r1",
                "lifecycle": "active",
                "volumeId": "volume-r1",
                "title": "穿过封锁线",
            }
        ],
        "volumes": [
            {
                "id": "volume-r1",
                "lifecycle": "active",
                "order": 1,
                "title": "黑潮初临",
            },
            {
                "id": "volume-retired",
                "lifecycle": "retired",
                "order": 9,
                "title": "黑潮初临",
            },
        ],
    }
    values = {
        "project": {
            "id": "project / 一 % _ ' \"",
            "title": "典镇山河",
            "genre": " 备用题材 ",
            "description": " 备用创意 ",
            "target_words": 2_400_000,
            "target_chapters": 720,
            "updated_at": 1_788_067_200_000,
            "archived_at": None,
        },
        "selected_seed": {
            "selection_revision": 2,
            "selected_at": 600,
            "updated_at": 610,
            "payload_json": {
                "genre": "东方奇幻",
                "logline": "少年以县志镇压黑潮。",
            },
        },
        "contract": {"revision": 3, "updated_at": 700, "has_draft": 0},
        "bible": {"revision": 4, "updated_at": 800, "has_draft": 0},
        "planning": {
            "revision": 2,
            "updated_at": 900,
            "content_json": {
                "storyBlocks": [
                    {
                        "id": "block-r2",
                        "volumeId": "volume-r2",
                        "title": "同名不能回退",
                    }
                ],
                "volumes": [
                    {
                        "id": "volume-r2",
                        "lifecycle": "active",
                        "order": 2,
                        "title": "黑潮初临",
                    }
                ],
            },
            "has_draft": 0,
        },
        "outline": {
            "revision": 1,
            "updated_at": 950,
            "content_json": {
                "storyBlockRef": {"id": "block-r1"},
            },
            "planning_revision_id": "planning-r1",
            "planning_revision": 1,
            "planning_hash": "1" * 64,
            "pinned_planning_content_json": pinned_planning,
            "has_draft": False,
        },
        "session": {"id": "session-4", "status": "drafting"},
        "writer_core": {"canon_revision": 3, "projection_revision": 3},
        "final_aggregate": {
            "chapter_count": 3,
            "scalar_count": 11_840,
            "latest_number": 3,
            "latest_title": "夜渡",
            "latest_finalized_at": 1_000,
        },
        "authoritative_chapter_number": 4,
    }
    values.update(changes)
    return values


@pytest.mark.asyncio
async def test_get_uses_one_connection_and_one_exact_repository_read():
    project_id = "project / 一 % _ ' \""
    repository = RecordingRepository(_snapshot())
    connections = RecordingConnections()

    result = await ProjectOverviewService(
        repository,
        connection_factory=connections,
    ).get(project_id)

    assert result.project.id == project_id
    assert connections.calls == 1
    assert connections.exits == 1
    assert repository.calls == [(connections.session, project_id)]


@pytest.mark.asyncio
async def test_missing_project_raises_existing_public_error_after_one_read():
    repository = RecordingRepository(None)
    connections = RecordingConnections()

    with pytest.raises(ProjectNotFound):
        await ProjectOverviewService(
            repository,
            connection_factory=connections,
        ).get("missing")

    assert connections.calls == connections.exits == 1
    assert repository.calls == [(connections.session, "missing")]


def test_complete_snapshot_maps_to_exact_camel_case_author_response():
    result = build_project_overview(_snapshot()).model_dump(
        mode="json",
        by_alias=True,
    )

    assert result == {
        "project": {
            "id": "project / 一 % _ ' \"",
            "title": "典镇山河",
            "genre": "东方奇幻",
            "logline": "少年以县志镇压黑潮。",
            "targetWords": 2_400_000,
            "targetChapters": 720,
            "updatedAtMs": 1_788_067_200_000,
            "lifecycle": "active",
        },
        "progress": {
            "authoritativeChapterNumber": 4,
            "currentVolume": {
                "id": "volume-r1",
                "order": 1,
                "title": "黑潮初临",
            },
            "latestFinalChapter": {
                "number": 3,
                "title": "夜渡",
                "finalizedAtMs": 1_000,
            },
            "finalizedChapterCount": 3,
            "finalizedScalarCount": 11_840,
        },
        "modules": {
            "seed": "current",
            "contract": "current",
            "bible": "current",
            "planning": "current",
            "outline": "current",
            "writing": "working_draft",
        },
        "writerCore": {
            "canonRevision": 3,
            "projectionRevision": 3,
            "synchronized": True,
        },
        "continuity": {
            "availability": "pending_module",
            "pendingCount": None,
        },
        "recentAchievements": [
            {
                "kind": "final_chapter",
                "label": "第 3 章《夜渡》已定稿",
                "occurredAtMs": 1_000,
            },
            {
                "kind": "planning",
                "label": "故事规划已确认",
                "occurredAtMs": 900,
            },
            {
                "kind": "bible",
                "label": "创作圣经已确认",
                "occurredAtMs": 800,
            },
            {
                "kind": "contract",
                "label": "创作契约已确认",
                "occurredAtMs": 700,
            },
            {
                "kind": "seed",
                "label": "创意种子已确认",
                "occurredAtMs": 600,
            },
        ],
    }


@pytest.mark.parametrize(
    ("head", "draft", "expected"),
    (
        (None, None, "missing"),
        ({"revision": 0}, {"id": "draft-1"}, "working_draft"),
        ({"revision": 1}, None, "current"),
        ({"revision": 1, "content_json": None}, None, "needs_review"),
        ({"revision": 1, "content_json": "[]"}, None, "needs_review"),
    ),
)
def test_artifact_lifecycle_mapping_table(head, draft, expected):
    required_json = ("content_json",) if head and "content_json" in head else ()
    assert map_artifact_status(
        head=head,
        draft=draft,
        required_json=required_json,
    ) == expected


@pytest.mark.parametrize(
    ("session", "chapter_count", "expected"),
    (
        ({"status": "drafting"}, 1, "working_draft"),
        (None, 1, "current"),
        (None, 0, "missing"),
    ),
)
def test_whole_manuscript_writing_status(session, chapter_count, expected):
    aggregate = {
        "chapter_count": chapter_count,
        "scalar_count": 10 if chapter_count else 0,
        "latest_number": 1 if chapter_count else None,
        "latest_title": "第一章" if chapter_count else None,
        "latest_finalized_at": 10 if chapter_count else None,
    }
    authoritative = 2 if chapter_count else 1
    result = build_project_overview(
        _snapshot(
            session=session,
            final_aggregate=aggregate,
            authoritative_chapter_number=authoritative,
        )
    )
    assert result.modules.writing == expected


@pytest.mark.parametrize(
    "session",
    ({}, {"status": "final"}, "raw-secret-marker"),
)
def test_non_drafting_session_snapshot_fails_closed(session):
    with pytest.raises(ProjectOverviewConsistencyError, match="writing session"):
        build_project_overview(_snapshot(session=session))


def test_archived_project_remains_readable():
    snapshot = _snapshot()
    snapshot["project"] = snapshot["project"] | {"archived_at": 123}

    assert build_project_overview(snapshot).project.lifecycle == "archived"


def test_unsynchronized_writer_heads_are_valid_read_output():
    result = build_project_overview(
        _snapshot(writer_core={"canon_revision": 7, "projection_revision": 6})
    )

    assert result.writer_core.model_dump() == {
        "canon_revision": 7,
        "projection_revision": 6,
        "synchronized": False,
    }


@pytest.mark.parametrize(
    "writer_core",
    (None, {}, {"canon_revision": 1}, {"canon_revision": "1", "projection_revision": 1}),
)
def test_missing_or_malformed_writer_head_fails_closed(writer_core):
    with pytest.raises(ProjectOverviewConsistencyError, match="writer core"):
        build_project_overview(_snapshot(writer_core=writer_core))


@pytest.mark.parametrize(
    "aggregate",
    (
        {
            "chapter_count": 1,
            "scalar_count": 10,
            "latest_number": None,
            "latest_title": None,
            "latest_finalized_at": None,
        },
        {
            "chapter_count": 0,
            "scalar_count": 10,
            "latest_number": None,
            "latest_title": None,
            "latest_finalized_at": None,
        },
        {
            "chapter_count": 1,
            "scalar_count": 10,
            "latest_number": 1,
            "latest_title": None,
            "latest_finalized_at": 10,
        },
        {
            "chapter_count": "1",
            "scalar_count": 10,
            "latest_number": 1,
            "latest_title": "第一章",
            "latest_finalized_at": 10,
        },
    ),
)
def test_inconsistent_final_aggregate_fails_closed(aggregate):
    with pytest.raises(ProjectOverviewConsistencyError, match="final chapter"):
        build_project_overview(_snapshot(final_aggregate=aggregate))


@pytest.mark.parametrize("as_text", (False, True))
def test_repository_json_accepts_mapping_or_text(as_text):
    import json

    snapshot = _snapshot()
    for owner, field in (
        (snapshot["selected_seed"], "payload_json"),
        (snapshot["planning"], "content_json"),
        (snapshot["outline"], "content_json"),
        (snapshot["outline"], "pinned_planning_content_json"),
    ):
        if as_text:
            owner[field] = json.dumps(owner[field], ensure_ascii=False)

    result = build_project_overview(snapshot)

    assert result.project.genre == "东方奇幻"
    assert result.progress.current_volume is not None
    assert result.progress.current_volume.id == "volume-r1"
    assert result.modules.seed == "current"
    assert result.modules.planning == "current"
    assert result.modules.outline == "current"


@pytest.mark.parametrize(
    "hostile",
    (
        "[\"raw-secret-marker\"]",
        "{malformed raw-secret-marker",
        42,
        ["raw-secret-marker"],
    ),
)
def test_hostile_seed_json_falls_back_without_leaking(hostile):
    snapshot = _snapshot()
    snapshot["selected_seed"] = snapshot["selected_seed"] | {
        "payload_json": hostile
    }

    result = build_project_overview(snapshot)
    serialized = str(result.model_dump(mode="json", by_alias=True))

    assert result.project.genre == "备用题材"
    assert result.project.logline == "备用创意"
    assert result.modules.seed == "needs_review"
    assert "raw-secret-marker" not in serialized


@pytest.mark.parametrize(
    "selected_seed",
    (
        {"selected_at": 600, "payload_json": {"genre": "历史"}},
        {
            "selection_revision": 0,
            "selected_at": 600,
            "payload_json": {"genre": "历史"},
        },
        {
            "selection_revision": 1,
            "selected_at": "600",
            "payload_json": {"genre": "历史"},
        },
    ),
)
def test_incomplete_seed_selection_authority_needs_review(selected_seed):
    result = build_project_overview(_snapshot(selected_seed=selected_seed))

    assert result.modules.seed == "needs_review"
    assert result.project.genre == "备用题材"
    assert "seed" not in {
        achievement.kind for achievement in result.recent_achievements
    }


def test_blank_project_copy_uses_fixed_non_factual_author_copy():
    snapshot = _snapshot()
    snapshot["selected_seed"] = None
    snapshot["project"] = snapshot["project"] | {"genre": " ", "description": ""}

    project = build_project_overview(snapshot).project

    assert project.genre == "题材尚未填写"
    assert project.logline == "一句话创意尚未填写"


@pytest.mark.parametrize(
    "pinned",
    (
        None,
        "not-json raw-secret-marker",
        [],
        {"storyBlocks": [], "volumes": []},
        {
            "storyBlocks": [
                {"id": "block-r1", "volumeId": "volume-r1"},
                {"id": "block-r1", "volumeId": "volume-r2"},
            ],
            "volumes": [
                {
                    "id": "volume-r2",
                    "lifecycle": "active",
                    "order": 2,
                    "title": "黑潮初临",
                }
            ],
        },
        {
            "storyBlocks": [{"id": "block-r1", "volumeId": "volume-r1"}],
            "volumes": [
                {
                    "id": "volume-r1",
                    "lifecycle": "retired",
                    "order": 1,
                    "title": "黑潮初临",
                },
                {
                    "id": "volume-r2",
                    "lifecycle": "active",
                    "order": 2,
                    "title": "黑潮初临",
                },
            ],
        },
    ),
)
def test_current_volume_never_falls_back_to_current_planning_or_name(pinned):
    snapshot = _snapshot()
    snapshot["outline"] = snapshot["outline"] | {
        "pinned_planning_content_json": pinned
    }

    result = build_project_overview(snapshot)
    serialized = str(result.model_dump(mode="json", by_alias=True))

    assert result.progress.current_volume is None
    assert result.modules.outline == "needs_review"
    assert "volume-r2" not in serialized
    assert "raw-secret-marker" not in serialized


def test_malformed_outline_reference_returns_null_without_leaking():
    snapshot = _snapshot()
    snapshot["outline"] = snapshot["outline"] | {
        "content_json": {"storyBlockRef": ["raw-secret-marker"]}
    }

    result = build_project_overview(snapshot)

    assert result.progress.current_volume is None
    assert result.modules.outline == "needs_review"
    assert "raw-secret-marker" not in str(result.model_dump(mode="json"))


def test_achievement_ties_are_deterministic_and_bad_timestamps_are_excluded():
    snapshot = _snapshot()
    snapshot["selected_seed"] = snapshot["selected_seed"] | {"selected_at": 50}
    snapshot["contract"] = snapshot["contract"] | {"updated_at": 50}
    snapshot["bible"] = snapshot["bible"] | {"updated_at": "50"}
    snapshot["planning"] = snapshot["planning"] | {"updated_at": -1}
    snapshot["final_aggregate"] = snapshot["final_aggregate"] | {
        "latest_finalized_at": 50
    }

    result = build_project_overview(snapshot)

    assert [item.kind for item in result.recent_achievements] == [
        "seed",
        "contract",
        "final_chapter",
    ]
    assert len({
        (item.kind, item.label, item.occurred_at_ms)
        for item in result.recent_achievements
    }) == len(result.recent_achievements)
