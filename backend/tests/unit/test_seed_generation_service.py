from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import importlib
import json

import pytest

from backend.repositories.seeds import SeedRepository


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
ATTEMPT_ID = "00000000-0000-0000-0000-000000000601"
REQUEST_ID = "00000000-0000-0000-0000-000000000602"
SNAPSHOT_ID = "00000000-0000-0000-0000-000000000201"
SNAPSHOT_B = "00000000-0000-0000-0000-000000000202"
ANALYSIS_ID = "00000000-0000-0000-0000-000000000301"
NOW = 1_721_000_000_000


def _feature():
    try:
        domain = importlib.import_module("backend.domain.seeds")
        service = importlib.import_module("backend.services.seed_generation")
        gateway = importlib.import_module("backend.gateways.seed_provider")
    except (AttributeError, ModuleNotFoundError):
        pytest.fail("seed inspiration service feature is missing")
    return domain, service, gateway


def _analysis_json() -> dict:
    return {
        "currentHeat": [
            {
                "text": "当前穿越升级题材热度较高。",
                "snapshotIds": [SNAPSHOT_ID],
                "inference": False,
            }
        ],
        "growthDirections": [],
        "crowding": [],
        "opportunities": [],
        "uncertainties": [],
        "sourceCoverage": {
            "snapshotIds": [SNAPSHOT_ID, SNAPSHOT_B],
            "summary": "两份冻结公开榜单快照。",
        },
    }


def _inputs() -> dict:
    return {
        "selection_revision": None,
        "binding_revision_id": "00000000-0000-0000-0000-000000000401",
        "binding_hash": "d" * 64,
        "resolution_status": "bound",
        "provider_id": "00000000-0000-0000-0000-000000000501",
        "model_name_snapshot": "deepseek-v4-flash",
        "provider": {
            "id": "00000000-0000-0000-0000-000000000501",
            "provider_type": "openai-compatible",
            "model_name": "deepseek-v4-flash",
            "base_url": "https://private.provider.invalid/v1",
            "api_key": "PRIVATE_PROVIDER_KEY",
            "enabled": 1,
            "lifecycle_status": "active",
            "temperature": 0.7,
            "max_output_tokens": 1600,
        },
        "snapshots": (
            {
                "id": SNAPSHOT_ID,
                "source_id": "00000000-0000-0000-0000-000000000101",
                "content_hash": "a" * 64,
                "manifest_hash": "b" * 64,
                "captured_at": NOW,
                "platform": "qidian",
                "ranking_name": "newsign",
                "category": "male",
                "source_url": "https://www.qidian.com/rank/newsign/",
                "entries": (
                    {
                        "rank": 1,
                        "title": "雾港天文钟",
                        "author": "公开作者",
                        "category": "玄幻",
                        "public_metrics": {"weeklyRecommendations": 321},
                    },
                ),
            },
            {
                "id": SNAPSHOT_B,
                "source_id": "00000000-0000-0000-0000-000000000102",
                "content_hash": "f" * 64,
                "manifest_hash": "1" * 64,
                "captured_at": NOW + 1,
                "platform": "qq_reading",
                "ranking_name": "male_popular",
                "category": "male",
                "source_url": "https://book.qq.com/book-rank",
                "entries": (
                    {
                        "rank": 1,
                        "title": "群星渡口",
                        "author": "公开作者乙",
                        "category": "仙侠",
                        "public_metrics": {"heat": 222},
                    },
                ),
            },
        ),
        "analysis": {
            "id": ANALYSIS_ID,
            "result_hash": "c" * 64,
            "input_manifest_hash": "e" * 64,
            "status": "succeeded",
            "input_manifest_json": {
                "snapshots": [
                    {
                        "id": SNAPSHOT_ID,
                        "hash": "a" * 64,
                        "manifestHash": "b" * 64,
                        "sourceId": "00000000-0000-0000-0000-000000000101",
                    },
                    {
                        "id": SNAPSHOT_B,
                        "hash": "f" * 64,
                        "manifestHash": "1" * 64,
                        "sourceId": "00000000-0000-0000-0000-000000000102",
                    },
                ]
            },
            "analysis_json": _analysis_json(),
        },
    }


