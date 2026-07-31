from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json

import pytest

from backend.domain.bibles import BiblePayload, canonical_bible_hash
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.gateways.bible_provider import (
    BibleProviderError,
    BibleProviderHTTPError,
    BibleProviderParseError,
    BibleProviderTimeoutError,
    BibleProviderTransportError,
)
from backend.services.bible_generation import (
    BIBLE_GENERATION_LEASE_MS,
    BibleGenerationConflict,
    BibleGenerationIdempotencyConflict,
    BibleGenerationNotReady,
    BibleGenerationParseFailed,
    BibleGenerationProviderFailed,
    BibleGenerationRetryable,
    BibleGenerationService,
    GenerateBibleDraft,
)
from backend.services.bibles import BibleAlreadyConfirmed


PROJECT_ID = "project-1"
NOW = 1_900_000_000_000


def _seed():
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


def _experience():
    return {
        "schemaVersion": "experience-card-v1",
        "category": "long_arc_continuity",
        "method": "每次兑现都留下新的长期代价。",
        "applicability": ["长篇推进"],
        "non_applicability": ["一次性反转"],
        "risks": ["代价不可重复"],
        "original_micro_demo": "救人会暴露藏书地点。",
    }


def _bible(**changes):
    item = lambda identity: ({"id": identity, "text": f"{identity} design"},)
    values = {
        "premiseAndPromise": "知识能解决困境，也会制造新的关系债。",
        "worldRules": item("world"),
        "powerOrProgressionSystem": "成长来自组织知识与承担公开知识的代价。",
        "protagonist": "沈砚谨慎、固执，必须学会让同伴参与判断。",
        "coreCast": item("cast"),
        "factions": item("faction"),
        "longTermConflicts": item("conflict"),
        "relationshipDynamics": item("relationship"),
        "toneAndNarrativeBoundaries": "克制、具体，不把知识写成万能答案。",
        "continuityGuardrails": item("guardrail"),
        "openDesignQuestions": item("question"),
    }
    values.update(changes)
    return BiblePayload(**values)


def _contract():
    experience_hash = canonical_hash(_experience())
    return {
        "project_id": PROJECT_ID,
        "revision": 2,
        "selection_revision": 3,
        "creation_contract_id": "creation-contract-1",
        "style_contract_id": "style-contract-1",
        "contract_ready": True,
        "reasons": (),
        "seed_ref": {
            "id": "seed-1",
            "revision_id": "seed-revision-1",
            "content_hash": canonical_hash(_seed()),
        },
        "binding_ref": {
            "id": "binding-revision-1",
            "revision": 4,
            "content_hash": "b" * 64,
        },
        "style_refs": (
            {
                "role": "primary",
                "id": "style-1",
                "revision": 1,
                "contentHash": "c" * 64,
            },
        ),
        "experience_card_refs": (
            {
                "id": "experience-1",
                "revision": 1,
                "contentHash": experience_hash,
            },
        ),
        "corpus_source_refs": (
            {
                "id": "corpus-1",
                "revision": 1,
                "revisionId": "corpus-revision-1",
                "contentHash": "d" * 64,
                "selectionMode": "author",
                "fragments": (
                    {
                        "chapterId": "chapter-1",
                        "fragmentId": "fragment-1",
                        "fragmentHash": "e" * 64,
                        "chapterCharStart": 0,
                        "chapterCharEnd": 24,
                        "referenceUse": "structure",
                    },
                ),
            },
        ),
        "creation_contract": {
            "schemaVersion": "creation-contract-v1",
            "storyPromise": "知识解决难题也制造新的关系债。",
        },
        "style_contract": {
            "schemaVersion": "style-contract-v1",
            "readingExperience": "人物先做选择。",
        },
        "creation_hash": "f" * 64,
        "style_hash": "a" * 64,
    }


class FakeContractService:
    def __init__(self):
        self.head = _contract()
        self.calls = []

    async def get_head(self, project_id, *, session, for_update):
        self.calls.append((project_id, for_update))
        return deepcopy(self.head)


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


