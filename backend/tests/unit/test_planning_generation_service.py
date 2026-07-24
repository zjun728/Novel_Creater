from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from pymysql.err import OperationalError

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.planning import (
    DraftPlanningAggregate,
    normalize_planning_aggregate,
)
from backend.gateways.planning_provider import PlanningProviderError
from backend.http_errors import ProjectArchived


NOW = 2_000_000_000_000


def _draft_payload(title: str = "旧卷") -> dict[str, object]:
    return {
        "activeStoryBlockRef": None,
        "volumes": [
            {
                "clientNodeKey": "volume-1",
                "order": 1,
                "title": title,
                "coreChange": "主角从逃亡转为立足。",
                "mainPressure": "追兵逼近。",
                "ensembleFocus": ["主角", "同伴"],
                "forbiddenEvents": ["不可提前揭示幕后人"],
            }
        ],
        "plots": [
            {
                "clientNodeKey": "plot-1",
                "order": 1,
                "title": "立足主线",
                "plotType": "main",
                "storyQuestion": "主角如何活下来？",
                "futureDirection": "从逃亡转为主动布局。",
                "expectedPayoff": "建立据点。",
                "relatedCharacters": ["主角"],
            }
        ],
        "storyBlocks": [],
    }


def _persisted_draft(title: str = "旧卷"):
    identifiers = iter(("volume-id", "plot-id"))
    return normalize_planning_aggregate(
        DraftPlanningAggregate.model_validate(_draft_payload(title)),
        previous_confirmed=None,
        previous_draft=None,
        id_factory=identifiers.__next__,
    )


class TransactionTracker:
    def __init__(self):
        self.active = 0
        self.entries = 0

    def factory(self):
        tracker = self

        class Transaction:
            async def __aenter__(self):
                tracker.active += 1
                tracker.entries += 1
                return object()

            async def __aexit__(self, exc_type, exc, tb):
                tracker.active -= 1
                return False

        return Transaction()


