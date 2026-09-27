"""Read-only server-authoritative chapter mode and available writer actions."""

from contextlib import asynccontextmanager
from backend.domain.workbench import WorkbenchBootstrap, WorkbenchVolumeSummaryList, WorkbenchChapterIndexPage
from backend.repositories.chapter_sessions import authoritative_chapter


class WorkbenchProjectMissing(LookupError):
    pass


@asynccontextmanager
async def existing_session(session):
    yield session


class WorkbenchReader:
    def __init__(self, repository, connection_factory):
        self.repository = repository
        self.connection_factory = connection_factory

    async def bootstrap(self, project_id, number, *, _session=None):
        if type(number) is not int or not 1 <= number <= 2147483647:
            raise ValueError('invalid chapter number')
        async with (self.connection_factory() if _session is None else existing_session(_session)) as session:
            repo = self.repository
            project = await repo.project(session, project_id)
            if project is None:
                raise WorkbenchProjectMissing()
            active = await repo.read_active_session(session, project_id)
            maximum = await repo.read_max_final_chapter_number(session, project_id)
            current = authoritative_chapter(active, maximum)
            if active and current != (maximum or 0) + 1:
                raise ValueError('active chapter contradicts final history')
            head = await repo.read_projection_head(session, project_id)
            canon = head['canon_revision_number'] if head else None
            projection = head['projection_revision_number'] if head else None
            synchronized = canon is not None and canon == projection
            archived = project['archived_at'] is not None
            reasons = []
            def block(code, message):
                reasons.append({'code': code, 'message': message})
            if archived:
                block('project_archived', '项目已归档，仅可阅读。')
            if not synchronized:
                block('canon_projection_unsynchronized', '正文事实正在同步，请稍后重试。')
            mode = 'historical' if number < current else 'current' if number == current else 'future'
            bundle = {}
            actions = []
            session_ref = None
            if mode == 'historical':
                bundle = await repo.historical(session, project_id, number)
                actions = ['view_chapter', 'view_outline']
            elif mode == 'future':
                block('future_chapter', '请先完成当前章节。')
            else:
                bundle = await repo.current_bundle(session, project_id, number, active, head) or {}
                if not bundle:
                    block('outline_required', '请先在故事规划中确认当前章小纲。')
                else:
                    actions.append('view_outline')
                if active:
                    session_ref = {'id': active['id'], 'chapter_number': current, 'status': 'drafting'}
                    actions.extend(['view_chapter', 'compare_candidates'])
                    busy = await repo.finalization_busy(session, project_id, active['id'])
                    if busy:
                        block('finalization_in_progress', '当前章节已有审查，请先处理现有审查。')
                    if not archived:
                        actions.extend(['edit_draft', 'save_candidate'])
                        if synchronized:
                            actions.extend(['run_ai_operation', 'finalize_candidate'])
                            if not busy:
                                actions.append('audit_candidate')
                else:
                    block('session_not_created', '当前章节尚未开始写作。')
                    if bundle and synchronized and not archived:
                        actions.append('create_session')
            return WorkbenchBootstrap(
                project_id=project_id, requested_chapter=number, authoritative_chapter=current,
                mode=mode, volume=bundle.get('volume'), outline=bundle.get('outline'),
                final_chapter=bundle.get('final_chapter'), session=session_ref,
                available_actions=tuple(actions), blocked_reasons=tuple(reasons),
                canon_revision=canon, projection_revision=projection,
                canon_projection_synchronized=synchronized,
            )

    async def _navigation(self, session, project_id):
        active = await self.repository.read_active_session(session, project_id)
        maximum = await self.repository.read_max_final_chapter_number(session, project_id)
        current = authoritative_chapter(active, maximum)
        bootstrap = await self.bootstrap(project_id, current, _session=session)
        rows = await self.repository.volume_summaries(session, project_id)
        if sum(row['chapter_count'] for row in rows) != (maximum or 0):
            raise ValueError('volume summary does not cover final history')
        volumes = [{
            'volume': (bootstrap.volume.model_dump() if bootstrap.volume and bootstrap.volume.id == row['id']
                       else {'id': row['id'], 'order': row['volume_order'], 'title': row['title']}),
            'finalized_chapter_count': row['chapter_count'], 'first_finalized_chapter': row['first_chapter'],
            'last_finalized_chapter': row['last_chapter'],
            'contains_authoritative_chapter': bool(bootstrap.volume and bootstrap.volume.id == row['id']),
        } for row in rows]
        if bootstrap.volume and not any(item['contains_authoritative_chapter'] for item in volumes):
            volumes.append({'volume': bootstrap.volume.model_dump(), 'finalized_chapter_count': 0,
                            'contains_authoritative_chapter': True})
        for planned in await self.repository.planned_volumes(session, project_id):
            if not any(item['volume']['id'] == planned['id'] for item in volumes):
                volumes.append({'volume': planned, 'finalized_chapter_count': 0,
                                'contains_authoritative_chapter': False})
        volumes.sort(key=lambda item: item['volume']['order'])
        result = WorkbenchVolumeSummaryList(
            project_id=project_id, volumes=tuple(volumes), authoritative_chapter=current,
            unassigned_authoritative_chapter=current if bootstrap.volume is None else None,
        )
        return bootstrap, result

    async def volumes(self, project_id):
        async with self.connection_factory() as session:
            _, result = await self._navigation(session, project_id)
            return result

    async def chapters(self, project_id, volume_id, *, cursor=None, limit=50):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('invalid page limit')
        async with self.connection_factory() as session:
            bootstrap, summary = await self._navigation(session, project_id)
            selected = next((item for item in summary.volumes if item.volume.id == volume_id), None)
            if selected is None:
                raise ValueError('volume missing')
            stamp = f'{bootstrap.canon_revision}:{bootstrap.projection_revision}:{bootstrap.authoritative_chapter}'
            after = 0
            if cursor:
                prefix, separator, suffix = cursor.rpartition(':')
                if prefix != stamp or not separator or not suffix.isascii() or not suffix.isdecimal() or len(suffix) > 10:
                    raise ValueError('page snapshot changed')
                after = int(suffix)
            rows = await self.repository.chapter_page(session, project_id, volume_id, after, limit + 1)
            if len(rows) <= limit and selected.contains_authoritative_chapter and bootstrap.authoritative_chapter > after:
                rows.append({'chapter_number': bootstrap.authoritative_chapter,
                             'title': f'第 {bootstrap.authoritative_chapter} 章 · 当前写作', 'mode': 'current',
                             'session_id': bootstrap.session.id if bootstrap.session else None})
            next_cursor = f'{stamp}:{rows[limit - 1]["chapter_number"]}' if len(rows) > limit else None
            return WorkbenchChapterIndexPage(project_id=project_id, volume=selected.volume,
                                            chapters=tuple(rows[:limit]), next_cursor=next_cursor, limit=limit)
