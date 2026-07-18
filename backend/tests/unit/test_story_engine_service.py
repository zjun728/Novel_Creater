from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import re
from urllib.parse import quote

import httpx
import pytest

from backend.gateways.story_engine_provider import (
    StoryEngineProviderHTTPError,
    StoryEngineProviderResponseError,
)

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.http_errors import (
    ProjectArchived,
    StoryEngineBatchConflict,
    StoryEngineBatchNotFound,
    StoryEnginePreconditionFailed,
)
from backend.services.story_engines import (
    DEFAULT_CHANNEL_PROFILE,
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
    assert result.selection_revision == 7
    assert stored["selection_revision"] == 7
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
        assert item["selection_revision"] == 7
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
    assert stored["provider_id"] == "provider-seed"
    assert stored["model_name_snapshot"] == "seed-model"
    assert harness.gateway.calls == 0


@pytest.mark.asyncio
async def test_provider_same_key_conflicts_when_frozen_request_facts_change():
    harness = StoryEngineHarness()
    first = await harness.service.reserve_provider(ReserveStoryEngineBatch("p1", "same"))
    original_hash = first.request_hash

    harness.repository.bindings["planning"].update(
        provider_id="provider-planning-changed",
        model_name_snapshot="planning-model-changed",
    )
    replay = await harness.service.reserve_provider(ReserveStoryEngineBatch("p1", "same"))
    assert replay.request_hash == original_hash

    harness.repository.bindings["planning"].update(
        provider_id="provider-planning",
        model_name_snapshot="planning-model",
    )
    harness.repository.bindings["seed"].update(
        provider_id="provider-seed-changed",
        model_name_snapshot="seed-model-changed",
    )
    changed = await harness.service.reserve_provider(
        ReserveStoryEngineBatch("p1", "changed-seed")
    )
    assert changed.request_hash != original_hash

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
    assert failed.attempt_id is None
    assert failed.attempt_started_at is None
    assert failed.lease_expires_at is None

    running_batch = await harness.service.reserve_provider(ReserveStoryEngineBatch("p1", "u"))
    running = await harness.service.start_attempt("p1", running_batch.id)
    harness.clock.advance(RUNNING_LEASE_MS)
    unknown = await harness.service.reconcile("p1", running.id)
    assert unknown.status == "outcome_unknown"
    assert unknown.public_error_code == "outcome_unknown"
    assert harness.gateway.calls == 0


@pytest.mark.asyncio
async def test_mark_outcome_unknown_rechecks_active_project_before_writeback():
    harness = StoryEngineHarness()
    reserved = await harness.service.reserve_provider(
        ReserveStoryEngineBatch("p1", "archived-writeback")
    )
    running = await harness.service.start_attempt("p1", reserved.id)
    harness.repository.projects["p1"]["status"] = "archived"

    with pytest.raises(ProjectArchived):
        await harness.service.mark_outcome_unknown(
            "p1", running.id, running.attempt_id
        )

    assert harness.repository.batches[running.id]["status"] == "running"


@pytest.mark.asyncio
async def test_recoverable_batches_are_read_only_bounded_public_summaries():
    harness = StoryEngineHarness()
    harness.repository.recoverable_rows = [
        {
            "id": "batch-running",
            "status": "running",
            "public_error_code": None,
            "created_at": 10,
            "finished_at": None,
        },
        {
            "id": "batch-unknown",
            "status": "outcome_unknown",
            "public_error_code": "outcome_unknown",
            "created_at": 20,
            "finished_at": 30,
        },
    ]

    result = await harness.service.list_recoverable("p1")

    assert [item.id for item in result] == ["batch-running", "batch-unknown"]
    assert result[1].public_error_code == "outcome_unknown"
    assert set(result[0].model_dump()) == {
        "id", "status", "public_error_code", "created_at", "finished_at"
    }
    assert harness.gateway.calls == 0
    assert harness.repository.recoverable_calls == [("p1", 10)]
    assert harness.transaction_enter_count == 0


@pytest.mark.asyncio
async def test_recoverable_batches_missing_project_uses_public_not_found():
    harness = StoryEngineHarness()

    with pytest.raises(StoryEngineBatchNotFound):
        await harness.service.list_recoverable("missing")

    assert harness.gateway.calls == 0
    assert harness.transaction_enter_count == 0


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
    with pytest.raises(ProjectArchived):
        await harness.service.create_manual(
            CreateManualStoryEngineBatch("p1", "archived", three_options())
        )

    harness = StoryEngineHarness()
    harness.repository.bindings["seed"] = None
    with pytest.raises(StoryEnginePreconditionFailed):
        await harness.service.reserve_provider(ReserveStoryEngineBatch("p1", "no-binding"))


@pytest.mark.asyncio
async def test_unbound_reserved_batch_cannot_start_an_attempt():
    harness = StoryEngineHarness()
    harness.repository.bindings["seed"].update(
        resolution_status="unbound",
        provider_id=None,
        model_name_snapshot=None,
    )
    batch = await harness.service.reserve_provider(
        ReserveStoryEngineBatch("p1", "unbound-start")
    )

    with pytest.raises(StoryEngineBatchConflict):
        await harness.service.start_attempt("p1", batch.id)


def _provider_response(*, suffix=""):
    return json.dumps(
        {
            "options": [
                item.model_dump(mode="json")
                for item in three_options(suffix=suffix)
            ]
        },
        ensure_ascii=False,
    )


class ScriptedGateway:
    def __init__(self, harness, outcome=None):
        self.harness = harness
        self.outcome = outcome if outcome is not None else _provider_response()
        self.calls = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False

    async def generate(self, *, provider, messages, generation_config):
        assert self.harness.transaction_active == 0
        self.calls.append(
            (dict(provider), tuple(messages), dict(generation_config))
        )
        self.entered.set()
        if self.block:
            await self.release.wait()
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


@pytest.mark.asyncio
async def test_generate_provider_freezes_prompt_and_calls_gateway_outside_transaction_once():
    harness = StoryEngineHarness()
    gateway = ScriptedGateway(harness)
    harness.service.provider_gateway = gateway

    result = await harness.service.generate_provider(
        ReserveStoryEngineBatch("p1", "generated")
    )

    assert result.status == "succeeded"
    assert len(result.options) == 3
    assert result.raw_response_text is None
    assert result.raw_response_hash == sha256(
        gateway.outcome.encode("utf-8")
    ).hexdigest()
    stored = harness.repository.batches[result.id]
    assert stored["raw_response_text"] is None
    assert stored["raw_response_hash"] == result.raw_response_hash
    assert len(gateway.calls) == 1
    assert harness.transaction_enter_count == 3
    provider, messages, generation_config = gateway.calls[0]
    assert provider == {
        key: harness.repository.providers["provider-seed"][key]
        for key in (
            "id",
            "provider_type",
            "model_name",
            "base_url",
            "api_key",
            "enabled",
            "lifecycle_status",
        )
    }
    assert generation_config == {
        "temperature": 0.456,
        "maxOutputTokens": 4_321,
    }
    prompt = json.loads(messages[1]["content"])
    assert prompt["seedSnapshot"]["title"] == "冻结标题"
    assert prompt["channelProfile"] == DEFAULT_CHANNEL_PROFILE
    assert prompt["genreProfile"] == {
        "schemaVersion": "writer-genre-profile-v1",
        "projectGenre": "男频玄幻",
        "seedGenre": "玄幻",
    }
    stored_request = harness.repository.batches[result.id]["request"]
    assert stored_request["channelProfile"] == DEFAULT_CHANNEL_PROFILE
    assert stored_request["genreProfile"] == prompt["genreProfile"]
    assert stored_request["generationConfig"] == generation_config
    rendered = harness.repository.batches[result.id]["request_json"]
    assert "KEY_SENTINEL" not in rendered
    assert "https://provider.example" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("secret_field", ("api_key", "base_url"))
@pytest.mark.parametrize(
    "encoding",
    (
        "exact",
        "stripped",
        "percent",
        "percent-lower",
        "json-slash",
        "unicode-full",
        "unicode-mixed",
    ),
)
async def test_provider_response_containing_connection_secret_fails_before_options_are_saved(
    secret_field, encoding
):
    harness = StoryEngineHarness()
    provider = harness.repository.providers["provider-seed"]
    original = provider[secret_field]
    provider[secret_field] = f"  {original}  "
    normalized = original.strip()
    rendered_secret = {
        "exact": provider[secret_field],
        "stripped": normalized,
        "percent": quote(normalized, safe=""),
        "percent-lower": re.sub(
            r"%[0-9A-F]{2}",
            lambda match: match.group(0).lower(),
            quote(normalized, safe=""),
        ),
        "json-slash": normalized,
        "unicode-full": normalized,
        "unicode-mixed": normalized,
    }[encoding]
    raw = _provider_response()
    payload = json.loads(raw)
    payload["options"][1]["ensembleRoles"][0]["purpose"] = (
        f"nested providerEcho={rendered_secret}"
    )
    raw = json.dumps(payload, ensure_ascii=False)
    if encoding == "json-slash":
        raw = raw.replace(normalized, normalized.replace("/", r"\/"))
    elif encoding == "unicode-full":
        escaped = "".join(f"\\u{ord(character):04x}" for character in normalized)
        raw = raw.replace(normalized, escaped)
        assert normalized not in raw
    elif encoding == "unicode-mixed":
        escaped = "".join(
            f"\\u{ord(character):04x}" if index % 2 == 0 else character
            for index, character in enumerate(normalized)
        )
        raw = raw.replace(normalized, escaped)
        assert normalized not in raw
    gateway = ScriptedGateway(harness, raw)
    harness.service.provider_gateway = gateway

    result = await harness.service.generate_provider(
        ReserveStoryEngineBatch("p1", f"secret-{secret_field}-{encoding}")
    )

    stored = harness.repository.batches[result.id]
    assert result.status == "failed"
    assert result.public_error_code == "invalid_response"
    assert result.options == ()
    assert stored["raw_response_text"] is None
    assert result.raw_response_text is None
    assert result.raw_response_hash == sha256(raw.encode("utf-8")).hexdigest()
    assert stored["raw_response_hash"] == result.raw_response_hash
    assert normalized not in str(result)
    assert normalized not in canonical_json(stored)


def test_decoded_response_secret_scan_rejects_excessive_depth_or_nodes():
    harness = StoryEngineHarness()
    deep_payload: object = "value"
    for _ in range(33):
        deep_payload = [deep_payload]

    for payload in (deep_payload, {"items": ["value"] * 10_001}):
        with pytest.raises(ValueError, match="response structure exceeds scan limits"):
            harness.service._decoded_payload_contains_connection_secret(
                payload,
                harness.repository.providers["provider-seed"],
            )


@pytest.mark.asyncio
async def test_malformed_provider_content_keeps_only_exact_utf8_hash():
    harness = StoryEngineHarness()
    raw = '  {"options": [ invalid ]}\r\n'
    gateway = ScriptedGateway(harness, raw)
    harness.service.provider_gateway = gateway

    result = await harness.service.generate_provider(
        ReserveStoryEngineBatch("p1", "malformed-hash")
    )

    stored = harness.repository.batches[result.id]
    assert result.status == "failed"
    assert result.public_error_code == "invalid_response"
    assert result.raw_response_text is None
    assert stored["raw_response_text"] is None
    assert result.raw_response_hash == sha256(raw.encode("utf-8")).hexdigest()
    assert stored["raw_response_hash"] == result.raw_response_hash
    assert raw not in canonical_json(stored)


@pytest.mark.asyncio
async def test_safe_gateway_response_error_hash_is_persisted_without_raw_body():
    harness = StoryEngineHarness()
    response_hash = "f" * 64
    gateway = ScriptedGateway(
        harness,
        StoryEngineProviderResponseError(
            "provider response was invalid",
            response_hash=response_hash,
        ),
    )
    harness.service.provider_gateway = gateway

    result = await harness.service.generate_provider(
        ReserveStoryEngineBatch("p1", "gateway-envelope-hash")
    )

    assert result.status == "failed"
    assert result.public_error_code == "invalid_response"
    assert result.raw_response_text is None
    assert result.raw_response_hash == response_hash


@pytest.mark.asyncio
async def test_gateway_protocol_error_without_definite_body_has_no_hash_evidence():
    harness = StoryEngineHarness()
    gateway = ScriptedGateway(
        harness,
        StoryEngineProviderResponseError("provider response was invalid"),
    )
    harness.service.provider_gateway = gateway

    result = await harness.service.generate_provider(
        ReserveStoryEngineBatch("p1", "gateway-no-body")
    )

    assert result.status == "failed"
    assert result.public_error_code == "provider_failed"
    assert result.raw_response_text is None
    assert result.raw_response_hash is None


@pytest.mark.asyncio
async def test_terminal_replay_and_expired_running_never_call_provider_again():
    harness = StoryEngineHarness()
    gateway = ScriptedGateway(harness)
    harness.service.provider_gateway = gateway
    command = ReserveStoryEngineBatch("p1", "replay")
    first = await harness.service.generate_provider(command)
    replay = await harness.service.generate_provider(command)
    assert replay == first
    assert len(gateway.calls) == 1
    assert harness.transaction_enter_count == 4

    reserved = await harness.service.reserve_provider(
        ReserveStoryEngineBatch("p1", "expired")
    )
    await harness.service.start_attempt("p1", reserved.id)
    harness.clock.advance(RUNNING_LEASE_MS)
    unknown = await harness.service.reconcile("p1", reserved.id)
    replayed_unknown = await harness.service.generate_provider(
        ReserveStoryEngineBatch("p1", "expired")
    )
    assert unknown.status == replayed_unknown.status == "outcome_unknown"
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_concurrent_same_key_has_one_outbound_call():
    harness = StoryEngineHarness()
    gateway = ScriptedGateway(harness)
    gateway.block = True
    harness.service.provider_gateway = gateway
    command = ReserveStoryEngineBatch("p1", "concurrent")

    winner = asyncio.create_task(harness.service.generate_provider(command))
    await gateway.entered.wait()
    loser = await harness.service.generate_provider(command)
    gateway.release.set()
    completed = await winner

    assert loser.status == "running"
    assert completed.status == "succeeded"
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("api_key", "short"),
        ("base_url", "x"),
    ),
)
async def test_nonblank_short_connection_fields_remain_callable(field, value):
    harness = StoryEngineHarness()
    gateway = ScriptedGateway(harness)
    harness.service.provider_gateway = gateway
    harness.repository.providers["provider-seed"][field] = value

    result = await harness.service.generate_provider(
        ReserveStoryEngineBatch("p1", f"short-{field}")
    )

    assert result.status == "succeeded"
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_legacy_openai_type_fails_before_gateway():
    harness = StoryEngineHarness()
    gateway = ScriptedGateway(harness)
    harness.service.provider_gateway = gateway
    harness.repository.providers["provider-seed"]["provider_type"] = "openai"

    result = await harness.service.generate_provider(
        ReserveStoryEngineBatch("p1", "legacy-openai")
    )

    assert result.status == "failed"
    assert result.public_error_code == "provider_configuration"
    assert result.attempt_id is None
    assert gateway.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configuration",
    (
        "unbound",
        "missing",
        "deleted",
        "disabled",
        "empty-key",
        "empty-base",
        "empty-model",
        "model-mismatch",
        "unsupported-type",
    ),
)
async def test_unavailable_configuration_fails_before_attempt_with_zero_transport(
    configuration,
):
    harness = StoryEngineHarness()
    gateway = ScriptedGateway(harness)
    harness.service.provider_gateway = gateway
    binding = harness.repository.bindings["seed"]
    provider = harness.repository.providers["provider-seed"]
    if configuration == "unbound":
        binding.update(
            resolution_status="unbound",
            provider_id=None,
            model_name_snapshot=None,
        )
    elif configuration == "missing":
        harness.repository.providers.clear()
    elif configuration == "deleted":
        provider.update(lifecycle_status="deleted", enabled=0, api_key="", base_url="")
    elif configuration == "disabled":
        provider["enabled"] = 0
    elif configuration == "empty-key":
        provider["api_key"] = " "
    elif configuration == "empty-base":
        provider["base_url"] = " "
    elif configuration == "empty-model":
        provider["model_name"] = " "
    elif configuration == "model-mismatch":
        provider["model_name"] = "changed-model"
    elif configuration == "unsupported-type":
        provider["provider_type"] = "anthropic"

    result = await harness.service.generate_provider(
        ReserveStoryEngineBatch("p1", f"configuration-{configuration}")
    )

    assert result.status == "failed"
    assert result.public_error_code == "provider_configuration"
    assert result.attempt_id is None
    assert result.attempt_started_at is None
    assert result.lease_expires_at is None
    assert gateway.calls == []
    assert harness.transaction_enter_count == 2