class FakeRepository:
    def __init__(self):
        self.project = {"id": PROJECT_ID, "archived_at": None}
        self.head = {
            "project_id": PROJECT_ID,
            "revision": 0,
            "bible_revision_id": None,
            "content_hash": None,
        }
        self.draft = None
        self.retired_drafts = []
        self.attempts = {}
        self.attempt_by_key = {}
        self.fail_success = False
        self.binding = {
            "binding_revision_id": "binding-revision-1",
            "binding_hash": "b" * 64,
            "resolution_status": "bound",
            "provider_id": "provider-1",
            "model_name_snapshot": "novel-model",
            "id": "provider-1",
            "provider_type": "openai-compatible",
            "model_name": "novel-model",
            "base_url": "https://provider.invalid/v1",
            "api_key": "PRIVATE_PROVIDER_KEY_123456",
            "enabled": 1,
            "lifecycle_status": "active",
            "revision": 7,
            "temperature": 0.5,
            "max_context_tokens": 32_768,
            "max_output_tokens": 8_192,
        }
        self.seed = {
            "seed_id": "seed-1",
            "seed_revision_id": "seed-revision-1",
            "seed_hash": canonical_hash(_seed()),
            "payload_json": canonical_json(_seed()),
        }
        self.experience = {
            "id": "experience-1",
            "revision": 1,
            "content_hash": canonical_hash(_experience()),
            "payload_json": canonical_json(_experience()),
        }
        self.fragments = (
            {
                "source_id": "corpus-1",
                "source_revision_id": "corpus-revision-1",
                "source_revision": 1,
                "source_hash": "d" * 64,
                "chapter_id": "chapter-1",
                "fragment_id": "fragment-1",
                "fragment_hash": "e" * 64,
                "fragment_char_start": 0,
                "fragment_char_end": 24,
                "normalized_text": "困境先迫使人物结盟，结盟随后改变资源分配。",
            },
        )

    def snapshot(self):
        return deepcopy(
            (
                self.head,
                self.draft,
                self.retired_drafts,
                self.attempts,
                self.attempt_by_key,
            )
        )

    def restore(self, snapshot):
        (
            self.head,
            self.draft,
            self.retired_drafts,
            self.attempts,
            self.attempt_by_key,
        ) = snapshot

    async def lock_project(self, _session, project_id):
        return self.project if project_id == PROJECT_ID else None

    async def lock_bible_head(self, _session, project_id):
        return self.head if project_id == PROJECT_ID else None

    async def lock_active_draft(self, _session, project_id):
        return self.draft if project_id == PROJECT_ID else None

    async def lock_generation_attempt_by_key(
        self, _session, project_id, idempotency_key
    ):
        attempt_id = self.attempt_by_key.get((project_id, idempotency_key))
        return self.attempts.get(attempt_id)

    async def lock_generation_attempt(self, _session, project_id, attempt_id):
        row = self.attempts.get(attempt_id)
        return row if row and row["project_id"] == project_id else None

    async def read_generation_attempt(self, _session, project_id, attempt_id):
        return await self.lock_generation_attempt(
            _session, project_id, attempt_id
        )

    async def insert_generation_attempt(self, _session, row):
        self.attempts[row["id"]] = deepcopy(row)
        self.attempt_by_key[
            (row["project_id"], row["idempotency_key"])
        ] = row["id"]
        return True

    async def lock_planning_binding(self, _session, project_id):
        return deepcopy(self.binding) if project_id == PROJECT_ID else None

    async def read_seed_revision(
        self, _session, project_id, revision_id, *, lock=False
    ):
        if project_id == PROJECT_ID and revision_id == self.seed["seed_revision_id"]:
            return deepcopy(self.seed)
        return None

    async def read_experience_revision(
        self, _session, asset_id, *, lock=False
    ):
        return deepcopy(self.experience) if asset_id == "experience-1" else None

    async def read_corpus_fragments(
        self,
        _session,
        source_id,
        revision_id,
        fragment_ids,
        *,
        lock=False,
    ):
        if (
            source_id == "corpus-1"
            and revision_id == "corpus-revision-1"
            and tuple(fragment_ids) == ("fragment-1",)
        ):
            return deepcopy(self.fragments)
        return ()

    async def finish_generation_attempt(
        self,
        _session,
        *,
        project_id,
        attempt_id,
        owner_token,
        expected_attempt_version,
        status,
        public_error_code,
        completed_at,
    ):
        row = self.attempts.get(attempt_id)
        if (
            row is None
            or row["project_id"] != project_id
            or row["owner_token"] != owner_token
            or row["attempt_version"] != expected_attempt_version
            or row["status"] not in {"reserved", "running"}
        ):
            return False
        row.update(
            status=status,
            owner_token=None,
            lease_expires_at=None,
            attempt_version=expected_attempt_version + 1,
            result_json=None,
            result_hash=None,
            public_error_code=public_error_code,
            completed_at=completed_at,
        )
        return True

    async def succeed_generation_attempt(
        self,
        _session,
        *,
        project_id,
        attempt_id,
        owner_token,
        expected_attempt_version,
        result_json,
        result_hash,
        completed_at,
    ):
        if self.fail_success:
            raise RuntimeError("PRIVATE_COMMIT_PATH_DETAIL")
        row = self.attempts.get(attempt_id)
        if (
            row is None
            or row["project_id"] != project_id
            or row["owner_token"] != owner_token
            or row["attempt_version"] != expected_attempt_version
            or row["status"] != "running"
        ):
            return False
        row.update(
            status="succeeded",
            owner_token=None,
            lease_expires_at=None,
            attempt_version=expected_attempt_version + 1,
            result_json=result_json,
            result_hash=result_hash,
            public_error_code=None,
            completed_at=completed_at,
        )
        return True

    async def insert_draft(self, _session, row):
        if self.draft is not None:
            return False
        self.draft = deepcopy(row)
        return True

    async def deactivate_active_draft(
        self,
        _session,
        project_id,
        draft_id,
        expected_version,
        content_hash,
    ):
        if (
            self.draft is None
            or self.draft["project_id"] != project_id
            or self.draft["id"] != draft_id
            or self.draft["draft_version"] != expected_version
            or self.draft["content_hash"] != content_hash
        ):
            return False
        retired = deepcopy(self.draft)
        retired["active_slot"] = None
        self.retired_drafts.append(retired)
        self.draft = None
        return True

    async def cas_update_draft(
        self,
        _session,
        row,
        expected_version,
        *,
        update_binding=False,
    ):
        if (
            self.draft is None
            or self.draft["id"] != row["id"]
            or self.draft["draft_version"] != expected_version
        ):
            return False
        if not update_binding:
            row["binding_revision_id"] = self.draft.get(
                "binding_revision_id"
            )
            row["binding_hash"] = self.draft.get("binding_hash")
        self.draft = deepcopy(row)
        return True


