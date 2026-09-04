from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from hashlib import sha256
import inspect
import json

import httpx
import pytest

from backend.domain.json_contracts import canonical_hash
from backend.domain.seeds import (
    SeedPayload,
    build_seed_provenance,
    seed_revision_document,
)
from backend.domain.style_trials import (
    StyleTrialFailure,
    StyleTrialProviderOutput,
)
from backend.gateways.style_trial_provider import (
    StyleTrialProviderError,
    StyleTrialProviderGateway,
)
from backend.services.style_trials import (
    STYLE_TRIAL_POLICY_VERSION,
    GenerateStyleTrial,
    StyleTrialService,
)


IDEMPOTENCY_KEY = "i" * 64


def _seed_payload():
    return {
        "title": "典镇山河",
        "genre": "历史穿越",
        "logline": "守住失散的典籍",
        "protagonist": "沈砚",
        "desire": "让同伴活着离开",
        "coreConflict": "知识会招来争夺",
        "worldPressure": "战乱逼近",
        "openingHook": "残页显字",
        "differentiation": "每次使用知识都有代价",
    }


def _engine_payload():
    return {
        "name": "残典求生",
        "storyPromise": "知识改变处境也制造新债",
        "protagonistDesire": "保住同伴与残典",
        "sustainedPressure": "官府、豪强与战乱持续收紧空间",
        "growthDirection": "从独自判断走向组织同伴",
        "conflictLoop": "线索、资源、代价、新压力",
        "ensembleRoles": [{"role": "抄书匠", "purpose": "质疑牺牲"}],
        "advantageAndCost": "懂旧制但暴露会招来危险",
        "satisfactionSources": ["知识解决现实难题"],
        "longFormVariation": ["地方生存", "制度博弈"],
        "endingAnchor": "让知识可以传承",
        "risks": ["知识不能成为万能答案"],
        "differentiation": "解决问题会改变人物关系",
    }


def _style_payload(anchor):
    return {
        "schemaVersion": "style-template-v1",
        "reading_experience": "人物先做选择",
        "applicability": ["历史穿越"],
        "non_applicability": ["纯说明"],
        "standard_scene_example": "短示例",
        "complete_application_example": "完整示例",
        "narrative_distance": "贴近人物",
        "rhythm": "压力、选择、后果",
        "diction_density": "具体动词",
        "dialogue": "各说现实账",
        "subtext": "条件藏诉求",
        "character_voices": "欲望区分声音",
        "emotion": "情绪改变行动",
        "interiority": "念头落到决定",
        "action": "动作改变局面",
        "explanation": "先后果后规则",
        "environment": "环境约束行动",
        "body_response": "疲惫影响判断",
        "preferred_techniques": ["代价可见"],
        "risks": ["避免清单感"],
        "original_anchor": anchor,
    }


def _oversized_style_payload(anchor):
    payload = _style_payload(anchor)
    payload["standard_scene_example"] = "例" * 20_000
    payload["complete_application_example"] = "文" * 20_000
    return payload


def _inputs():
    return {
        "project": {"id": "project-1", "archived_at": None},
        "selection": {
            "selection_revision": 3,
            "seed_id": "seed-1",
            "seed_revision_id": "seed-rev-1",
            "seed_hash": "1" * 64,
            "payload_json": json.dumps(_seed_payload(), ensure_ascii=False),
        },
        "engine": {
            "id": "engine-1",
            "batch_id": "batch-1",
            "content_hash": "2" * 64,
            "payload_json": json.dumps(_engine_payload(), ensure_ascii=False),
            "status": "succeeded",
            "selection_revision": 3,
            "seed_revision_id": "seed-rev-1",
            "seed_hash": "1" * 64,
        },
        "styles": (
            {
                "role": "primary",
                "id": "style-primary",
                "stable_key": "direct-propulsive",
                "revision": 1,
                "content_hash": "3" * 64,
                "payload_json": json.dumps(_style_payload("主锚点"), ensure_ascii=False),
                "status": "active",
                "head_id": "style-primary",
                "head_revision": 1,
                "head_hash": "3" * 64,
            },
            {
                "role": "secondary",
                "id": "style-secondary",
                "stable_key": "light-humorous",
                "revision": 1,
                "content_hash": "4" * 64,
                "payload_json": json.dumps(_style_payload("辅锚点"), ensure_ascii=False),
                "status": "active",
                "head_id": "style-secondary",
                "head_revision": 1,
                "head_hash": "4" * 64,
            },
        ),
        "binding_revision_id": "binding-1",
        "binding_hash": "5" * 64,
        "resolution_status": "bound",
        "provider_id": "provider-1",
        "model_name_snapshot": "deepseek-v4-flash",
        "provider": {
            "id": "provider-1",
            "provider_type": "openai-compatible",
            "model_name": "deepseek-v4-flash",
            "base_url": "https://provider.test/v1",
            "api_key": "do-not-persist",
            "enabled": 1,
            "lifecycle_status": "active",
            "revision": 7,
            "temperature": 0.7,
            "max_output_tokens": 4096,
        },
    }


