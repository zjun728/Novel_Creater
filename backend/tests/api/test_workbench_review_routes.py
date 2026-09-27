import aiomysql
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.routers import workbench
from backend.security.redaction import install_error_handlers
from backend.services.workbench import WorkbenchProjectMissing
from backend.services.workbench_reviews import WorkbenchReviewMissing, WorkbenchReviewReader
from backend.tests.unit.test_workbench_review_reader import Repository, connection


def test_review_route_is_private_bounded_and_uses_fixed_public_errors(monkeypatch):
    class Reader:
        async def review(self, project_id, number):
            errors = {'missing': WorkbenchProjectMissing(), 'current': WorkbenchReviewMissing(),
                      'invalid': ValueError('PRIVATE_PROVIDER_TEXT'), 'unavailable': aiomysql.OperationalError('PRIVATE_DSN')}
            if project_id in errors:
                raise errors[project_id]
            return await WorkbenchReviewReader(Repository(), connection).review('project-id', number)
    monkeypatch.setattr(workbench, 'review_reader', Reader())
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(workbench.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/projects/project-id/workbench/chapters/1/review')
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'private, no-store'
        assert response.json()['projectId'] == 'project-id'
        for project_id, status, code in (
            ('missing', 404, 'WorkbenchProjectMissing'), ('current', 404, 'WorkbenchReviewMissing'),
            ('invalid', 409, 'WorkbenchAuthorityInvalid'), ('unavailable', 503, 'WorkbenchUnavailable'),
        ):
            response = client.get(f'/projects/{project_id}/workbench/chapters/1/review')
            assert response.status_code == status and response.json()['code'] == code
            assert 'PRIVATE_' not in response.text
        for number in ('0', '-1', '2147483648', 'nan'):
            assert client.get(f'/projects/project-id/workbench/chapters/{number}/review').status_code == 422