class Transactions:
    def __init__(self, repository):
        self.repository = repository
        self.active = 0
        self.gateway_observed_transaction = False
        self.commit_failure = None

    @asynccontextmanager
    async def factory(self):
        snapshot = self.repository.snapshot()
        self.active += 1
        try:
            yield object()
        except BaseException:
            self.repository.restore(snapshot)
            raise
        else:
            if self.commit_failure is not None:
                failure = self.commit_failure
                self.commit_failure = None
                raise failure
        finally:
            self.active -= 1


class FakeGateway:
    def __init__(self, transactions, result=None):
        self.transactions = transactions
        self.result = result or _bible()
        self.calls = 0
        self.on_call = None

    async def generate(self, **_values):
        self.calls += 1
        if self.transactions.active:
            self.transactions.gateway_observed_transaction = True
        if self.on_call:
            self.on_call()
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _command(**changes):
    values = {
        "project_id": PROJECT_ID,
        "author_instructions": "强调群像分工与长期关系代价。",
        "expected_draft_version": 0,
        "expected_head_revision": 0,
        "idempotency_key": "generation-key-1",
    }
    values.update(changes)
    return GenerateBibleDraft(**values)


def _harness(*, gateway_result=None):
    repository = FakeRepository()
    contracts = FakeContractService()
    transactions = Transactions(repository)
    gateway = FakeGateway(transactions, gateway_result)
    ids = iter(
        (
            "owner-token-0000-0000-0000-000000000001",
            "attempt-00000000-0000-0000-000000000001",
            "draft-00000000-0000-0000-000000000001",
            "owner-token-0000-0000-0000-000000000002",
            "attempt-00000000-0000-0000-000000000002",
            "draft-00000000-0000-0000-000000000002",
        )
    )
    clock = Clock()
    service = BibleGenerationService(
        repository,
        contract_service=contracts,
        transaction_factory=transactions.factory,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=clock,
    )
    return service, repository, contracts, transactions, gateway, clock


