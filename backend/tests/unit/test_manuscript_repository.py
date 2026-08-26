from __future__ import annotations

import traceback

import aiomysql
import pytest

from backend.domain.manuscripts import ManuscriptCorrupt, ManuscriptUnavailable
from backend.tests.unit.test_novel_download_repository import _row


class CapturingSession:
    def __init__(self, responses=(), *, failure: Exception | None = None):
        self.responses = [list(rows) for rows in responses]
        self.failure = failure
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []

    async def fetchall(self, sql, args=None):
        self.calls.append((sql, args))
        if self.failure is not None:
            raise self.failure
        return self.responses.pop(0)


def _directory_row(**kwargs):
    row = _row(**kwargs)
    row.pop("final_content")
    row.pop("final_content_hash")
    row.update(
        project_id="project-id",
        project_archived_at=None,
        final_scalar_count=4,
        final_finalized_at=1_724_544_000_000,
    )
    return row


def _target_row(**kwargs):
    row = _directory_row(**kwargs)
    row["final_content"] = kwargs.get("prose", "最终正文")
    from hashlib import sha256

    row["final_content_hash"] = sha256(row["final_content"].encode("utf-8")).hexdigest()
    return row


@pytest.mark.asyncio
async def test_directory_query_is_lightweight_parameterized_and_deterministic():
    from backend.repositories.manuscripts import ManuscriptRepository

    session = CapturingSession(([_directory_row()],))
    record = await ManuscriptRepository().load_directory(session, "project-id")

    assert record is not None and record.total_scalar_count == 4
    assert record.lifecycle == "active"
    assert record.volumes[0].chapters[0].title == "章节标题"
    assert len(session.calls) == 1
    sql, args = session.calls[0]
    projection = sql.lower().split(" from ", 1)[0]
    assert "char_length(final.content) as final_scalar_count" in projection
    assert "final.content as" not in projection
    assert "final.content_hash" not in projection
    assert args == ("project-id",)
    assert "order by final.chapter_num asc, final.id asc" in " ".join(sql.lower().split())


@pytest.mark.asyncio
async def test_directory_distinguishes_missing_project_from_empty_archived_project():
    from backend.repositories.manuscripts import ManuscriptRepository

    repository = ManuscriptRepository()
    assert await repository.load_directory(CapturingSession(([],)), "missing") is None

    empty = await repository.load_directory(
        CapturingSession(([{"project_id": "project-id", "book_title": "书名", "project_archived_at": 9, "final_id": None}],)),
        "project-id",
    )
    assert empty is not None
    assert empty.lifecycle == "archived"
    assert empty.volumes == () and empty.total_scalar_count == 0


@pytest.mark.asyncio
async def test_directory_allows_global_chapter_gaps_and_sums_database_scalar_counts():
    from backend.repositories.manuscripts import ManuscriptRepository

    chapter_1 = _directory_row(final_id="final-1", chapter_number=1, title="泔水醒来，三日织机赌局")
    chapter_3 = _directory_row(final_id="final-3", chapter_number=3, title="复验定局")
    chapter_1["final_scalar_count"] = 10
    chapter_3["final_scalar_count"] = 8
    result = await ManuscriptRepository().load_directory(
        CapturingSession(([chapter_3, chapter_1],)), "project-id",
    )

    assert result is not None
    assert [chapter.number for volume in result.volumes for chapter in volume.chapters] == [1, 3]
    assert result.total_scalar_count == 18


@pytest.mark.asyncio
async def test_directory_ignores_prose_hash_but_rejects_authority_and_structure_corruption():
    from backend.repositories.manuscripts import ManuscriptRepository

    valid = _directory_row()
    valid["final_content"] = "SHOULD_NOT_BE_NEEDED"
    valid["final_content_hash"] = "0" * 64
    assert await ManuscriptRepository().load_directory(CapturingSession(([valid],)), "project-id")

    for key, value in (
        ("session_story_block_hash", "0" * 64),
        ("outline_content_hash", "0" * 64),
        ("planning_content_hash", "0" * 64),
    ):
        row = _directory_row()
        row[key] = value
        with pytest.raises(ManuscriptCorrupt) as caught:
            await ManuscriptRepository().load_directory(CapturingSession(([row],)), "project-id")
        assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_directory_rejects_an_internally_equal_authority_chain_owned_by_another_project():
    from backend.repositories.manuscripts import ManuscriptRepository

    row = _directory_row()
    for key in (
        "final_project_id", "session_project_id", "outline_project_id",
        "planning_project_id",
    ):
        row[key] = "other-project"
    with pytest.raises(ManuscriptCorrupt):
        await ManuscriptRepository().load_directory(
            CapturingSession(([row],)), "project-id",
        )


