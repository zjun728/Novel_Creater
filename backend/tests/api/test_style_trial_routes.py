from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from backend.domain.style_trials import (
    SafeProviderIdentity,
    StyleTrialFailure,
    StyleTrialResult,
)
from backend.routers import style_trials
from backend.security.redaction import install_error_handlers


class FakeService:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.result = None

    async def generate(self, command):
        self.calls.append(command)
        if self.failure is not None:
            raise self.failure
        if self.result is not None:
            return self.result
        return StyleTrialResult(
            attempt_id="attempt-1",
            status="succeeded",
            sample="原创试写正文",
            result_hash="a" * 64,
            public_error_code=None,
            provider=SafeProviderIdentity(
                provider_id="provider-1",
                provider_type="openai",
                model_name="deepseek-v4-flash",
                profile_revision=7,
            ),
            created_at=100,
            completed_at=200,
        )


def _body():
    return {
        "selectionRevision": 3,
        "engineOptionId": "engine-1",
        "engineHash": "1" * 64,
        "primaryStyleRevisionId": "style-primary",
        "primaryStyleHash": "2" * 64,
        "secondaryStyleRevisionId": "style-secondary",
        "secondaryStyleHash": "3" * 64,
        "authorScenario": "主角要在救人和保住残页之间选择。",
        "idempotencyKey": "i" * 64,
    }


def _client():
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(style_trials.router, prefix="/api")
    service = FakeService()
    app.dependency_overrides[style_trials.get_style_trial_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False), service


def test_post_style_trial_uses_backend_service_and_returns_safe_attempt():
    client, service = _client()
    response = client.post("/api/projects/project-1/style-trials", json=_body())

    assert response.status_code == 200
    assert response.json() == {
        "attemptId": "attempt-1",
        "status": "succeeded",
        "sample": "原创试写正文",
        "resultHash": "a" * 64,
        "publicErrorCode": None,
        "provider": {
            "providerId": "provider-1",
            "providerType": "openai",
            "modelName": "deepseek-v4-flash",
            "profileRevision": 7,
        },
        "createdAt": 100,
        "completedAt": 200,
    }
    assert len(service.calls) == 1
    command = service.calls[0]
    assert command.project_id == "project-1"
    assert command.author_scenario == _body()["authorScenario"]


def test_style_trial_body_rejects_partial_secondary_ref_and_unknown_fields():
    client, service = _client()
    partial = _body()
    partial["secondaryStyleHash"] = None
    unknown = _body() | {"apiKey": "must-never-enter-the-service"}

    partial_response = client.post(
        "/api/projects/project-1/style-trials", json=partial
    )
    unknown_response = client.post(
        "/api/projects/project-1/style-trials", json=unknown
    )

    assert partial_response.status_code == 422
    assert unknown_response.status_code == 422
    assert "must-never-enter-the-service" not in unknown_response.text
    assert service.calls == []


@pytest.mark.parametrize(
    ("project_id", "field", "invalid"),
    (
        ("!!!", None, None),
        ("p" * 37, None, None),
        ("project-1", "engineOptionId", "!!!"),
        ("project-1", "engineOptionId", "nested/path"),
        ("project-1", "primaryStyleRevisionId", "style!"),
        ("project-1", "secondaryStyleRevisionId", "s" * 37),
        ("project-1", "engineHash", "A" * 64),
        ("project-1", "idempotencyKey", "!" * 64),
        ("project-1", "authorScenario", "场" * 2_001),
    ),
)
def test_invalid_identifiers_hashes_and_lengths_are_safe_422_before_service(
    caplog, project_id, field, invalid,
):
    client, service = _client()
    body = _body()
    if field is not None:
        body[field] = invalid

    response = client.post(
        f"/api/projects/{project_id}/style-trials", json=body
    )

    assert response.status_code == 422
    assert service.calls == []
    if invalid is not None:
        assert str(invalid) not in caplog.text


def test_style_trial_input_changed_failure_keeps_its_fixed_409_contract():
    client, service = _client()
    service.failure = StyleTrialFailure("STYLE_TRIAL_INPUT_CHANGED")

    response = client.post("/api/projects/project-1/style-trials", json=_body())

    assert response.status_code == 409
    assert response.json()["code"] == "STYLE_TRIAL_INPUT_CHANGED"
    assert "provider" not in response.text.lower()


def test_failed_provider_attempt_api_never_exposes_raw_envelope_or_secret(caplog):
    client, service = _client()
    service.result = StyleTrialResult(
        attempt_id="attempt-1",
        status="failed",
        sample=None,
        result_hash=None,
        public_error_code="STYLE_TRIAL_PROVIDER_FAILED",
        provider=SafeProviderIdentity(
            provider_id="provider-1",
            provider_type="openai",
            model_name="deepseek-v4-flash",
            profile_revision=7,
        ),
        created_at=100,
        completed_at=200,
    )

    response = client.post("/api/projects/project-1/style-trials", json=_body())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["sample"] is None
    assert response.json()["publicErrorCode"] == "STYLE_TRIAL_PROVIDER_FAILED"
    for private_value in ("abc", "xabcx", "providerLeak"):
        assert private_value not in response.text
        assert private_value not in caplog.text


@pytest.mark.parametrize(
    "sentinel",
    (
        "SENTINEL_API_KEY_123456",
        "https://sentinel-provider.invalid/v1",
        "key7",
        "url7",
    ),
)
def test_secret_bearing_scenario_public_failure_is_fixed_and_safe(
    caplog, sentinel,
):
    client, service = _client()
    service.failure = StyleTrialFailure("STYLE_TRIAL_NOT_READY")
    body = _body()
    body["authorScenario"] = f"错误场景包含 {sentinel}"

    response = client.post("/api/projects/project-1/style-trials", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "STYLE_TRIAL_NOT_READY"
    assert "provider" not in response.text.lower()
    assert sentinel not in response.text
    assert sentinel not in caplog.text


def test_oversized_prompt_failure_is_a_fixed_safe_422(caplog):
    client, service = _client()
    service.failure = StyleTrialFailure("STYLE_TRIAL_NOT_READY")

    response = client.post("/api/projects/project-1/style-trials", json=_body())

    assert response.status_code == 422
    assert response.json()["code"] == "STYLE_TRIAL_NOT_READY"
    assert (
        response.json()["message"]
        == "Style trial prerequisites are unavailable"
    )
    assert "prompt exceeds" not in response.text.lower()
    assert "prompt exceeds" not in caplog.text.lower()


def test_production_dependency_uses_repository_and_database_boundaries():
    service = style_trials.get_style_trial_service()
    assert type(service.repository).__name__ == "StyleTrialRepository"
    assert callable(service._transaction)
    assert not hasattr(service, "_connection")
