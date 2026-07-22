from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

import pytest

from backend.domain.asset_eligibility import load_asset_eligibility_package
from backend.domain.assets import load_asset_package
from backend.domain.json_contracts import canonical_hash
from backend.domain.seeds import SeedPayload


ASSET_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "assets" / "writer-core-v1.1.0" / "manifest.json"
)
TAXONOMY_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "assets" / "recommendation-taxonomy-v1.0.0" / "manifest.json"
)
NOW = 1_780_000_000_000
REQUEST_ID = "00000000-0000-0000-0000-000000000001"
ATTEMPT_ID = "00000000-0000-0000-0000-000000000002"


def test_asset_recommendation_in_progress_has_a_safe_explicit_409_contract():
    import backend.http_errors as errors

    assert hasattr(errors, "AssetRecommendationInProgress")
    error = errors.AssetRecommendationInProgress()
    assert error.status_code == 409
    assert error.code == "AssetRecommendationInProgress"
    assert "provider" not in error.message.casefold()


def _seed():
    return SeedPayload(
        title="典镇山河",
        genre="历史",
        logline="现代修复师在边城推动制度试行。",
        protagonist="谨慎的典籍修复师",
        desire="让边城形成可持续秩序",
        coreConflict="旧权力阻挠改革",
        worldPressure="资源与战争压力",
        openingHook="残卷解决水患",
        differentiation="制度必须反复验证",
    )


def _engine():
    return {
        "name": "残卷筑城",
        "storyPromise": "共同守城",
        "protagonistDesire": "建立长期秩序",
        "sustainedPressure": "战争与资源压力",
        "growthDirection": "组织群像协作",
        "conflictLoop": "试行、承担后果、再修正",
        "ensembleRoles": [{"role": "工匠", "purpose": "验证技术"}],
        "advantageAndCost": "知识需要试错",
        "satisfactionSources": ["建设成果"],
        "longFormVariation": ["水利", "商路"],
        "endingAnchor": "守住新秩序",
        "risks": ["写成说明书"],
        "differentiation": "长期因果跨章保留",
    }


def _asset_row(asset, revision_id, asset_type):
    return {
        "id": revision_id,
        "stable_key": asset.stable_key,
        "revision": asset.revision,
        "label": asset.name if asset_type == "style" else asset.title,
        "category": None if asset_type == "style" else asset.category,
        "payload_json": asset.payload.model_dump(mode="json"),
        "provenance_json": asset.provenance.model_dump(mode="json"),
        "content_hash": asset.content_hash,
        "status": "active",
    }


class TransactionProbe:
    def __init__(self):
        self.active = 0
        self.entries = 0

    @asynccontextmanager
    async def transaction(self):
        self.active += 1
        self.entries += 1
        try:
            yield "transaction"
        finally:
            self.active -= 1

    @asynccontextmanager
    async def connection(self):
        yield "connection"


class PublishCommitCancellationProbe(TransactionProbe):
    def __init__(self, repository, *, rollback):
        super().__init__()
        self.repository = repository
        self.rollback = rollback

    @asynccontextmanager
    async def transaction(self):
        self.active += 1
        self.entries += 1
        entry = self.entries
        requests_before = deepcopy(self.repository.requests)
        attempts_before = deepcopy(self.repository.attempts)
        try:
            yield "transaction"
            if entry == 3:
                if self.rollback:
                    self.repository.requests = requests_before
                    self.repository.attempts = attempts_before
                raise asyncio.CancelledError()
        finally:
            self.active -= 1