def _command(**changes):
    values = {
        "project_id": "project-1",
        "selection_revision": 3,
        "engine_option_id": "engine-1",
        "engine_hash": "2" * 64,
        "primary_style_revision_id": "style-primary",
        "primary_style_hash": "3" * 64,
        "secondary_style_revision_id": "style-secondary",
        "secondary_style_hash": "4" * 64,
        "author_scenario": "主角必须在救人和保住残页之间选择。",
        "idempotency_key": IDEMPOTENCY_KEY,
    }
    values.update(changes)
    return GenerateStyleTrial(**values)


class MemoryRepository:
    def __init__(self, inputs=None):
        self.inputs = inputs or _inputs()
        self.requests = {}
        self.attempts = {}
        self.publish_matches = True
        self.insert_order = []

    async def lock_project(self, _session, project_id):
        return self.inputs["project"] if project_id == "project-1" else None

    async def lock_request(self, _session, project_id, idempotency_key):
        return self.requests.get((project_id, idempotency_key))

    async def lock_inputs(self, _session, command):
        return self.inputs

    async def insert_request(self, _session, row):
        self.insert_order.append(("request", row["status"], row["attempt_id"]))
        self.requests[(row["project_id"], row["idempotency_key"])] = dict(row)

    async def insert_attempt(self, _session, row):
        self.insert_order.append(("attempt", row["status"], row["id"]))
        self.attempts[(row["project_id"], row["id"])] = dict(row)

    async def read_attempt(self, _session, project_id, attempt_id):
        return self.attempts.get((project_id, attempt_id))

    async def publish(self, _session, **values):
        attempt = self.attempts[(values["project_id"], values["attempt_id"])]
        request = self.requests[(values["project_id"], values["idempotency_key"])]
        if not self.publish_matches:
            attempt.update(
                status="failed", public_error_code="STYLE_TRIAL_INPUT_CHANGED",
                completed_at=values["completed_at"],
            )
            request.update(
                status="failed", attempt_id=values["attempt_id"],
                public_error_code="STYLE_TRIAL_INPUT_CHANGED",
                completed_at=values["completed_at"],
            )
            return False
        attempt.update(
            status="succeeded", result_json=values["result_json"],
            result_hash=values["result_hash"], completed_at=values["completed_at"],
        )
        request.update(
            status="succeeded", attempt_id=values["attempt_id"],
            result_hash=values["result_hash"], completed_at=values["completed_at"],
        )
        return True

    async def fail(self, _session, **values):
        attempt = self.attempts[(values["project_id"], values["attempt_id"])]
        request = self.requests[(values["project_id"], values["idempotency_key"])]
        attempt.update(
            status=values["attempt_status"], result_json=None, result_hash=None,
            public_error_code=values["public_error_code"],
            completed_at=values["completed_at"],
        )
        request.update(
            status=values["request_status"], attempt_id=values["attempt_id"],
            result_hash=None, public_error_code=values["public_error_code"],
            completed_at=values["completed_at"],
        )
        return True

    async def cleanup_interrupted(self, _session, **values):
        request = self.requests.get((
            values["project_id"], values["idempotency_key"]
        ))
        if request is None:
            return False
        if (
            request["request_hash"] != values["request_hash"]
            or request["id"] != values["request_id"]
            or request["attempt_id"] != values["attempt_id"]
        ):
            return False
        attempt = self.attempts.get((values["project_id"], values["attempt_id"]))
        if attempt is None:
            raise RuntimeError("style trial interruption attempt is missing")
        if request["status"] in {"succeeded", "failed", "outcome_unknown"}:
            if attempt["status"] != request["status"]:
                raise RuntimeError("style trial interruption state diverged")
            return False
        if request["status"] != "running" or attempt["status"] != "running":
            raise RuntimeError("style trial interruption state diverged")
        attempt.update(
            status="outcome_unknown", result_json=None, result_hash=None,
            public_error_code=values["public_error_code"],
            completed_at=values["completed_at"],
        )
        request.update(
            status="outcome_unknown", result_hash=None,
            public_error_code=values["public_error_code"],
            completed_at=values["completed_at"],
        )
        return True


