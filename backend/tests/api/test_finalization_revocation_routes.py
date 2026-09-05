from backend.services.finalization import ReviewedFinalization
from backend.tests.api.test_finalization_routes import _client, HASH_A


def test_revoke_requires_exact_attempt_and_revision_and_keeps_confirmation():
    client, service, _ = _client()
    calls = []

    async def revoke(command):
        calls.append(command)
        return ReviewedFinalization(
            attempt_id=command.attempt_id, status='cancelled',
            current_revision=2, current_revision_hash=HASH_A,
            confirmed_revision=2, confirmed_revision_hash=HASH_A,
        )

    service.revoke = revoke
    url = '/api/projects/project-1/chapter-sessions/session-1/finalization/attempts/attempt-1/revoke'
    response = client.post(url, json={'expectedRevision': 2, 'expectedRevisionHash': HASH_A})
    assert response.status_code == 200
    assert response.json()['confirmedRevision'] == 2
    assert calls[0].attempt_id == 'attempt-1'
    assert calls[0].project_id == 'project-1'
    assert calls[0].chapter_session_id == 'session-1'
    assert client.post(url, json={'expectedRevision': 2, 'expectedRevisionHash': HASH_A, 'force': True}).status_code == 422
    assert len(calls) == 1


def test_exact_attempt_state_is_read_only_and_returns_no_private_context():
    client, service, _ = _client()
    calls = []

    async def read(project_id, session_id, attempt_id):
        calls.append((project_id, session_id, attempt_id))
        return ReviewedFinalization(attempt_id, 'cancelled', 2, HASH_A, 2, HASH_A)

    service.get_attempt_state = read
    response = client.get('/api/projects/p/chapter-sessions/s/finalization/attempts/a')
    assert response.status_code == 200
    assert calls == [('p', 's', 'a')]
    assert set(response.json()) == {'attemptId', 'status', 'currentRevision', 'currentRevisionHash',
                                   'confirmedRevision', 'confirmedRevisionHash'}
