from __future__ import annotations

from hashlib import sha256
import json

import pytest

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.novel_downloads import (
    DownloadFormat,
    DownloadScope,
    NovelDownloadIntegrityError,
    NovelDownloadSelector,
)
from backend.domain.finalization import change_set_hash
from backend.repositories.finalization import FinalizationRepository
from backend.repositories.novel_downloads import NovelDownloadRepository
from backend.services.finalization_commit import CommitFinalization
from backend.services.novel_downloads import NovelDownloadService
from backend.tests.integration.test_atomic_finalization_mysql import (
    HASH_B,
    PROJECT_ID,
    SESSION_ID,
    _seed,
    _service,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


def _selector(scope, **kwargs):
    return NovelDownloadSelector(
        scope=scope,
        format=DownloadFormat.TXT,
        **kwargs,
    )


async def _insert_additional_final_chapter(
    session,
    *,
    chapter_number: int,
    suffix: str,
    content: str,
    persisted_hash: str,
) -> None:
    outline_id = f"61000000-0000-4000-8000-0000000000{suffix}"
    session_id = f"62000000-0000-4000-8000-0000000000{suffix}"
    candidate_id = f"63000000-0000-4000-8000-0000000000{suffix}"
    record_id = f"64000000-0000-4000-8000-0000000000{suffix}"
    final_id = f"65000000-0000-4000-8000-0000000000{suffix}"
    base_outline = await session.fetchone(
        """SELECT planning_revision_id,planning_revision,planning_hash,
                  canon_revision,projection_revision,projection_hash,
                  content_json
             FROM chapter_outline_revisions
            WHERE project_id=%s AND id=%s""",
        (PROJECT_ID, "10000000-0000-4000-8000-000000000009"),
    )
    outline_payload = base_outline["content_json"]
    if isinstance(outline_payload, str):
        outline_payload = json.loads(outline_payload)
    outline_payload = dict(outline_payload)
    outline_payload["chapterNumber"] = chapter_number
    outline_payload.pop("contentHash", None)
    outline_hash = canonical_hash(outline_payload)
    outline_payload["contentHash"] = outline_hash
    await session.execute(
        """INSERT INTO chapter_outline_revisions
           (id,project_id,chapter_num,revision,parent_revision,
            planning_revision_id,planning_revision,planning_hash,
            canon_revision,projection_revision,projection_hash,content_json,
            content_hash,created_at)
           VALUES (%s,%s,%s,1,0,%s,%s,%s,%s,%s,%s,%s,%s,2100000000002)""",
        (
            outline_id,
            PROJECT_ID,
            chapter_number,
            base_outline["planning_revision_id"],
            base_outline["planning_revision"],
            base_outline["planning_hash"],
            base_outline["canon_revision"],
            base_outline["projection_revision"],
            base_outline["projection_hash"],
            canonical_json(outline_payload),
            outline_hash,
        ),
    )
    base_session = await session.fetchone(
        """SELECT planning_revision_id,planning_revision,planning_hash,
                  story_block_id,story_block_revision,story_block_hash,
                  expected_canon_revision
             FROM chapter_sessions
            WHERE project_id=%s AND id=%s""",
        (PROJECT_ID, SESSION_ID),
    )
    await session.execute(
        """INSERT INTO chapter_sessions
           (id,project_id,planning_revision_id,planning_revision,planning_hash,
            story_block_id,story_block_revision,story_block_hash,
            chapter_outline_revision_id,chapter_outline_revision,
            chapter_outline_hash,chapter_num,expected_canon_revision,status,
            created_at,finalized_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,'final',
                   2100000000002,2100000000003)""",
        (
            session_id,
            PROJECT_ID,
            base_session["planning_revision_id"],
            base_session["planning_revision"],
            base_session["planning_hash"],
            base_session["story_block_id"],
            base_session["story_block_revision"],
            base_session["story_block_hash"],
            outline_id,
            outline_hash,
            chapter_number,
            base_session["expected_canon_revision"],
        ),
    )
    content_hash = sha256(content.encode("utf-8")).hexdigest()
    await session.execute(
        """INSERT INTO draft_candidates
           (id,project_id,chapter_session_id,working_draft_revision,content,
            content_hash,basis_hash,provenance_json,created_at)
           VALUES (%s,%s,%s,1,%s,%s,%s,'{}',2100000000002)""",
        (candidate_id, PROJECT_ID, session_id, content, content_hash, "f" * 64),
    )
    base_record = await session.fetchone(
        """SELECT change_set_id,change_set_revision,request_fingerprint,
                  change_set_hash,expected_canon_revision,committed_canon_revision,
                  result_payload_json
             FROM finalization_records
            WHERE project_id=%s AND chapter_session_id=%s""",
        (PROJECT_ID, SESSION_ID),
    )
    await session.execute(
        """INSERT INTO finalization_records
           (id,project_id,chapter_session_id,draft_candidate_id,change_set_id,
            change_set_revision,idempotency_key,request_fingerprint,
            candidate_hash,change_set_hash,expected_canon_revision,
            committed_canon_revision,result_payload_json,finalized_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,2100000000003)""",
        (
            record_id,
            PROJECT_ID,
            session_id,
            candidate_id,
            base_record["change_set_id"],
            base_record["change_set_revision"],
            suffix[-1] * 64,
            base_record["request_fingerprint"],
            content_hash,
            base_record["change_set_hash"],
            base_record["expected_canon_revision"],
            base_record["committed_canon_revision"],
            base_record["result_payload_json"],
        ),
    )
    base_final = await session.fetchone(
        """SELECT canon_revision,planning_revision_id,planning_revision,
                  planning_hash
             FROM final_chapters
            WHERE project_id=%s AND chapter_session_id=%s""",
        (PROJECT_ID, SESSION_ID),
    )
    await session.execute(
        """INSERT INTO final_chapters
           (id,project_id,chapter_session_id,draft_candidate_id,
            finalization_record_id,chapter_num,title,content,content_hash,
            canon_revision,planning_revision_id,planning_revision,
            planning_hash,chapter_outline_revision_id,
            chapter_outline_revision,chapter_outline_hash,finalized_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,
                   2100000000003)""",
        (
            final_id,
            PROJECT_ID,
            session_id,
            candidate_id,
            record_id,
            chapter_number,
            f"第{chapter_number}章",
            content,
            persisted_hash,
            base_final["canon_revision"],
            base_final["planning_revision_id"],
            base_final["planning_revision"],
            base_final["planning_hash"],
            outline_id,
            outline_hash,
        ),
    )


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_load_snapshot_compiles_against_disposable_empty_schema(disposable_mysql):
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    async with transaction_factory() as session:
        assert await NovelDownloadRepository().load_finalized_snapshot(
            session, "00000000-0000-0000-0000-000000000099",
            _selector(DownloadScope.BOOK),
        ) is None


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_load_snapshot_ignores_changed_current_head_and_uses_final_pins(
    disposable_mysql,
):
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    async with transaction_factory() as session:
        planning, change_set = await _seed(session, transaction_factory)
    service = _service(transaction_factory, FinalizationRepository(), (
        "50000000-0000-4000-8000-000000000011",
        "50000000-0000-4000-8000-000000000012",
        "50000000-0000-4000-8000-000000000013",
    ))
    await service.commit(CommitFinalization(
        project_id=PROJECT_ID, chapter_session_id=SESSION_ID,
        idempotency_key=HASH_B, expected_revision=1,
        expected_revision_hash=change_set_hash(change_set),
    ))

    async with transaction_factory() as session:
        snapshot = await NovelDownloadRepository().load_finalized_snapshot(
            session, PROJECT_ID, _selector(DownloadScope.BOOK),
        )
        head = await session.fetchone(
            "SELECT revision,content_hash FROM project_planning_heads WHERE project_id=%s",
            (PROJECT_ID,),
        )
    assert snapshot is not None
    assert snapshot.chapters[0].chapter_number == 1
    assert snapshot.chapters[0].volume_title == "第一卷"
    assert head["revision"] == 2
    assert head["content_hash"] != planning.content_hash


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_download_integrity_is_limited_to_selected_prose_after_global_structure_check(
    disposable_mysql,
):
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
    chapter_2 = "第二章正文。"
    chapter_3 = "第三章正文。"
    async with transaction_factory() as session:
        await _insert_additional_final_chapter(
            session,
            chapter_number=2,
            suffix="02",
            content=chapter_2,
            persisted_hash=sha256(chapter_2.encode("utf-8")).hexdigest(),
        )
        await _insert_additional_final_chapter(
            session,
            chapter_number=3,
            suffix="03",
            content=chapter_3,
            persisted_hash="0" * 64,
        )
        project_before = await session.fetchone(
            """SELECT id,title,genre,description,target_words,target_chapters,
                      status,current_chapter,archived_at,lifecycle_revision,
                      created_at,updated_at
                 FROM projects WHERE id=%s""",
            (PROJECT_ID,),
        )

    downloads = NovelDownloadService(transaction_factory, NovelDownloadRepository())
    options = await downloads.options(PROJECT_ID)
    assert [chapter.number for chapter in options.chapters] == [1, 2, 3]
    chapter_1 = await downloads.download(
        PROJECT_ID,
        _selector(DownloadScope.CHAPTER, chapter_number=1),
    )
    assert "正文证据。".encode("utf-8") in chapter_1.content
    for selector in (
        _selector(DownloadScope.CHAPTER, chapter_number=3),
        _selector(DownloadScope.VOLUME, volume_id=options.volumes[0].id),
        _selector(DownloadScope.BOOK),
    ):
        with pytest.raises(NovelDownloadIntegrityError):
            await downloads.download(PROJECT_ID, selector)

    async with transaction_factory() as session:
        await session.execute(
            """UPDATE chapter_sessions
                  SET story_block_hash=%s
                WHERE project_id=%s AND chapter_num=3""",
            ("0" * 64, PROJECT_ID),
        )
    with pytest.raises(NovelDownloadIntegrityError):
        await downloads.download(
            PROJECT_ID,
            _selector(DownloadScope.CHAPTER, chapter_number=1),
        )

    async with transaction_factory() as session:
        project_after = await session.fetchone(
            """SELECT id,title,genre,description,target_words,target_chapters,
                      status,current_chapter,archived_at,lifecycle_revision,
                      created_at,updated_at
                 FROM projects WHERE id=%s""",
            (PROJECT_ID,),
        )
    assert project_after == project_before