class CountingGateway:
    def __init__(self, *, failure=False):
        self.calls = []
        self.failure = failure

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise StyleTrialProviderError("style trial provider failed")
        return StyleTrialProviderOutput(sample="城门的铜铃响到第三遍时，沈砚才把手从残页上移开。")


class Factories:
    def __init__(self):
        self.active = 0
        self.gateway_seen_inside_transaction = None

    @asynccontextmanager
    async def transaction(self):
        self.active += 1
        try:
            yield object()
        finally:
            self.active -= 1

class PublishCommitCancellationFactories(Factories):
    def __init__(self, repository, *, rollback):
        super().__init__()
        self.repository = repository
        self.rollback = rollback
        self.entries = 0

    @asynccontextmanager
    async def transaction(self):
        self.active += 1
        self.entries += 1
        entry = self.entries
        requests_before = deepcopy(self.repository.requests)
        attempts_before = deepcopy(self.repository.attempts)
        try:
            yield object()
            if entry == 2:
                if self.rollback:
                    self.repository.requests = requests_before
                    self.repository.attempts = attempts_before
                raise asyncio.CancelledError("publication commit interrupted")
        finally:
            self.active -= 1


class ReservationCommitCancellationFactories(Factories):
    def __init__(self, repository):
        super().__init__()
        self.repository = repository
        self.entries = 0

    @asynccontextmanager
    async def transaction(self):
        self.active += 1
        self.entries += 1
        entry = self.entries
        try:
            yield object()
            if entry == 1:
                raise asyncio.CancelledError("reservation commit interrupted")
        finally:
            self.active -= 1


def _service(repository=None, gateway=None, *, factories=None, clock=None):
    repo = repository or MemoryRepository()
    gw = gateway or CountingGateway()
    factories = factories or Factories()
    original = gw.generate

    async def checked_generate(**kwargs):
        factories.gateway_seen_inside_transaction = factories.active > 0
        return await original(**kwargs)

    gw.generate = checked_generate
    ids = iter(("request-1", "attempt-1", "request-2", "attempt-2"))
    service = StyleTrialService(
        repo,
        transaction_factory=factories.transaction,
        provider_gateway=gw,
        id_factory=lambda: next(ids),
        clock=clock or (lambda: 100),
    )
    return service, repo, gw, factories