class FakeRepository:
    def __init__(self, package):
        seed = _seed()
        engine = _engine()
        self.requests = {}
        self.attempts = {}
        self.project = {"id": "project-1", "archived_at": None}
        self.inputs = {
            "selected": {
                "selection_revision": 3,
                "seed_id": "seed-1",
                "seed_revision_id": "seed-revision-1",
                "seed_hash": canonical_hash(seed),
                "revision_hash": canonical_hash(seed),
                "payload_json": seed.model_dump(mode="json"),
            },
            "engine": {
                "id": "engine-1",
                "project_id": "project-1",
                "batch_status": "succeeded",
                "selection_revision": 3,
                "seed_id": "seed-1",
                "seed_revision_id": "seed-revision-1",
                "seed_hash": canonical_hash(seed),
                "content_hash": canonical_hash(engine),
                "payload_json": engine,
            },
            "draft": None,
            "binding_revision_id": "binding-revision-1",
            "binding_hash": "b" * 64,
            "resolution_status": "bound",
            "provider_id": "provider-1",
            "model_name_snapshot": "ranker-model",
            "provider": {
                "id": "provider-1",
                "provider_type": "openai-compatible",
                "model_name": "ranker-model",
                "base_url": "https://private-provider.example/v1",
                "api_key": "PRIVATE_API_KEY_123456789",
                "enabled": 1,
                "lifecycle_status": "active",
                "revision": 7,
                "temperature": 0.2,
                "max_output_tokens": 800,
            },
            "styles": tuple(
                _asset_row(asset, f"style-{index}", "style")
                for index, asset in enumerate(package.styles, 1)
            ),
            "cards": tuple(
                _asset_row(asset, f"card-{index}", "card")
                for index, asset in enumerate(package.experience_cards, 1)
            ),
        }

    async def lock_recommendation_project(self, session, project_id):
        return deepcopy(self.project) if project_id == "project-1" else None

    async def lock_recommendation_request(self, session, project_id, key):
        return deepcopy(self.requests.get((project_id, key)))

    async def lock_recommendation_inputs(self, session, project_id, engine_id):
        return deepcopy(self.inputs)

    async def insert_recommendation_request(self, session, row):
        self.requests[(row["project_id"], row["idempotency_key"])] = deepcopy(row)

    async def insert_recommendation_attempt(self, session, row):
        self.attempts[row["id"]] = deepcopy(row)

    async def insert_failed_recommendation_request(self, session, row):
        self.requests[(row["project_id"], row["idempotency_key"])] = deepcopy(row)

    async def fail_recommendation(self, session, **values):
        attempt = self.attempts[values["attempt_id"]]
        attempt.update({
            "status": "failed", "result_json": None, "result_hash": None,
            "public_error_code": values["public_error_code"],
            "completed_at": values["completed_at"],
        })
        request = self.requests[(values["project_id"], values["idempotency_key"])]
        request.update({
            "status": "failed", "attempt_id": values["attempt_id"],
            "public_error_code": values["public_error_code"],
            "completed_at": values["completed_at"],
        })

    async def mark_recommendation_outcome_unknown(self, session, **values):
        attempt = self.attempts[values["attempt_id"]]
        attempt.update({
            "status": "outcome_unknown",
            "result_json": None,
            "result_hash": None,
            "public_error_code": values["public_error_code"],
            "completed_at": values["completed_at"],
        })
        request = self.requests[(values["project_id"], values["idempotency_key"])]
        request.update({
            "status": "outcome_unknown",
            "result_hash": None,
            "public_error_code": values["public_error_code"],
            "completed_at": values["completed_at"],
        })

    async def cleanup_cancelled_recommendation(self, session, **values):
        request = self.requests.get((
            values["project_id"], values["idempotency_key"]
        ))
        if request is None or request["request_hash"] != values["request_hash"]:
            raise RuntimeError("asset recommendation cancellation state is missing")
        attempt = self.attempts.get(request["attempt_id"])
        if attempt is None:
            raise RuntimeError("asset recommendation cancellation attempt is missing")
        if request["status"] in {"succeeded", "failed", "outcome_unknown"}:
            if attempt["status"] != request["status"]:
                raise RuntimeError("asset recommendation cancellation state diverged")
            return False
        if request["status"] != "running" or attempt["status"] != "running":
            raise RuntimeError("asset recommendation cancellation state diverged")
        await self.mark_recommendation_outcome_unknown(
            session,
            project_id=values["project_id"],
            idempotency_key=values["idempotency_key"],
            attempt_id=request["attempt_id"],
            public_error_code=values["public_error_code"],
            completed_at=values["completed_at"],
        )
        return True

    async def publish_recommendation(self, session, **values):
        attempt = self.attempts[values["attempt_id"]]
        attempt.update({
            "status": "succeeded",
            "result_json": values["result_json"],
            "result_hash": values["result_hash"],
            "completed_at": values["completed_at"],
        })
        request = self.requests[(values["project_id"], values["idempotency_key"])]
        request.update({
            "status": "succeeded", "attempt_id": values["attempt_id"],
            "result_hash": values["result_hash"],
            "completed_at": values["completed_at"],
        })
        return True

    async def read_recommendation_attempt(self, session, project_id, attempt_id):
        return deepcopy(self.attempts.get(attempt_id))


class FakeCorpusService:
    def __init__(self, transactions):
        self.transactions = transactions
        self.calls = 0

    async def candidates(self, query_texts):
        from backend.domain.corpus_recommendations import CorpusCandidate

        assert self.transactions.active == 0
        assert query_texts
        self.calls += 1
        return (CorpusCandidate(
            source_id="source-1",
            source_revision_id="source-revision-1",
            source_revision=2,
            source_hash="c" * 64,
            chapter_id="chapter-1",
            fragment_id="fragment-1",
            fragment_hash="d" * 64,
            window_start=100,
            window_end=110,
            excerpt="边城制度反复修正",
        ),)


class FakeGateway:
    def __init__(self, transactions, response):
        self.transactions = transactions
        self.response = response
        self.calls = 0

    async def rank(self, **kwargs):
        assert self.transactions.active == 0
        self.calls += 1
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def _command(taxonomy, **updates):
    from backend.services.assets import GenerateAssetRecommendations

    values = {
        "project_id": "project-1",
        "engine_option_id": "engine-1",
        "idempotency_key": "i" * 64,
        "taxonomy_version": taxonomy.package_version,
        "taxonomy_hash": taxonomy.manifest.eligibility_file.sha256,
        "genre": "historical",
        "creation_stage": "drafting",
        "status": "active",
        "prohibited_directions": (),
    }
    values.update(updates)
    return GenerateAssetRecommendations(**values)


def _harness(response=None):
    from backend.domain.asset_recommendations import ProviderRankingOutput
    from backend.services.assets import AssetRecommendationService

    package = load_asset_package(ASSET_MANIFEST, mode="release")
    taxonomy = load_asset_eligibility_package(
        TAXONOMY_MANIFEST, asset_package=package, mode="release"
    )
    repository = FakeRepository(package)
    transactions = TransactionProbe()
    gateway = FakeGateway(
        transactions,
        response if response is not None else ProviderRankingOutput(
            assetRecommendations=({
                "assetRevisionId": "style-1",
                "reason": "契合当前叙事距离",
                "confidence": 0.91,
            },),
            corpusRecommendations=({
                "fragmentId": "fragment-1",
                "rangeStart": 100,
                "rangeEnd": 104,
                "use": "作为制度试行参照",
                "reason": "与当前冲突直接相关",
                "confidence": 0.88,
            },),
        ),
    )
    ids = iter((REQUEST_ID, ATTEMPT_ID))
    service = AssetRecommendationService(
        repository,
        transaction_factory=transactions.transaction,
        connection_factory=transactions.connection,
        provider_gateway=gateway,
        corpus_service=FakeCorpusService(transactions),
        taxonomy=taxonomy,
        id_factory=lambda: next(ids),
        clock=lambda: NOW,
    )
    return service, repository, gateway, transactions, taxonomy