@pytest.mark.asyncio
async def test_generation_config_is_frozen_before_current_profile_changes():
    harness = StoryEngineHarness()
    gateway = ScriptedGateway(harness)
    harness.service.provider_gateway = gateway

    def change_current_profile():
        harness.repository.providers["provider-seed"].update(
            temperature=0.999,
            max_output_tokens=9_999,
        )
        harness.repository.on_lock_provider_connection = None

    harness.repository.on_lock_provider_connection = change_current_profile
    result = await harness.service.generate_provider(
        ReserveStoryEngineBatch("p1", "frozen-generation-config")
    )

    assert result.status == "succeeded"
    assert gateway.calls[0][2] == {
        "temperature": 0.456,
        "maxOutputTokens": 4_321,
    }
    stored = harness.repository.batches[result.id]
    assert stored["request"]["generationConfig"] == gateway.calls[0][2]
    changed = await harness.service.reserve_provider(
        ReserveStoryEngineBatch("p1", "changed-generation-config")
    )
    assert changed.request_hash != result.request_hash
    with pytest.raises(StoryEngineBatchConflict):
        await harness.service.reserve_provider(
            ReserveStoryEngineBatch("p1", "frozen-generation-config")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "status", "code"),
    (
        ("not-json", "failed", "invalid_response"),
        ('{"options": []}', "failed", "invalid_response"),
        (StoryEngineProviderHTTPError("RAW_SENTINEL"), "failed", "provider_failed"),
        (StoryEngineProviderResponseError("RAW_SENTINEL"), "failed", "provider_failed"),
        (TimeoutError("KEY_SENTINEL PRIVATE_URL_SENTINEL"), "outcome_unknown", "outcome_unknown"),
        (httpx.TransportError("KEY_SENTINEL PRIVATE_URL_SENTINEL"), "outcome_unknown", "outcome_unknown"),
    ),
)
async def test_generation_rejection_and_uncertain_transport_have_stable_classification(
    outcome, status, code
):
    harness = StoryEngineHarness()
    gateway = ScriptedGateway(harness, outcome)
    harness.service.provider_gateway = gateway

    result = await harness.service.generate_provider(
        ReserveStoryEngineBatch("p1", f"classification-{status}-{type(outcome).__name__}")
    )

    assert result.status == status
    assert result.public_error_code == code
    assert len(gateway.calls) == 1
    assert "KEY_SENTINEL" not in str(result)
    assert "PRIVATE_URL_SENTINEL" not in str(result)
    assert result.raw_response_text is None
    if isinstance(outcome, str):
        assert result.raw_response_hash == sha256(outcome.encode("utf-8")).hexdigest()
    else:
        assert result.raw_response_hash is None