@pytest.mark.asyncio
async def test_success_freezes_safe_manifest_and_validated_sample_without_side_effects():
    service, repo, gateway, factories = _service()

    result = await service.generate(_command())

    assert result.status == "succeeded"
    assert result.sample.startswith("城门")
    assert result.provider.provider_id == "provider-1"
    assert result.provider.provider_type == "openai-compatible"
    assert result.provider.model_name == "deepseek-v4-flash"
    assert result.provider.profile_revision == 7
    assert factories.gateway_seen_inside_transaction is False
    assert len(gateway.calls) == 1
    attempt = repo.attempts[("project-1", "attempt-1")]
    manifest = json.loads(attempt["input_manifest_json"])
    assert manifest["selection"] == {
        "revision": 3,
        "seedId": "seed-1",
        "seedRevisionId": "seed-rev-1",
        "seedHash": "1" * 64,
    }
    assert manifest["engine"] == {
        "optionId": "engine-1", "hash": "2" * 64, "batchId": "batch-1"
    }
    assert [item["role"] for item in manifest["styles"]] == ["primary", "secondary"]
    assert manifest["policyVersion"] == STYLE_TRIAL_POLICY_VERSION
    assert "authorScenario" not in manifest
    assert manifest["scenarioHash"] == sha256(
        _command().author_scenario.encode("utf-8")
    ).hexdigest()
    assert manifest["scenarioLength"] == len(_command().author_scenario)
    assert manifest["provider"] == {
        "providerId": "provider-1",
        "providerType": "openai-compatible",
        "modelName": "deepseek-v4-flash",
        "profileRevision": 7,
    }
    serialized = json.dumps({"attempt": attempt, "result": result.model_dump(mode="json")})
    assert _command().author_scenario not in serialized
    assert "do-not-persist" not in serialized
    assert "provider.test" not in serialized
    assert "prompt" not in serialized.lower()
    assert set(json.loads(attempt["result_json"])) == {"sample"}
    assert not {"contract", "candidate", "canon", "selected"} & set(
        json.loads(attempt["result_json"])
    )


@pytest.mark.asyncio
async def test_success_accepts_seed_revision_with_verified_provenance():
    inputs = _inputs()
    seed = SeedPayload.model_validate(_seed_payload(), strict=True)
    provenance = build_seed_provenance(
        kind="manual",
        snapshots=(),
        analysis=None,
        inspiration_attempt=None,
        public_notes=("作者从项目种子页显式保存。",),
    )
    inputs["selection"]["payload_json"] = json.dumps(
        seed_revision_document(seed, provenance), ensure_ascii=False
    )
    service, _repo, gateway, _factories = _service(
        repository=MemoryRepository(inputs)
    )

    result = await service.generate(_command())

    assert result.status == "succeeded"
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_provider_failure_records_exactly_one_failed_attempt_without_retry_or_raw_response():
    gateway = CountingGateway(failure=True)
    service, repo, gateway, _ = _service(gateway=gateway)

    result = await service.generate(_command())

    assert result.status == "failed"
    assert result.sample is None
    assert result.public_error_code == "STYLE_TRIAL_PROVIDER_FAILED"
    assert len(gateway.calls) == 1
    assert len(repo.attempts) == 1
    attempt = next(iter(repo.attempts.values()))
    assert attempt["status"] == "failed"
    assert attempt["result_json"] is None
    assert attempt["result_hash"] is None
    assert "raw" not in attempt
    request = next(iter(repo.requests.values()))
    assert request["attempt_id"] == attempt["id"]


@pytest.mark.asyncio
async def test_short_secret_in_provider_envelope_records_one_safe_failed_attempt(
    caplog,
):
    inputs = _inputs()
    inputs["provider"]["api_key"] = "abc"
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "providerLeak": "xabcx",
                "choices": [
                    {"message": {"content": '{"sample":"安全正文"}'}}
                ],
            },
        )

    gateway = StyleTrialProviderGateway(transport=httpx.MockTransport(handler))
    service, repo, _gateway, _ = _service(
        repository=MemoryRepository(inputs), gateway=gateway
    )

    result = await service.generate(_command())

    assert calls == 1
    assert (result.status, result.sample, result.public_error_code) == (
        "failed",
        None,
        "STYLE_TRIAL_PROVIDER_FAILED",
    )
    request = next(iter(repo.requests.values()))
    attempt = next(iter(repo.attempts.values()))
    assert request["status"] == attempt["status"] == "failed"
    assert request["result_hash"] is None
    assert attempt["result_json"] is None
    assert attempt["result_hash"] is None
    public_and_stored = json.dumps(
        {
            "result": result.model_dump(mode="json"),
            "request": request,
            "attempt": attempt,
        },
        ensure_ascii=False,
    )
    assert "abc" not in public_and_stored
    assert "providerLeak" not in public_and_stored
    assert "xabcx" not in public_and_stored
    assert "abc" not in caplog.text
    assert "providerLeak" not in caplog.text