def test_corpus_query_is_bounded_to_domain_input_contract():
    from backend.services.assets import AssetRecommendationService

    engine = {
        f"field-{index}": [f"value-{index}-{nested}" * 500 for nested in range(10)]
        for index in range(30)
    }

    query = AssetRecommendationService._query_texts(_seed(), engine)

    assert 1 <= len(query) <= 20
    assert all(len(value) <= 2_000 for value in query)
    assert sum(map(len, query)) <= 40_000


@pytest.mark.asyncio
async def test_success_calls_provider_once_outside_transaction_and_replay_is_stable():
    service, repository, gateway, _, taxonomy = _harness()
    command = _command(taxonomy)

    result = await service.recommend(command)
    replay = await service.recommend(command)

    assert gateway.calls == 1
    assert result == replay
    assert result.public_reason == "recommendationsAvailable"
    assert result.ranking_unavailable is False
    assert result.full_browse_available is True
    assert len(result.asset_recommendations) == 1
    assert result.asset_recommendations[0].asset_revision_id == "style-1"
    assert len(result.corpus_recommendations) == 1
    assert result.corpus_recommendations[0].source_revision == 2
    assert result.corpus_recommendations[0].range_start == 100
    assert result.input_manifest_hash == canonical_hash(result.input_manifest)
    assert result.input_manifest["provider"] == {
        "providerId": "provider-1",
        "modelName": "ranker-model",
        "providerProfileRevision": 7,
        "providerType": "openai-compatible",
    }
    assert not {
        "apiKey", "baseUrl", "api_key", "base_url", "secret"
    }.intersection(result.input_manifest["provider"])
    stored = json.dumps(repository.attempts[ATTEMPT_ID], ensure_ascii=False)
    assert not any(secret in stored for secret in (
        "PRIVATE_API_KEY", "private-provider.example", "边城制度反复修正"
    ))


def _put_running_recommendation(repository, *, created_at):
    key = ("project-1", "i" * 64)
    repository.requests[key] = {
        "id": REQUEST_ID,
        "project_id": "project-1",
        "idempotency_key": "i" * 64,
        "request_hash": None,
        "status": "running",
        "attempt_id": ATTEMPT_ID,
        "result_hash": None,
        "public_error_code": None,
        "created_at": created_at,
        "completed_at": None,
    }
    repository.attempts[ATTEMPT_ID] = {
        "id": ATTEMPT_ID,
        "project_id": "project-1",
        "status": "running",
        "result_json": None,
        "result_hash": None,
        "public_error_code": None,
        "created_at": created_at,
        "completed_at": None,
    }
    return key


@pytest.mark.asyncio
async def test_non_stale_running_replay_returns_explicit_in_progress_409():
    from backend.http_errors import AssetRecommendationInProgress

    service, repository, gateway, _, taxonomy = _harness()
    command = _command(taxonomy)
    key = _put_running_recommendation(repository, created_at=NOW - 239_999)
    repository.requests[key]["request_hash"] = service._request_hash(command)

    with pytest.raises(AssetRecommendationInProgress):
        await service.recommend(command)

    assert repository.requests[key]["status"] == "running"
    assert repository.attempts[ATTEMPT_ID]["status"] == "running"
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_stale_running_replay_terminalizes_outcome_unknown_at_240_seconds():
    service, repository, gateway, _, taxonomy = _harness()
    command = _command(taxonomy)
    key = _put_running_recommendation(repository, created_at=NOW - 240_000)
    repository.requests[key]["request_hash"] = service._request_hash(command)

    result = await service.recommend(command)
    replay = await service.recommend(command)

    assert result == replay
    assert result.public_reason == "rankingUnavailable"
    assert repository.requests[key]["status"] == "outcome_unknown"
    assert repository.attempts[ATTEMPT_ID]["status"] == "outcome_unknown"
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_provider_observes_atomically_linked_running_request_and_attempt():
    service, repository, gateway, _, taxonomy = _harness()
    original_rank = gateway.rank

    async def inspect_reservation(**kwargs):
        request = repository.requests[("project-1", "i" * 64)]
        assert request["status"] == "running"
        assert request["attempt_id"] == ATTEMPT_ID
        assert repository.attempts[ATTEMPT_ID]["status"] == "running"
        return await original_rank(**kwargs)

    gateway.rank = inspect_reservation

    result = await service.recommend(_command(taxonomy))

    assert result.public_reason == "recommendationsAvailable"