@pytest.mark.asyncio
async def test_chapter_reads_only_target_prose_and_metadata_only_neighbors():
    from backend.repositories.manuscripts import ManuscriptRepository

    target = _target_row(chapter_number=2, title="废料改机", prose="第二章正文")
    neighbors = [
        {"project_id": "project-id", "final_chapter_num": 1},
        {"project_id": "project-id", "final_chapter_num": 2},
        {"project_id": "project-id", "final_chapter_num": 5},
    ]
    session = CapturingSession(([target], neighbors))
    lookup = await ManuscriptRepository().load_chapter(session, "project-id", 2)

    assert lookup.project_exists is True and lookup.chapter is not None
    chapter = lookup.chapter
    assert chapter.content == "第二章正文"
    assert chapter.previous_number == 1 and chapter.next_number == 5
    assert chapter.outline.model_dump() == {
        "chapter_goal": "目标",
        "expected_characters": (),
        "continuation": (),
        "planned_tasks": ("任务",),
        "scenes": ("场景",),
        "forbidden_early_events": (),
    }
    target_sql, target_args = session.calls[0]
    assert "project.id=%s" in target_sql and "final.chapter_num=%s" in target_sql
    assert target_args == ("project-id", 2)
    neighbor_sql, neighbor_args = session.calls[1]
    neighbor_projection = neighbor_sql.lower().split(" from ", 1)[0]
    assert "final.content" not in neighbor_projection
    assert neighbor_args == ("project-id",)


@pytest.mark.asyncio
async def test_chapter_lookup_separates_missing_project_and_missing_target():
    from backend.repositories.manuscripts import ManuscriptRepository

    repository = ManuscriptRepository()
    missing_project = await repository.load_chapter(
        CapturingSession(([], [])), "missing", 1,
    )
    missing_target = await repository.load_chapter(
        CapturingSession(([], [{"project_id": "project-id", "final_chapter_num": 3}])),
        "project-id", 1,
    )
    assert missing_project.project_exists is False and missing_project.chapter is None
    assert missing_target.project_exists is True and missing_target.chapter is None


@pytest.mark.asyncio
async def test_chapter_rejects_target_hash_but_ignores_out_of_range_prose_corruption():
    from backend.repositories.manuscripts import ManuscriptRepository

    target = _target_row(chapter_number=1, prose="第一章正文")
    lookup = await ManuscriptRepository().load_chapter(
        CapturingSession(([target], [
            {"project_id": "project-id", "final_chapter_num": 1},
            {"project_id": "project-id", "final_chapter_num": 3, "final_content": "BAD", "final_content_hash": "0" * 64},
        ])),
        "project-id", 1,
    )
    assert lookup.chapter is not None and lookup.chapter.next_number == 3

    target["final_content_hash"] = "0" * 64
    with pytest.raises(ManuscriptCorrupt):
        await ManuscriptRepository().load_chapter(
            CapturingSession(([target], [{"project_id": "project-id", "final_chapter_num": 1}])),
            "project-id", 1,
        )


@pytest.mark.asyncio
async def test_repository_maps_only_driver_availability_failures_without_sensitive_causes():
    from backend.repositories.manuscripts import ManuscriptRepository

    failure = aiomysql.OperationalError(2006, "SECRET_SQL_AND_HOST")
    with pytest.raises(ManuscriptUnavailable) as caught:
        await ManuscriptRepository().load_directory(
            CapturingSession(failure=failure), "SECRET_PROJECT_ID",
        )
    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert "SECRET_SQL_AND_HOST" not in rendered
    assert "SECRET_PROJECT_ID" not in rendered

    with pytest.raises(TypeError):
        await ManuscriptRepository().load_directory(
            CapturingSession(failure=TypeError("programmer bug")), "project-id",
        )
