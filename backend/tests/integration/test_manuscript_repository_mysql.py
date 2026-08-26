from __future__ import annotations

from hashlib import sha256

import pytest

from backend.domain.finalization import change_set_hash
from backend.domain.manuscripts import ManuscriptCorrupt
from backend.repositories.finalization import FinalizationRepository
from backend.repositories.manuscripts import ManuscriptRepository
from backend.services.finalization_commit import CommitFinalization
from backend.tests.integration.test_atomic_finalization_mysql import (
    HASH_B,
    PROJECT_ID,
    SESSION_ID,
    _seed,
    _service,
)
from backend.tests.integration.test_novel_download_repository_mysql import (
    _insert_additional_final_chapter,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


async def _seed_three_chapters(disposable_mysql):
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    async with transaction_factory() as session:
        _, change_set = await _seed(session, transaction_factory)
    finalization = _service(transaction_factory, FinalizationRepository(), (
        "50000000-0000-4000-8000-000000000011",
        "50000000-0000-4000-8000-000000000012",
        "50000000-0000-4000-8000-000000000013",
    ))
    await finalization.commit(CommitFinalization(
        project_id=PROJECT_ID,
        chapter_session_id=SESSION_ID,
        idempotency_key=HASH_B,
        expected_revision=1,
        expected_revision_hash=change_set_hash(change_set),
    ))
    async with transaction_factory() as session:
        await session.execute(
            "UPDATE final_chapters SET title=%s WHERE project_id=%s AND chapter_num=1",
            ("泔水醒来，三日织机赌局", PROJECT_ID),
        )
        for number, suffix, title, content in (
            (2, "02", "废料改机", "第二章正文。"),
            (3, "03", "复验定局", "第三章正文。"),
        ):
            await _insert_additional_final_chapter(
                session,
                chapter_number=number,
                suffix=suffix,
                content=content,
                persisted_hash=sha256(content.encode("utf-8")).hexdigest(),
            )
            await session.execute(
                "UPDATE final_chapters SET title=%s WHERE project_id=%s AND chapter_num=%s",
                (title, PROJECT_ID, number),
            )
    return transaction_factory


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_repository_compiles_and_separates_missing_empty_and_target_missing(disposable_mysql):
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    repository = ManuscriptRepository()
    async with transaction_factory() as session:
        assert await repository.load_directory(session, "00000000-0000-0000-0000-000000000099") is None
        await session.execute(
            """INSERT INTO projects
               (id,title,genre,description,target_words,target_chapters,status,
                current_chapter,created_at,updated_at)
               VALUES (%s,'空书','测试','',1000,10,'drafting',0,1,1)""",
            ("00000000-0000-0000-0000-000000000098",),
        )
        empty = await repository.load_directory(
            session, "00000000-0000-0000-0000-000000000098",
        )
        missing_target = await repository.load_chapter(
            session, "00000000-0000-0000-0000-000000000098", 1,
        )
    assert empty is not None and empty.volumes == ()
    assert missing_target.project_exists is True and missing_target.chapter is None


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_active_and_archived_reads_keep_titles_gaps_and_pinned_historical_planning(disposable_mysql):
    transaction_factory = await _seed_three_chapters(disposable_mysql)
    repository = ManuscriptRepository()
    async with transaction_factory() as session:
        complete = await repository.load_directory(session, PROJECT_ID)
        await session.execute(
            "DELETE FROM final_chapters WHERE project_id=%s AND chapter_num=2",
            (PROJECT_ID,),
        )
        active_directory = await repository.load_directory(session, PROJECT_ID)
        active_chapter = await repository.load_chapter(session, PROJECT_ID, 1)
        head = await session.fetchone(
            "SELECT revision FROM project_planning_heads WHERE project_id=%s", (PROJECT_ID,),
        )
        await session.execute(
            "UPDATE projects SET archived_at=99 WHERE id=%s", (PROJECT_ID,),
        )
        archived_directory = await repository.load_directory(session, PROJECT_ID)
        archived_chapter = await repository.load_chapter(session, PROJECT_ID, 1)

    assert complete is not None
    assert [chapter.title for volume in complete.volumes for chapter in volume.chapters] == [
        "泔水醒来，三日织机赌局", "废料改机", "复验定局",
    ]
    assert active_directory is not None and archived_directory is not None
    assert [chapter.title for volume in active_directory.volumes for chapter in volume.chapters] == [
        "泔水醒来，三日织机赌局", "复验定局",
    ]
    assert [chapter.number for volume in active_directory.volumes for chapter in volume.chapters] == [1, 3]
    assert head["revision"] == 2
    assert active_directory.lifecycle == "active" and archived_directory.lifecycle == "archived"
    assert archived_directory.model_copy(update={"lifecycle": "active"}) == active_directory
    assert active_chapter.chapter is not None and archived_chapter.chapter is not None
    assert active_chapter.chapter.next_number == 3
    assert archived_chapter.chapter.model_copy(update={"lifecycle": "active"}) == active_chapter.chapter


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_corrupt_out_of_range_prose_does_not_block_directory_or_chapter_one(disposable_mysql):
    transaction_factory = await _seed_three_chapters(disposable_mysql)
    repository = ManuscriptRepository()
    async with transaction_factory() as session:
        await session.execute(
            "UPDATE final_chapters SET content_hash=%s WHERE project_id=%s AND chapter_num=3",
            ("0" * 64, PROJECT_ID),
        )
        directory = await repository.load_directory(session, PROJECT_ID)
        chapter_1 = await repository.load_chapter(session, PROJECT_ID, 1)
        with pytest.raises(ManuscriptCorrupt):
            await repository.load_chapter(session, PROJECT_ID, 3)
    assert directory is not None
    assert [chapter.number for volume in directory.volumes for chapter in volume.chapters] == [1, 2, 3]
    assert chapter_1.chapter is not None and chapter_1.chapter.next_number == 2


@pytest.mark.mysql
@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ("outline_hash", "planning_hash", "missing_outline"))
async def test_exact_pinned_authority_corruption_fails_closed(disposable_mysql, corruption):
    transaction_factory = await _seed_three_chapters(disposable_mysql)
    repository = ManuscriptRepository()
    async with transaction_factory() as session:
        if corruption == "outline_hash":
            await session.execute(
                "UPDATE chapter_outline_revisions SET content_json=JSON_SET(content_json,'$.chapterGoal','tampered') WHERE project_id=%s AND chapter_num=1",
                (PROJECT_ID,),
            )
        elif corruption == "planning_hash":
            await session.execute(
                "UPDATE planning_revisions SET content_json=JSON_SET(content_json,'$.volumes[0].title','tampered') WHERE project_id=%s AND revision=1",
                (PROJECT_ID,),
            )
        else:
            await session.execute("SET FOREIGN_KEY_CHECKS=0")
            await session.execute(
                "DELETE FROM chapter_outline_revisions WHERE project_id=%s AND chapter_num=1",
                (PROJECT_ID,),
            )
            await session.execute("SET FOREIGN_KEY_CHECKS=1")
        with pytest.raises(ManuscriptCorrupt):
            await repository.load_directory(session, PROJECT_ID)
        with pytest.raises(ManuscriptCorrupt):
            await repository.load_chapter(session, PROJECT_ID, 1)
