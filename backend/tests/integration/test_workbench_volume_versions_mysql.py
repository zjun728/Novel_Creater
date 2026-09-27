"""Workbench volume identities survive metadata changes between final pins."""

from __future__ import annotations

import json

import pytest

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.planning import PlanningAggregate, planning_content_hash
from backend.repositories.workbench import WorkbenchRepository
from backend.services.workbench import WorkbenchReader
from backend.tests.integration.test_atomic_finalization_mysql import PLANNING_ID, PROJECT_ID
from backend.tests.integration.test_manuscript_repository_mysql import _seed_three_chapters


def _renamed_planning(source, title, order):
    payload = json.loads(source) if isinstance(source, str) else dict(source)
    payload = json.loads(canonical_json(payload))
    volume = payload['volumes'][0]
    volume.update(title=title, order=order, revision=volume['revision'] + 1)
    volume['contentHash'] = canonical_hash({
        key: value for key, value in volume.items() if key not in ('revision', 'contentHash')
    })
    payload['contentHash'] = planning_content_hash({
        key: value for key, value in payload.items() if key != 'contentHash'
    })
    return PlanningAggregate.model_validate(payload)


async def _insert_planning_version(session, planning, identity, revision):
    await session.execute(
        """INSERT INTO planning_revisions
           (id,project_id,revision,parent_revision,selection_revision,seed_id,
            seed_revision_id,seed_hash,contract_revision,creation_contract_id,
            creation_hash,style_contract_id,style_hash,bible_revision,
            bible_revision_id,bible_hash,content_json,content_hash,created_at)
           SELECT %s,project_id,%s,%s,selection_revision,seed_id,
                  seed_revision_id,seed_hash,contract_revision,creation_contract_id,
                  creation_hash,style_contract_id,style_hash,bible_revision,
                  bible_revision_id,bible_hash,%s,%s,created_at+%s
             FROM planning_revisions WHERE project_id=%s AND id=%s""",
        (identity, revision, revision - 1,
         canonical_json(planning.model_dump(by_alias=True, mode='json')),
         planning.content_hash, revision, PROJECT_ID, PLANNING_ID),
    )


@pytest.mark.mysql
@pytest.mark.asyncio
@pytest.mark.parametrize('renamed_order', (1, 2))
async def test_volume_summary_groups_stable_id_and_uses_latest_final_pin(disposable_mysql, renamed_order):
    connection = await _seed_three_chapters(disposable_mysql)
    revised_id = '71000000-0000-4000-8000-000000000003'
    future_id = '71000000-0000-4000-8000-000000000004'
    revised_outline_id = '71000000-0000-4000-8000-000000000005'
    async with connection() as session:
        base = await session.fetchone(
            'SELECT content_json FROM planning_revisions WHERE project_id=%s AND id=%s',
            (PROJECT_ID, PLANNING_ID),
        )
        renamed = _renamed_planning(base['content_json'], '改名后的卷', renamed_order)
        await _insert_planning_version(session, renamed, revised_id, 3)
        row = await session.fetchone(
            'SELECT id,content_json FROM chapter_outline_revisions WHERE project_id=%s AND chapter_num=3',
            (PROJECT_ID,),
        )
        outline = json.loads(row['content_json']) if isinstance(row['content_json'], str) else row['content_json']
        outline.update(planningRevisionId=revised_id, planningRevision=3, planningHash=renamed.content_hash)
        volume = renamed.volumes[0]
        outline['volumeRef'] = {'id': volume.id, 'revision': volume.revision, 'contentHash': volume.content_hash}
        outline['contentHash'] = canonical_hash({
            key: value for key, value in outline.items() if key != 'contentHash'
        })
        # Construct a second valid historical pin in this disposable fixture;
        # earlier final chapters retain their original Planning and Outline.
        await session.execute(
            """INSERT INTO chapter_outline_revisions
               (id,project_id,chapter_num,revision,parent_revision,
                planning_revision_id,planning_revision,planning_hash,
                canon_revision,projection_revision,projection_hash,content_json,content_hash,created_at)
               SELECT %s,project_id,chapter_num,2,1,%s,3,%s,
                      canon_revision,projection_revision,projection_hash,%s,%s,created_at+1
                 FROM chapter_outline_revisions WHERE project_id=%s AND id=%s""",
            (revised_outline_id, revised_id, renamed.content_hash, canonical_json(outline), outline['contentHash'], PROJECT_ID, row['id']),
        )
        for table in ('chapter_sessions', 'final_chapters'):
            await session.execute(
                f"""UPDATE {table} SET planning_revision_id=%s,planning_revision=3,
                        planning_hash=%s,chapter_outline_revision_id=%s,chapter_outline_revision=2,
                        chapter_outline_hash=%s WHERE project_id=%s AND chapter_num=3""",
                (revised_id, renamed.content_hash, revised_outline_id, outline['contentHash'], PROJECT_ID),
            )
        future = _renamed_planning(renamed.model_dump(by_alias=True, mode='json'), '仅未来规划的卷名', renamed_order)
        await _insert_planning_version(session, future, future_id, 4)
        await session.execute(
            'UPDATE project_planning_heads SET revision=4,planning_revision_id=%s,content_hash=%s WHERE project_id=%s',
            (future_id, future.content_hash, PROJECT_ID),
        )

    reader = WorkbenchReader(WorkbenchRepository(), connection)
    summary = await reader.volumes(PROJECT_ID)
    assert len(summary.volumes) == 1
    selected = summary.volumes[0]
    assert (selected.volume.id, selected.volume.title, selected.volume.order) == (volume.id, '改名后的卷', renamed_order)
    assert selected.finalized_chapter_count == 3
    assert (selected.first_finalized_chapter, selected.last_finalized_chapter) == (1, 3)
    page = await reader.chapters(PROJECT_ID, volume.id, limit=2)
    following = await reader.chapters(PROJECT_ID, volume.id, limit=2, cursor=page.next_cursor)
    assert [item.chapter_number for item in page.chapters + following.chapters] == [1, 2, 3]
    assert (await reader.bootstrap(PROJECT_ID, 1)).volume.title == '第一卷'
    assert (await reader.bootstrap(PROJECT_ID, 3)).volume.title == '改名后的卷'
