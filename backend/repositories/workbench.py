"""Single-chapter authority reads for the author workbench; never opens sessions."""

from backend.domain.chapter_outlines import ChapterOutline, DraftChapterOutline, normalize_chapter_outline
from backend.domain.planning import PlanningAggregate, planning_content_hash
from backend.repositories.chapter_sessions import ChapterSessionRepository, CURRENT_GENERATION_FIELDS
from backend.repositories.manuscripts import (
    _AUTHORITY_COLUMNS, _AUTHORITY_JOINS, decode_finalized_authority, decode_json_object,
)


class WorkbenchRepository(ChapterSessionRepository):
    async def planned_volumes(self, session, project_id):
        row = await session.fetchone(
            """SELECT planning.content_json,planning.content_hash FROM project_planning_heads head
               JOIN planning_revisions planning ON planning.project_id=head.project_id
                 AND planning.id=head.planning_revision_id AND planning.revision=head.revision
                 AND planning.content_hash=head.content_hash WHERE head.project_id=%s""", (project_id,),
        )
        if row is None:
            return []
        planning = PlanningAggregate.model_validate(decode_json_object(row['content_json']))
        if planning_content_hash(planning.model_dump(by_alias=True, mode='json', exclude={'content_hash'})) != row['content_hash']:
            raise ValueError('planning hash differs')
        return [{'id': item.id, 'order': item.order, 'title': item.title}
                for item in planning.volumes if item.lifecycle == 'active']

    async def volume_summaries(self, session, project_id):
        # Titles and order can change between pinned Planning versions. Group
        # by stable identity, taking metadata from this volume's latest final.
        return await session.fetchall(
            """WITH pinned_volumes AS (
                   SELECT volume.node_id AS id, volume.position AS volume_order,
                          volume.title, final.chapter_num
                     FROM final_chapters final
                     JOIN chapter_outline_revisions outline ON outline.project_id=final.project_id
                       AND outline.id=final.chapter_outline_revision_id
                       AND outline.revision=final.chapter_outline_revision AND outline.content_hash=final.chapter_outline_hash
                     JOIN planning_revisions planning ON planning.project_id=final.project_id
                       AND planning.id=final.planning_revision_id
                       AND planning.revision=final.planning_revision AND planning.content_hash=final.planning_hash
                     JOIN JSON_TABLE(planning.content_json, '$.volumes[*]' COLUMNS (
                         node_id VARCHAR(100) PATH '$.id', position INT PATH '$.order', title VARCHAR(4000) PATH '$.title'
                     )) volume ON CAST(volume.node_id AS BINARY)=CAST(JSON_UNQUOTE(JSON_EXTRACT(outline.content_json,'$.volumeRef.id')) AS BINARY)
                    WHERE final.project_id=%s
               ), ranked_volumes AS (
                   SELECT id,volume_order,title,
                          COUNT(*) OVER volume_history AS chapter_count,
                          MIN(chapter_num) OVER volume_history AS first_chapter,
                          MAX(chapter_num) OVER volume_history AS last_chapter,
                          ROW_NUMBER() OVER (PARTITION BY CAST(id AS BINARY) ORDER BY chapter_num DESC) AS latest
                     FROM pinned_volumes
                     WINDOW volume_history AS (PARTITION BY CAST(id AS BINARY))
               )
               SELECT id,volume_order,title,chapter_count,first_chapter,last_chapter
                 FROM ranked_volumes WHERE latest=1 ORDER BY volume_order""",
            (project_id,),
        )

    async def chapter_page(self, session, project_id, volume_id, after, limit):
        rows = await session.fetchall(
            f"""SELECT {_AUTHORITY_COLUMNS}, CHAR_LENGTH(final.content) AS scalar_count
                FROM projects project {_AUTHORITY_JOINS}
                WHERE project.id=%s AND final.chapter_num>%s
                  AND CAST(JSON_UNQUOTE(JSON_EXTRACT(outline.content_json,'$.volumeRef.id')) AS BINARY)=CAST(%s AS BINARY)
                ORDER BY final.chapter_num LIMIT %s""", (project_id, after, volume_id, limit),
        )
        result = []
        for row in rows:
            authority = decode_finalized_authority(row, expected_project_id=project_id)
            result.append({
                'chapter_number': authority.chapter_number, 'title': authority.chapter_title,
                'mode': 'historical', 'scalar_count': row['scalar_count'],
                'finalized_at_ms': authority.finalized_at_ms, 'final_chapter_id': authority.final_id,
            })
        return result

    async def project(self, session, project_id):
        return await session.fetchone(
            "SELECT id,archived_at FROM projects WHERE id=%s", (project_id,),
        )

    async def historical(self, session, project_id, number):
        row = await session.fetchone(
            f"""SELECT {_AUTHORITY_COLUMNS}, final.content_hash AS final_content_hash
                FROM projects project {_AUTHORITY_JOINS}
                WHERE project.id=%s AND final.chapter_num=%s""", (project_id, number),
        )
        if row is None:
            raise ValueError('historical chapter missing')
        authority = decode_finalized_authority(row, expected_project_id=project_id)
        return {
            'volume': {'id': authority.volume.id, 'order': authority.volume.order, 'title': authority.volume.title},
            'outline': {'id': row['outline_id'], 'revision': row['outline_revision'], 'content_hash': row['outline_content_hash']},
            'final_chapter': {'id': authority.final_id, 'chapter_number': number, 'content_hash': row['final_content_hash']},
        }

    async def current_bundle(self, session, project_id, number, active, head):
        # New draft operations and candidates use the current confirmed outline;
        # the session's creation-time pin does not advance when it is revised.
        row = await self.read_current_outline(session, project_id, number)
        if row is None:
            if active:
                raise ValueError('active session has no pinned outline')
            return None
        if not active:
            # A new session must use the current generation, including all
            # immutable seed/contract/Bible identities checked by the writer.
            if any(row.get(f'planning_{key}') != row.get(f'current_{key}')
                   for key in CURRENT_GENERATION_FIELDS):
                return None
            if (row['planning_revision_id'], row['planning_revision'], row['planning_hash']) != (
                row['current_planning_revision_id'], row['current_planning_revision'], row['current_planning_hash'],
            ):
                return None
            if head is None or (row['canon_revision'], row['projection_revision'], row['projection_hash']) != (
                head['canon_revision_number'], head['projection_revision_number'], head['content_hash'],
            ):
                return None
        planning_row = await session.fetchone(
            """SELECT content_json FROM planning_revisions
               WHERE project_id=%s AND id=%s AND revision=%s AND content_hash=%s""",
            (project_id, row['planning_revision_id'], row['planning_revision'], row['planning_hash']),
        )
        if planning_row is None:
            raise ValueError('pinned planning missing')
        planning = PlanningAggregate.model_validate(decode_json_object(planning_row['content_json']))
        if planning_content_hash(planning.model_dump(by_alias=True, mode='json', exclude={'content_hash'})) != row['planning_hash']:
            raise ValueError('pinned planning hash differs')
        outline = ChapterOutline.model_validate(row['chapter_outline'])
        draft = DraftChapterOutline.model_validate(outline.model_dump(by_alias=True, mode='json', exclude={
            'canon_revision', 'projection_revision', 'projection_hash', 'content_hash',
        }))
        verified = normalize_chapter_outline(
            draft, planning=planning, authoritative_chapter_number=number,
            planning_revision_id=row['planning_revision_id'], planning_revision=row['planning_revision'],
            capacity_policy=outline.capacity_policy, canon_revision=outline.canon_revision,
            projection_revision=outline.projection_revision, projection_hash=outline.projection_hash,
        )
        if verified.content_hash != row['chapter_outline_hash'] or outline.content_hash != verified.content_hash:
            raise ValueError('pinned outline hash differs')
        volume = next(item for item in planning.volumes if item.id == outline.volume_ref.id)
        return {
            'volume': {'id': volume.id, 'order': volume.order, 'title': volume.title},
            'outline': {'id': row['chapter_outline_revision_id'], 'revision': row['chapter_outline_revision'], 'content_hash': outline.content_hash},
        }

    async def finalization_busy(self, session, project_id, session_id):
        row = await session.fetchone(
            """SELECT id FROM finalization_change_sets WHERE project_id=%s
               AND chapter_session_id=%s AND status IN ('preparing','awaiting_author','committing') LIMIT 1""",
            (project_id, session_id),
        )
        return row is not None