class FakePlanningRepository:
    def __init__(self):
        content = _persisted_draft()
        self.project = {"id": "p1", "archived_at": None}
        self.basis = {
            "selection_revision": 1,
            "seed_id": "seed-1",
            "seed_revision_id": "seed-revision-1",
            "seed_hash": "1" * 64,
            "contract_revision": 2,
            "creation_contract_id": "creation-1",
            "creation_hash": "2" * 64,
            "style_contract_id": "style-1",
            "style_hash": "3" * 64,
            "chapter_capacity_policy": '{"chapterWordRangePreference":[3000,5000]}',
            "bible_revision": 3,
            "bible_revision_id": "bible-1",
            "bible_hash": "4" * 64,
        }
        self.head = {
            "project_id": "p1",
            "revision": 0,
            "planning_revision_id": None,
            "content_hash": None,
            "content_json": None,
        }
        self.draft = {
            "id": "draft-1",
            "project_id": "p1",
            "active_slot": 1,
            "base_head_revision": 0,
            "draft_revision": 1,
            **{
                key: value
                for key, value in self.basis.items()
                if key != "chapter_capacity_policy"
            },
            "content_json": canonical_json(
                content.model_dump(mode="json", by_alias=True)
            ),
            "content_hash": content.content_hash,
            "source_attempt_id": None,
            "status": "active",
        }
        self.binding = {
            "binding_revision_id": "binding-1",
            "binding_revision": 1,
            "binding_hash": "5" * 64,
            "binding_task_key": "planning",
            "resolution_status": "bound",
            "provider_id": "provider-1",
            "model_name_snapshot": "deepseek-v4-flash",
            "id": "provider-1",
            "provider_type": "openai-compatible",
            "model_name": "deepseek-v4-flash",
            "base_url": "https://provider.invalid/v1",
            "api_key": "TEST_ONLY_PRIVATE_KEY",
            "enabled": 1,
            "lifecycle_status": "active",
            "revision": 1,
            "temperature": 0.6,
            "max_context_tokens": 100_000,
            "max_output_tokens": 8_192,
        }
        self.attempts: dict[str, dict] = {}
        self.load_calls = 0
        self.lock_order: list[str] = []
        self.lock_operation_reads = 0
        self.plain_operation_reads = 0
        self.plain_key_reads = 0

    async def lock_active_project(self, _session, project_id):
        self.lock_order.append("project")
        if self.project["archived_at"] is not None:
            raise ProjectArchived()
        if project_id != "p1":
            return None
        return self.project

    async def read_project_any(self, _session, project_id):
        return self.project if project_id == "p1" else None

    async def read_current_basis(self, _session, project_id):
        self.lock_order.append("basis")
        return self.basis if project_id == "p1" else None

    async def lock_planning_head(self, _session, project_id):
        self.lock_order.append("head")
        return self.head if project_id == "p1" else None

    async def read_draft(self, _session, project_id, draft_id):
        self.lock_order.append("draft")
        if project_id == "p1" and draft_id == self.draft["id"]:
            return self.draft
        return None

    async def lock_planning_binding(self, _session, project_id):
        self.lock_order.append("binding")
        return self.binding if project_id == "p1" else None

    async def lock_generation_attempt_by_key(
        self, _session, project_id, idempotency_key
    ):
        self.lock_order.append("idempotency")
        return next(
            (
                row
                for row in self.attempts.values()
                if row["project_id"] == project_id
                and row["idempotency_key"] == idempotency_key
            ),
            None,
        )

    async def read_generation_attempt_by_key(
        self, _session, project_id, idempotency_key
    ):
        self.plain_key_reads += 1
        self.lock_order.append("idempotency-read")
        return next(
            (
                row
                for row in self.attempts.values()
                if row["project_id"] == project_id
                and row["idempotency_key"] == idempotency_key
            ),
            None,
        )

    async def lock_generation_attempt(
        self, _session, project_id, operation_id
    ):
        self.lock_operation_reads += 1
        self.lock_order.append("operation")
        row = self.attempts.get(operation_id)
        return row if row and row["project_id"] == project_id else None

    async def read_generation_attempt(
        self, _session, project_id, operation_id
    ):
        self.plain_operation_reads += 1
        row = self.attempts.get(operation_id)
        return row if row and row["project_id"] == project_id else None

    async def lock_active_generation_attempt(self, _session, draft_id):
        self.lock_order.append("active")
        return next(
            (
                row
                for row in self.attempts.values()
                if row["draft_id"] == draft_id
                and row["status"] == "pending"
                and row["active_slot"] == 1
            ),
            None,
        )

    async def read_active_generation_attempt(self, _session, draft_id):
        self.lock_order.append("active-read")
        return next(
            (
                row
                for row in self.attempts.values()
                if row["draft_id"] == draft_id
                and row["status"] == "pending"
                and row["active_slot"] == 1
            ),
            None,
        )

    async def next_fencing_token(self, _session, draft_id):
        self.lock_order.append("token")
        tokens = [
            row["fencing_token"]
            for row in self.attempts.values()
            if row["draft_id"] == draft_id
        ]
        return max(tokens, default=0) + 1

    async def insert_generation_attempt(self, _session, row):
        self.attempts[row["operation_id"]] = {
            **deepcopy(row),
            "active_slot": 1,
            "status": "pending",
            "failure_code": None,
            "result_content_json": None,
            "result_content_hash": None,
            "loaded_draft_revision": None,
            "loaded_at": None,
        }
        return True

    async def supersede_generation_attempt(
        self,
        _session,
        *,
        project_id,
        operation_id,
        fencing_token,
        updated_at,
    ):
        row = self.attempts.get(operation_id)
        if not self._owns(row, project_id, fencing_token):
            return False
        row.update(status="superseded", active_slot=None, updated_at=updated_at)
        return True

    async def fail_generation_attempt(
        self,
        _session,
        *,
        project_id,
        operation_id,
        fencing_token,
        failure_code,
        updated_at,
    ):
        row = self.attempts.get(operation_id)
        if not self._owns(row, project_id, fencing_token):
            return False
        row.update(
            status="failed",
            active_slot=None,
            failure_code=failure_code,
            updated_at=updated_at,
        )
        return True

    async def succeed_generation_attempt(
        self,
        _session,
        *,
        project_id,
        operation_id,
        fencing_token,
        result_content_json,
        result_content_hash,
        updated_at,
    ):
        row = self.attempts.get(operation_id)
        if not self._owns(row, project_id, fencing_token):
            return False
        row.update(
            status="succeeded",
            active_slot=None,
            result_content_json=result_content_json,
            result_content_hash=result_content_hash,
            updated_at=updated_at,
        )
        return True

    async def load_generation_result_into_draft(
        self,
        _session,
        *,
        project_id,
        draft_id,
        expected_revision,
        expected_hash,
        operation_id,
        fencing_token,
        content_json,
        content_hash,
        loaded_at,
    ):
        self.load_calls += 1
        row = self.attempts.get(operation_id)
        if (
            not self._owns(row, project_id, fencing_token)
            or self.draft["id"] != draft_id
            or self.draft["draft_revision"] != expected_revision
            or self.draft["content_hash"] != expected_hash
        ):
            return False
        loaded_revision = expected_revision + 1
        self.draft.update(
            draft_revision=loaded_revision,
            content_json=content_json,
            content_hash=content_hash,
            source_attempt_id=row["id"],
        )
        row.update(
            status="succeeded",
            active_slot=None,
            result_content_json=content_json,
            result_content_hash=content_hash,
            loaded_draft_revision=loaded_revision,
            loaded_at=loaded_at,
            updated_at=loaded_at,
        )
        return True

    @staticmethod
    def _owns(row, project_id, token):
        return (
            row is not None
            and row["project_id"] == project_id
            and row["status"] == "pending"
            and row["active_slot"] == 1
            and row["fencing_token"] == token
        )


