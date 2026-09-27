import pytest
from dataclasses import replace

from backend.domain.finalization import change_set_hash
from backend.domain.canon import thaw_json
from backend.repositories.canon import CanonRepository
from backend.repositories.finalization import FinalizationRepository
from backend.services.canon import CanonService
from backend.services import finalization_commit as commit_module
from backend.services.finalization_commit import CommitFinalization
from backend.tests.integration import test_atomic_finalization_mysql as fixture
from backend.tests.support.disposable_mysql import transaction_factory_for
from backend.tests.unit.test_finalization_storage_ids import long_ids
from backend.tests.integration.test_schema_bootstrap import _insert_project


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_atomic_commit_preserves_other_project_with_same_entity_and_alias_ids(disposable_mysql):
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    other_project = '90000000-0000-4000-8000-000000000001'
    async with transaction_factory() as session:
        _, change_set = await fixture._seed(session, transaction_factory)
        await _insert_project(session, other_project)
        entity = change_set.entities[0]
        alias = change_set.aliases[0]
        await session.execute('''INSERT INTO canon_entities
            (id,project_id,entity_type,canonical_name,normalized_name,created_revision,created_at)
            VALUES (%s,%s,'person','Existing person','existing person',0,1)''', (entity.id, other_project))
        await session.execute('''INSERT INTO entity_aliases
            (id,project_id,entity_id,alias,normalized_alias,created_revision,created_at)
            VALUES (%s,%s,%s,'Existing alias','existing alias',0,1)''', (alias.id, other_project, entity.id))
        old_entity = await session.fetchone('SELECT * FROM canon_entities WHERE id=%s', (entity.id,))
        old_alias = await session.fetchone('SELECT * FROM entity_aliases WHERE id=%s', (alias.id,))
    command = CommitFinalization(fixture.PROJECT_ID, fixture.SESSION_ID, fixture.HASH_B, 1, change_set_hash(change_set))
    service = fixture._service(transaction_factory, FinalizationRepository(), (
        '50000000-0000-4000-8000-000000000031',
        '50000000-0000-4000-8000-000000000032',
        '50000000-0000-4000-8000-000000000033'))
    committed = await service.commit(command)
    assert (await service.commit(command)).record_id == committed.record_id
    async with transaction_factory() as session:
        assert await session.fetchone('SELECT * FROM canon_entities WHERE id=%s', (entity.id,)) == old_entity
        assert await session.fetchone('SELECT * FROM entity_aliases WHERE id=%s', (alias.id,)) == old_alias
        new_entity = await session.fetchone('SELECT id FROM canon_entities WHERE project_id=%s', (fixture.PROJECT_ID,))
        new_alias = await session.fetchone('SELECT id,entity_id FROM entity_aliases WHERE project_id=%s', (fixture.PROJECT_ID,))
        events = await session.fetchall('SELECT entity_id FROM canon_events WHERE project_id=%s AND entity_id IS NOT NULL', (fixture.PROJECT_ID,))
        review = await FinalizationRepository().read_current_view(session, fixture.PROJECT_ID, fixture.SESSION_ID)
    assert new_entity['id'] != entity.id
    assert new_alias['id'] != alias.id
    assert new_alias['entity_id'] == new_entity['id']
    assert events and all(row['entity_id'] == new_entity['id'] for row in events)
    assert review['changeSet']['contentHash'] == change_set_hash(change_set)


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_long_review_event_ids_commit_and_replay_without_rewriting_review(disposable_mysql, monkeypatch):
    original_factory = fixture._change_set
    monkeypatch.setattr(fixture, '_change_set', lambda *args: long_ids(original_factory(*args)))
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    async with transaction_factory() as session:
        _, change_set = await fixture._seed(session, transaction_factory)
    original_hash = change_set_hash(change_set)
    command = CommitFinalization(project_id=fixture.PROJECT_ID,
        chapter_session_id=fixture.SESSION_ID, idempotency_key=fixture.HASH_B,
        expected_revision=1, expected_revision_hash=original_hash)
    service = fixture._service(transaction_factory, FinalizationRepository(), (
        '50000000-0000-4000-8000-000000000011',
        '50000000-0000-4000-8000-000000000012',
        '50000000-0000-4000-8000-000000000013',
    ))
    committed = await service.commit(command)
    replayed = await service.commit(command)
    assert committed.canon_revision == 1
    assert replayed.replayed and replayed.record_id == committed.record_id
    async with transaction_factory() as session:
        rows = await session.fetchall('SELECT id,entity_id FROM canon_events WHERE project_id=%s', (fixture.PROJECT_ID,))
        review = await FinalizationRepository().read_current_view(session, fixture.PROJECT_ID, fixture.SESSION_ID)
        final = await session.fetchone('SELECT status FROM chapter_sessions WHERE id=%s', (fixture.SESSION_ID,))
        entities = await session.fetchall('SELECT id FROM canon_entities WHERE project_id=%s', (fixture.PROJECT_ID,))
    assert len(rows) == len(change_set.canon_events) + len(change_set.story_progress_events)
    assert all(len(row['id']) <= 36 for row in rows)
    assert all(row['entity_id'] is None or row['entity_id'] in {item['id'] for item in entities} for row in rows)
    assert review['changeSet']['contentHash'] == original_hash
    assert review['changeSet']['payload']['canonEvents'][0]['id'] == change_set.canon_events[0].id
    assert final['status'] == 'final'


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_legacy_short_ids_replay_and_later_review_reuses_local_ids(disposable_mysql, monkeypatch):
    original_factory = fixture._change_set

    def short_ids(*args):
        value = original_factory(*args)
        return value.model_copy(update={
            'canon_events': tuple(item.model_copy(update={'id': f'ce-{index:02}'})
                                  for index, item in enumerate(value.canon_events, 1)),
            'story_progress_events': tuple(item.model_copy(update={'id': f'sp-{index:02}'})
                                           for index, item in enumerate(value.story_progress_events, 1)),
        })

    monkeypatch.setattr(fixture, '_change_set', short_ids)
    transaction_factory = transaction_factory_for(disposable_mysql.connection_config)
    async with transaction_factory() as session:
        _, change_set = await fixture._seed(session, transaction_factory)
    original_hash = change_set_hash(change_set)
    command = CommitFinalization(project_id=fixture.PROJECT_ID,
        chapter_session_id=fixture.SESSION_ID, idempotency_key=fixture.HASH_B,
        expected_revision=1, expected_revision_hash=original_hash)
    service = fixture._service(transaction_factory, FinalizationRepository(), (
        '50000000-0000-4000-8000-000000000021',
        '50000000-0000-4000-8000-000000000022',
        '50000000-0000-4000-8000-000000000023',
    ))
    current_builder = commit_module.build_canon_commit

    def legacy_builder(value, **kwargs):
        request = current_builder(value, **kwargs)
        local_ids = [item.id for item in (*value.canon_events, *value.story_progress_events)]
        reverse = {stored.id: local.id for stored, local in zip(request.entities, value.entities, strict=True)}
        return replace(request,
            entities=tuple(replace(item, id=reverse[item.id]) for item in request.entities),
            aliases=tuple(replace(item, id=local.id, entity_id=reverse.get(item.entity_id, item.entity_id))
                          for item, local in zip(request.aliases, value.aliases, strict=True)),
            events=tuple(replace(event, id=local_id, event=replace(event.event,
                entity_id=reverse.get(event.event.entity_id, event.event.entity_id),
                value=thaw_json(event.event.value), evidence=thaw_json(event.event.evidence)))
                for event, local_id in zip(request.events, local_ids, strict=True)))

    # Commit through the complete Atomic service using the previous storage policy.
    monkeypatch.setattr(commit_module, 'build_canon_commit', legacy_builder)
    committed = await service.commit(command)
    async with transaction_factory() as session:
        before = await session.fetchall(
            'SELECT id,evidence_json FROM canon_events WHERE project_id=%s ORDER BY event_order',
            (fixture.PROJECT_ID,))
    assert [row['id'] for row in before] == ['ce-01', 'sp-01', 'sp-02']

    def forbidden_builder(*args, **kwargs):
        pytest.fail('an already committed review must replay before building Canon events')

    monkeypatch.setattr(commit_module, 'build_canon_commit', forbidden_builder)
    replayed = await service.commit(command)
    assert replayed.replayed
    assert replace(replayed, replayed=False) == committed

    # A later review uses the same model-local IDs but refers to existing entities.
    later = change_set.model_copy(update={
        'existing_entity_ids': tuple(item.id for item in change_set.entities),
        'entities': (), 'aliases': (), 'planning_patches': (),
    })
    canon = CanonService(CanonRepository(), transaction_factory=transaction_factory)
    for chapter, source, key in ((2, 'later-review-2', 'd' * 64),
                                 (3, 'later-review-3', 'e' * 64)):
        request = current_builder(later, project_id=fixture.PROJECT_ID,
            expected_head=chapter - 1, idempotency_key=key,
            source_id=source, chapter_number=chapter)
        result = await canon.commit(request)
        assert result.revision_number == chapter
    async with transaction_factory() as session:
        rows = await session.fetchall(
            'SELECT id,revision_number FROM canon_events WHERE project_id=%s',
            (fixture.PROJECT_ID,))
        legacy = await session.fetchall(
            'SELECT id,evidence_json FROM canon_events WHERE project_id=%s AND revision_number=1 ORDER BY event_order',
            (fixture.PROJECT_ID,))
        review = await FinalizationRepository().read_current_view(
            session, fixture.PROJECT_ID, fixture.SESSION_ID)
    assert len(rows) == 9 and len({row['id'] for row in rows}) == 9
    assert all(len(row['id']) == 36 for row in rows if row['revision_number'] > 1)
    assert legacy == before
    assert review['changeSet']['contentHash'] == original_hash
    assert review['changeSet']['payload']['canonEvents'][0]['id'] == 'ce-01'