@pytest.mark.asyncio
async def test_success_is_one_call_outside_transaction_and_replays_atomically():
    service, repository, contracts, transactions, gateway, _ = _harness()
    command = _command()

    first = await service.generate(command)
    replay = await service.generate(command)

    assert first == replay
    assert first.status == "succeeded"
    assert first.attempt_version == 2
    assert first.result_hash == canonical_bible_hash(_bible())
    assert gateway.calls == 1
    assert transactions.gateway_observed_transaction is False
    assert all(for_update for _, for_update in contracts.calls)
    assert repository.draft["draft_version"] == 1
    assert repository.draft["binding_revision_id"] == "binding-revision-1"
    assert repository.draft["binding_hash"] == "b" * 64
    assert repository.draft["draft_json"] == canonical_json(_bible())
    assert repository.attempts[first.attempt_id]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_confirmed_bible_blocks_generation_before_provider_or_attempt_write():
    service, repository, _, _, gateway, _ = _harness()
    repository.head["revision"] = 1

    with pytest.raises(BibleAlreadyConfirmed):
        await service.generate(
            _command(expected_head_revision=1, idempotency_key="locked-head")
        )

    assert gateway.calls == 0
    assert repository.attempts == {}
    assert repository.draft is None


@pytest.mark.asyncio
async def test_manifest_is_deterministic_and_never_persists_prompt_or_secrets():
    service, repository, _, _, gateway, _ = _harness()
    first = await service.generate(_command(idempotency_key="manifest-key-1"))
    repository.draft = None
    second = await service.generate(_command(idempotency_key="manifest-key-2"))

    first_row = repository.attempts[first.attempt_id]
    second_row = repository.attempts[second.attempt_id]
    assert first.input_manifest_hash == second.input_manifest_hash
    assert gateway.calls == 2
    stored = first_row["input_manifest_json"]
    manifest = json.loads(stored)
    assert first_row["input_manifest_hash"] == canonical_hash(manifest)
    assert manifest["authorInstructions"] == {
        "hash": canonical_hash("强调群像分工与长期关系代价。"),
        "length": len("强调群像分工与长期关系代价。"),
    }
    assert manifest["provider"]["providerId"] == "provider-1"
    assert manifest["provider"]["modelName"] == "novel-model"
    for forbidden in (
        "PRIVATE_PROVIDER_KEY_123456",
        "https://provider.invalid/v1",
        "困境先迫使人物结盟",
        "Generate one complete",
        "messages",
        "prompt",
        "corpusRoot",
        "apiKey",
        "baseURL",
    ):
        assert forbidden not in stored


@pytest.mark.asyncio
async def test_context_budget_and_secret_bearing_author_input_fail_before_reserve():
    service, repository, _, _, gateway, _ = _harness()
    repository.binding["max_context_tokens"] = 1
    with pytest.raises(BibleGenerationNotReady):
        await service.generate(_command(idempotency_key="budget-key"))

    repository.binding["max_context_tokens"] = 32_768
    with pytest.raises(BibleGenerationNotReady):
        await service.generate(
            _command(
                idempotency_key="secret-key",
                author_instructions="请使用 PRIVATE_PROVIDER_KEY_123456",
            )
        )
    assert repository.attempts == {}
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_same_key_different_request_conflicts_without_second_call():
    service, _, _, _, gateway, _ = _harness()
    await service.generate(_command())
    with pytest.raises(BibleGenerationIdempotencyConflict):
        await service.generate(
            _command(author_instructions="不同请求")
        )
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_reservation_commit_uncertainty_closes_landed_lease_without_call():
    service, repository, _, transactions, gateway, _ = _harness()
    transactions.commit_failure = RuntimeError("PRIVATE_COMMIT_DETAIL")

    result = await service.generate(_command())

    assert result.status == "outcome_unknown"
    assert result.public_error_code == BibleGenerationRetryable.code
    assert repository.attempts[result.attempt_id]["status"] == "outcome_unknown"
    assert repository.draft is None
    assert gateway.calls == 0
    assert "PRIVATE_" not in json.dumps(repository.attempts)