class FakeRepository:
    def __init__(self):
        self.requests: dict[str, dict] = {}
        self.attempts: dict[str, dict] = {}
        self.events: list[tuple | str] = []
        self.inputs_match = True
        self.seed_count = 0
        self.release_reservation = asyncio.Event()
        self.block_reservation = False

    async def lock_inspiration_project(self, _session, project_id):
        self.events.append(("project", project_id))
        return {"id": project_id, "archived_at": None}

    async def lock_inspiration_request(self, _session, project_id, key):
        self.events.append(("key", key))
        row = self.requests.get(key)
        return dict(row) if row and row["project_id"] == project_id else None

    async def lock_inspiration_inputs(
        self, _session, project_id, snapshot_ids, analysis_id
    ):
        self.events.append(("inputs", tuple(snapshot_ids), analysis_id))
        return _inputs()

    async def insert_inspiration_request(self, _session, row):
        self.events.append("insert-request")
        self.requests[row["idempotency_key"]] = dict(row)

    async def insert_inspiration_attempt(self, _session, row):
        self.events.append("insert-attempt")
        self.attempts[row["id"]] = dict(row)

    async def read_inspiration_attempt(self, _session, project_id, attempt_id):
        row = self.attempts.get(attempt_id)
        if row and row["project_id"] == project_id:
            return dict(row)
        return None

    async def publish_inspiration(self, _session, **values):
        self.events.append("publish")
        row = self.attempts[values["attempt_id"]]
        request = self.requests[values["idempotency_key"]]
        if not self.inputs_match:
            row.update(
                status="failed",
                result_json=None,
                result_hash=None,
                public_error_code="SEED_INSPIRATION_INPUT_CHANGED",
                completed_at=values["completed_at"],
            )
            request.update(
                status="failed",
                attempt_id=None,
                result_hash=None,
                public_error_code="SEED_INSPIRATION_INPUT_CHANGED",
                completed_at=values["completed_at"],
            )
            return False
        row.update(
            status="succeeded",
            result_json=values["result_json"],
            result_hash=values["result_hash"],
            public_error_code=None,
            completed_at=values["completed_at"],
        )
        request.update(
            status="succeeded",
            attempt_id=values["attempt_id"],
            result_hash=values["result_hash"],
            public_error_code=None,
            completed_at=values["completed_at"],
        )
        return True

    async def fail_inspiration(self, _session, **values):
        self.events.append(("fail", values["public_error_code"]))
        attempt = self.attempts[values["attempt_id"]]
        request = self.requests[values["idempotency_key"]]
        attempt.update(
            status=values["attempt_status"],
            result_json=None,
            result_hash=None,
            public_error_code=values["public_error_code"],
            completed_at=values["completed_at"],
        )
        request.update(
            status=values["request_status"],
            attempt_id=(
                values["attempt_id"]
                if values["request_status"] == "outcome_unknown"
                else None
            ),
            result_hash=None,
            public_error_code=values["public_error_code"],
            completed_at=values["completed_at"],
        )
        return True


class TransactionProbe:
    def __init__(self):
        self.active = False

    @asynccontextmanager
    async def factory(self):
        assert self.active is False
        self.active = True
        try:
            yield object()
        finally:
            self.active = False