class FakeGateway:
    def __init__(self, output=None, *, tracker=None, hook=None):
        self.output = output or _draft_payload("AI 新卷")
        self.tracker = tracker
        self.hook = hook
        self.calls = []

    async def generate(
        self, *, provider, model_name, manifest, author_instructions
    ):
        if self.tracker is not None:
            assert self.tracker.active == 0
        self.calls.append(
            {
                "provider": dict(provider),
                "model_name": model_name,
                "manifest": manifest,
                "author_instructions": author_instructions,
            }
        )
        if self.hook is not None:
            self.hook()
        if isinstance(self.output, BaseException):
            raise self.output
        return deepcopy(self.output)


class BlockingGateway(FakeGateway):
    def __init__(self, *, tracker):
        super().__init__(tracker=tracker)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, **kwargs):
        assert self.tracker.active == 0
        self.calls.append(kwargs)
        self.entered.set()
        await self.release.wait()
        return deepcopy(self.output)


class SettlementBarrierRepository(FakePlanningRepository):
    def __init__(self):
        super().__init__()
        self.settlement_entered = asyncio.Event()
        self.release_settlement = asyncio.Event()
        self.block_next_operation_lock = True

    async def lock_generation_attempt(
        self, session, project_id, operation_id
    ):
        if self.block_next_operation_lock:
            self.block_next_operation_lock = False
            self.settlement_entered.set()
            await self.release_settlement.wait()
        return await super().lock_generation_attempt(
            session, project_id, operation_id
        )


class CoordinationFailureRepository(FakePlanningRepository):
    def __init__(self, stage, code):
        super().__init__()
        self.stage = stage
        self.code = code

    def _raise(self):
        raise OperationalError(
            self.code,
            "RAW_DATABASE_COORDINATION_SENTINEL",
        )

    async def lock_active_project(self, session, project_id):
        if self.stage == "reserve":
            self._raise()
        return await super().lock_active_project(session, project_id)

    async def read_generation_attempt(
        self, session, project_id, operation_id
    ):
        if self.stage == "get":
            self._raise()
        return await super().read_generation_attempt(
            session, project_id, operation_id
        )

    async def lock_generation_attempt(
        self, session, project_id, operation_id
    ):
        if self.stage == "settlement":
            self._raise()
        return await super().lock_generation_attempt(
            session, project_id, operation_id
        )