@pytest.mark.asyncio
async def test_same_key_concurrency_reserves_one_attempt_and_calls_provider_once():
    from backend.http_errors import AssetRecommendationInProgress

    service, _, gateway, _, taxonomy = _harness()
    command = _command(taxonomy)
    started = asyncio.Event()
    release = asyncio.Event()
    original_response = gateway.response

    async def blocking_rank(**_kwargs):
        gateway.calls += 1
        started.set()
        await release.wait()
        return original_response

    gateway.rank = blocking_rank
    first = asyncio.create_task(service.recommend(command))
    await started.wait()

    try:
        with pytest.raises(AssetRecommendationInProgress):
            await service.recommend(command)
    finally:
        release.set()
        result = await first
    assert result.public_reason == "recommendationsAvailable"
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_provider_cancellation_marks_linked_attempt_outcome_unknown():
    service, repository, gateway, _, taxonomy = _harness()

    async def cancelled(**_kwargs):
        gateway.calls += 1
        raise asyncio.CancelledError()

    gateway.rank = cancelled

    with pytest.raises(asyncio.CancelledError):
        await service.recommend(_command(taxonomy))

    request = repository.requests[("project-1", "i" * 64)]
    assert request["status"] == "outcome_unknown"
    assert request["attempt_id"] == ATTEMPT_ID
    assert repository.attempts[ATTEMPT_ID]["status"] == "outcome_unknown"


def _replace_transactions(service, gateway, probe):
    service._transaction = probe.transaction
    gateway.transactions = probe
    service._corpus.transactions = probe


