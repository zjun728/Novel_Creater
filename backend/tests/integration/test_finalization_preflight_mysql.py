from uuid import uuid4

import pytest

from backend.domain.finalization import FinalizationChangeSet
from backend.repositories.finalization import FinalizationRepository
from backend.services.finalization import ConfirmFinalization, FinalizationService, PrepareFinalization
from backend.services.finalization_commit import CommitFinalization
from backend.tests.integration.test_atomic_finalization_mysql import (
    BINDING_ID, CANDIDATE_ID, HASH_A, HASH_B, NOW, PROJECT_ID, SESSION_ID,
    _seed, _service as atomic_service,
)
from backend.tests.integration.test_schema_bootstrap import _insert_active_provider
from backend.tests.support.disposable_mysql import transaction_factory_for


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_protected_patch_becomes_suggestion_then_confirm_and_atomic_commit(disposable_mysql):
    transactions = transaction_factory_for(disposable_mysql.connection_config)
    repository = FinalizationRepository()
    async with transactions() as session:
        planning, changes = await _seed(session, transactions, with_review=False)
        provider_id = str(uuid4())
        await _insert_active_provider(session, provider_id, 'preflight mock')
        await session.execute(
            "UPDATE provider_profiles SET provider_type='openai-compatible' WHERE id=%s", (provider_id,),
        )
        await session.execute(
            """UPDATE project_model_binding_items SET resolution_status='bound',provider_id=%s,
               provider_name_snapshot='preflight mock',model_name_snapshot='model'
               WHERE binding_revision_id=%s AND task_key IN ('audit','extraction')""",
            (provider_id, BINDING_ID),
        )
        candidate = await repository.lock_candidate(session, PROJECT_ID, SESSION_ID, CANDIDATE_ID)
        current = await repository.lock_current_authority(session, PROJECT_ID, 1)
    payload = changes.model_dump(by_alias=True, mode='json')
    block = planning.story_blocks[0]
    protected_id = str(uuid4())
    payload['planningPatches'].append({
        'id': protected_id, 'targetType': 'story_block', 'targetId': block.id,
        'expectedRevision': block.revision, 'expectedHash': block.content_hash,
        'fieldPath': 'expectedChange', 'replacement': '已入城，建议仅供后续参考。',
        'evidence': payload['planningPatches'][0]['evidence'],
    })

    class Provider:
        calls = []

        async def audit(self, **kwargs):
            self.calls.append('audit')
            return ()

        async def extract(self, **kwargs):
            self.calls.append('extract')
            assert block.id in kwargs['manifest'].planning_context['protectedNodeIds']
            return FinalizationChangeSet.model_validate(payload)

    provider = Provider()
    service = FinalizationService(
        transaction_factory=transactions, repository=repository,
        quality_provider=provider, extraction_provider=provider, clock=lambda: NOW + 1,
    )
    prepared = await service.prepare(PrepareFinalization(
        project_id=PROJECT_ID, chapter_session_id=SESSION_ID,
        candidate_id=CANDIDATE_ID, candidate_hash=candidate['content_hash'],
        expected_canon_revision=0, expected_planning_hash=planning.content_hash,
        expected_outline_hash=current['outline_hash'], idempotency_key=HASH_A,
    ))
    assert prepared.status == 'awaiting_author'
    async with transactions() as session:
        revision = await repository.lock_change_set_revision(
            session, PROJECT_ID, prepared.attempt_id, 1, prepared.current_revision_hash,
        )
    saved = revision['change_set']
    assert [item.id for item in saved.planning_suggestions] == [protected_id]
    assert saved.planning_patches == changes.planning_patches
    assert saved.canon_events == changes.canon_events
    assert saved.story_progress_events == changes.story_progress_events
    confirmed = await service.confirm(ConfirmFinalization(
        project_id=PROJECT_ID, chapter_session_id=SESSION_ID,
        expected_revision=1, expected_revision_hash=prepared.current_revision_hash,
    ))
    assert confirmed.confirmed_revision_hash == prepared.current_revision_hash
    commit = atomic_service(transactions, repository, (str(uuid4()) for _ in range(3)))
    command = CommitFinalization(
        project_id=PROJECT_ID, chapter_session_id=SESSION_ID,
        expected_revision=1, expected_revision_hash=prepared.current_revision_hash,
        idempotency_key=HASH_B,
    )
    result = await commit.commit(command)
    assert result.canon_revision == 1
    assert result.planning_revision == 2
    assert (await commit.commit(command)).replayed is True
    assert provider.calls == ['audit', 'extract']
    async with transactions() as session:
        head = await session.fetchone(
            """SELECT revision.content_json FROM project_planning_heads head
               JOIN planning_revisions revision ON revision.id=head.planning_revision_id
               WHERE head.project_id=%s""", (PROJECT_ID,),
        )
        final_count = await session.fetchone(
            'SELECT COUNT(*) AS count_value FROM final_chapters WHERE project_id=%s', (PROJECT_ID,),
        )
        projections = await session.fetchone(
            'SELECT canon_revision_number,projection_revision_number FROM projection_heads WHERE project_id=%s',
            (PROJECT_ID,),
        )
    import json
    updated = json.loads(head['content_json'])
    assert updated['storyBlocks'][0] == planning.model_dump(by_alias=True, mode='json')['storyBlocks'][0]
    assert updated['plots'][0]['futureDirection'] == changes.planning_patches[0].replacement
    assert final_count['count_value'] == 1
    assert projections == {'canon_revision_number': 1, 'projection_revision_number': 1}
