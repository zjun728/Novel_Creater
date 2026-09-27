from backend.domain.finalization import FinalizationChangeSet, change_set_hash, change_set_payload
from backend.services.finalization_commit import build_canon_commit
from backend.tests.unit.test_finalization_commit import _planning, _change_set


def long_ids(change_set):
    payload = change_set_payload(change_set)
    payload['canonEvents'][0]['id'] = 'event-' + 'v' * 70
    payload['storyProgressEvents'][0]['id'] = 'progress-' + 'p' * 70
    return FinalizationChangeSet.model_validate(payload)


def test_long_review_ids_fit_storage_without_changing_review_or_evidence():
    change_set = long_ids(_change_set(_planning()))
    original_hash = change_set_hash(change_set)
    def mapped(project='project-1', source='attempt-1'):
        return build_canon_commit(change_set, project_id=project, expected_head=0,
            idempotency_key='a' * 64, source_id=source, chapter_number=1)
    result = mapped()
    ids = [x.id for x in (*result.entities, *result.aliases, *result.events)]
    assert all(len(value) <= 36 for value in ids)
    assert len(set(ids)) == len(ids)
    assert result.aliases[0].entity_id == result.entities[0].id
    assert result.events[0].event.entity_id == result.entities[0].id
    assert mapped().events == result.events
    assert mapped(source='attempt-2').events[0].id != result.events[0].id
    assert mapped(project='project-2').events[0].id != result.events[0].id
    assert change_set_hash(change_set) == original_hash
    assert result.events[0].event.value == change_set.canon_events[0].value
    assert result.events[0].event.evidence['excerptHash'] == change_set.canon_events[0].evidence.excerpt_hash
    assert result.events[1].event.field_path.endswith('block-1')


def test_short_review_ids_are_scoped_and_new_entity_references_follow_mapping():
    change_set = _change_set(_planning())
    result = build_canon_commit(change_set, project_id='project-1', expected_head=0,
        idempotency_key='a' * 64, source_id='attempt-1', chapter_number=1)
    assert result.entities[0].id != change_set.entities[0].id
    assert result.aliases[0].id != change_set.aliases[0].id
    assert result.aliases[0].entity_id == result.entities[0].id
    assert result.events[0].event.entity_id == result.entities[0].id
    assert result.events[0].id != change_set.canon_events[0].id
    original_hash = change_set_hash(change_set)
    for project, source in [('project-1', 'attempt-2'), ('project-2', 'attempt-1')]:
        other = build_canon_commit(change_set, project_id=project, expected_head=1,
            idempotency_key='b' * 64, source_id=source, chapter_number=2)
        assert {event.id for event in result.events}.isdisjoint(event.id for event in other.events)
        assert result.entities[0].id != other.entities[0].id
        assert result.aliases[0].id != other.aliases[0].id
    repeated = build_canon_commit(change_set, project_id='project-1', expected_head=0,
        idempotency_key='a' * 64, source_id='attempt-1', chapter_number=1)
    assert repeated.events == result.events
    assert repeated.entities == result.entities
    assert repeated.aliases == result.aliases
    assert change_set_hash(change_set) == original_hash


def test_existing_entity_references_and_unstructured_values_are_not_remapped():
    payload = change_set_payload(_change_set(_planning()))
    payload['existingEntityIds'] = ['existing-entity']
    payload['aliases'].append({'id': 'alias-existing', 'entityId': 'existing-entity', 'alias': '旧人物'})
    existing_event = dict(payload['canonEvents'][0], id='existing-event', entityId='existing-entity', value='entity-new')
    global_event = dict(payload['canonEvents'][0], id='global-event', entityId=None, value={'reference': 'entity-new'})
    payload['canonEvents'].extend([existing_event, global_event])
    value = FinalizationChangeSet.model_validate(payload)
    result = build_canon_commit(value, project_id='project-1', expected_head=1,
        idempotency_key='a' * 64, source_id='attempt-2', chapter_number=2)
    assert result.aliases[1].entity_id == 'existing-entity'
    assert result.events[1].event.entity_id == 'existing-entity'
    assert result.events[1].event.value == 'entity-new'
    assert result.events[2].event.entity_id is None
    assert result.events[2].event.value == {'reference': 'entity-new'}
