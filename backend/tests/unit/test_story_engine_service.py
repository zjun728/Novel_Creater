from __future__ import annotations

import pytest

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.http_errors import (
    StoryEngineBatchConflict,
    StoryEngineBatchNotFound,
    StoryEnginePreconditionFailed,
)
from backend.services.story_engines import (
    PROVIDER_TIMEOUT_SECONDS,
    RESERVED_TIMEOUT_MS,
    RUNNING_LEASE_MS,
    CreateManualStoryEngineBatch,
    ReserveStoryEngineBatch,
)
from backend.tests.support.story_engine_fakes import StoryEngineHarness, three_options


@pytest.mark.asyncio
async def test_manual_create_is_atomic_canonical_and_has_exactly_three_null_provider_options():
    harness = StoryEngineHarness()
    result = await harness.service.create_manual(
        CreateManualStoryEngineBatch("p1", "manual-key", three_options())
    )

    stored = harness.repository.batches[result.id]
    assert result.status == "succeeded"
    assert len(result.options) == 3
    assert [item.option_order for item in result.options] == [1, 2, 3]
    assert stored["binding_revision_id"] is None
    assert stored["provider_id"] is None
    assert stored["model_name_snapshot"] is None
    assert stored["attempt_id"] is None
    assert stored["raw_response_text"] is None
    assert result.raw_response_text is None
    assert result.raw_response_hash is None
    assert stored["request_hash"] == canonical_hash(stored["request"])
    for item, domain_option in zip(harness.repository.options[result.id], result.options):
        assert item["payload_json"] == canonical_json(domain_option.payload)
        assert item["content_hash"] == canonical_hash(domain_option.payload)


@pytest.mark.asyncio
async def test_manual_create_rolls_back_batch_and_options_when_any_option_fails():
    harness = StoryEngineHarness()
    harness.repository.fail_option_order = 2

    with pytest.raises(RuntimeError, match="synthetic option failure"):
        await harness.service.create_manual(
            CreateManualStoryEngineBatch("p1", "manual-key", three_options())
        )

    assert harness.repository.batches == {}
    assert harness.repository.options == {}


@pytest.mark.asyncio
async def test_same_canonical_request_replays_and_changed_request_conflicts():
    harness = StoryEngineHarness()
    first = await harness.service.create_manual(
        CreateManualStoryEngineBatch("p1", "same-key", three_options())
    )
    replay = await harness.service.create_manual(
        CreateManualStoryEngineBatch("p1", "same-key", three_options())
    )
    assert replay == first
    assert len(harness.repository.batches) == 1

    with pytest.raises(StoryEngineBatchConflict):
        await harness.service.create_manual(
            CreateManualStoryEngineBatch("p1", "same-key", three_options(suffix="变"))
        )


@pytest.mark.asyncio
async def test_provider_create_only_reserves_frozen_metadata_and_never_calls_gateway():
    harness = StoryEngineHarness()
    result = await harness.service.reserve_provider(
        ReserveStoryEngineBatch("p1", "provider-key")
    )

    stored = harness.repository.batches[result.id]
    assert result.status == "reserved"
    assert stored["seed_revision_id"] == "seed-revision-1"
    assert stored["binding_revision_id"] == "binding-revision-1"
    assert stored["provider_id"] == "provider-1"
    assert stored["model_name_snapshot"] == "safe-model"
    assert harness.gateway.calls == 0


@pytest.mark.asyncio
async def test_provider_same_key_conflicts_when_frozen_request_facts_change():
    harness = StoryEngineHarness()
    await harness.service.reserve_provider(ReserveStoryEngineBatch("p1", "same"))
    harness.repository.seed["seed_hash"] = "c" * 64

    with pytest.raises(StoryEngineBatchConflict):
        await harness.service.reserve_provider(ReserveStoryEngineBatch("p1", "same"))