class ExhaustingExpiredRepository(FakePlanningRepository):
    def __init__(self):
        super().__init__()
        self.reserve_reads = 0
        self.settles = 0
        self._add_expired(1)

    def _add_expired(self, number):
        self.attempts[f"expired-operation-{number}"] = {
            "id": f"expired-row-{number}",
            "project_id": "p1",
            "draft_id": "draft-1",
            "operation_id": f"expired-operation-{number}",
            "idempotency_key": f"expired-key-{number}",
            "request_fingerprint": f"{number:x}".rjust(64, "0"),
            "binding_revision_id": "binding-1",
            "binding_revision": 1,
            "binding_hash": "5" * 64,
            "provider_id": "provider-1",
            "model_name_snapshot": "deepseek-v4-flash",
            "fencing_token": number,
            "lease_expires_at": NOW - 1,
            "input_manifest_json": "{}",
            "input_manifest_hash": "7" * 64,
            "status": "pending",
            "active_slot": 1,
            "failure_code": None,
            "loaded_draft_revision": None,
        }

    async def read_active_generation_attempt(self, session, draft_id):
        self.reserve_reads += 1
        return await super().read_active_generation_attempt(
            session, draft_id
        )

    async def supersede_generation_attempt(self, session, **kwargs):
        changed = await super().supersede_generation_attempt(
            session, **kwargs
        )
        if changed:
            self.settles += 1
            if self.settles < 3:
                self._add_expired(self.settles + 1)
        return changed


def _service(
    repository=None,
    gateway=None,
    tracker=None,
    *,
    clock=lambda: NOW,
):
    from backend.services.planning_generation import PlanningGenerationService

    repository = repository or FakePlanningRepository()
    tracker = tracker or TransactionTracker()
    gateway = gateway or FakeGateway(tracker=tracker)
    identifiers = iter(
        [
            "attempt-row-1",
            "operation-1",
            "generated-volume-1",
            "generated-plot-1",
            "attempt-row-2",
            "operation-2",
            "generated-volume-2",
            "generated-plot-2",
        ]
    )
    return (
        PlanningGenerationService(
            repository,
            provider_gateway=gateway,
            transaction_factory=tracker.factory,
            id_factory=identifiers.__next__,
            clock=clock,
        ),
        repository,
        gateway,
        tracker,
    )


def _command(key="generate-1", *, instructions="强化群像"):
    from backend.services.planning_generation import GeneratePlanningDraft

    content = _persisted_draft()
    return GeneratePlanningDraft(
        project_id="p1",
        draft_id="draft-1",
        draft_revision=1,
        draft_hash=content.content_hash,
        idempotency_key=key,
        author_instructions=instructions,
    )


@pytest.mark.asyncio
async def test_success_uses_two_short_transactions_and_atomically_loads_exact_draft():
    service, repository, gateway, tracker = _service()

    result = await service.generate(_command())

    assert result.status == "succeeded"
    assert result.loaded is True
    assert result.loaded_draft_revision == 2
    assert result.model.provider_id == "provider-1"
    assert result.model.model_name == "deepseek-v4-flash"
    assert repository.draft["source_attempt_id"] == "attempt-row-1"
    assert repository.load_calls == 1
    assert len(gateway.calls) == 1
    assert tracker.entries == 2
    assert tracker.active == 0
    assert repository.lock_order[:8] == [
        "project",
        "basis",
        "head",
        "draft",
        "binding",
        "idempotency-read",
        "active-read",
        "token",
    ]


@pytest.mark.asyncio
async def test_same_key_same_fingerprint_replays_without_gateway_call():
    service, _repository, gateway, _tracker = _service()
    first = await service.generate(_command())
    second = await service.generate(_command())

    assert second == first
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_same_key_different_fingerprint_conflicts_without_gateway_call():
    from backend.services.planning_generation import (
        PlanningGenerationIdempotencyConflict,
    )

    service, _repository, gateway, _tracker = _service()
    await service.generate(_command())

    with pytest.raises(PlanningGenerationIdempotencyConflict):
        await service.generate(_command(instructions="完全不同的要求"))

    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_same_key_expired_pending_replay_supersedes_without_hidden_retry():
    repository = FakePlanningRepository()
    tracker = TransactionTracker()
    gateway = BlockingGateway(tracker=tracker)
    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=gateway,
        tracker=tracker,
    )
    first_call = asyncio.create_task(service.generate(_command()))
    await gateway.entered.wait()
    repository.attempts["operation-1"]["lease_expires_at"] = NOW - 1

    replay = await service.generate(_command())

    assert replay.status == "superseded"
    assert replay.loaded is False
    assert len(gateway.calls) == 1
    gateway.release.set()
    stale = await first_call
    assert stale.status == "superseded"
    assert repository.load_calls == 0