class CommitBarrierProbe:
    def __init__(
        self,
        barrier_call: int,
        *,
        commit_error: BaseException | None = None,
    ):
        self.active = False
        self.calls = 0
        self.barrier_call = barrier_call
        self.commit_error = commit_error
        self.commit_started = asyncio.Event()
        self.release_commit = asyncio.Event()

    @asynccontextmanager
    async def factory(self):
        assert self.active is False
        self.active = True
        self.calls += 1
        call = self.calls
        try:
            yield object()
            if call == self.barrier_call:
                self.commit_started.set()
                await self.release_commit.wait()
                if self.commit_error is not None:
                    raise self.commit_error
        finally:
            self.active = False


class RollbackCommitProbe:
    def __init__(
        self,
        repository,
        *,
        barrier_call: int,
        commit_error: BaseException,
    ):
        self.repository = repository
        self.active = False
        self.calls = 0
        self.barrier_call = barrier_call
        self.commit_error = commit_error

    @asynccontextmanager
    async def factory(self):
        assert self.active is False
        self.active = True
        self.calls += 1
        call = self.calls
        requests = deepcopy(self.repository.requests)
        attempts = deepcopy(self.repository.attempts)
        try:
            yield object()
            if call == self.barrier_call:
                self.repository.requests = requests
                self.repository.attempts = attempts
                raise self.commit_error
        finally:
            self.active = False


class FakeGateway:
    def __init__(self, probe, response):
        self.probe = probe
        self.response = response
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False

    async def generate(self, **values):
        assert self.probe.active is False
        assert "provider_id" not in values
        self.calls += 1
        self.started.set()
        if self.block:
            await self.release.wait()
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def _harness(response="把永乐大典拆成知识、权力与身份三条递进冲突线。"):
    _, module, _ = _feature()
    repository = FakeRepository()
    probe = TransactionProbe()
    gateway = FakeGateway(probe, response)
    ids = iter((REQUEST_ID, ATTEMPT_ID))
    service = module.SeedGenerationService(
        repository,
        transaction_factory=probe.factory,
        connection_factory=probe.factory,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=lambda: NOW,
    )
    command = module.GenerateSeedInspiration(
        project_id=PROJECT_ID,
        transcript=(
            {"role": "user", "content": "我想写明代穿越群像故事。"},
        ),
        snapshot_ids=(SNAPSHOT_ID, SNAPSHOT_B),
        analysis_id=ANALYSIS_ID,
        idempotency_key="i" * 64,
    )
    return service, repository, gateway, command


@pytest.mark.asyncio
async def test_repository_partial_terminal_write_raises_to_force_transaction_rollback():
    class PartialSession:
        calls = 0

        async def execute(self, _sql, _args):
            self.calls += 1
            return 1 if self.calls == 1 else 0

    with pytest.raises(RuntimeError, match="atomic"):
        await SeedRepository()._terminalize_inspiration(
            PartialSession(),
            project_id=PROJECT_ID,
            idempotency_key="i" * 64,
            attempt_id=ATTEMPT_ID,
            attempt_status="failed",
            request_status="failed",
            public_error_code="SEED_INSPIRATION_PROVIDER_FAILED",
            completed_at=NOW,
        )


