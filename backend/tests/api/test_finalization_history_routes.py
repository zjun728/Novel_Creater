from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.domain.routers import finalization
from backend.security.redaction import install_error_handlers
from backend.tests.unit.test_finalization_history import context, reader, source


def client_and_fixture(value=None):
    row = context()
    service, command, saved, history = reader(row, [source(value)])
    app = FastAPI()
    app.include_router(finalization.router, prefix="/api")
    app.dependency_overrides[finalization.get_finalization_history_reader] = lambda: service
    install_error_handlers(app)
    params = command.identity()
    params.pop("projectId")
    params.pop("chapterSessionId")
    return TestClient(app, raise_server_exceptions=False), params, saved, history


@pytest.mark.parametrize("value", [None, "", [], {}, False, 0, {"nested": [None, False, 0, [], {}]}])
def test_real_history_route_preserves_json_and_never_writes_fixture(value):
    client, params, saved, history = client_and_fixture(value)
    before = deepcopy(saved.row)
    response = client.get("/api/projects/p/chapter-sessions/s/finalization/history-reference", params=params)
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["state"] == "present" and item["value"] == value and type(item["value"]) is type(value)
    assert saved.row == before
    assert len(history.calls) == 2


@pytest.mark.parametrize("field,value", [("attemptId", "another"), ("candidateId", "another"),
    ("candidateHash", "a" * 64), ("canonRevision", 13), ("expectedRevision", 2),
    ("expectedRevisionHash", "a" * 64)])
def test_history_route_rejects_mismatched_saved_pins(field, value):
    client, params, saved, history = client_and_fixture()
    params[field] = value
    result = client.get("/api/projects/p/chapter-sessions/s/finalization/history-reference", params=params)
    assert result.status_code == 409
    assert not history.calls


def test_history_route_cannot_select_arbitrary_entity_path_or_another_session():
    client, params, saved, history = client_and_fixture("旧值")
    params.update(entityId="another", fieldPath="secret.path")
    result = client.get("/api/projects/p/chapter-sessions/s/finalization/history-reference", params=params)
    assert result.status_code == 200
    assert result.json()["items"][0]["entityId"] == "hero"
    assert result.json()["items"][0]["fieldPath"] == "observation.Record"
    history.calls.clear()
    result = client.get("/api/projects/p/chapter-sessions/another/finalization/history-reference", params=params)
    assert result.status_code == 409 and not history.calls


@pytest.mark.parametrize("field,value", [("candidateHash", "bad"), ("canonRevision", -1),
    ("expectedRevision", 0), ("attemptId", ""), ("canonRevision", "not-integer")])
def test_history_route_validates_query_without_reading(field, value):
    client, params, saved, history = client_and_fixture()
    params[field] = value
    result = client.get("/api/projects/p/chapter-sessions/s/finalization/history-reference", params=params)
    assert result.status_code == 422 and saved.reads == 0 and not history.calls


def test_failed_history_read_is_safe_and_does_not_modify_saved_review():
    client, params, saved, history = client_and_fixture()
    before = deepcopy(saved.row)
    async def fail(*args):
        raise RuntimeError("private raw input must not cross HTTP")
    history.state_history_reference = fail
    result = client.get("/api/projects/p/chapter-sessions/s/finalization/history-reference", params=params)
    assert result.status_code == 500
    assert "private raw input" not in result.text
    assert saved.row == before