@pytest.mark.asyncio
async def test_same_idempotency_request_replays_terminal_result_without_provider_call():
    service, _repo, gateway, _ = _service()
    first = await service.generate(_command())
    second = await service.generate(_command())

    assert second == first
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_same_idempotency_key_with_different_hash_conflicts_before_provider():
    service, _repo, gateway, _ = _service()
    await service.generate(_command())

    with pytest.raises(StyleTrialFailure) as captured:
        await service.generate(_command(author_scenario="另一个场景"))

    assert captured.value.code == "STYLE_TRIAL_IDEMPOTENCY_CONFLICT"
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda value: value["selection"].update(selection_revision=4), "STYLE_TRIAL_INPUT_CHANGED"),
        (lambda value: value["engine"].update(content_hash="9" * 64), "STYLE_TRIAL_INPUT_CHANGED"),
        (lambda value: value["styles"][0].update(head_hash="9" * 64), "STYLE_TRIAL_INPUT_CHANGED"),
        (lambda value: value.update(binding_revision_id=None), "STYLE_TRIAL_NOT_READY"),
        (lambda value: value.update(model_name_snapshot="stale-model"), "STYLE_TRIAL_NOT_READY"),
    ],
)
async def test_input_drift_fails_closed_before_provider(mutate, expected_code):
    inputs = _inputs()
    mutate(inputs)
    service, repo, gateway, _ = _service(repository=MemoryRepository(inputs))

    with pytest.raises(StyleTrialFailure) as captured:
        await service.generate(_command())

    assert captured.value.code == expected_code
    assert gateway.calls == []
    assert repo.attempts == {}


@pytest.mark.asyncio
async def test_drift_after_provider_terminalizes_attempt_instead_of_publishing_sample():
    repository = MemoryRepository()
    repository.publish_matches = False
    service, repo, gateway, _ = _service(repository=repository)

    result = await service.generate(_command())

    assert len(gateway.calls) == 1
    assert result.status == "failed"
    assert result.sample is None
    assert result.public_error_code == "STYLE_TRIAL_INPUT_CHANGED"
    assert next(iter(repo.attempts.values()))["result_json"] is None


def test_request_hash_covers_every_author_input_and_policy_version():
    base = StyleTrialService.request_hash(_command())
    variants = (
        _command(selection_revision=4),
        _command(engine_option_id="engine-2"),
        _command(engine_hash="8" * 64),
        _command(primary_style_revision_id="style-other"),
        _command(primary_style_hash="7" * 64),
        _command(secondary_style_revision_id=None, secondary_style_hash=None),
        _command(author_scenario="另一个场景"),
    )
    assert all(StyleTrialService.request_hash(item) != base for item in variants)
    assert base == canonical_hash(
        StyleTrialService.request_document(_command())
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("secret_field", ("api_key", "base_url"))
async def test_author_scenario_containing_provider_secret_fails_before_writes(
    secret_field,
):
    inputs = _inputs()
    secret = inputs["provider"][secret_field]
    service, repo, gateway, _ = _service(repository=MemoryRepository(inputs))

    with pytest.raises(StyleTrialFailure) as captured:
        await service.generate(
            _command(author_scenario=f"这一段错误地嵌入秘密：{secret}；必须拒绝。")
        )

    assert captured.value.code == "STYLE_TRIAL_NOT_READY"
    assert repo.requests == {}
    assert repo.attempts == {}
    assert gateway.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("secret_field", "secret"),
    (("api_key", "key7"), ("base_url", "url7")),
)
async def test_short_provider_secret_embedded_in_scenario_fails_before_writes(
    secret_field, secret,
):
    inputs = _inputs()
    inputs["provider"][secret_field] = secret
    service, repo, gateway, _ = _service(repository=MemoryRepository(inputs))

    with pytest.raises(StyleTrialFailure) as captured:
        await service.generate(
            _command(author_scenario=f"场景里误写了 {secret} 这个短秘密。")
        )

    assert captured.value.code == "STYLE_TRIAL_NOT_READY"
    assert repo.requests == {}
    assert repo.attempts == {}
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_short_provider_secret_embedded_in_non_scenario_prompt_fails_closed():
    inputs = _inputs()
    inputs["provider"]["api_key"] = "key7"
    seed = _seed_payload()
    seed["logline"] = "修复师发现 key7 被误写进种子。"
    inputs["selection"]["payload_json"] = json.dumps(seed, ensure_ascii=False)
    service, repo, gateway, _ = _service(repository=MemoryRepository(inputs))

    with pytest.raises(StyleTrialFailure) as captured:
        await service.generate(_command())

    assert captured.value.code == "STYLE_TRIAL_NOT_READY"
    assert repo.requests == {}
    assert repo.attempts == {}
    assert gateway.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("secret_field", "secret"),
    (("api_key", "key7"), ("base_url", "url7")),
)
async def test_short_provider_secret_not_in_prompt_or_manifest_remains_callable(
    secret_field, secret,
):
    inputs = _inputs()
    inputs["provider"][secret_field] = secret
    service, repo, gateway, _ = _service(repository=MemoryRepository(inputs))

    result = await service.generate(_command())

    assert result.status == "succeeded"
    assert len(gateway.calls) == 1
    assert len(repo.requests) == len(repo.attempts) == 1


