from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256

import pytest

from backend.domain.finalization import FinalizationChangeSet, QualityFinding
from backend.domain.json_contracts import canonical_hash
from backend.gateways.finalization_provider import FinalizationProviderError
from backend.services.finalization import (
    CancelFinalization,
    ConfirmFinalization,
    CorrectFinalization,
    FinalizationConflict,
    FinalizationService,
    PrepareFinalization,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = 2_100_000_000_000


def _candidate():
    content = "第一章正文。" * 30
    content_hash = sha256(content.encode("utf-8")).hexdigest()
    basis = {
        "schemaVersion": "draft-candidate-basis-v1",
        "outlineRevisionId": "outline-revision-1",
        "outlineRevision": 1,
        "outlineHash": HASH_B,
        "planningRevisionId": "planning-revision-1",
        "planningRevision": 1,
        "planningHash": HASH_A,
        "canonRevision": 0,
        "projectionRevision": 0,
        "projectionHash": HASH_B,
    }
    return {
        "id": "candidate-1",
        "project_id": "project-1",
        "chapter_session_id": "session-1",
        "content": content,
        "content_hash": content_hash,
        "basis_hash": canonical_hash(basis),
        "provenance": basis,
    }


def _session():
    candidate_hash = _candidate()["content_hash"]
    return {
        "id": "session-1",
        "project_id": "project-1",
        "chapter_num": 1,
        "status": "drafting",
        "active_draft_operation_id": None,
        "expected_canon_revision": 0,
        "planning_hash": HASH_A,
        "chapter_outline_hash": HASH_B,
        "working_draft_content_hash": candidate_hash,
    }


def _current():
    return {
        "canon_revision": 0,
        "projection_revision": 0,
        "projection_hash": HASH_B,
        "planning_hash": HASH_A,
        "outline_hash": HASH_B,
    }


def _binding(task_key: str):
    return {
        "task_key": task_key,
        "id": f"provider-{task_key}",
        "model_name": f"model-{task_key}",
        "revision": 3,
        "provider_type": "openai_compatible",
        "base_url": "https://provider.invalid/v1",
        "api_key": "SECRET",
        "enabled": 1,
        "lifecycle_status": "active",
    }


def _snapshot():
    return {
        "canon_context": {"revision": 0, "entities": []},
        "planning_context": {
            "revision": 1, "contentHash": HASH_A,
            "content": {"volumes": [], "plots": [], "storyBlocks": []},
        },
        "outline_context": {"revision": 1, "contentHash": HASH_B},
        "contract_context": {"revision": 1, "contentHash": HASH_A},
        "bible_context": {"revision": 1, "contentHash": HASH_B},
        "policy_version": "quality-v1",
        "reference_sources": [],
        "audit_binding": _binding("audit"),
        "extraction_binding": _binding("extraction"),
    }


def _change_set():
    return FinalizationChangeSet.model_validate({
        "schemaVersion": "finalization-changeset-v1",
        "title": "第一章",
        "summary": "主角进入城中。",
        "existingEntityIds": [],
        "entities": [],
        "aliases": [],
        "canonEvents": [],
        "storyProgressEvents": [],
        "planningPatches": [],
        "planningSuggestions": [],
    })


def _finding():
    content = _candidate()["content"]
    return QualityFinding.model_validate({
        "id": "finding-1",
        "dimension": "pacing",
        "reason": "开场节奏偏慢。",
        "suggestedAction": "压缩首段。",
        "evidence": {
            "startScalar": 0,
            "endScalar": 4,
            "excerptHash": sha256(content[:4].encode("utf-8")).hexdigest(),
            "confidence": 0.8,
            "rationale": "首段连续说明较多。",
        },
    })


class FakeRepository:
    def __init__(self, *, snapshots=None, existing=None, active=None):
        self.snapshots = list(snapshots or [_snapshot(), _snapshot()])
        self.existing = existing
        self.active = active
        self.inserted_attempts = []
        self.inserted_reports = []
        self.inserted_revisions = []
        self.terminal = []
        self.published = []
        self.current_attempt = None
        self.current_revision = None
        self.advanced = []
        self.confirmed = []
        self.cancelled = []
        self.view = None
        self.session = _session()

    async def lock_project(self, session, project_id):
        return {"id": project_id}

    async def lock_session(self, session, project_id, session_id):
        return self.session

    async def lock_candidate(self, session, project_id, session_id, candidate_id):
        return _candidate()

    async def lock_current_authority(self, session, project_id, chapter_number):
        current = _current()
        if self.snapshots and self.snapshots[0].get("drift"):
            current["planning_hash"] = HASH_B
        return current

    async def load_preparation_context(self, session, project_id, chapter_number):
        return self.snapshots.pop(0)

    async def find_by_idempotency(self, session, project_id, session_id, key):
        return self.existing

    async def find_active(self, session, project_id, session_id):
        return self.active

    async def insert_preparing_attempt(self, session, row):
        self.inserted_attempts.append(row)

    async def insert_quality_report(self, session, row):
        self.inserted_reports.append(row)

    async def insert_change_set_revision(self, session, row):
        self.inserted_revisions.append(row)

    async def publish_awaiting_author(self, session, **row):
        self.published.append(row)
        return True

    async def mark_terminal(self, session, **row):
        self.terminal.append(row)
        return True

    async def lock_current_attempt(self, session, project_id, session_id):
        return self.current_attempt

    async def lock_change_set_revision(
        self, session, project_id, change_set_id, revision, content_hash,
    ):
        return self.current_revision

    async def advance_current_revision(self, session, **row):
        self.advanced.append(row)
        return True

    async def confirm_current_revision(self, session, **row):
        self.confirmed.append(row)
        return True

    async def cancel_awaiting_author(self, session, **row):
        self.cancelled.append(row)
        return True

    async def read_current_view(self, session, project_id, session_id):
        return self.view


class TransactionFactory:
    def __init__(self):
        self.active = False
        self.count = 0

    @asynccontextmanager
    async def __call__(self):
        assert not self.active
        self.active = True
        self.count += 1
        try:
            yield object()
        finally:
            self.active = False


class QualityProvider:
    def __init__(self, transactions, *, failure=None):
        self.transactions = transactions
        self.failure = failure
        self.calls = []

    async def audit(self, **kwargs):
        assert not self.transactions.active
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return (_finding(),)


class ExtractionProvider:
    def __init__(
        self, transactions, *, failure=None, cancelled=False, result=None,
    ):
        self.transactions = transactions
        self.failure = failure
        self.cancelled = cancelled
        self.result = result
        self.calls = []

    async def extract(self, **kwargs):
        assert not self.transactions.active
        self.calls.append(kwargs)
        if self.cancelled:
            raise asyncio.CancelledError()
        if self.failure:
            raise self.failure
        return self.result or _change_set()


def _command():
    candidate = _candidate()
    return PrepareFinalization(
        project_id="project-1",
        chapter_session_id="session-1",
        candidate_id="candidate-1",
        candidate_hash=candidate["content_hash"],
        expected_canon_revision=0,
        expected_planning_hash=HASH_A,
        expected_outline_hash=HASH_B,
        idempotency_key="c" * 64,
    )


def _service(repository, *, quality_failure=None, extraction_failure=None,
             cancelled=False, extraction_result=None):
    transactions = TransactionFactory()
    quality = QualityProvider(transactions, failure=quality_failure)
    extraction = ExtractionProvider(
        transactions, failure=extraction_failure, cancelled=cancelled,
        result=extraction_result,
    )
    identifiers = iter((
        "attempt-1", "report-1", "extraction-1", "revision-row-1",
    ))
    service = FinalizationService(
        transaction_factory=transactions,
        repository=repository,
        quality_provider=quality,
        extraction_provider=extraction,
        clock=lambda: NOW,
        id_factory=identifiers.__next__,
    )
    return service, transactions, quality, extraction


@pytest.mark.asyncio
async def test_prepare_uses_two_short_transactions_and_publishes_revision_one():
    repository = FakeRepository()
    service, transactions, quality, extraction = _service(repository)

    result = await service.prepare(_command())

    assert transactions.count == 2
    assert len(quality.calls) == len(extraction.calls) == 1
    assert result.status == "awaiting_author"
    assert result.quality_status == "completed"
    assert result.current_revision == 1
    assert len(repository.inserted_attempts) == 1
    assert len(repository.inserted_reports) == 1
    assert len(repository.inserted_revisions) == 1
    assert repository.published[0]["revision"] == 1
    assert "candidateProse" not in str(repository.inserted_attempts[0]["context_manifest"])


@pytest.mark.asyncio
async def test_author_can_cancel_an_unconfirmed_review_and_release_active_slot():
    repository = FakeRepository()
    repository.current_attempt = {
        "id": "attempt-1", "status": "awaiting_author",
        "current_revision": 1, "current_revision_hash": HASH_A,
        "confirmed_revision": None, "confirmed_revision_hash": None,
    }
    service, _, _, _ = _service(repository)

    result = await service.cancel(CancelFinalization(
        project_id="project-1",
        chapter_session_id="session-1",
        expected_revision=1,
        expected_revision_hash=HASH_A,
    ))

    assert result.status == "cancelled"
    assert repository.cancelled == [{
        "project_id": "project-1",
        "session_id": "session-1",
        "change_set_id": "attempt-1",
        "expected_revision": 1,
        "expected_revision_hash": HASH_A,
        "updated_at": NOW,
    }]


@pytest.mark.asyncio
async def test_prepare_keeps_corpus_refs_in_authority_but_not_provider_manifest():
    snapshot = _snapshot()
    snapshot["contract_context"] = {
        "revision": 1,
        "contentHash": HASH_A,
        "content": {
            "genre": "玄幻",
            "corpusSourceRefs": [{
                "id": "source-1",
                "fragments": [{"fragmentId": "fragment-1"}],
            }],
        },
    }
    repository = FakeRepository(snapshots=[snapshot, snapshot])
    service, _, quality, extraction = _service(repository)

    result = await service.prepare(_command())

    assert result.status == "awaiting_author"
    for call in (*quality.calls, *extraction.calls):
        provider_contract = call["manifest"].contract_context
        assert provider_contract["content"] == {"genre": "玄幻"}
    authority = repository.inserted_attempts[0]["context_manifest"]
    assert authority["contexts"]["contractHash"] == canonical_hash(
        snapshot["contract_context"],
    )


@pytest.mark.asyncio
async def test_quality_failure_is_advisory_and_extraction_still_runs_once():
    repository = FakeRepository()
    service, _, quality, extraction = _service(
        repository, quality_failure=FinalizationProviderError("safe"),
    )

    result = await service.prepare(_command())

    assert len(quality.calls) == len(extraction.calls) == 1
    assert result.status == "awaiting_author"
    assert result.quality_status == "quality_not_completed"
    assert repository.inserted_reports[0]["findings"] == []


@pytest.mark.asyncio
async def test_deterministic_hard_block_never_calls_extraction():
    blocked = _snapshot()
    blocked["reference_sources"] = [{
        "id": "reference-1",
        "content": _candidate()["content"],
        "content_hash": _candidate()["content_hash"],
    }]
    repository = FakeRepository(snapshots=[blocked])
    service, transactions, quality, extraction = _service(repository)

    result = await service.prepare(_command())

    assert transactions.count == 2
    assert len(quality.calls) == 1
    assert extraction.calls == []
    assert result.status == "failed"
    assert result.hard_blocks[0].code == "deterministic_copy"
    assert repository.terminal[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_same_idempotency_fingerprint_replays_without_provider_calls():
    repository = FakeRepository()
    probe, _, _, _ = _service(repository)
    fingerprint = probe.request_fingerprint(_command(), _snapshot())
    repository.existing = {
        "id": "attempt-old",
        "request_fingerprint": fingerprint,
        "status": "awaiting_author",
        "current_revision": 1,
        "current_revision_hash": HASH_A,
        "quality_report_id": "report-old",
    }
    service, transactions, quality, extraction = _service(repository)

    result = await service.prepare(_command())

    assert result.replayed is True and result.attempt_id == "attempt-old"
    assert transactions.count == 1
    assert quality.calls == extraction.calls == []


@pytest.mark.asyncio
async def test_idempotency_payload_conflict_and_other_active_attempt_fail_closed():
    conflict = FakeRepository(existing={
        "id": "attempt-old", "request_fingerprint": HASH_A,
    })
    service, _, quality, extraction = _service(conflict)
    with pytest.raises(FinalizationConflict, match="FINALIZATION_IDEMPOTENCY_CONFLICT"):
        await service.prepare(_command())
    assert quality.calls == extraction.calls == []

    active = FakeRepository(active={"id": "other-attempt"})
    service, _, quality, extraction = _service(active)
    with pytest.raises(FinalizationConflict, match="FINALIZATION_ACTIVE_CONFLICT"):
        await service.prepare(_command())
    assert quality.calls == extraction.calls == []


@pytest.mark.asyncio
async def test_authority_drift_after_provider_work_invalidates_attempt():
    first = _snapshot()
    second = _snapshot()
    second["drift"] = True
    repository = FakeRepository(snapshots=[first, second])
    service, _, quality, extraction = _service(repository)

    result = await service.prepare(_command())

    assert len(quality.calls) == len(extraction.calls) == 1
    assert result.status == "invalidated"
    assert repository.inserted_revisions == []
    assert repository.terminal[0]["status"] == "invalidated"


@pytest.mark.asyncio
async def test_extraction_failure_records_fixed_failed_state():
    repository = FakeRepository()
    service, _, _, extraction = _service(
        repository, extraction_failure=FinalizationProviderError("safe"),
    )

    result = await service.prepare(_command())

    assert len(extraction.calls) == 1
    assert result.status == "failed"
    assert repository.terminal[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_extraction_with_identity_outside_frozen_context_is_failed():
    payload = _change_set().model_dump(by_alias=True, mode="json")
    payload["existingEntityIds"] = ["missing-entity"]
    invalid = FinalizationChangeSet.model_validate(payload)
    repository = FakeRepository()
    service, _, _, extraction = _service(
        repository, extraction_result=invalid,
    )

    result = await service.prepare(_command())

    assert len(extraction.calls) == 1
    assert result.status == "failed"
    assert repository.inserted_revisions == []


@pytest.mark.asyncio
async def test_cancellation_is_recorded_then_propagated_with_priority():
    repository = FakeRepository()
    service, _, _, _ = _service(repository, cancelled=True)

    with pytest.raises(asyncio.CancelledError):
        await service.prepare(_command())

    assert repository.terminal[0]["status"] == "cancelled"


def _review_service(repository):
    transactions = TransactionFactory()
    quality = QualityProvider(transactions)
    extraction = ExtractionProvider(transactions)
    service = FinalizationService(
        transaction_factory=transactions,
        repository=repository,
        quality_provider=quality,
        extraction_provider=extraction,
        clock=lambda: NOW,
        id_factory=lambda: "revision-row-2",
    )
    return service, transactions, quality, extraction


def _awaiting_attempt():
    change_set = _change_set()
    command = _command()
    context_manifest_hash = canonical_hash(
        FinalizationService._context_manifest(command, 1, _snapshot())
    )
    return {
        "id": "attempt-1",
        "draft_candidate_id": "candidate-1",
        "status": "awaiting_author",
        "candidate_hash": _candidate()["content_hash"],
        "expected_canon_revision": 0,
        "expected_planning_hash": HASH_A,
        "expected_outline_hash": HASH_B,
        "current_revision": 1,
        "current_revision_hash": canonical_hash(
            change_set.model_dump(by_alias=True, mode="json")
        ),
        "confirmed_revision": None,
        "confirmed_revision_hash": None,
        "context_manifest_hash": context_manifest_hash,
        "idempotency_key": command.idempotency_key,
        "request_fingerprint": "d" * 64,
    }


@pytest.mark.asyncio
async def test_author_correction_appends_one_revision_without_provider():
    repository = FakeRepository()
    repository.current_attempt = _awaiting_attempt()
    service, transactions, quality, extraction = _review_service(repository)
    corrected = _change_set().model_copy(update={"summary": "作者修正摘要。"})

    result = await service.correct(CorrectFinalization(
        project_id="project-1",
        chapter_session_id="session-1",
        expected_revision=1,
        expected_revision_hash=repository.current_attempt["current_revision_hash"],
        change_set=corrected,
    ))

    assert transactions.count == 1
    assert quality.calls == extraction.calls == []
    assert result.current_revision == 2
    assert repository.inserted_revisions[0]["source"] == "author_correction"
    assert repository.advanced[0]["expected_revision"] == 1


@pytest.mark.asyncio
async def test_correction_rejects_stale_or_already_confirmed_revision():
    repository = FakeRepository()
    repository.current_attempt = _awaiting_attempt()
    repository.current_attempt["confirmed_revision"] = 1
    service, _, quality, extraction = _review_service(repository)

    with pytest.raises(FinalizationConflict, match="FINALIZATION_STATE_CONFLICT"):
        await service.correct(CorrectFinalization(
            project_id="project-1",
            chapter_session_id="session-1",
            expected_revision=1,
            expected_revision_hash=repository.current_attempt["current_revision_hash"],
            change_set=_change_set(),
        ))

    assert quality.calls == extraction.calls == []
    assert repository.inserted_revisions == []


@pytest.mark.asyncio
async def test_correction_rejects_context_manifest_drift_without_provider():
    changed = _snapshot()
    changed["extraction_binding"] = {
        **changed["extraction_binding"], "revision": 4,
    }
    repository = FakeRepository(snapshots=[changed])
    repository.current_attempt = _awaiting_attempt()
    service, _, quality, extraction = _review_service(repository)

    with pytest.raises(FinalizationConflict, match="FINALIZATION_STATE_CONFLICT"):
        await service.correct(CorrectFinalization(
            project_id="project-1",
            chapter_session_id="session-1",
            expected_revision=1,
            expected_revision_hash=repository.current_attempt["current_revision_hash"],
            change_set=_change_set(),
        ))

    assert quality.calls == extraction.calls == []
    assert repository.inserted_revisions == []


@pytest.mark.asyncio
async def test_confirmation_pins_exact_current_revision_without_provider_or_commit():
    repository = FakeRepository()
    repository.current_attempt = _awaiting_attempt()
    repository.current_revision = {"revision": 1}
    service, transactions, quality, extraction = _review_service(repository)

    result = await service.confirm(ConfirmFinalization(
        project_id="project-1",
        chapter_session_id="session-1",
        expected_revision=1,
        expected_revision_hash=repository.current_attempt["current_revision_hash"],
    ))

    assert transactions.count == 1
    assert quality.calls == extraction.calls == []
    assert result.confirmed_revision == 1
    assert repository.confirmed[0]["revision_hash"] == (
        repository.current_attempt["current_revision_hash"]
    )


@pytest.mark.asyncio
async def test_get_review_returns_repository_public_view_without_provider():
    repository = FakeRepository()
    repository.view = {"attemptId": "attempt-1", "status": "awaiting_author"}
    service, transactions, quality, extraction = _review_service(repository)

    assert await service.get_review("project-1", "session-1") == repository.view
    assert transactions.count == 1
    assert quality.calls == extraction.calls == []


@pytest.mark.asyncio
async def test_get_review_returns_closed_empty_state_for_existing_session_without_attempt():
    repository = FakeRepository()
    repository.view = None
    repository.session = {"id": "session-1"}
    service, transactions, quality, extraction = _review_service(repository)

    assert await service.get_review("project-1", "session-1") == {"state": "empty"}
    assert transactions.count == 1
    assert quality.calls == extraction.calls == []


@pytest.mark.asyncio
async def test_get_review_keeps_missing_session_not_found():
    repository = FakeRepository()
    repository.view = None
    repository.session = None
    service, *_ = _review_service(repository)

    with pytest.raises(FinalizationConflict, match="FINALIZATION_NOT_FOUND"):
        await service.get_review("project-1", "session-1")