@pytest.mark.asyncio
async def test_publish_body_cancellation_marks_running_ledgers_outcome_unknown():
    service, repository, gateway, _, taxonomy = _harness()

    async def cancelled_publish(_session, **_values):
        raise asyncio.CancelledError()

    repository.publish_recommendation = cancelled_publish

    with pytest.raises(asyncio.CancelledError):
        await service.recommend(_command(taxonomy))

    request = repository.requests[("project-1", "i" * 64)]
    assert request["status"] == "outcome_unknown"
    assert repository.attempts[ATTEMPT_ID]["status"] == "outcome_unknown"
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_publish_commit_cancellation_after_rollback_marks_outcome_unknown():
    service, repository, gateway, _, taxonomy = _harness()
    transactions = PublishCommitCancellationProbe(repository, rollback=True)
    _replace_transactions(service, gateway, transactions)

    with pytest.raises(asyncio.CancelledError):
        await service.recommend(_command(taxonomy))

    request = repository.requests[("project-1", "i" * 64)]
    assert request["status"] == "outcome_unknown"
    assert repository.attempts[ATTEMPT_ID]["status"] == "outcome_unknown"
    assert transactions.entries == 4
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_post_commit_cancellation_preserves_succeeded_terminal_state():
    service, repository, gateway, _, taxonomy = _harness()
    transactions = PublishCommitCancellationProbe(repository, rollback=False)
    _replace_transactions(service, gateway, transactions)
    cleanup_calls = 0
    original_cleanup = repository.cleanup_cancelled_recommendation

    async def recording_cleanup(session, **values):
        nonlocal cleanup_calls
        cleanup_calls += 1
        return await original_cleanup(session, **values)

    repository.cleanup_cancelled_recommendation = recording_cleanup
    command = _command(taxonomy)

    with pytest.raises(asyncio.CancelledError):
        await service.recommend(command)
    replay = await service.recommend(command)

    request = repository.requests[("project-1", "i" * 64)]
    assert request["status"] == "succeeded"
    assert repository.attempts[ATTEMPT_ID]["status"] == "succeeded"
    assert replay.public_reason == "recommendationsAvailable"
    assert cleanup_calls == 1
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_independent_cleanup_to_finish():
    service, repository, gateway, _, taxonomy = _harness()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    original_cleanup = repository.cleanup_cancelled_recommendation

    async def cancelled_publish(_session, **_values):
        raise asyncio.CancelledError()

    async def delayed_cleanup(session, **values):
        cleanup_started.set()
        await release_cleanup.wait()
        return await original_cleanup(session, **values)

    repository.publish_recommendation = cancelled_publish
    repository.cleanup_cancelled_recommendation = delayed_cleanup
    task = asyncio.create_task(service.recommend(_command(taxonomy)))
    try:
        await asyncio.wait_for(cleanup_started.wait(), timeout=1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release_cleanup.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    request = repository.requests[("project-1", "i" * 64)]
    assert request["status"] == "outcome_unknown"
    assert repository.attempts[ATTEMPT_ID]["status"] == "outcome_unknown"
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_cancellation_cleanup_failure_preserves_both_errors():
    service, repository, gateway, _, taxonomy = _harness()

    async def cancelled_publish(_session, **_values):
        raise asyncio.CancelledError("publish cancelled")

    async def failed_cleanup(_session, **_values):
        raise RuntimeError("cleanup database failed")

    repository.publish_recommendation = cancelled_publish
    repository.cleanup_cancelled_recommendation = failed_cleanup

    with pytest.raises(BaseExceptionGroup) as captured:
        await service.recommend(_command(taxonomy))

    assert any(
        isinstance(error, asyncio.CancelledError)
        for error in captured.value.exceptions
    )
    assert any(
        isinstance(error, RuntimeError)
        and str(error) == "cleanup database failed"
        for error in captured.value.exceptions
    )
    assert gateway.calls == 1


@pytest.mark.parametrize("drift", ("selection", "binding", "asset"))
@pytest.mark.asyncio
async def test_reservation_rejects_input_drift_during_unlocked_corpus_scan(drift):
    from backend.http_errors import AssetRecommendationConflict

    service, repository, gateway, transactions, taxonomy = _harness()
    original_corpus = service._corpus

    class DriftingCorpus:
        async def candidates(self, query_texts):
            candidates = await original_corpus.candidates(query_texts)
            if drift == "selection":
                repository.inputs["selected"]["selection_revision"] += 1
            elif drift == "binding":
                repository.inputs["binding_hash"] = "7" * 64
            else:
                repository.inputs["styles"][0]["content_hash"] = "7" * 64
            return candidates

    service._corpus = DriftingCorpus()

    with pytest.raises(AssetRecommendationConflict):
        await service.recommend(_command(taxonomy))

    assert transactions.active == 0
    assert repository.requests == {}
    assert repository.attempts == {}
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_frozen_manifest_identifies_selected_styles_by_revision_and_hash():
    service, repository, _, _, taxonomy = _harness()
    selected = repository.inputs["styles"][0]
    repository.inputs["draft"] = {
        "draft_json": {
            "primaryStyleRef": {
                "id": selected["id"],
                "revision": selected["revision"],
                "contentHash": selected["content_hash"],
            },
            "secondaryStyleRef": None,
        }
    }

    result = await service.recommend(_command(taxonomy))

    assert result.input_manifest["selectedStyles"] == [{
        "role": "primary",
        "id": selected["id"],
        "revision": selected["revision"],
        "hash": selected["content_hash"],
    }]


@pytest.mark.asyncio
async def test_no_eligible_candidates_returns_empty_without_provider_call():
    service, repository, gateway, transactions, taxonomy = _harness()
    service._corpus = type(
        "EmptyCorpusService",
        (),
        {"candidates": lambda _self, _query: _empty_candidates()},
    )()

    result = await service.recommend(_command(taxonomy, status="archived"))

    assert result.public_reason == "noEligibleCandidates"
    assert result.asset_recommendations == result.corpus_recommendations == ()
    assert result.full_browse_available is True
    assert gateway.calls == 0
    assert repository.requests[("project-1", "i" * 64)]["attempt_id"] is None
    assert repository.requests[("project-1", "i" * 64)]["status"] == "failed"
    assert transactions.entries == 2


async def _empty_candidates():
    return ()


@pytest.mark.asyncio
async def test_unready_seed_binding_returns_ranking_unavailable_without_provider_call():
    service, repository, gateway, transactions, taxonomy = _harness()
    repository.inputs.update({
        "resolution_status": "unbound",
        "provider_id": None,
        "model_name_snapshot": None,
        "provider": None,
    })

    result = await service.recommend(_command(taxonomy))

    assert result.public_reason == "rankingUnavailable"
    assert result.ranking_unavailable is True
    assert result.full_browse_available is True
    assert gateway.calls == 0
    assert service._corpus.calls == 0
    assert repository.requests[("project-1", "i" * 64)]["status"] == "failed"
    assert transactions.entries == 1


@pytest.mark.asyncio
async def test_disabled_mysql_provider_decimal_returns_without_gateway_call():
    service, repository, gateway, transactions, taxonomy = _harness()
    command = _command(taxonomy)
    repository.inputs["provider"].update({
        "enabled": 0,
        "temperature": Decimal("0.700"),
    })
    decimal_prepared = service._prepared_inputs(command, repository.inputs)
    float_inputs = deepcopy(repository.inputs)
    float_inputs["provider"]["temperature"] = 0.7
    float_prepared = service._prepared_inputs(command, float_inputs)

    assert service._reservation_fingerprint(decimal_prepared) == (
        service._reservation_fingerprint(float_prepared)
    )

    result = await service.recommend(command)

    assert result.public_reason == "rankingUnavailable"
    assert result.ranking_unavailable is True
    assert gateway.calls == 0
    assert service._corpus.calls == 0
    assert repository.requests[("project-1", "i" * 64)]["status"] == "failed"
    assert repository.attempts == {}
    assert transactions.entries == 1


@pytest.mark.parametrize("failure", ("low", "unknown", "provider"))
@pytest.mark.asyncio
async def test_low_confidence_invalid_reference_and_provider_failure_share_safe_empty_reason(
    failure,
):
    from backend.domain.asset_recommendations import ProviderRankingOutput
    from backend.gateways.asset_recommendation_provider import (
        AssetRecommendationProviderError,
    )

    if failure == "provider":
        response = AssetRecommendationProviderError("PRIVATE_PROVIDER_DETAIL")
    else:
        response = ProviderRankingOutput(
            assetRecommendations=({
                "assetRevisionId": "unknown" if failure == "unknown" else "style-1",
                "reason": "short",
                "confidence": 0.2 if failure == "low" else 0.9,
            },),
            corpusRecommendations=(),
        )
    service, repository, gateway, _, taxonomy = _harness(response)

    result = await service.recommend(_command(taxonomy))

    assert result.public_reason == "rankingUnavailable"
    assert result.ranking_unavailable is True
    assert result.asset_recommendations == result.corpus_recommendations == ()
    assert result.input_manifest is None
    assert repository.attempts[ATTEMPT_ID]["result_json"] is None
    assert repository.requests[("project-1", "i" * 64)][
        "attempt_id"
    ] == ATTEMPT_ID
    assert "PRIVATE_PROVIDER_DETAIL" not in json.dumps(repository.attempts)
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_publication_drift_returns_ranking_unavailable_and_keeps_failed_attempt():
    service, repository, gateway, _, taxonomy = _harness()

    async def reject_publication(session, **values):
        await repository.fail_recommendation(
            session,
            project_id=values["project_id"],
            idempotency_key=values["idempotency_key"],
            attempt_id=values["attempt_id"],
            public_error_code="ASSET_RECOMMENDATION_UNAVAILABLE",
            completed_at=values["completed_at"],
        )
        return False

    repository.publish_recommendation = reject_publication

    result = await service.recommend(_command(taxonomy))

    request = repository.requests[("project-1", "i" * 64)]
    attempt = repository.attempts[ATTEMPT_ID]
    assert result.public_reason == "rankingUnavailable"
    assert result.ranking_unavailable is True
    assert result.asset_recommendations == result.corpus_recommendations == ()
    assert request["status"] == attempt["status"] == "failed"
    assert request["attempt_id"] == ATTEMPT_ID
    assert gateway.calls == 1


class RecordingRecommendationSession:
    def __init__(self, one=None, all_rows=None):
        self.one = list(one or ())
        self.all_rows = list(all_rows or ())
        self.calls = []

    async def fetchone(self, sql, params=None):
        self.calls.append(("one", sql, params))
        return self.one.pop(0) if self.one else None

    async def fetchall(self, sql, params=None):
        self.calls.append(("all", sql, params))
        return self.all_rows.pop(0) if self.all_rows else ()

    async def execute(self, sql, params=None):
        self.calls.append(("execute", sql, params))
        return 1


def _style_ref(style_id, revision, content_hash):
    return {"id": style_id, "revision": revision, "contentHash": content_hash}


def _publication_manifest(selected_styles):
    return {
        "selection": {
            "revision": 3,
            "seedRevisionId": "seed-revision-1",
            "hash": "a" * 64,
        },
        "engine": {"id": "engine-1", "hash": "e" * 64},
        "binding": {
            "revisionId": "binding-1",
            "hash": "b" * 64,
            "taskKey": "seed",
        },
        "provider": {
            "providerId": "provider-1",
            "modelName": "ranker-model",
            "providerProfileRevision": 7,
            "providerType": "openai-compatible",
        },
        "selectedStyles": selected_styles,
        "assetCandidates": [
            {"id": "style-1", "type": "style", "revision": 1, "hash": "c" * 64},
            {"id": "style-2", "type": "style", "revision": 1, "hash": "8" * 64},
            {
                "id": "card-1",
                "type": "experience_card",
                "revision": 1,
                "hash": "d" * 64,
            },
        ],
        "corpusCandidates": [{
            "sourceId": "source-1",
            "sourceRevisionId": "source-revision-1",
            "sourceRevision": 2,
            "sourceHash": "f" * 64,
            "chapterId": "chapter-1",
            "fragmentId": "fragment-1",
            "fragmentHash": "9" * 64,
            "windowStart": 100,
            "windowEnd": 110,
        }],
    }


def _publication_locked_rows(draft):
    return (
        {
            "selection_revision": 3,
            "seed_revision_id": "seed-revision-1",
            "seed_hash": "a" * 64,
        },
        {"binding_revision_id": "binding-1", "content_hash": "b" * 64},
        {
            "id": "engine-1",
            "content_hash": "e" * 64,
            "selection_revision": 3,
            "seed_revision_id": "seed-revision-1",
            "seed_hash": "a" * 64,
            "status": "succeeded",
        },
        {"draft_json": draft},
    )


def _publication_candidate_rows():
    return (
        (
            {"id": "style-1", "revision": 1, "content_hash": "c" * 64},
            {"id": "style-2", "revision": 1, "content_hash": "8" * 64},
        ),
        ({"id": "card-1", "revision": 1, "content_hash": "d" * 64},),
        ({
            "source_id": "source-1",
            "source_revision_id": "source-revision-1",
            "source_revision": 2,
            "source_hash": "f" * 64,
            "chapter_id": "chapter-1",
            "fragment_id": "fragment-1",
            "fragment_hash": "9" * 64,
            "chapter_char_start": 100,
            "chapter_char_end": 130,
        },),
    )


@pytest.mark.asyncio
async def test_repository_recommendation_inputs_bind_only_seed_task_and_current_heads():
    from backend.repositories.assets import AssetRepository

    binding = {
        "binding_revision_id": "binding-1", "binding_hash": "b" * 64,
        "resolution_status": "unbound", "provider_id": None,
        "model_name_snapshot": None, "current_provider_id": None,
        "provider_type": None, "model_name": None, "base_url": None,
        "api_key": None, "enabled": 0, "lifecycle_status": "unconfigured",
        "provider_profile_revision": 11,
        "temperature": 0.2, "max_output_tokens": 800,
    }
    session = RecordingRecommendationSession(
        one=(binding, {"selection_revision": 3}, {"id": "engine-1"}, None),
        all_rows=((), ()),
    )

    result = await AssetRepository().lock_recommendation_inputs(
        session, "project-1", "engine-1"
    )

    rendered = " ".join(
        sql.casefold() for _, sql, _ in session.calls
    )
    assert "item.task_key='seed'" in rendered
    assert "style_template_heads" in rendered
    assert "experience_card_heads" in rendered
    assert "provider_profiles" in rendered
    assert "provider.revision as provider_profile_revision" in " ".join(
        rendered.split()
    )
    assert " for update" in rendered
    assert result["resolution_status"] == "unbound"
    assert result["provider"]["api_key"] is None
    assert result["provider"]["revision"] == 11


@pytest.mark.asyncio
async def test_repository_publication_revalidates_frozen_asset_and_corpus_heads():
    from backend.repositories.assets import AssetRepository

    manifest = _publication_manifest([])
    session = RecordingRecommendationSession(
        one=_publication_locked_rows({
            "primaryStyleRef": None,
            "secondaryStyleRef": None,
        }),
        all_rows=_publication_candidate_rows(),
    )

    matches = await AssetRepository()._publication_inputs_match(
        session,
        {"project_id": "project-1", "input_manifest": manifest},
    )

    rendered = " ".join(sql.casefold() for _, sql, _ in session.calls)
    assert matches is True
    assert "style_template_heads" in rendered
    assert "experience_card_heads" in rendered
    assert "corpus_source_heads" in rendered
    assert "source.archived_at is null" in rendered
    assert "provider_profiles" not in rendered


_PRIMARY_STYLE = {
    "role": "primary",
    "id": "style-1",
    "revision": 1,
    "hash": "c" * 64,
}
_SECONDARY_STYLE = {
    "role": "secondary",
    "id": "style-2",
    "revision": 1,
    "hash": "8" * 64,
}


@pytest.mark.parametrize(
    ("selected_styles", "current_draft"),
    (
        (
            [],
            {
                "primaryStyleRef": _style_ref("style-1", 1, "c" * 64),
                "secondaryStyleRef": None,
            },
        ),
        (
            [_PRIMARY_STYLE, _SECONDARY_STYLE],
            {
                "primaryStyleRef": _style_ref("style-2", 1, "8" * 64),
                "secondaryStyleRef": _style_ref("style-1", 1, "c" * 64),
            },
        ),
        (
            [_PRIMARY_STYLE],
            {
                "primaryStyleRef": _style_ref("style-1", 2, "7" * 64),
                "secondaryStyleRef": None,
            },
        ),
        (
            [_PRIMARY_STYLE],
            {
                "primaryStyleRef": _style_ref("style-2", 1, "8" * 64),
                "secondaryStyleRef": None,
            },
        ),
    ),
    ids=("none-to-selected", "roles-swapped", "revision-changed", "style-changed"),
)
@pytest.mark.asyncio
async def test_repository_atomically_rejects_publication_after_selected_style_drift(
    selected_styles,
    current_draft,
):
    from backend.repositories.assets import AssetRepository

    session = RecordingRecommendationSession(
        one=(
            {"status": "running"},
            *_publication_locked_rows(current_draft),
        ),
        all_rows=_publication_candidate_rows(),
    )

    published = await AssetRepository().publish_recommendation(
        session,
        project_id="project-1",
        idempotency_key="i" * 64,
        request_hash="1" * 64,
        attempt_id=ATTEMPT_ID,
        input_manifest=_publication_manifest(selected_styles),
        result_json="{}",
        result_hash="2" * 64,
        completed_at=NOW,
    )

    mutations = [
        (sql.casefold(), params)
        for kind, sql, params in session.calls
        if kind == "execute"
    ]
    assert published is False
    assert len(mutations) == 2
    assert all("status='failed'" in sql for sql, _ in mutations)
    assert not any("status='succeeded'" in sql for sql, _ in mutations)
    request_sql, request_params = next(
        item for item in mutations if "asset_recommendation_requests" in item[0]
    )
    assert "attempt_id=%s" in request_sql
    assert ATTEMPT_ID in request_params


@pytest.mark.parametrize(
    ("malformed_manifest", "locked_rows"),
    (
        (None, ()),
        ([], ()),
        ("{", ()),
        (b"\xff", ()),
        ({}, (None, None)),
    ),
    ids=("none", "wrong-type", "json", "unicode", "missing-key"),
)
@pytest.mark.asyncio
async def test_repository_malformed_manifest_atomically_fails_running_ledgers(
    malformed_manifest,
    locked_rows,
):
    from backend.repositories.assets import AssetRepository

    session = RecordingRecommendationSession(
        one=({"status": "running"}, *locked_rows),
    )

    published = await AssetRepository().publish_recommendation(
        session,
        project_id="project-1",
        idempotency_key="i" * 64,
        request_hash="1" * 64,
        attempt_id=ATTEMPT_ID,
        input_manifest=malformed_manifest,
        result_json="{}",
        result_hash="2" * 64,
        completed_at=NOW,
    )

    mutations = [
        sql.casefold()
        for kind, sql, _ in session.calls
        if kind == "execute"
    ]
    assert published is False
    assert len(mutations) == 2
    assert all("status='failed'" in sql for sql in mutations)


@pytest.mark.asyncio
async def test_repository_publication_does_not_swallow_database_failures():
    from backend.repositories.assets import AssetRepository

    class FailingSession:
        async def fetchone(self, _sql, _params=None):
            raise RuntimeError("database connection failed")

    with pytest.raises(RuntimeError, match="database connection failed"):
        await AssetRepository().publish_recommendation(
            FailingSession(),
            project_id="project-1",
            idempotency_key="i" * 64,
            request_hash="1" * 64,
            attempt_id=ATTEMPT_ID,
            input_manifest=_publication_manifest([]),
            result_json="{}",
            result_hash="2" * 64,
            completed_at=NOW,
        )


@pytest.mark.asyncio
async def test_repository_ignores_unrelated_draft_changes_when_styles_are_stable():
    from backend.repositories.assets import AssetRepository

    current_draft = {
        "primaryStyleRef": _style_ref("style-1", 1, "c" * 64),
        "secondaryStyleRef": _style_ref("style-2", 1, "8" * 64),
        "likes": ["unrelated field changed while provider was running"],
    }
    session = RecordingRecommendationSession(
        one=_publication_locked_rows(current_draft),
        all_rows=_publication_candidate_rows(),
    )

    matches = await AssetRepository()._publication_inputs_match(
        session,
        {
            "project_id": "project-1",
            "input_manifest": _publication_manifest([
                _PRIMARY_STYLE,
                _SECONDARY_STYLE,
            ]),
        },
    )

    rendered = " ".join(sql.casefold() for _, sql, _ in session.calls)
    assert matches is True
    assert "project_contract_drafts" in rendered


@pytest.mark.asyncio
async def test_repository_publication_locks_only_the_manifest_engine_draft():
    from backend.repositories.assets import AssetRepository

    session = RecordingRecommendationSession(
        one=_publication_locked_rows({
            "primaryStyleRef": None,
            "secondaryStyleRef": None,
        }),
        all_rows=_publication_candidate_rows(),
    )

    matches = await AssetRepository()._publication_inputs_match(
        session,
        {
            "project_id": "project-1",
            "input_manifest": _publication_manifest([]),
        },
    )

    draft_sql, draft_params = next(
        (sql, params)
        for kind, sql, params in session.calls
        if kind == "one" and "project_contract_drafts" in sql
    )
    normalized = " ".join(draft_sql.casefold().split())
    assert matches is True
    assert "where project_id=%s and engine_option_id=%s for update" in normalized
    assert draft_params == ("project-1", "engine-1")


@pytest.mark.asyncio
async def test_repository_attempt_mutations_use_existing_request_attempt_schema():
    from backend.repositories.assets import AssetRepository

    repository = AssetRepository()
    session = RecordingRecommendationSession()
    request = {
        "id": REQUEST_ID, "project_id": "project-1",
        "idempotency_key": "i" * 64, "request_hash": "a" * 64,
        "attempt_id": ATTEMPT_ID, "created_at": NOW,
    }
    attempt = {
        "id": ATTEMPT_ID, "project_id": "project-1",
        "selection_revision": 3, "binding_revision_id": "binding-1",
        "binding_hash": "b" * 64, "input_manifest_json": "{}",
        "input_manifest_hash": "c" * 64, "created_at": NOW,
    }

    await repository.insert_recommendation_attempt(session, attempt)
    await repository.insert_recommendation_request(session, request)
    await repository.insert_failed_recommendation_request(session, {
        "id": "00000000-0000-0000-0000-000000000003",
        "project_id": "project-1",
        "idempotency_key": "j" * 64,
        "request_hash": "d" * 64,
        "public_error_code": "ASSET_RECOMMENDATION_NO_CANDIDATES",
        "created_at": NOW,
        "completed_at": NOW,
    })

    statements = [sql.casefold() for _, sql, _ in session.calls]
    rendered = " ".join(statements)
    assert "asset_recommendation_attempts" in statements[0]
    assert "'running',%s" in statements[1]
    assert "'failed',null" in statements[2]
    assert "insert into asset_recommendation_requests" in rendered
    assert "insert into asset_recommendation_attempts" in rendered
    assert "result_json" in rendered
    assert "'reserved'" not in rendered
    assert "raw" not in rendered and "prompt" not in rendered


@pytest.mark.asyncio
async def test_repository_failed_attempt_remains_linked_from_request():
    from backend.repositories.assets import AssetRepository

    session = RecordingRecommendationSession()

    await AssetRepository().fail_recommendation(
        session,
        project_id="project-1",
        idempotency_key="i" * 64,
        attempt_id=ATTEMPT_ID,
        public_error_code="ASSET_RECOMMENDATION_UNAVAILABLE",
        completed_at=NOW,
    )

    request_update = next(
        (sql, params)
        for kind, sql, params in session.calls
        if kind == "execute" and "asset_recommendation_requests" in sql
    )
    sql, params = request_update
    assert "attempt_id=%s" in " ".join(sql.split())
    assert ATTEMPT_ID in params


@pytest.mark.asyncio
async def test_repository_cancel_cleanup_locks_identity_and_terminalizes_running_pair():
    from backend.repositories.assets import AssetRepository

    session = RecordingRecommendationSession(one=(
        {"status": "running", "attempt_id": ATTEMPT_ID},
        {"status": "running"},
    ))

    changed = await AssetRepository().cleanup_cancelled_recommendation(
        session,
        project_id="project-1",
        idempotency_key="i" * 64,
        request_hash="a" * 64,
        public_error_code="ASSET_RECOMMENDATION_UNAVAILABLE",
        completed_at=NOW,
    )

    reads = [
        (" ".join(sql.casefold().split()), params)
        for kind, sql, params in session.calls
        if kind == "one"
    ]
    writes = [
        sql.casefold()
        for kind, sql, _ in session.calls
        if kind == "execute"
    ]
    assert changed is True
    assert "request_hash=%s for update" in reads[0][0]
    assert reads[0][1] == ("project-1", "i" * 64, "a" * 64)
    assert "asset_recommendation_attempts" in reads[1][0]
    assert reads[1][1] == ("project-1", ATTEMPT_ID)
    assert len(writes) == 2
    assert all("status='outcome_unknown'" in sql for sql in writes)


@pytest.mark.parametrize("status", ("succeeded", "failed", "outcome_unknown"))
@pytest.mark.asyncio
async def test_repository_cancel_cleanup_preserves_existing_terminal_pair(status):
    from backend.repositories.assets import AssetRepository

    session = RecordingRecommendationSession(one=(
        {"status": status, "attempt_id": ATTEMPT_ID},
        {"status": status},
    ))

    changed = await AssetRepository().cleanup_cancelled_recommendation(
        session,
        project_id="project-1",
        idempotency_key="i" * 64,
        request_hash="a" * 64,
        public_error_code="ASSET_RECOMMENDATION_UNAVAILABLE",
        completed_at=NOW,
    )

    assert changed is False
    assert not any(kind == "execute" for kind, _, _ in session.calls)