@pytest.mark.asyncio
async def test_one_unexpired_active_lease_rejects_another_key():
    from backend.services.planning_generation import PlanningGenerationConflict

    service, repository, gateway, _tracker = _service()
    repository.attempts["busy-operation"] = {
        "id": "busy-row",
        "project_id": "p1",
        "draft_id": "draft-1",
        "operation_id": "busy-operation",
        "idempotency_key": "busy-key",
        "request_fingerprint": "6" * 64,
        "binding_revision_id": "binding-1",
        "binding_revision": 1,
        "binding_hash": "5" * 64,
        "provider_id": "provider-1",
        "model_name_snapshot": "deepseek-v4-flash",
        "fencing_token": 1,
        "lease_expires_at": NOW + 1,
        "input_manifest_json": "{}",
        "input_manifest_hash": "7" * 64,
        "status": "pending",
        "active_slot": 1,
        "failure_code": None,
        "loaded_draft_revision": None,
    }

    with pytest.raises(PlanningGenerationConflict):
        await service.generate(_command("different-key"))

    assert gateway.calls == []


@pytest.mark.asyncio
async def test_public_model_summary_cannot_echo_provider_secret():
    from backend.services.planning_generation import (
        PlanningGenerationNotReady,
    )

    repository = FakePlanningRepository()
    repository.binding["model_name"] = repository.binding["api_key"]
    repository.binding["model_name_snapshot"] = repository.binding["api_key"]
    service, _repository, gateway, _tracker = _service(
        repository=repository
    )

    with pytest.raises(PlanningGenerationNotReady):
        await service.generate(_command())

    assert gateway.calls == []


@pytest.mark.asyncio
async def test_expired_lease_is_superseded_and_new_key_gets_higher_fence():
    service, repository, gateway, _tracker = _service()
    repository.attempts["expired-operation"] = {
        "id": "expired-row",
        "project_id": "p1",
        "draft_id": "draft-1",
        "operation_id": "expired-operation",
        "idempotency_key": "expired-key",
        "request_fingerprint": "6" * 64,
        "binding_revision_id": "binding-1",
        "binding_revision": 1,
        "binding_hash": "5" * 64,
        "provider_id": "provider-1",
        "model_name_snapshot": "deepseek-v4-flash",
        "fencing_token": 1,
        "lease_expires_at": NOW - 1,
        "input_manifest_json": "{}",
        "input_manifest_hash": "7" * 64,
        "status": "pending",
        "active_slot": 1,
        "failure_code": None,
        "loaded_draft_revision": None,
    }

    result = await service.generate(_command("fresh-key"))

    assert repository.attempts["expired-operation"]["status"] == "superseded"
    assert repository.attempts[result.operation_id]["fencing_token"] == 2
    assert result.loaded is True
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_gateway_failure_and_malformed_result_terminalize_without_loading():
    for output, code in (
        (PlanningProviderError("Planning provider failed"), "PlanningProviderFailed"),
        ({"not": "a planning draft"}, "PlanningProviderResultInvalid"),
    ):
        service, repository, gateway, _tracker = _service(
            gateway=FakeGateway(output)
        )

        result = await service.generate(_command())

        assert result.status == "failed"
        assert result.failure_code == code
        assert result.loaded is False
        assert repository.load_calls == 0
        assert len(gateway.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output", "failure_code"),
    (
        (
            PlanningProviderError("Planning provider failed"),
            "PlanningProviderFailed",
        ),
        ({"not": "a planning draft"}, "PlanningProviderResultInvalid"),
    ),
    ids=("provider-failure", "invalid-result"),
)
async def test_cancel_during_first_settlement_await_still_releases_owned_attempt(
    output,
    failure_code,
):
    repository = SettlementBarrierRepository()
    tracker = TransactionTracker()
    service, repository, _gateway, _tracker = _service(
        repository=repository,
        gateway=FakeGateway(output),
        tracker=tracker,
    )
    pending = asyncio.create_task(service.generate(_command()))
    await repository.settlement_entered.wait()

    pending.cancel()
    repository.release_settlement.set()
    with pytest.raises(asyncio.CancelledError):
        await pending

    attempt = repository.attempts["operation-1"]
    assert attempt["status"] == "failed"
    assert attempt["active_slot"] is None
    assert attempt["failure_code"] == failure_code
    assert repository.draft["draft_revision"] == 1
    assert repository.draft["source_attempt_id"] is None
    assert repository.load_calls == 0
    assert tracker.active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (2, 4))