@pytest.mark.asyncio
async def test_reservation_commit_cancellation_closes_landed_lease_then_reraises():
    service, repository, _, transactions, gateway, _ = _harness()
    transactions.commit_failure = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await service.generate(_command())

    [attempt] = repository.attempts.values()
    assert attempt["status"] == "outcome_unknown"
    assert attempt["public_error_code"] == BibleGenerationRetryable.code
    assert repository.draft is None
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_valid_owned_lease_replays_inflight_without_gateway_call():
    service, repository, _, _, gateway, clock = _harness()
    command = _command()
    request_hash = service.request_hash(command)
    row = {
        "id": "attempt-inflight",
        "project_id": PROJECT_ID,
        "selection_revision": 3,
        "seed_id": "seed-1",
        "seed_revision_id": "seed-revision-1",
        "seed_hash": canonical_hash(_seed()),
        "contract_revision": 2,
        "creation_contract_id": "creation-contract-1",
        "creation_hash": "f" * 64,
        "style_contract_id": "style-contract-1",
        "style_hash": "a" * 64,
        "binding_revision_id": "binding-revision-1",
        "binding_hash": "b" * 64,
        "provider_id": "provider-1",
        "model_name_snapshot": "novel-model",
        "policy_version": "creation-bible-generation-v1",
        "idempotency_key": command.idempotency_key,
        "request_hash": request_hash,
        "input_manifest_json": "{}",
        "input_manifest_hash": canonical_hash({}),
        "status": "running",
        "owner_token": "other-owner",
        "lease_expires_at": clock() + BIBLE_GENERATION_LEASE_MS,
        "attempt_version": 1,
        "result_json": None,
        "result_hash": None,
        "public_error_code": None,
        "created_at": clock(),
        "completed_at": None,
    }
    await repository.insert_generation_attempt(None, row)

    replay = await service.generate(command)

    assert replay.status == "running"
    assert replay.attempt_version == 1
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_expired_owned_lease_becomes_unknown_and_is_never_recalled():
    service, repository, _, _, gateway, clock = _harness()
    command = _command()
    row = {
        **{
            "id": "attempt-expired",
            "project_id": PROJECT_ID,
            "selection_revision": 3,
            "seed_id": "seed-1",
            "seed_revision_id": "seed-revision-1",
            "seed_hash": canonical_hash(_seed()),
            "contract_revision": 2,
            "creation_contract_id": "creation-contract-1",
            "creation_hash": "f" * 64,
            "style_contract_id": "style-contract-1",
            "style_hash": "a" * 64,
            "binding_revision_id": "binding-revision-1",
            "binding_hash": "b" * 64,
            "provider_id": "provider-1",
            "model_name_snapshot": "novel-model",
            "policy_version": "creation-bible-generation-v1",
            "idempotency_key": command.idempotency_key,
            "request_hash": service.request_hash(command),
            "input_manifest_json": "{}",
            "input_manifest_hash": canonical_hash({}),
            "status": "running",
            "owner_token": "expired-owner",
            "lease_expires_at": clock(),
            "attempt_version": 1,
            "result_json": None,
            "result_hash": None,
            "public_error_code": None,
            "created_at": clock() - BIBLE_GENERATION_LEASE_MS,
            "completed_at": None,
        }
    }
    await repository.insert_generation_attempt(None, row)

    replay = await service.generate(command)

    assert replay.status == "outcome_unknown"
    assert replay.public_error_code == BibleGenerationRetryable.code
    assert replay.attempt_version == 2
    assert repository.draft is None
    assert gateway.calls == 0


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    (
        (
            BibleProviderHTTPError("PRIVATE_HTTP_DETAIL"),
            "failed",
            BibleGenerationProviderFailed.code,
        ),
        (
            BibleProviderParseError("PRIVATE_RAW_BODY"),
            "failed",
            BibleGenerationParseFailed.code,
        ),
        (
            BibleProviderTimeoutError("PRIVATE_TIMEOUT_DETAIL"),
            "outcome_unknown",
            BibleGenerationRetryable.code,
        ),
        (
            BibleProviderTransportError("PRIVATE_TRANSPORT_DETAIL"),
            "outcome_unknown",
            BibleGenerationRetryable.code,
        ),
        (
            BibleProviderError("PRIVATE_UNKNOWN_PROVIDER_DETAIL"),
            "outcome_unknown",
            BibleGenerationRetryable.code,
        ),
        (
            RuntimeError("PRIVATE_CALL_DETAIL"),
            "outcome_unknown",
            BibleGenerationRetryable.code,
        ),
    ),
)
@pytest.mark.asyncio
async def test_gateway_failures_are_safe_terminal_and_never_change_draft(
    failure,
    status,
    code,
):
    service, repository, _, _, gateway, _ = _harness(
        gateway_result=failure
    )

    result = await service.generate(_command())
    replay = await service.generate(_command())

    assert result == replay
    assert result.status == status
    assert result.public_error_code == code
    assert result.result_hash is None
    assert repository.draft is None
    assert gateway.calls == 1
    persisted = json.dumps(repository.attempts)
    assert "PRIVATE_" not in persisted