@pytest.mark.asyncio
async def test_final_manifest_secret_collision_fails_before_writes_or_provider():
    inputs = _inputs()
    secret = inputs["provider"]["api_key"]
    inputs["styles"][0]["stable_key"] = f"style-{secret}-collision"
    service, repo, gateway, _ = _service(repository=MemoryRepository(inputs))

    with pytest.raises(StyleTrialFailure) as captured:
        await service.generate(_command())

    assert captured.value.code == "STYLE_TRIAL_NOT_READY"
    assert repo.requests == {}
    assert repo.attempts == {}
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_oversized_valid_style_prompt_is_fixed_not_ready_before_ledger_or_provider():
    inputs = _inputs()
    inputs["styles"][0]["payload_json"] = json.dumps(
        _oversized_style_payload("主锚点"), ensure_ascii=False
    )
    service, repo, gateway, _ = _service(repository=MemoryRepository(inputs))

    with pytest.raises(StyleTrialFailure) as captured:
        await service.generate(_command())

    assert captured.value.code == "STYLE_TRIAL_NOT_READY"
    assert repo.requests == {}
    assert repo.attempts == {}
    assert gateway.calls == []


def _put_running_trial(service, repository, *, created_at):
    command = _command()
    request_hash = service.request_hash(command)
    manifest = service._manifest(command, repository.inputs)
    attempt = {
        "id": "attempt-1",
        "project_id": "project-1",
        "selection_revision": 3,
        "binding_revision_id": "binding-1",
        "binding_hash": "5" * 64,
        "input_manifest_json": json.dumps(manifest),
        "input_manifest_hash": canonical_hash(manifest),
        "status": "running",
        "result_json": None,
        "result_hash": None,
        "public_error_code": None,
        "created_at": created_at,
        "completed_at": None,
    }
    request = {
        "id": "request-1",
        "project_id": "project-1",
        "idempotency_key": IDEMPOTENCY_KEY,
        "request_hash": request_hash,
        "status": "running",
        "attempt_id": "attempt-1",
        "result_hash": None,
        "public_error_code": None,
        "created_at": created_at,
        "completed_at": None,
    }
    repository.attempts[("project-1", "attempt-1")] = attempt
    repository.requests[("project-1", IDEMPOTENCY_KEY)] = request
    return command


@pytest.mark.asyncio
async def test_reservation_links_running_attempt_before_provider_call():
    service, repo, gateway, _ = _service()
    original = gateway.generate

    async def inspect(**kwargs):
        request = repo.requests[("project-1", IDEMPOTENCY_KEY)]
        attempt = repo.attempts[("project-1", request["attempt_id"])]
        assert request["status"] == attempt["status"] == "running"
        assert repo.insert_order == [
            ("attempt", "running", "attempt-1"),
            ("request", "running", "attempt-1"),
        ]
        return await original(**kwargs)

    gateway.generate = inspect

    result = await service.generate(_command())

    assert result.status == "succeeded"