async def test_multiple_cancellations_wait_for_owned_settlement_and_leave_no_task(
    cancel_count,
):
    repository = SettlementBarrierRepository()
    tracker = TransactionTracker()
    service, repository, _gateway, _tracker = _service(
        repository=repository,
        gateway=FakeGateway(
            PlanningProviderError("Planning provider failed")
        ),
        tracker=tracker,
    )
    pending = asyncio.create_task(service.generate(_command()))
    await repository.settlement_entered.wait()

    for _ in range(cancel_count):
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
    repository.release_settlement.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await asyncio.sleep(0)

    attempt = repository.attempts["operation-1"]
    assert attempt["status"] == "failed"
    assert attempt["active_slot"] is None
    assert pending.cancelled() is True
    assert pending.cancelling() == cancel_count
    assert not [
        task
        for task in asyncio.all_tasks()
        if not task.done()
        and task.get_name() == "planning-generation-settlement"
    ]


@pytest.mark.asyncio
async def test_cancelled_wait_propagates_finished_settlement_failure_without_leak():
    service, _repository, _gateway, _tracker = _service()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def failing_settlement():
        entered.set()
        await release.wait()
        raise RuntimeError("SETTLEMENT_FAILURE_SENTINEL")

    pending = asyncio.create_task(
        service._await_settlement(failing_settlement())
    )
    await entered.wait()
    pending.cancel()
    await asyncio.sleep(0)
    pending.cancel()
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(
        RuntimeError, match="^SETTLEMENT_FAILURE_SENTINEL$"
    ):
        await pending
    await asyncio.sleep(0)
    assert pending.cancelled() is False
    assert pending.cancelling() == 0
    assert not [
        task
        for task in asyncio.all_tasks()
        if not task.done()
        and task.get_name() == "planning-generation-settlement"
    ]