@pytest.mark.asyncio
async def test_cancel_terminalizes_unknown_without_draft_then_reraises():
    service, repository, _, _, gateway, _ = _harness(
        gateway_result=asyncio.CancelledError()
    )
    with pytest.raises(asyncio.CancelledError):
        await service.generate(_command())

    replay = await service.generate(_command())
    assert replay.status == "outcome_unknown"
    assert replay.public_error_code == BibleGenerationRetryable.code
    assert repository.draft is None
    assert gateway.calls == 1


@pytest.mark.parametrize("stage", ("gateway", "publish"))
@pytest.mark.asyncio
async def test_real_task_cancel_survives_failed_best_effort_settlement(
    monkeypatch,
    stage,
):
    service, repository, _, _, gateway, _ = _harness()
    entered = asyncio.Event()
    never = asyncio.Event()

    if stage == "gateway":
        async def block_gateway(**_values):
            gateway.calls += 1
            entered.set()
            await never.wait()

        monkeypatch.setattr(gateway, "generate", block_gateway)
    else:
        async def block_publish(*_values):
            entered.set()
            await never.wait()

        monkeypatch.setattr(service, "_publish", block_publish)

    async def fail_settlement(*_values, **_options):
        raise RuntimeError("PRIVATE_SETTLEMENT_DETAIL")

    monkeypatch.setattr(service, "_terminalize", fail_settlement)
    task = asyncio.create_task(service.generate(_command()))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    [attempt] = repository.attempts.values()
    assert attempt["status"] == "running"
    assert attempt["result_json"] is None
    assert repository.draft is None
    assert gateway.calls == 1


@pytest.mark.parametrize("failure", (KeyboardInterrupt(), SystemExit()))
@pytest.mark.asyncio
async def test_process_control_exceptions_are_not_business_outcomes(failure):
    service, repository, _, _, gateway, _ = _harness(
        gateway_result=failure
    )

    with pytest.raises(type(failure)):
        await service.generate(_command())

    [attempt] = repository.attempts.values()
    assert attempt["status"] == "running"
    assert repository.draft is None
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_response_basis_drift_fails_without_installing_provider_result():
    service, repository, contracts, _, gateway, _ = _harness()
    gateway.on_call = lambda: contracts.head.update(
        creation_hash="0" * 64
    )

    result = await service.generate(_command())

    assert result.status == "failed"
    assert result.public_error_code == BibleGenerationConflict.code
    assert repository.draft is None
    assert repository.attempts[result.attempt_id]["result_json"] is None


@pytest.mark.asyncio
async def test_project_disappearing_after_provider_is_failed_input_drift():
    service, repository, _, _, gateway, _ = _harness()
    gateway.on_call = lambda: setattr(repository, "project", None)

    result = await service.generate(_command())

    assert result.status == "failed"
    assert result.public_error_code == BibleGenerationConflict.code
    assert repository.draft is None
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_publication_error_rolls_back_draft_and_terminalizes_unknown():
    service, repository, _, _, gateway, _ = _harness()
    repository.fail_success = True

    result = await service.generate(_command())

    assert result.status == "outcome_unknown"
    assert result.public_error_code == BibleGenerationRetryable.code
    assert repository.draft is None
    assert gateway.calls == 1
