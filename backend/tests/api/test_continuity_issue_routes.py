import aiomysql
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.database import DatabaseUnavailable
from backend.domain.continuity_issues import (
    ContinuityIssueConflict, ContinuityIssueInvalid, ContinuityIssueNotFound,
    ContinuityIssueSourceInvalid,
)
from backend.domain.routers import continuity_issues
from backend.http_errors import ProjectArchived, ProjectNotFound
from backend.security.redaction import install_error_handlers
from backend.tests.unit.test_continuity_issues import ISSUE_ID, PROJECT_ID, Repository, service


@pytest.fixture
def api():
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(continuity_issues.router, prefix='/api')
    repo = Repository()
    app.dependency_overrides[continuity_issues.get_continuity_issue_service] = lambda: service(repo)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, app, repo


def payload(**changes):
    return {'id': ISSUE_ID, 'category': 'fact', 'severity': 'medium', 'description': '事实冲突'} | changes


BASE = f'/api/projects/{PROJECT_ID}/continuity/issues'


def test_routes_create_read_update_and_retry_use_camel_case_private_dtos(api):
    client, _, _ = api
    created = client.post(BASE, json=payload(sourceChapterNumber=1))
    assert created.status_code == 200
    assert created.headers['Cache-Control'] == 'private, no-store'
    value = created.json()
    assert value['sourceChapterNumber'] == 1 and value['sourceCanonRevision'] == 1
    assert value['projectId'] == PROJECT_ID and not any('_' in key for key in value)
    updated = client.patch(BASE + '/' + ISSUE_ID, json={
        'status': 'resolved', 'resolutionNote': '第四章说明原因', 'expectedUpdatedAt': value['updatedAt']})
    assert updated.status_code == 200 and updated.json()['updatedAt'] == 101
    assert client.get(BASE + '/' + ISSUE_ID).json() == updated.json()
    assert client.post(BASE, json=payload(sourceChapterNumber=1)).json() == updated.json()
    listed = client.get(BASE + '?status=resolved&limit=1').json()
    assert listed == {'projectId': PROJECT_ID, 'lifecycle': 'active', 'items': [updated.json()], 'nextOffset': None}
    assert client.get(BASE + '?status=pending').json()['items'] == []


@pytest.mark.parametrize('method,path,body', [
    ('post', '', payload(sourceFinalizationId='private-id')),
    ('post', '', payload(source_chapter=1)), ('post', '', payload(description=' ')),
    ('post', '', payload(sourceChapterNumber=True)), ('post', '', payload(severity='critical')),
    ('patch', '/' + ISSUE_ID, {'status': 'resolved', 'expectedUpdatedAt': 100}),
    ('patch', '/' + ISSUE_ID, {'status': 'ignored', 'resolutionNote': '', 'expectedUpdatedAt': 100}),
    ('patch', '/' + ISSUE_ID, {'status': 'pending', 'expectedUpdatedAt': '100'}),
    ('patch', '/' + ISSUE_ID, {'status': 'pending', 'expectedUpdatedAt': 100, 'description': '改原文'}),
    ('get', '?limit=51', None), ('get', '?offset=-1', None), ('get', '?status=closed', None),
])
def test_invalid_requests_are_fixed_safe_and_do_not_reach_service(api, method, path, body):
    client, _, repo = api
    response = client.request(method, BASE + path, json=body)
    assert response.status_code == 422 and response.json()['code'] == 'ContinuityIssueInvalid'
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert repo.actions == []
    assert 'private-id' not in response.text


@pytest.mark.parametrize('error,status,code', [
    (ContinuityIssueNotFound(), 404, 'ContinuityIssueNotFound'),
    (ContinuityIssueConflict(), 409, 'ContinuityIssueConflict'),
    (ContinuityIssueSourceInvalid(), 422, 'ContinuityIssueSourceInvalid'),
    (ContinuityIssueInvalid(), 422, 'ContinuityIssueInvalid'),
    (ProjectArchived(), 409, 'ProjectArchived'), (ProjectNotFound(), 404, 'ProjectNotFound'),
    (DatabaseUnavailable(), 503, 'ContinuityIssueUnavailable'),
    (aiomysql.OperationalError(1146, 'PRIVATE_DSN'), 503, 'ContinuityIssueUnavailable'),
    (aiomysql.IntegrityError(1452, 'PRIVATE_CONSTRAINT'), 503, 'ContinuityIssueUnavailable'),
])
def test_domain_and_storage_errors_are_private_and_safe(api, error, status, code):
    client, app, _ = api
    class Broken:
        async def list(self, *args, **kwargs):
            raise error
    app.dependency_overrides[continuity_issues.get_continuity_issue_service] = Broken
    response = client.get(BASE)
    assert response.status_code == status and response.json()['code'] == code
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'PRIVATE_' not in response.text and response.json()['correlationId']


def test_archived_reads_and_guarded_writes_through_real_service(api):
    client, _, repo = api
    client.post(BASE, json=payload())
    repo.project['archived_at'] = 200
    assert client.get(BASE).json()['lifecycle'] == 'archived'
    assert client.get(BASE + '/' + ISSUE_ID).json()['lifecycle'] == 'archived'
    for method, path, body in (
        ('post', BASE, payload()),
        ('patch', BASE + '/' + ISSUE_ID, {'status': 'pending', 'expectedUpdatedAt': 100}),
    ):
        response = client.request(method, path, json=body)
        assert response.status_code == 409 and response.json()['code'] == 'ProjectArchived'