@pytest.mark.asyncio
async def test_author_save_during_generation_keeps_result_as_evidence_without_loading():
    repository = FakePlanningRepository()

    def author_save():
        repository.draft["draft_revision"] += 1
        repository.draft["content_hash"] = "9" * 64

    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=FakeGateway(hook=author_save),
    )

    result = await service.generate(_command())

    assert result.status == "succeeded"
    assert result.loaded is False
    assert result.loaded_draft_revision is None
    assert repository.draft["draft_revision"] == 2
    assert repository.draft["content_hash"] == "9" * 64
    assert repository.load_calls == 0
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "persisted_manifest",
    ("{}", "{"),
    ids=("valid-but-tampered", "invalid-json"),
)
async def test_persisted_manifest_tamper_keeps_evidence_without_loading(
    persisted_manifest,
):
    repository = FakePlanningRepository()

    def tamper_manifest():
        repository.attempts["operation-1"]["input_manifest_json"] = (
            persisted_manifest
        )

    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=FakeGateway(hook=tamper_manifest),
    )

    result = await service.generate(_command())

    assert result.status == "succeeded"
    assert result.loaded is False
    assert result.loaded_draft_revision is None
    assert repository.draft["draft_revision"] == 1
    assert repository.draft["source_attempt_id"] is None
    assert repository.load_calls == 0
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_publish_treats_lease_equal_to_now_as_expired():
    repository = FakePlanningRepository()
    current_time = [NOW]

    def reach_exact_expiry():
        current_time[0] = NOW + 240_000

    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=FakeGateway(hook=reach_exact_expiry),
        clock=lambda: current_time[0],
    )

    result = await service.generate(_command())

    assert result.status == "succeeded"
    assert result.loaded is False
    assert result.loaded_draft_revision is None
    assert repository.draft["draft_revision"] == 1
    assert repository.load_calls == 0
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift",
    ("project", "basis", "head", "binding", "provider"),
)
async def test_authority_drift_never_overwrites_draft(drift):
    repository = FakePlanningRepository()

    def mutate():
        if drift == "project":
            repository.project["archived_at"] = NOW
        elif drift == "basis":
            repository.basis["bible_hash"] = "8" * 64
        elif drift == "head":
            repository.head["revision"] = 1
        elif drift == "binding":
            repository.binding["binding_hash"] = "8" * 64
        else:
            repository.binding["revision"] = 2

    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=FakeGateway(hook=mutate),
    )

    result = await service.generate(_command())

    assert result.status == "succeeded"
    assert result.loaded is False
    assert repository.draft["draft_revision"] == 1
    assert repository.load_calls == 0
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_stale_fence_cannot_publish_after_expired_attempt_was_superseded():
    repository = FakePlanningRepository()
    tracker = TransactionTracker()
    gateway = BlockingGateway(tracker=tracker)
    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=gateway,
        tracker=tracker,
    )

    pending = asyncio.create_task(service.generate(_command()))
    await gateway.entered.wait()
    attempt = repository.attempts["operation-1"]
    attempt.update(status="superseded", active_slot=None)
    gateway.release.set()
    result = await pending

    assert result.status == "superseded"
    assert result.loaded is False
    assert repository.load_calls == 0


@pytest.mark.asyncio
async def test_cancellation_releases_owned_lease_without_loading():
    repository = FakePlanningRepository()
    tracker = TransactionTracker()
    gateway = BlockingGateway(tracker=tracker)
    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=gateway,
        tracker=tracker,
    )
    pending = asyncio.create_task(service.generate(_command()))
    await gateway.entered.wait()

    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    assert repository.attempts["operation-1"]["status"] == "failed"
    assert repository.attempts["operation-1"]["failure_code"] == (
        "PlanningGenerationCancelled"
    )
    assert repository.load_calls == 0
    assert tracker.active == 0


@pytest.mark.asyncio
async def test_get_operation_is_pure_query_with_no_gateway_or_hidden_retry():
    service, _repository, gateway, tracker = _service()
    generated = await service.generate(_command())
    calls_before = len(gateway.calls)
    entries_before = tracker.entries
    lock_reads_before = _repository.lock_operation_reads
    plain_reads_before = _repository.plain_operation_reads

    observed = await service.get_operation("p1", generated.operation_id)

    assert observed == generated
    assert len(gateway.calls) == calls_before
    assert tracker.entries == entries_before + 1
    assert _repository.lock_operation_reads == lock_reads_before
    assert _repository.plain_operation_reads == plain_reads_before + 1


@pytest.mark.asyncio
async def test_get_operation_by_key_is_one_pure_read_with_no_hidden_work():
    service, repository, gateway, tracker = _service()
    generated = await service.generate(_command("recovery-key"))
    calls_before = len(gateway.calls)
    entries_before = tracker.entries
    key_reads_before = repository.plain_key_reads
    operation_reads_before = repository.plain_operation_reads
    lock_reads_before = repository.lock_operation_reads
    repository.lock_order.clear()

    observed = await service.get_operation_by_key("p1", "recovery-key")

    assert observed == generated
    assert repository.lock_order == ["idempotency-read"]
    assert tracker.entries == entries_before + 1
    assert repository.plain_key_reads == key_reads_before + 1
    assert repository.plain_operation_reads == operation_reads_before
    assert repository.lock_operation_reads == lock_reads_before
    assert len(gateway.calls) == calls_before