@pytest.mark.asyncio
async def test_fresh_running_replay_is_in_progress_without_provider_call():
    repository = MemoryRepository()
    service, _, gateway, _ = _service(
        repository=repository, clock=lambda: 1_000_000
    )
    command = _put_running_trial(
        service, repository, created_at=1_000_000 - 239_999
    )

    with pytest.raises(StyleTrialFailure) as captured:
        await service.generate(command)

    assert captured.value.code == "STYLE_TRIAL_IN_PROGRESS"
    assert repository.requests[("project-1", IDEMPOTENCY_KEY)]["status"] == "running"
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_stale_running_replay_terminalizes_unknown_at_240_seconds():
    repository = MemoryRepository()
    service, _, gateway, _ = _service(
        repository=repository, clock=lambda: 1_000_000
    )
    command = _put_running_trial(
        service, repository, created_at=1_000_000 - 240_000
    )

    result = await service.generate(command)
    replay = await service.generate(command)

    assert result == replay
    assert result.status == "outcome_unknown"
    assert result.public_error_code == "STYLE_TRIAL_OUTCOME_UNKNOWN"
    assert repository.requests[("project-1", IDEMPOTENCY_KEY)]["status"] == "outcome_unknown"
    assert repository.attempts[("project-1", "attempt-1")]["status"] == "outcome_unknown"
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_cancelled_fresh_same_key_replay_cannot_terminalize_owner_pair():
    repository = MemoryRepository()
    service, _, gateway, _ = _service(
        repository=repository, clock=lambda: 1_000_000
    )
    command = _put_running_trial(
        service, repository, created_at=1_000_000 - 1_000
    )
    original_lock = repository.lock_request
    locked = asyncio.Event()

    async def cancel_at_locked_replay(session, project_id, idempotency_key):
        row = await original_lock(session, project_id, idempotency_key)
        locked.set()
        await asyncio.Event().wait()
        return row

    repository.lock_request = cancel_at_locked_replay
    task = asyncio.create_task(service.generate(command))
    await locked.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    request = repository.requests[("project-1", IDEMPOTENCY_KEY)]
    assert request["status"] == "running"
    assert repository.attempts[("project-1", "attempt-1")]["status"] == "running"
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_cleanup_with_wrong_reservation_ids_is_a_noop():
    repository = MemoryRepository()
    service, _, _, _ = _service(
        repository=repository, clock=lambda: 1_000_000
    )
    command = _put_running_trial(
        service, repository, created_at=1_000_000 - 1_000
    )

    changed = await repository.cleanup_interrupted(
        object(),
        project_id=command.project_id,
        idempotency_key=command.idempotency_key,
        request_hash=service.request_hash(command),
        request_id="not-this-request",
        attempt_id="not-this-attempt",
        public_error_code="STYLE_TRIAL_OUTCOME_UNKNOWN",
        completed_at=1_000_000,
    )

    assert changed is False
    assert repository.requests[("project-1", IDEMPOTENCY_KEY)]["status"] == "running"
    assert repository.attempts[("project-1", "attempt-1")]["status"] == "running"


@pytest.mark.asyncio
async def test_external_provider_cancellation_marks_running_pair_unknown():
    service, repo, gateway, _ = _service()
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking(**kwargs):
        gateway.calls.append(kwargs)
        started.set()
        await release.wait()
        return StyleTrialProviderOutput(sample="不会到达")

    gateway.generate = blocking
    task = asyncio.create_task(service.generate(_command()))
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    request = repo.requests[("project-1", IDEMPOTENCY_KEY)]
    assert request["status"] == "outcome_unknown"
    assert repo.attempts[("project-1", request["attempt_id"])]["status"] == "outcome_unknown"
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_reservation_commit_cancellation_reconciles_committed_running_pair():
    repository = MemoryRepository()
    factories = ReservationCommitCancellationFactories(repository)
    service, _, gateway, _ = _service(
        repository=repository, factories=factories
    )

    with pytest.raises(asyncio.CancelledError):
        await service.generate(_command())

    request = repository.requests[("project-1", IDEMPOTENCY_KEY)]
    assert request["status"] == "outcome_unknown"
    assert repository.attempts[("project-1", request["attempt_id"])]["status"] == "outcome_unknown"
    assert gateway.calls == []
    assert factories.entries == 2