@pytest.mark.asyncio
async def test_start_succeed_and_fail_use_attempt_cas_and_terminal_is_immutable():
    harness = StoryEngineHarness()
    succeeded = await harness.service.reserve_provider(ReserveStoryEngineBatch("p1", "s"))
    running = await harness.service.start_attempt("p1", succeeded.id)
    assert running.status == "running"
    assert running.attempt_started_at == harness.clock.now
    assert running.lease_expires_at == harness.clock.now + RUNNING_LEASE_MS
    terminal = await harness.service.succeed_attempt(
        "p1", succeeded.id, running.attempt_id, "raw response", three_options()
    )
    assert terminal.status == "succeeded"
    assert len(terminal.options) == 3
    with pytest.raises(StoryEngineBatchConflict):
        await harness.service.fail_attempt(
            "p1", succeeded.id, running.attempt_id, "provider_failed"
        )

    failed = await harness.service.reserve_provider(ReserveStoryEngineBatch("p1", "f"))
    failed_running = await harness.service.start_attempt("p1", failed.id)
    failure = await harness.service.fail_attempt(
        "p1", failed.id, failed_running.attempt_id, "provider_failed"
    )
    assert failure.status == "failed"
    with pytest.raises(StoryEngineBatchConflict):
        await harness.service.succeed_attempt(
            "p1", failed.id, failed_running.attempt_id, "late", three_options()
        )


@pytest.mark.asyncio
async def test_reconcile_stale_reserved_and_expired_running_without_gateway_calls():
    harness = StoryEngineHarness()
    reserved = await harness.service.reserve_provider(ReserveStoryEngineBatch("p1", "r"))
    harness.clock.advance(RESERVED_TIMEOUT_MS)
    failed = await harness.service.reconcile("p1", reserved.id)
    assert failed.status == "failed"
    assert failed.public_error_code == "not_started"

    running_batch = await harness.service.reserve_provider(ReserveStoryEngineBatch("p1", "u"))
    running = await harness.service.start_attempt("p1", running_batch.id)
    harness.clock.advance(RUNNING_LEASE_MS)
    unknown = await harness.service.reconcile("p1", running.id)
    assert unknown.status == "outcome_unknown"
    assert unknown.public_error_code == "outcome_unknown"
    assert harness.gateway.calls == 0


@pytest.mark.asyncio
async def test_provider_deadline_plus_sixty_second_margin_keeps_live_attempt_running():
    assert PROVIDER_TIMEOUT_SECONDS == 180
    assert RUNNING_LEASE_MS == (PROVIDER_TIMEOUT_SECONDS + 60) * 1000
    harness = StoryEngineHarness()
    batch = await harness.service.reserve_provider(ReserveStoryEngineBatch("p1", "live"))
    running = await harness.service.start_attempt("p1", batch.id)
    harness.clock.advance(PROVIDER_TIMEOUT_SECONDS * 1000 + 59_999)

    reconciled = await harness.service.reconcile("p1", running.id)

    assert reconciled.status == "running"


@pytest.mark.asyncio
async def test_reconcile_and_start_attempt_cas_cannot_both_win():
    harness = StoryEngineHarness()
    batch = await harness.service.reserve_provider(ReserveStoryEngineBatch("p1", "race"))
    harness.clock.advance(RESERVED_TIMEOUT_MS)
    reconciled = await harness.service.reconcile("p1", batch.id)
    assert reconciled.status == "failed"
    with pytest.raises(StoryEngineBatchConflict):
        await harness.service.start_attempt("p1", batch.id)


@pytest.mark.asyncio
async def test_missing_archived_and_missing_prerequisites_are_stable_public_errors():
    harness = StoryEngineHarness()
    with pytest.raises(StoryEngineBatchNotFound):
        await harness.service.get("p1", "missing")
    harness.repository.projects["p1"]["status"] = "archived"
    with pytest.raises(StoryEngineBatchNotFound):
        await harness.service.create_manual(
            CreateManualStoryEngineBatch("p1", "archived", three_options())
        )

    harness = StoryEngineHarness()
    harness.repository.binding = None
    with pytest.raises(StoryEnginePreconditionFailed):
        await harness.service.reserve_provider(ReserveStoryEngineBatch("p1", "no-binding"))