@pytest.mark.asyncio
async def test_generation_is_transient_replays_and_never_inserts_creative_seed():
    _, _, _ = _feature()
    service, repository, gateway, command = _harness()

    first = await service.generate(command)
    replay = await service.generate(command)

    assert first.status == replay.status == "succeeded"
    assert replay.assistant_turn == first.assistant_turn
    assert replay.attempt_id == ATTEMPT_ID
    assert gateway.calls == 1
    assert repository.seed_count == 0
    attempt = repository.attempts[ATTEMPT_ID]
    request = repository.requests["i" * 64]
    assert "我想写明代穿越群像故事" not in attempt["input_manifest_json"]
    assert "我想写明代穿越群像故事" not in json.dumps(request)
    assert "PRIVATE_PROVIDER_KEY" not in json.dumps(attempt)
    assert "private.provider.invalid" not in json.dumps(attempt)
    assert "raw" not in "".join(attempt)
    assert attempt["result_json"] == json.dumps(
        first.assistant_turn.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    manifest = json.loads(attempt["input_manifest_json"])
    assert [item["id"] for item in manifest["snapshots"]] == [
        SNAPSHOT_ID,
        SNAPSHOT_B,
    ]
    assert [item["hash"] for item in manifest["snapshots"]] == [
        "a" * 64,
        "f" * 64,
    ]


@pytest.mark.asyncio
async def test_same_key_different_request_conflicts_and_concurrency_calls_once():
    domain, module, _ = _feature()
    service, _, gateway, command = _harness()
    gateway.block = True
    owner = asyncio.create_task(service.generate(command))
    await gateway.started.wait()

    with pytest.raises(domain.SeedInspirationFailure) as in_progress:
        await service.generate(command)
    assert in_progress.value.code == "SEED_INSPIRATION_IN_PROGRESS"

    changed = command.model_copy(
        update={
            "transcript": (
                domain.SeedChatTurn(role="user", content="改成清代穿越。"),
            )
        }
    )
    with pytest.raises(domain.SeedInspirationFailure) as conflict:
        await service.generate(changed)
    assert conflict.value.code == "SEED_INSPIRATION_IDEMPOTENCY_CONFLICT"

    gateway.release.set()
    result = await owner
    assert result.status == "succeeded"
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_provider_parse_and_manifest_failures_are_terminal_without_synthetic_seed():
    domain, module, gateway_module = _feature()
    cases = (
        (
            gateway_module.SeedProviderHTTPError("safe"),
            "SEED_INSPIRATION_PROVIDER_FAILED",
        ),
        ("apiKey=PRIVATE_PROVIDER_KEY", "SEED_INSPIRATION_INVALID_RESPONSE"),
    )
    for response, expected_code in cases:
        service, repository, gateway, command = _harness(response)
        result = await service.generate(command)
        replay = await service.generate(command)
        assert result.status == replay.status == "failed"
        assert result.public_error_code == expected_code
        assert result.assistant_turn is None
        assert repository.seed_count == 0
        assert gateway.calls == 1
        assert repository.attempts[ATTEMPT_ID]["result_json"] is None

    service, repository, _, command = _harness()
    repository.inputs_match = False
    result = await service.generate(command)
    assert result.status == "failed"
    assert result.public_error_code == "SEED_INSPIRATION_INPUT_CHANGED"
    assert result.assistant_turn is None


@pytest.mark.parametrize("failure_source", ("prompt", "gateway"))
@pytest.mark.asyncio
async def test_unexpected_prompt_or_gateway_exception_is_safe_and_terminal(
    monkeypatch,
    failure_source,
):
    _, module, _ = _feature()
    service, repository, gateway, command = _harness()
    private_detail = "apiKey=PRIVATE_UNEXPECTED_DETAIL"
    if failure_source == "prompt":
        def fail_prompt(**_values):
            raise KeyError(private_detail)

        monkeypatch.setattr(
            module,
            "build_seed_inspiration_messages",
            fail_prompt,
        )
    else:
        gateway.response = RuntimeError(private_detail)

    result = await service.generate(command)
    replay = await service.generate(command)

    assert result.status == replay.status == "failed"
    assert (
        result.public_error_code
        == replay.public_error_code
        == "SEED_INSPIRATION_PROVIDER_FAILED"
    )
    assert result.assistant_turn is None
    assert private_detail not in json.dumps(repository.requests)
    assert private_detail not in json.dumps(repository.attempts)
    assert gateway.calls == (0 if failure_source == "prompt" else 1)


@pytest.mark.asyncio
async def test_retryable_publication_failure_is_terminal_and_replay_safe():
    _, module, _ = _feature()
    service, repository, gateway, command = _harness()

    async def deadlocked_publication(_session, **_values):
        raise RuntimeError(1213, "PRIVATE_DATABASE_DETAIL")

    repository.publish_inspiration = deadlocked_publication

    result = await service.generate(command)
    replay = await service.generate(command)

    assert result.status == replay.status == "failed"
    assert (
        result.public_error_code
        == replay.public_error_code
        == "SEED_INSPIRATION_PUBLICATION_FAILED"
    )
    assert repository.requests[command.idempotency_key]["status"] == "failed"
    assert repository.attempts[ATTEMPT_ID]["status"] == "failed"
    assert "PRIVATE_DATABASE_DETAIL" not in json.dumps(
        (repository.requests, repository.attempts)
    )
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_reservation_commit_cancellation_is_owned_and_terminalized():
    _, module, _ = _feature()
    repository = FakeRepository()
    transactions = CommitBarrierProbe(barrier_call=1)
    connections = TransactionProbe()
    gateway = FakeGateway(
        transactions,
        "把知识优势拆成三次递进兑现。",
    )
    ids = iter((REQUEST_ID, ATTEMPT_ID))
    service = module.SeedGenerationService(
        repository,
        transaction_factory=transactions.factory,
        connection_factory=connections.factory,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=lambda: NOW,
    )
    command = module.GenerateSeedInspiration(
        project_id=PROJECT_ID,
        transcript=({"role": "user", "content": "明代穿越群像"},),
        snapshot_ids=(SNAPSHOT_ID, SNAPSHOT_B),
        analysis_id=ANALYSIS_ID,
        idempotency_key="r" * 64,
    )
    task = asyncio.create_task(service.generate(command))
    try:
        await asyncio.wait_for(
            transactions.commit_started.wait(),
            timeout=1,
        )
        task.cancel()
        task.cancel()
        await asyncio.sleep(0)
        transactions.release_commit.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
    finally:
        transactions.release_commit.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    terminalizers = tuple(service._terminalizers)
    if terminalizers:
        await asyncio.wait_for(
            asyncio.gather(*terminalizers),
            timeout=1,
        )
    replay = await service.generate(command)
    assert replay.status == "outcome_unknown"
    assert replay.public_error_code == "SEED_INSPIRATION_CANCELLED"
    assert repository.attempts[ATTEMPT_ID]["result_json"] is None
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_publication_commit_cancellation_respects_committed_success():
    _, module, _ = _feature()
    repository = FakeRepository()
    transactions = CommitBarrierProbe(barrier_call=2)
    connections = TransactionProbe()
    gateway = FakeGateway(
        transactions,
        "把知识优势拆成三次递进兑现。",
    )
    ids = iter((REQUEST_ID, ATTEMPT_ID))
    service = module.SeedGenerationService(
        repository,
        transaction_factory=transactions.factory,
        connection_factory=connections.factory,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=lambda: NOW,
    )
    command = module.GenerateSeedInspiration(
        project_id=PROJECT_ID,
        transcript=({"role": "user", "content": "明代穿越群像"},),
        snapshot_ids=(SNAPSHOT_ID, SNAPSHOT_B),
        analysis_id=ANALYSIS_ID,
        idempotency_key="p" * 64,
    )
    task = asyncio.create_task(service.generate(command))
    try:
        await asyncio.wait_for(
            transactions.commit_started.wait(),
            timeout=1,
        )
        task.cancel()
        task.cancel()
        await asyncio.sleep(0)
        transactions.release_commit.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
    finally:
        transactions.release_commit.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    terminalizers = tuple(service._terminalizers)
    if terminalizers:
        await asyncio.wait_for(
            asyncio.gather(*terminalizers),
            timeout=1,
        )
    replay = await service.generate(command)
    assert replay.status == "succeeded"
    assert replay.assistant_turn.content == "把知识优势拆成三次递进兑现。"
    assert repository.attempts[ATTEMPT_ID]["status"] == "succeeded"
    assert repository.attempts[ATTEMPT_ID]["result_json"] is not None
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_reservation_commit_error_reconciles_running_attempt_to_failure():
    _, module, _ = _feature()
    repository = FakeRepository()
    transactions = CommitBarrierProbe(
        barrier_call=1,
        commit_error=RuntimeError(2013, "PRIVATE_COMMIT_DETAIL"),
    )
    transactions.release_commit.set()
    connections = TransactionProbe()
    gateway = FakeGateway(
        transactions,
        "把知识优势拆成三次递进兑现。",
    )
    ids = iter((REQUEST_ID, ATTEMPT_ID))
    service = module.SeedGenerationService(
        repository,
        transaction_factory=transactions.factory,
        connection_factory=connections.factory,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=lambda: NOW,
    )
    command = module.GenerateSeedInspiration(
        project_id=PROJECT_ID,
        transcript=({"role": "user", "content": "明代穿越群像"},),
        snapshot_ids=(SNAPSHOT_ID, SNAPSHOT_B),
        analysis_id=ANALYSIS_ID,
        idempotency_key="e" * 64,
    )

    result = await service.generate(command)
    replay = await service.generate(command)

    assert result.status == replay.status == "failed"
    assert (
        result.public_error_code
        == replay.public_error_code
        == "SEED_INSPIRATION_RESERVATION_FAILED"
    )
    assert repository.requests[command.idempotency_key]["status"] == "failed"
    assert repository.attempts[ATTEMPT_ID]["status"] == "failed"
    assert "PRIVATE_COMMIT_DETAIL" not in json.dumps(
        (repository.requests, repository.attempts)
    )
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_publication_commit_error_reconciles_committed_success():
    _, module, _ = _feature()
    repository = FakeRepository()
    transactions = CommitBarrierProbe(
        barrier_call=2,
        commit_error=RuntimeError(2013, "PRIVATE_COMMIT_DETAIL"),
    )
    transactions.release_commit.set()
    connections = TransactionProbe()
    gateway = FakeGateway(
        transactions,
        "把知识优势拆成三次递进兑现。",
    )

    async def atomic_failure(_session, **values):
        attempt = repository.attempts[values["attempt_id"]]
        if attempt["status"] != "running":
            raise RuntimeError("seed inspiration terminal write must remain atomic")
        return await FakeRepository.fail_inspiration(
            repository,
            _session,
            **values,
        )

    repository.fail_inspiration = atomic_failure
    ids = iter((REQUEST_ID, ATTEMPT_ID))
    service = module.SeedGenerationService(
        repository,
        transaction_factory=transactions.factory,
        connection_factory=connections.factory,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=lambda: NOW,
    )
    command = module.GenerateSeedInspiration(
        project_id=PROJECT_ID,
        transcript=({"role": "user", "content": "明代穿越群像"},),
        snapshot_ids=(SNAPSHOT_ID, SNAPSHOT_B),
        analysis_id=ANALYSIS_ID,
        idempotency_key="u" * 64,
    )

    result = await service.generate(command)
    replay = await service.generate(command)

    assert result.status == replay.status == "succeeded"
    assert result.assistant_turn.content == "把知识优势拆成三次递进兑现。"
    assert repository.requests[command.idempotency_key]["status"] == "succeeded"
    assert repository.attempts[ATTEMPT_ID]["status"] == "succeeded"
    assert gateway.calls == 1


@pytest.mark.parametrize("commit_landed", (False, True))
@pytest.mark.asyncio
async def test_failure_commit_error_reconciles_landed_and_not_landed(
    commit_landed,
):
    _, module, gateway_module = _feature()
    repository = FakeRepository()
    commit_error = RuntimeError(2013, "PRIVATE_FAILURE_COMMIT_DETAIL")
    if commit_landed:
        transactions = CommitBarrierProbe(
            barrier_call=2,
            commit_error=commit_error,
        )
        transactions.release_commit.set()
    else:
        transactions = RollbackCommitProbe(
            repository,
            barrier_call=2,
            commit_error=commit_error,
        )
    connections = TransactionProbe()
    gateway = FakeGateway(
        transactions,
        gateway_module.SeedProviderHTTPError("PRIVATE_PROVIDER_DETAIL"),
    )
    ids = iter((REQUEST_ID, ATTEMPT_ID))
    service = module.SeedGenerationService(
        repository,
        transaction_factory=transactions.factory,
        connection_factory=connections.factory,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=lambda: NOW,
    )
    command = module.GenerateSeedInspiration(
        project_id=PROJECT_ID,
        transcript=({"role": "user", "content": "明代穿越群像"},),
        snapshot_ids=(SNAPSHOT_ID, SNAPSHOT_B),
        analysis_id=ANALYSIS_ID,
        idempotency_key=("l" if commit_landed else "n") * 64,
    )

    result = await service.generate(command)
    replay = await service.generate(command)

    assert result.status == replay.status == "failed"
    assert (
        result.public_error_code
        == replay.public_error_code
        == "SEED_INSPIRATION_PROVIDER_FAILED"
    )
    assert repository.requests[command.idempotency_key]["status"] == "failed"
    assert repository.attempts[ATTEMPT_ID]["status"] == "failed"
    assert "PRIVATE_FAILURE_COMMIT_DETAIL" not in json.dumps(
        (repository.requests, repository.attempts)
    )
    assert "PRIVATE_PROVIDER_DETAIL" not in json.dumps(
        (repository.requests, repository.attempts)
    )
    assert gateway.calls == 1


@pytest.mark.parametrize(
    "transcript,response",
    (
        (
            ({"role": "user", "content": "明代穿越群像"},),
            "明代穿越群像",
        ),
        (
            (
                {"role": "user", "content": "主角带着知识穿越。"},
                {"role": "assistant", "content": "让配角争夺解释权。"},
            ),
            (
                '{"currentTranscript":['
                '{"content":"主角带着知识穿越。","role":"user"},'
                '{"content":"让配角争夺解释权。","role":"assistant"}]}'
            ),
        ),
        (
            (
                {"role": "user", "content": "主角带着知识穿越。"},
                {"role": "assistant", "content": "让配角争夺解释权。"},
            ),
            (
                "下面是当前对话：\n```json\n{\n"
                '  "currentTranscript": [\n'
                '    {"role": "user", "content": "主角带着知识穿越。"},\n'
                '    {"role": "assistant", "content": "让配角争夺解释权。"}\n'
                "  ]\n}\n```\n请继续。"
            ),
        ),
    ),
)
@pytest.mark.asyncio
async def test_raw_transcript_echo_is_terminal_and_never_persisted(
    transcript,
    response,
):
    domain, _, _ = _feature()
    service, repository, gateway, command = _harness(response)
    command = command.model_copy(
        update={
            "transcript": tuple(
                domain.SeedChatTurn.model_validate(turn, strict=True)
                for turn in transcript
            )
        }
    )

    result = await service.generate(command)
    replay = await service.generate(command)

    assert result.status == replay.status == "failed"
    assert (
        result.public_error_code
        == replay.public_error_code
        == "SEED_INSPIRATION_INVALID_RESPONSE"
    )
    assert result.assistant_turn is replay.assistant_turn is None
    assert repository.attempts[ATTEMPT_ID]["result_json"] is None
    assert response not in json.dumps(repository.attempts, ensure_ascii=False)
    assert gateway.calls == 1


def test_embedded_json_echo_scan_does_not_reject_nearby_creative_advice():
    domain, module, _ = _feature()
    transcript = (
        domain.SeedChatTurn(
            role="user",
            content="主角带着知识穿越。",
        ),
        domain.SeedChatTurn(
            role="assistant",
            content="让配角争夺解释权。",
        ),
    )
    advice = (
        "建议保留原冲突，但加入新变化：\n```json\n"
        '{"currentTranscript":[{"role":"user",'
        '"content":"主角带着残缺知识穿越。"}]}\n```'
    )

    assert module.SeedGenerationService._echoes_transcript(
        advice,
        transcript,
    ) is False


@pytest.mark.asyncio
async def test_cancel_terminalizes_attempt_and_replay_never_recalls_provider():
    _, _, _ = _feature()
    service, repository, gateway, command = _harness(asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await service.generate(command)
    replay = await service.generate(command)

    assert replay.status == "outcome_unknown"
    assert replay.public_error_code == "SEED_INSPIRATION_CANCELLED"
    assert replay.assistant_turn is None
    assert repository.seed_count == 0
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_interrupt_terminal_persistence():
    _, _, _ = _feature()
    service, repository, gateway, command = _harness(asyncio.CancelledError())
    failure_started = asyncio.Event()
    release_failure = asyncio.Event()
    original = repository.fail_inspiration

    async def blocking_failure(session, **values):
        failure_started.set()
        await release_failure.wait()
        return await original(session, **values)

    repository.fail_inspiration = blocking_failure
    task = asyncio.create_task(service.generate(command))
    try:
        await asyncio.wait_for(failure_started.wait(), timeout=1)
        task.cancel()
        task.cancel()
        await asyncio.sleep(0)
        assert task.done() is False
        release_failure.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release_failure.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert repository.attempts[ATTEMPT_ID]["status"] == "outcome_unknown"
    assert (
        repository.attempts[ATTEMPT_ID]["public_error_code"]
        == "SEED_INSPIRATION_CANCELLED"
    )
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_cancellation_cleanup_timeout_transfers_terminal_persistence(
    monkeypatch,
):
    _, module, _ = _feature()
    service, repository, gateway, command = _harness(asyncio.CancelledError())
    failure_started = asyncio.Event()
    release_failure = asyncio.Event()
    original = repository.fail_inspiration

    async def blocking_failure(session, **values):
        failure_started.set()
        await release_failure.wait()
        return await original(session, **values)

    repository.fail_inspiration = blocking_failure
    monkeypatch.setattr(
        module,
        "CANCELLATION_CLEANUP_TIMEOUT_SECONDS",
        0.01,
    )
    task = asyncio.create_task(service.generate(command))
    try:
        await asyncio.wait_for(failure_started.wait(), timeout=1)
        with pytest.raises(asyncio.CancelledError):
            await task
        terminalizers = tuple(service._terminalizers)
        assert len(terminalizers) == 1
        assert repository.requests["i" * 64]["status"] == "reserved"

        release_failure.set()
        await asyncio.wait_for(
            asyncio.gather(*terminalizers),
            timeout=1,
        )
    finally:
        release_failure.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    replay = await service.generate(command)
    assert replay.status == "outcome_unknown"
    assert replay.public_error_code == "SEED_INSPIRATION_CANCELLED"
    assert repository.attempts[ATTEMPT_ID]["status"] == "outcome_unknown"
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_cancellation_during_failed_publication_terminalizes_without_result():
    _, _, _ = _feature()
    service, repository, gateway, command = _harness()
    publish_started = asyncio.Event()
    release_publish = asyncio.Event()
    async def blocking_publish(session, **values):
        publish_started.set()
        await release_publish.wait()
        raise RuntimeError(1213, "PRIVATE_DATABASE_DETAIL")

    repository.publish_inspiration = blocking_publish
    task = asyncio.create_task(service.generate(command))
    try:
        await asyncio.wait_for(publish_started.wait(), timeout=1)
        task.cancel()
        release_publish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release_publish.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    row = repository.attempts[ATTEMPT_ID]
    assert row["status"] == "outcome_unknown"
    assert row["result_json"] is None
    assert row["result_hash"] is None
    assert row["public_error_code"] == "SEED_INSPIRATION_CANCELLED"
    assert gateway.calls == 1
