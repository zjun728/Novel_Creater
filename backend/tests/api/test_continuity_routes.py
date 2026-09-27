from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.domain.routers import continuity
from backend.security.redaction import install_error_handlers
from backend.services.continuity import ContinuityReadError


@pytest.fixture
def client(monkeypatch):
    class Reader:
        async def future_design(self, project_id, **filters):
            return {'projectId': project_id, 'revision': filters.get('revision'),
                    'entityId': filters.get('entity_id'), 'items': []}
        async def records(self, project_id, **filters):
            if project_id == 'missing':
                raise ContinuityReadError('project_missing')
            if filters.get('revision') == 1:
                raise ContinuityReadError('snapshot_changed')
            return {'projectId': project_id, 'revision': 2, 'kind': filters['kind'],
                    'entity': None, 'items': [], 'nextOffset': None}
    monkeypatch.setattr(continuity, 'reader', Reader())
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(continuity.router, prefix='/api')
    with TestClient(app, raise_server_exceptions=False) as value:
        yield value


def test_progress_is_a_separate_private_read(client):
    response = client.get('/api/projects/p/continuity/records?kind=progress')
    assert response.status_code == 200
    assert response.json()['kind'] == 'progress'
    assert response.headers['cache-control'] == 'private, no-store'


@pytest.mark.parametrize(('path', 'status', 'code'), [
    ('missing/continuity/records?kind=facts', 404, 'project_missing'),
    ('p/continuity/records?kind=facts&revision=1', 409, 'snapshot_changed'),
])
def test_read_failures_have_stable_public_codes(client, path, status, code):
    response = client.get('/api/projects/' + path)
    assert response.status_code == status
    assert response.json()['code'] == code


@pytest.mark.parametrize('query', ['kind=unknown', 'kind=facts&limit=51', 'kind=facts&offset=-1'])
def test_invalid_filters_fail_before_reading(client, query):
    assert client.get('/api/projects/p/continuity/records?' + query).status_code == 422


def test_future_design_route_passes_filters_and_is_private(client):
    response = client.get('/api/projects/p/continuity/future-design?revision=2&entity_id=person-1')
    assert response.status_code == 200
    assert response.json() == {'projectId': 'p', 'revision': 2, 'entityId': 'person-1', 'items': []}
    assert response.headers['cache-control'] == 'private, no-store'
    assert client.get('/api/projects/p/continuity/future-design?revision=-1').status_code == 422