@pytest.mark.asyncio
async def test_get_operation_by_key_uses_one_fixed_safe_not_found():
    from backend.services.planning_generation import (
        PlanningGenerationOperationNotFound,
    )

    service, repository, gateway, tracker = _service()
    entries_before = tracker.entries

    with pytest.raises(PlanningGenerationOperationNotFound) as missing:
        await service.get_operation_by_key("p1", "missing-key")
    with pytest.raises(PlanningGenerationOperationNotFound) as invalid:
        await service.get_operation_by_key("p1", "bad/key")

    for caught in (missing, invalid):
        assert str(caught.value) == "Planning generation operation not found"
        assert "missing-key" not in repr(caught.value)
        assert "bad/key" not in repr(caught.value)
    assert repository.plain_key_reads == 1
    assert tracker.entries == entries_before + 1
    assert gateway.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stage", "code"),
    (("reserve", 1213), ("get", 1205), ("settlement", 3572)),
)
async def test_mysql_coordination_failures_map_to_one_safe_retryable_error(
    stage,
    code,
):
    from backend.services.planning_generation import (
        PlanningGenerationRetryable,
    )

    repository = CoordinationFailureRepository(stage, code)
    gateway = FakeGateway(
        PlanningProviderError("Planning provider failed")
    )
    service, _repository, gateway, _tracker = _service(
        repository=repository,
        gateway=gateway,
    )

    with pytest.raises(PlanningGenerationRetryable) as caught:
        if stage == "get":
            await service.get_operation("p1", "operation-1")
        else:
            await service.generate(_command())

    assert str(caught.value) == (
        "Planning state changed; retry this request safely."
    )
    assert caught.value.__cause__ is None
    assert "RAW_DATABASE_COORDINATION_SENTINEL" not in repr(caught.value)
    assert len(gateway.calls) == (1 if stage == "settlement" else 0)


@pytest.mark.asyncio
async def test_expired_reconciliation_exhaustion_is_safe_retryable():
    from backend.services.planning_generation import (
        PlanningGenerationRetryable,
    )

    repository = ExhaustingExpiredRepository()
    service, repository, gateway, _tracker = _service(
        repository=repository
    )

    with pytest.raises(PlanningGenerationRetryable) as caught:
        await service.generate(_command("new-request-key"))

    assert caught.value.status_code == 503
    assert caught.value.retryable is True
    assert str(caught.value) == (
        "Planning state changed; retry this request safely."
    )
    assert repository.reserve_reads == 3
    assert repository.settles == 3
    assert gateway.calls == []


def test_coordination_classifier_requires_all_explicit_mysql_leaves():
    from backend.services.planning_generation import (
        PlanningGenerationService,
    )

    direct = OperationalError(1213, "direct")
    pure_group = ExceptionGroup(
        "pure",
        [
            OperationalError(1205, "timeout"),
            ExceptionGroup(
                "nested",
                [OperationalError(3572, "nowait")],
            ),
        ],
    )
    mixed_group = ExceptionGroup(
        "mixed",
        [OperationalError(1213, "deadlock"), RuntimeError("bug")],
    )
    try:
        try:
            raise OperationalError(1213, "implicit")
        except OperationalError:
            raise RuntimeError("programming failure")
    except RuntimeError as error:
        implicit_context = error
    assert isinstance(implicit_context.__context__, OperationalError)

    assert PlanningGenerationService._is_coordination_failure(direct)
    assert PlanningGenerationService._is_coordination_failure(pure_group)
    assert not PlanningGenerationService._is_coordination_failure(
        mixed_group
    )
    assert not PlanningGenerationService._is_coordination_failure(
        implicit_context
    )


def test_public_result_has_no_secret_prompt_raw_manifest_or_dsn_fields():
    from dataclasses import fields

    from backend.services.planning_generation import PlanningOperationResult

    names = {field.name for field in fields(PlanningOperationResult)}
    assert names == {
        "operation_id",
        "status",
        "failure_code",
        "model",
        "loaded",
        "loaded_draft_revision",
    }
    assert not names.intersection(
        {"api_key", "prompt", "raw_output", "manifest", "dsn"}
    )
