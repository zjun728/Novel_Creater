from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.routers import workbench
from backend.security.redaction import install_error_handlers
from backend.services.workbench import WorkbenchProjectMissing


def test_workbench_errors_are_safe_and_numbers_are_bounded(monkeypatch):
    class Reader:
        async def bootstrap(self, project_id, number):
            if project_id == 'missing':
                raise WorkbenchProjectMissing()
            raise ValueError('private diagnostic')
    monkeypatch.setattr(workbench, 'reader', Reader())
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(workbench.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        for number in (0, -1, 2147483648):
            assert client.get(f'/projects/p/workbench/chapters/{number}').status_code == 422
        response = client.get('/projects/missing/workbench/chapters/1')
        assert response.status_code == 404
        assert response.json()['code'] == 'WorkbenchProjectMissing'
        response = client.get('/projects/p/workbench/chapters/1')
        assert response.status_code == 409
        assert 'private diagnostic' not in response.text
