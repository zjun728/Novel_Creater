from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import importlib
import json

import pytest


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
ANALYSIS_ID = "00000000-0000-0000-0000-000000000301"
SNAPSHOT_A = "00000000-0000-0000-0000-000000000201"
SNAPSHOT_B = "00000000-0000-0000-0000-000000000202"
NOW = 1_721_000_000_000


def _feature():
    try:
        domain = importlib.import_module("backend.domain.market_analysis")
        service = importlib.import_module("backend.services.market_analysis")
        gateway = importlib.import_module(
            "backend.gateways.market_analysis_provider"
        )
    except ModuleNotFoundError:
        pytest.fail("frozen market analysis service feature is missing")
    return domain, service, gateway


def _snapshot(snapshot_id: str, content_hash: str, manifest_hash: str) -> dict:
    return {
        "id": snapshot_id,
        "source_id": "00000000-0000-0000-0000-000000000101",
        "captured_at": NOW,
        "platform": "qidian",
        "ranking_name": "newsign",
        "category": "male",
        "source_url": "https://www.qidian.com/rank/newsign/",
        "content_hash": content_hash,
        "manifest_hash": manifest_hash,
        "entry_count": 1,
        "entries": (
            {
                "rank": 1,
                "title": "雾港天文钟",
                "author": "合成作者甲",
                "category": "玄幻",
                "work_url": "https://www.qidian.com/book/900000001/",
                "public_metrics": {"weeklyRecommendations": 321},
            },
        ),
    }


def _payload(text: str = "当前穿越题材热度较高。") -> dict:
    evidence = {
        "text": text,
        "snapshotIds": [SNAPSHOT_A],
        "inference": False,
    }
    prediction = {
        "text": "穿越与群像经营的组合可能有增长空间。",
        "snapshotIds": [SNAPSHOT_A, SNAPSHOT_B],
        "inference": True,
    }
    return {
        "currentHeat": [evidence],
        "growthDirections": [prediction],
        "crowding": [evidence],
        "opportunities": [prediction],
        "uncertainties": [evidence],
        "sourceCoverage": {
            "snapshotIds": [SNAPSHOT_A, SNAPSHOT_B],
            "summary": "覆盖两份冻结快照。",
        },
    }