@pytest.mark.asyncio
async def test_unexpected_provider_exception_marks_running_pair_unknown_and_reraises():
    service, repo, gateway, _ = _service()

    async def explode(**kwargs):
        gateway.calls.append(kwargs)
        raise RuntimeError("unexpected provider adapter bug")

    gateway.generate = explode

    with pytest.raises(RuntimeError, match="unexpected provider adapter bug"):
        await service.generate(_command())

    request = repo.requests[("project-1", IDEMPOTENCY_KEY)]
    assert request["status"] == "outcome_unknown"
    assert repo.attempts[("project-1", request["attempt_id"])]["status"] == "outcome_unknown"
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_external_publish_cancellation_marks_running_pair_unknown():
    service, repo, gateway, _ = _service()
    started = asyncio.Event()
    release = asyncio.Event()
    original_publish = repo.publish

    async def blocking_publish(session, **values):
        started.set()
        await release.wait()
        return await original_publish(session, **values)

    repo.publish = blocking_publish
    task = asyncio.create_task(service.generate(_command()))
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    request = repo.requests[("project-1", IDEMPOTENCY_KEY)]
    assert request["status"] == "outcome_unknown"
    assert repo.attempts[("project-1", request["attempt_id"])]["status"] == "outcome_unknown"
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rollback", "expected_status"),
    ((True, "outcome_unknown"), (False, "succeeded")),
)
async def test_publication_commit_cancellation_reconciles_terminal_state(
    rollback, expected_status,
):
    repository = MemoryRepository()
    factories = PublishCommitCancellationFactories(repository, rollback=rollback)
    service, _, gateway, _ = _service(
        repository=repository, factories=factories
    )

    with pytest.raises(asyncio.CancelledError):
        await service.generate(_command())

    request = repository.requests[("project-1", IDEMPOTENCY_KEY)]
    assert request["status"] == expected_status
    assert repository.attempts[("project-1", request["attempt_id"])]["status"] == expected_status
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_until_independent_cleanup_finishes():
    service, repo, gateway, _ = _service()
    provider_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    original_cleanup = repo.cleanup_interrupted

    async def blocking_provider(**kwargs):
        gateway.calls.append(kwargs)
        provider_started.set()
        await asyncio.Event().wait()

    async def delayed_cleanup(session, **values):
        cleanup_started.set()
        await release_cleanup.wait()
        return await original_cleanup(session, **values)

    gateway.generate = blocking_provider
    repo.cleanup_interrupted = delayed_cleanup
    task = asyncio.create_task(service.generate(_command()))
    await provider_started.wait()
    task.cancel()
    await cleanup_started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    request = repo.requests[("project-1", IDEMPOTENCY_KEY)]
    assert request["status"] == "outcome_unknown"
    assert repo.attempts[("project-1", request["attempt_id"])]["status"] == "outcome_unknown"


@pytest.mark.asyncio
async def test_interruption_cleanup_failure_preserves_both_errors():
    service, repo, gateway, _ = _service()

    async def explode(**kwargs):
        gateway.calls.append(kwargs)
        raise RuntimeError("provider adapter exploded")

    async def cleanup_failed(_session, **_values):
        raise OSError("cleanup database failed")

    gateway.generate = explode
    repo.cleanup_interrupted = cleanup_failed

    with pytest.raises(BaseExceptionGroup) as captured:
        await service.generate(_command())

    assert any(
        isinstance(error, RuntimeError) and str(error) == "provider adapter exploded"
        for error in captured.value.exceptions
    )
    assert any(
        isinstance(error, OSError) and str(error) == "cleanup database failed"
        for error in captured.value.exceptions
    )


def test_service_has_no_unused_connection_factory_dependency():
    signature = inspect.signature(StyleTrialService)

    assert "connection_factory" not in signature.parameters