class FakeRepository:
    def __init__(self):
        self.rows = {}
        self.events = []
        self.input_manifest_matches = True

    async def lock_analysis_project(self, _session, project_id):
        self.events.append(("lock-project", project_id))
        return {"id": project_id, "archived_at": None}

    async def lock_analysis_by_key(self, _session, project_id, key):
        self.events.append(("lock-key", project_id, key))
        for row in self.rows.values():
            if row["project_id"] == project_id and row["idempotency_key"] == key:
                return row
        return None

    async def lock_analysis_inputs(self, _session, project_id, snapshot_ids):
        self.events.append(("lock-inputs", project_id, tuple(snapshot_ids)))
        return {
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
                "supports_json": 1,
                "temperature": 0.2,
                "max_output_tokens": 2400,
            },
            "snapshots": (
                _snapshot(SNAPSHOT_A, "a" * 64, "b" * 64),
                _snapshot(SNAPSHOT_B, "c" * 64, "e" * 64),
            ),
        }

    async def insert_analysis(self, _session, row):
        self.events.append(("insert", row["id"]))
        self.rows[row["id"]] = dict(row)

    async def read_analysis(self, _session, project_id, analysis_id):
        row = self.rows.get(analysis_id)
        if row is None or row["project_id"] != project_id:
            return None
        return row

    async def publish_analysis(self, _session, **values):
        self.events.append(("publish", values["analysis_id"]))
        row = self.rows[values["analysis_id"]]
        if not self.input_manifest_matches:
            row.update(
                status="failed",
                analysis_json=None,
                result_hash=None,
                public_error_code="MARKET_ANALYSIS_INPUT_CHANGED",
                completed_at=values["completed_at"],
            )
            return False
        row.update(
            status="succeeded",
            analysis_json=values["analysis_json"],
            result_hash=values["result_hash"],
            public_error_code=None,
            completed_at=values["completed_at"],
        )
        return True

    async def fail_analysis(self, _session, **values):
        self.events.append(("fail", values["public_error_code"]))
        self.rows[values["analysis_id"]].update(
            status="failed",
            analysis_json=None,
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


class FakeGateway:
    def __init__(self, probe, response):
        self.probe = probe
        self.response = response
        self.calls = 0

    async def generate(self, **_values):
        assert self.probe.active is False
        self.calls += 1
        if isinstance(self.response, BaseException):
            raise self.response
        return json.dumps(self.response, ensure_ascii=False)


def _service(response):
    _, module, _ = _feature()
    repository = FakeRepository()
    probe = TransactionProbe()
    gateway = FakeGateway(probe, response)
    ids = iter((ANALYSIS_ID,))
    service = module.MarketAnalysisService(
        repository,
        transaction_factory=probe.factory,
        connection_factory=probe.factory,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=lambda: NOW,
    )
    return service, repository, gateway


@pytest.mark.asyncio
async def test_service_freezes_inputs_calls_provider_outside_transaction_and_replays():
    domain, module, _ = _feature()
    service, repository, gateway = _service(_payload())
    command = module.AnalyzeMarket(
        project_id=PROJECT_ID,
        snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
        idempotency_key="i" * 64,
    )

    first = await service.analyze(command)
    replay = await service.analyze(command)

    assert first.status == "succeeded"
    assert replay == first
    assert gateway.calls == 1
    stored = repository.rows[ANALYSIS_ID]
    manifest = json.loads(stored["input_manifest_json"])
    assert [item["id"] for item in manifest["snapshots"]] == [
        SNAPSHOT_A,
        SNAPSHOT_B,
    ]
    assert manifest["binding"] == {
        "revisionId": "00000000-0000-0000-0000-000000000401",
        "hash": "d" * 64,
    }
    assert manifest["promptPolicyVersion"] == domain.MARKET_ANALYSIS_POLICY_VERSION
    assert len(stored["input_manifest_hash"]) == 64
    assert len(stored["request_hash"]) == 64
    assert stored["idempotency_key"] == "i" * 64
    assert "PRIVATE_PROVIDER_KEY" not in stored["input_manifest_json"]
    assert "private.provider.invalid" not in stored["input_manifest_json"]
    assert repository.events[0] == ("lock-project", PROJECT_ID)


@pytest.mark.asyncio
async def test_service_fails_without_synthetic_analysis_or_raw_response_persistence():
    _, module, gateway_module = _feature()
    error = gateway_module.MarketAnalysisProviderHTTPError(
        "provider request failed"
    )
    service, repository, gateway = _service(error)
    result = await service.analyze(
        module.AnalyzeMarket(
            project_id=PROJECT_ID,
            snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
            idempotency_key="f" * 64,
        )
    )

    assert gateway.calls == 1
    assert result.status == "failed"
    assert result.analysis is None
    assert result.public_error_code == "MARKET_ANALYSIS_PROVIDER_FAILED"
    row = repository.rows[ANALYSIS_ID]
    assert row["analysis_json"] is None
    assert row["result_hash"] is None
    assert "raw" not in row
    assert "response" not in row


@pytest.mark.asyncio
async def test_service_rejects_secret_raw_copy_and_manifest_race():
    _, module, _ = _feature()
    service, repository, _ = _service(
        _payload("泄漏 PRIVATE_PROVIDER_KEY")
    )
    rejected = await service.analyze(
        module.AnalyzeMarket(
            project_id=PROJECT_ID,
            snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
            idempotency_key="s" * 64,
        )
    )
    assert rejected.status == "failed"
    assert rejected.public_error_code == "MARKET_ANALYSIS_INVALID_RESPONSE"

    long_source = "原始榜单复制片段" * 20
    service, repository, _ = _service(_payload(long_source))
    repository_rows = await repository.lock_analysis_inputs(
        None, PROJECT_ID, (SNAPSHOT_A, SNAPSHOT_B)
    )
    repository_rows["snapshots"][0]["entries"][0]["public_metrics"][
        "publicNote"
    ] = long_source
    original = repository.lock_analysis_inputs

    async def raw_copy_inputs(*args):
        await original(*args)
        return repository_rows

    repository.lock_analysis_inputs = raw_copy_inputs
    rejected = await service.analyze(
        module.AnalyzeMarket(
            project_id=PROJECT_ID,
            snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
            idempotency_key="r" * 64,
        )
    )
    assert rejected.status == "failed"
    assert rejected.public_error_code == "MARKET_ANALYSIS_INVALID_RESPONSE"

    service, repository, _ = _service(_payload())
    repository.input_manifest_matches = False
    raced = await service.analyze(
        module.AnalyzeMarket(
            project_id=PROJECT_ID,
            snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
            idempotency_key="m" * 64,
        )
    )
    assert raced.status == "failed"
    assert raced.analysis is None
    assert raced.public_error_code == "MARKET_ANALYSIS_INPUT_CHANGED"


@pytest.mark.asyncio
async def test_same_key_different_order_conflicts_before_second_provider_call():
    domain, module, _ = _feature()
    service, _, gateway = _service(_payload())
    await service.analyze(
        module.AnalyzeMarket(
            project_id=PROJECT_ID,
            snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
            idempotency_key="c" * 64,
        )
    )
    with pytest.raises(domain.MarketAnalysisFailure) as caught:
        await service.analyze(
            module.AnalyzeMarket(
                project_id=PROJECT_ID,
                snapshot_ids=(SNAPSHOT_B, SNAPSHOT_A),
                idempotency_key="c" * 64,
            )
        )
    assert caught.value.code == "MARKET_ANALYSIS_IDEMPOTENCY_CONFLICT"
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_provider_cancellation_terminalizes_attempt_and_replay_never_recalls():
    _, module, _ = _feature()
    service, repository, gateway = _service(asyncio.CancelledError())
    command = module.AnalyzeMarket(
        project_id=PROJECT_ID,
        snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
        idempotency_key="z" * 64,
    )

    with pytest.raises(asyncio.CancelledError):
        await service.analyze(command)
    replay = await service.analyze(command)

    assert replay.status == "failed"
    assert replay.analysis is None
    assert replay.public_error_code == "MARKET_ANALYSIS_CANCELLED"
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_interrupt_terminal_persistence():
    _, module, _ = _feature()

    class BlockingFailureRepository(FakeRepository):
        def __init__(self):
            super().__init__()
            self.failure_started = asyncio.Event()
            self.release_failure = asyncio.Event()

        async def fail_analysis(self, session, **values):
            self.failure_started.set()
            await self.release_failure.wait()
            return await super().fail_analysis(session, **values)

    repository = BlockingFailureRepository()
    probe = TransactionProbe()
    gateway = FakeGateway(probe, asyncio.CancelledError())
    service = module.MarketAnalysisService(
        repository,
        transaction_factory=probe.factory,
        connection_factory=probe.factory,
        provider_gateway=gateway,
        id_factory=lambda: ANALYSIS_ID,
        clock=lambda: NOW,
    )
    command = module.AnalyzeMarket(
        project_id=PROJECT_ID,
        snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
        idempotency_key="y" * 64,
    )
    task = asyncio.create_task(service.analyze(command))
    try:
        await asyncio.wait_for(repository.failure_started.wait(), timeout=1)
        task.cancel()
        task.cancel()
        await asyncio.sleep(0)
        assert task.done() is False
        repository.release_failure.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        repository.release_failure.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    row = repository.rows[ANALYSIS_ID]
    assert row["status"] == "failed"
    assert row["public_error_code"] == "MARKET_ANALYSIS_CANCELLED"


@pytest.mark.asyncio
async def test_cancellation_during_publication_also_terminalizes_attempt():
    _, module, _ = _feature()

    class BlockingPublishRepository(FakeRepository):
        def __init__(self):
            super().__init__()
            self.publish_started = asyncio.Event()
            self.release_publish = asyncio.Event()

        async def publish_analysis(self, session, **values):
            self.publish_started.set()
            await self.release_publish.wait()
            return await super().publish_analysis(session, **values)

    repository = BlockingPublishRepository()
    probe = TransactionProbe()
    gateway = FakeGateway(probe, _payload())
    service = module.MarketAnalysisService(
        repository,
        transaction_factory=probe.factory,
        connection_factory=probe.factory,
        provider_gateway=gateway,
        id_factory=lambda: ANALYSIS_ID,
        clock=lambda: NOW,
    )
    command = module.AnalyzeMarket(
        project_id=PROJECT_ID,
        snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
        idempotency_key="p" * 64,
    )
    task = asyncio.create_task(service.analyze(command))
    try:
        await repository.publish_started.wait()
        task.cancel()
        repository.release_publish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        repository.release_publish.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    row = repository.rows[ANALYSIS_ID]
    assert row["status"] == "failed"
    assert row["public_error_code"] == "MARKET_ANALYSIS_CANCELLED"
