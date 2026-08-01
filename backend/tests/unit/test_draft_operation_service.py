from __future__ import annotations

import asyncio
import copy
from decimal import Decimal
import hashlib
import json
from uuid import UUID

import pytest

from backend.domain.json_contracts import canonical_hash
from backend.gateways.chapter_draft_provider import ChapterDraftProviderError


PROJECT_ID = "10000000-0000-4000-8000-000000000001"
SESSION_ID = "20000000-0000-4000-8000-000000000001"
KEY = "30000000-0000-4000-8000-000000000001"
EMPTY_HASH = hashlib.sha256(b"").hexdigest()


def _fingerprint(*, instruction="多一点人物试探", revision=1, content_hash=EMPTY_HASH):
    return canonical_hash({
        "projectId": PROJECT_ID,
        "chapterSessionId": SESSION_ID,
        "operationType": "generate_new",
        "baseWorkingDraftRevision": revision,
        "baseWorkingDraftHash": content_hash,
        "authorInstruction": instruction,
    })


class SequentialIds:
    def __init__(self):
        self.value = 100

    def __call__(self):
        self.value += 1
        return str(UUID(int=self.value))


class FakeClock:
    def __init__(self, now=10_000):
        self.now = now

    def __call__(self):
        return self.now


class TransactionTracker:
    def __init__(self, repository):
        self.repository = repository
        self.active = 0
        self.entries = 0

    def factory(self):
        tracker = self

        class Transaction:
            async def __aenter__(self):
                self.snapshot = tracker.repository.snapshot()
                tracker.active += 1
                tracker.entries += 1
                return object()

            async def __aexit__(self, exc_type, exc, tb):
                if exc_type is not None:
                    tracker.repository.restore(self.snapshot)
                tracker.active -= 1
                return False

        return Transaction()


class FakeGateway:
    def __init__(self, output="门轴轻响，沈砚没有立刻回头。", *, tracker=None, on_generate=None):
        self.output = output
        self.tracker = tracker
        self.on_generate = on_generate
        self.calls = []

    async def generate(self, *, provider, messages, generation_config):
        assert self.tracker is None or self.tracker.active == 0
        self.calls.append({
            "provider": dict(provider),
            "messages": list(messages),
            "generation_config": dict(generation_config),
        })
        if self.on_generate is not None:
            self.on_generate()
        if isinstance(self.output, BaseException):
            raise self.output
        return self.output


class MutatingGateway(FakeGateway):
    async def generate(self, *, provider, messages, generation_config):
        assert self.tracker is None or self.tracker.active == 0
        original_api_key = provider["api_key"]
        original_base_url = provider["base_url"]
        provider["api_key"] = "gateway-mutated-key"
        provider["base_url"] = "https://gateway-mutated.invalid/v1"
        messages[0]["content"] = "gateway-mutated-message"
        generation_config["temperature"] = 999
        self.calls.append({
            "provider": provider,
            "messages": messages,
            "generation_config": generation_config,
        })
        return f"provider leaked {original_api_key} from {original_base_url}"


class FakeRepository:
    def __init__(self):
        self.project = {"id": PROJECT_ID}
        self.session = {
            "id": SESSION_ID,
            "project_id": PROJECT_ID,
            "planning_revision_id": "planning-1",
            "planning_revision": 4,
            "planning_hash": "a" * 64,
            "story_block_id": "block-1",
            "story_block_revision": 2,
            "story_block_hash": "b" * 64,
            "chapter_outline_revision_id": "outline-1",
            "chapter_outline_revision": 3,
            "chapter_outline_hash": "c" * 64,
            "chapter_num": 7,
            "expected_canon_revision": 5,
            "outline_canon_revision": 5,
            "outline_projection_revision": 5,
            "outline_projection_hash": "d" * 64,
            "chapter_outline": {"chapterGoal": "逼主角公开选择阵营"},
            "status": "drafting",
            "draft_operation_fencing_token": 0,
            "active_draft_operation_id": None,
        }
        self.outline = {
            "chapter_outline_revision_id": "outline-1",
            "chapter_outline_revision": 3,
            "chapter_outline_hash": "c" * 64,
            "planning_revision_id": "planning-1",
            "planning_revision": 4,
            "planning_hash": "a" * 64,
            "canon_revision": 5,
            "projection_revision": 5,
            "projection_hash": "d" * 64,
            "chapter_outline": {"chapterGoal": "逼主角公开选择阵营"},
            "current_planning_revision_id": "planning-head-2",
            "current_planning_revision": 8,
            "current_planning_hash": "8" * 64,
            "planning_selection_revision": 1,
            "planning_seed_id": "seed-1",
            "planning_seed_revision_id": "seed-revision-1",
            "planning_seed_hash": "1" * 64,
            "planning_contract_revision": 1,
            "planning_creation_contract_id": "creation-contract-1",
            "planning_creation_hash": "2" * 64,
            "planning_style_contract_id": "style-contract-1",
            "planning_style_hash": "3" * 64,
            "planning_bible_revision": 1,
            "planning_bible_revision_id": "bible-revision-1",
            "planning_bible_hash": "4" * 64,
            "current_selection_revision": 1,
            "current_seed_id": "seed-1",
            "current_seed_revision_id": "seed-revision-1",
            "current_seed_hash": "1" * 64,
            "current_contract_revision": 1,
            "current_creation_contract_id": "creation-contract-1",
            "current_creation_hash": "2" * 64,
            "current_style_contract_id": "style-contract-1",
            "current_style_hash": "3" * 64,
            "current_bible_revision": 1,
            "current_bible_revision_id": "bible-revision-1",
            "current_bible_hash": "4" * 64,
            "story_block_id": "block-current",
            "story_block_revision": 9,
            "story_block_hash": "5" * 64,
        }
        self.projection = {
            "canon_revision_number": 5,
            "projection_revision_number": 5,
            "content_hash": "d" * 64,
        }
        self.draft = {
            "id": "draft-1",
            "project_id": PROJECT_ID,
            "chapter_session_id": SESSION_ID,
            "revision": 1,
            "content": "",
            "content_hash": EMPTY_HASH,
            "source_payload": {"source": "manual-empty"},
            "updated_at": 1,
            "effective_status": "drafting",
        }
        self.provider = {
            "binding_revision_id": "binding-1",
            "binding_revision": 2,
            "binding_hash": "e" * 64,
            "binding_item_hash": "f" * 64,
            "id": "provider-writing",
            "provider_type": "openai-compatible",
            "model_name": "fake-writing-model",
            "base_url": "https://private.provider.invalid/v1",
            "api_key": "private-provider-key",
            "temperature": Decimal("0.720"),
            "max_output_tokens": 4500,
        }
        self.operations = {}
        self.events = []
        self.revisions = []
        self.fail_snapshot_role = None
        self.fail_event_sequence = None
        self.fail_cas = False
        self.fail_complete = False
        self.fail_terminal_failure = False

    def snapshot(self):
        excluded = {
            "fail_snapshot_role", "fail_event_sequence", "fail_cas",
            "fail_complete", "fail_terminal_failure",
        }
        return copy.deepcopy({
            key: value for key, value in self.__dict__.items() if key not in excluded
        })

    def restore(self, snapshot):
        controls = {
            "fail_snapshot_role": self.fail_snapshot_role,
            "fail_event_sequence": self.fail_event_sequence,
            "fail_cas": self.fail_cas,
            "fail_complete": self.fail_complete,
            "fail_terminal_failure": self.fail_terminal_failure,
        }
        self.__dict__.update(copy.deepcopy(snapshot))
        self.__dict__.update(controls)

    async def lock_project(self, session, project_id):
        return self.project if project_id == PROJECT_ID else None

    async def lock_session_for_operation(self, session, project_id, chapter_session_id):
        if project_id == PROJECT_ID and chapter_session_id == SESSION_ID:
            derived = {
                "outline_canon_revision",
                "outline_projection_revision",
                "outline_projection_hash",
                "chapter_outline",
            }
            return {
                key: value for key, value in self.session.items()
                if key not in derived
            }
        return None

    async def read_session_by_id(self, session, project_id, chapter_session_id):
        if project_id == PROJECT_ID and chapter_session_id == SESSION_ID:
            return copy.deepcopy(self.session)
        return None

    async def lock_working_draft_for_operation(self, session, project_id, chapter_session_id):
        if project_id == PROJECT_ID and chapter_session_id == SESSION_ID:
            return dict(self.draft)
        return None

    async def read_current_outline(self, session, project_id, chapter_number):
        if project_id == PROJECT_ID and chapter_number == 7:
            return copy.deepcopy(self.outline)
        return None

    async def read_projection_head(self, session, project_id):
        return dict(self.projection) if project_id == PROJECT_ID else None

    async def resolve_writing_provider(self, session, project_id):
        return dict(self.provider) if project_id == PROJECT_ID else None

    async def read_draft_operation_by_key(self, session, chapter_session_id, key):
        return next((dict(row) for row in self.operations.values()
                     if row["chapter_session_id"] == chapter_session_id
                     and row["idempotency_key"] == key), None)

    async def read_draft_operation(self, session, project_id, chapter_session_id, operation_id):
        row = self.operations.get(operation_id)
        if row and row["project_id"] == project_id and row["chapter_session_id"] == chapter_session_id:
            return dict(row)
        return None

    async def read_active_draft_operation(self, session, chapter_session_id):
        return next((dict(row) for row in self.operations.values()
                     if row["chapter_session_id"] == chapter_session_id
                     and row["active_slot"] == 1), None)

    async def next_draft_operation_fencing_token(self, session, project_id, chapter_session_id):
        self.session["draft_operation_fencing_token"] += 1
        return self.session["draft_operation_fencing_token"]

    async def insert_draft_operation(self, session, row):
        self.operations[row["id"]] = copy.deepcopy(row)
        return True

    async def mark_draft_operation_running(self, session, operation_id, fencing_token, now):
        row = self.operations[operation_id]
        if row["fencing_token"] != fencing_token or row["status"] != "starting":
            return False
        row["status"] = "running"
        row["updated_at"] = now
        self.session["active_draft_operation_id"] = operation_id
        return True

    async def insert_draft_operation_event(self, session, row):
        if self.fail_event_sequence == row["sequence_num"]:
            return False
        operation = self.operations[row["draft_operation_id"]]
        if operation["last_event_sequence"] != row["sequence_num"] - 1:
            return False
        operation["last_event_sequence"] = row["sequence_num"]
        self.events.append(copy.deepcopy(row))
        return True

    async def expire_draft_operation(self, session, operation_id, fencing_token, now):
        row = self.operations[operation_id]
        if row["fencing_token"] != fencing_token or row["lease_expires_at"] > now:
            return False
        self._expire(row, now)
        return True

    async def expire_draft_operation_for_drift(
        self, session, project_id, chapter_session_id, operation_id, fencing_token, now
    ):
        row = self.operations[operation_id]
        if (row["project_id"] != project_id or row["chapter_session_id"] != chapter_session_id
                or row["fencing_token"] != fencing_token or row["status"] != "running"
                or row["lease_expires_at"] <= now
                or self.session["active_draft_operation_id"] != operation_id):
            return False
        self._expire(row, now)
        return True

    def _expire(self, row, now):
        row.update(status="expired", active_slot=None, updated_at=now, completed_at=now)
        self.session["active_draft_operation_id"] = None

    async def insert_working_draft_revision(self, session, row):
        if self.fail_snapshot_role == row["snapshot_role"]:
            return False
        self.revisions.append(copy.deepcopy(row))
        return True

    async def upsert_working_draft(
        self, session, row, *, expected_revision=None, expected_content_hash=None
    ):
        if (self.fail_cas or self.draft["revision"] != expected_revision
                or self.draft["content_hash"] != expected_content_hash):
            return False
        self.draft = copy.deepcopy(row)
        return True

    async def complete_draft_operation(self, session, row):
        if self.fail_complete:
            return False
        operation = self.operations[row["id"]]
        if operation["fencing_token"] != row["fencing_token"]:
            return False
        operation.update(
            status="completed",
            active_slot=None,
            result_working_draft_revision=row["result_working_draft_revision"],
            result_content_hash=row["result_content_hash"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )
        self.session["active_draft_operation_id"] = None
        return True

    async def fail_draft_operation(self, session, row):
        if self.fail_terminal_failure:
            return False
        operation = self.operations[row["id"]]
        operation.update(
            status="failed", active_slot=None, failure_code=row["failure_code"],
            updated_at=row["updated_at"], completed_at=row["completed_at"],
        )
        self.session["active_draft_operation_id"] = None
        return True


def make_service(repo=None, gateway=None, clock=None):
    from backend.services.draft_operations import DraftOperationService

    repo = repo or FakeRepository()
    clock = clock or FakeClock()
    tracker = TransactionTracker(repo)
    gateway = gateway or FakeGateway(tracker=tracker)
    gateway.tracker = tracker
    return (
        DraftOperationService(
            repo,
            provider_gateway=gateway,
            transaction_factory=tracker.factory,
            id_factory=SequentialIds(),
            clock=clock,
        ),
        repo,
        gateway,
        tracker,
        clock,
    )


def command(**overrides):
    from backend.services.draft_operations import StartDraftOperation

    values = {
        "project_id": PROJECT_ID,
        "chapter_session_id": SESSION_ID,
        "operation_type": "generate_new",
        "expected_working_draft_revision": 1,
        "expected_content_hash": EMPTY_HASH,
        "idempotency_key": KEY,
        "author_instruction": "多一点人物试探",
    }
    values.update(overrides)
    return StartDraftOperation(**values)


@pytest.mark.asyncio
async def test_generate_new_reserves_calls_outside_transaction_and_atomically_commits():
    service, repo, gateway, tracker, _ = make_service()

    result = await service.start(command())

    assert result.status == "completed"
    assert result.result_working_draft_revision == 2
    assert result.result_content_hash == repo.draft["content_hash"]
    assert tracker.active == 0
    assert tracker.entries == 2
    assert len(gateway.calls) == 1
    assert repo.draft["revision"] == 2
    assert [row["snapshot_role"] for row in repo.revisions] == ["before", "after"]
    assert [row["working_draft_revision"] for row in repo.revisions] == [1, 2]
    assert [row["event_type"] for row in repo.events] == ["started", "completed"]
    attempt = next(iter(repo.operations.values()))
    serialized_manifest = json.dumps(attempt["input_manifest"], ensure_ascii=False)
    assert repo.provider["api_key"] not in serialized_manifest
    assert repo.provider["base_url"] not in serialized_manifest
    rendered = "\n".join(item["content"] for item in gateway.calls[0]["messages"])
    assert "逼主角公开选择阵营" in rendered
    assert "当前工作稿" not in rendered


@pytest.mark.asyncio
async def test_current_outline_can_replace_session_entry_pins_before_prose_is_final():
    service, repo, gateway, _, _ = make_service()
    repo.session.update({
        "planning_revision_id": "entry-planning-old",
        "planning_revision": 1,
        "planning_hash": "6" * 64,
        "story_block_id": "entry-block-old",
        "story_block_revision": 1,
        "story_block_hash": "7" * 64,
        "chapter_outline_revision_id": "entry-outline-old",
        "chapter_outline_revision": 1,
        "chapter_outline_hash": "9" * 64,
        "expected_canon_revision": 1,
        "outline_canon_revision": 1,
        "outline_projection_revision": 1,
        "outline_projection_hash": "0" * 64,
    })
    repo.outline["chapter_outline"] = {"chapterGoal": "使用作者刚确认的新小纲"}

    result = await service.start(command())

    assert result.status == "completed"
    rendered = "\n".join(item["content"] for item in gateway.calls[0]["messages"])
    assert "使用作者刚确认的新小纲" in rendered
    attempt = next(iter(repo.operations.values()))
    assert attempt["input_manifest"]["outline"]["revisionId"] == "outline-1"
    assert (
        attempt["input_manifest"]["session"]["chapter_outline_revision_id"]
        == "entry-outline-old"
    )


@pytest.mark.asyncio
async def test_outline_planning_baseline_mismatch_is_precondition_before_provider():
    from backend.services.draft_operations import DraftOperationPreconditionFailed

    service, repo, gateway, _, _ = make_service()
    repo.outline["planning_seed_hash"] = "9" * 64

    with pytest.raises(DraftOperationPreconditionFailed):
        await service.start(command())
    assert gateway.calls == []
    assert repo.operations == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", (("expected_working_draft_revision", 9), ("expected_content_hash", "9" * 64)))
async def test_base_cas_mismatch_fails_before_provider(field, value):
    from backend.services.draft_operations import DraftOperationConflict

    service, repo, gateway, _, _ = make_service()
    with pytest.raises(DraftOperationConflict):
        await service.start(command(**{field: value}))
    assert gateway.calls == []
    assert repo.operations == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ("starting", "running", "completed", "failed"))
async def test_same_key_same_fingerprint_replays_without_provider_or_mutable_checks(status):
    service, repo, gateway, _, clock = make_service()
    operation_id = str(UUID(int=900))
    repo.operations[operation_id] = {
        "id": operation_id, "project_id": PROJECT_ID, "chapter_session_id": SESSION_ID,
        "operation_type": "generate_new", "idempotency_key": KEY,
        "request_fingerprint": _fingerprint(), "active_slot": 1 if status in {"starting", "running"} else None,
        "fencing_token": 1, "lease_expires_at": clock.now + 500,
        "base_working_draft_revision": 1, "base_working_draft_hash": EMPTY_HASH,
        "input_manifest": {}, "input_manifest_hash": "1" * 64,
        "provider_id": "provider-writing", "model_name_snapshot": "fake-writing-model",
        "result_working_draft_revision": 2 if status == "completed" else None,
        "result_content_hash": "2" * 64 if status == "completed" else None,
        "last_event_sequence": 2 if status in {"completed", "failed"} else 1,
        "failure_code": "DraftProviderFailed" if status == "failed" else None,
        "status": status, "created_at": 1, "updated_at": 1,
        "completed_at": 1 if status in {"completed", "failed"} else None,
    }
    repo.session["status"] = "finalized"
    repo.draft["revision"] = 99

    result = await service.start(command())

    assert result.status == status
    assert result.operation_id == operation_id
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_same_key_different_fingerprint_is_fixed_conflict():
    from backend.services.draft_operations import DraftOperationIdempotencyConflict

    service, repo, gateway, _, _ = make_service()
    operation_id = str(UUID(int=901))
    repo.operations[operation_id] = {
        "id": operation_id, "project_id": PROJECT_ID, "chapter_session_id": SESSION_ID,
        "operation_type": "generate_new", "idempotency_key": KEY,
        "request_fingerprint": "9" * 64, "active_slot": None, "fencing_token": 1,
        "lease_expires_at": 1, "base_working_draft_revision": 1,
        "base_working_draft_hash": EMPTY_HASH, "input_manifest": {},
        "input_manifest_hash": "1" * 64, "provider_id": "provider-writing",
        "model_name_snapshot": "fake-writing-model", "result_working_draft_revision": None,
        "result_content_hash": None, "last_event_sequence": 1, "failure_code": None,
        "status": "expired", "created_at": 1, "updated_at": 1, "completed_at": 1,
    }
    with pytest.raises(DraftOperationIdempotencyConflict):
        await service.start(command())
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_same_key_elapsed_attempt_replays_as_expired_without_provider():
    service, repo, gateway, _, clock = make_service()
    operation_id = str(UUID(int=906))
    repo.operations[operation_id] = {
        "id": operation_id, "project_id": PROJECT_ID, "chapter_session_id": SESSION_ID,
        "operation_type": "generate_new", "idempotency_key": KEY,
        "request_fingerprint": _fingerprint(), "active_slot": 1, "fencing_token": 1,
        "lease_expires_at": clock.now, "base_working_draft_revision": 1,
        "base_working_draft_hash": EMPTY_HASH, "input_manifest": {},
        "input_manifest_hash": "1" * 64, "provider_id": "provider-writing",
        "model_name_snapshot": "fake-writing-model", "result_working_draft_revision": None,
        "result_content_hash": None, "last_event_sequence": 1, "failure_code": None,
        "status": "running", "created_at": 1, "updated_at": 1, "completed_at": None,
    }
    repo.session["active_draft_operation_id"] = operation_id

    result = await service.start(command())

    assert result.status == "expired"
    assert repo.operations[operation_id]["status"] == "expired"
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_replay_fails_closed_for_malformed_stored_public_result():
    from backend.services.draft_operations import DraftOperationStorageError

    service, repo, gateway, _, _ = make_service()
    operation_id = str(UUID(int=907))
    repo.operations[operation_id] = {
        "id": operation_id, "project_id": PROJECT_ID, "chapter_session_id": SESSION_ID,
        "operation_type": "generate_new", "idempotency_key": KEY,
        "request_fingerprint": _fingerprint(), "active_slot": None, "fencing_token": 1,
        "lease_expires_at": 1, "base_working_draft_revision": 1,
        "base_working_draft_hash": EMPTY_HASH, "input_manifest": {},
        "input_manifest_hash": "1" * 64, "provider_id": "provider-writing",
        "model_name_snapshot": "fake-writing-model", "result_working_draft_revision": 2,
        "result_content_hash": "NOT-A-HASH", "last_event_sequence": 2,
        "failure_code": None, "status": "completed", "created_at": 1,
        "updated_at": 1, "completed_at": 1,
    }

    with pytest.raises(DraftOperationStorageError):
        await service.start(command())
    assert gateway.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "last_sequence,result_hash",
    ((999, None), (1, "8" * 64)),
)
async def test_expired_projection_does_not_rewrite_invalid_running_state(
    last_sequence, result_hash
):
    from backend.services.draft_operations import DraftOperationStorageError

    service, repo, gateway, _, clock = make_service()
    operation_id = str(UUID(int=908))
    repo.operations[operation_id] = {
        "id": operation_id, "project_id": PROJECT_ID,
        "chapter_session_id": SESSION_ID, "operation_type": "generate_new",
        "idempotency_key": KEY, "request_fingerprint": _fingerprint(),
        "active_slot": 1, "fencing_token": 1,
        "lease_expires_at": clock.now, "base_working_draft_revision": 1,
        "base_working_draft_hash": EMPTY_HASH, "input_manifest": {},
        "input_manifest_hash": "1" * 64, "provider_id": "provider-writing",
        "model_name_snapshot": "fake-writing-model",
        "result_working_draft_revision": None, "result_content_hash": result_hash,
        "last_event_sequence": last_sequence, "failure_code": None,
        "status": "running",
        "created_at": 1, "updated_at": 1, "completed_at": None,
    }
    repo.session["active_draft_operation_id"] = operation_id

    with pytest.raises(DraftOperationStorageError):
        await service.start(command())
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_live_active_different_key_is_rejected():
    from backend.services.draft_operations import DraftOperationConflict

    service, repo, gateway, _, clock = make_service()
    active_id = str(UUID(int=902))
    repo.operations[active_id] = {
        "id": active_id, "project_id": PROJECT_ID, "chapter_session_id": SESSION_ID,
        "idempotency_key": str(UUID(int=903)), "active_slot": 1,
        "fencing_token": 1, "lease_expires_at": clock.now + 1, "status": "running",
    }
    with pytest.raises(DraftOperationConflict):
        await service.start(command())
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_elapsed_active_is_expired_before_new_fence_reserves():
    service, repo, gateway, _, clock = make_service()
    active_id = str(UUID(int=904))
    repo.operations[active_id] = {
        "id": active_id, "project_id": PROJECT_ID, "chapter_session_id": SESSION_ID,
        "idempotency_key": str(UUID(int=905)), "active_slot": 1,
        "fencing_token": 4, "lease_expires_at": clock.now, "status": "running",
        "updated_at": 1, "completed_at": None,
    }
    repo.session["draft_operation_fencing_token"] = 4
    repo.session["active_draft_operation_id"] = active_id

    result = await service.start(command())

    assert result.status == "completed"
    assert repo.operations[active_id]["status"] == "expired"
    new_attempt = next(row for key, row in repo.operations.items() if key != active_id)
    assert new_attempt["fencing_token"] == 5
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_late_result_after_new_fence_cannot_update_draft():
    repo = FakeRepository()

    def fence_late_result():
        operation = next(iter(repo.operations.values()))
        repo._expire(operation, 10_100)
        repo.session["draft_operation_fencing_token"] += 1

    gateway = FakeGateway(on_generate=fence_late_result)
    service, repo, gateway, _, _ = make_service(repo=repo, gateway=gateway)

    result = await service.start(command())

    assert result.status == "expired"
    assert repo.draft["revision"] == 1
    assert repo.revisions == []
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ("outline", "planning", "projection", "provider", "manifest", "base"))
async def test_authority_or_base_drift_expires_without_changing_draft(drift):
    repo = FakeRepository()

    def mutate():
        if drift == "outline":
            repo.outline["chapter_outline_hash"] = "7" * 64
        elif drift == "planning":
            repo.outline["planning_hash"] = "7" * 64
        elif drift == "projection":
            repo.projection["content_hash"] = "7" * 64
        elif drift == "provider":
            repo.provider["binding_hash"] = "7" * 64
        elif drift == "manifest":
            next(iter(repo.operations.values()))["input_manifest_hash"] = "7" * 64
        else:
            repo.draft["content_hash"] = "7" * 64

    gateway = FakeGateway(on_generate=mutate)
    service, repo, _, _, _ = make_service(repo=repo, gateway=gateway)

    result = await service.start(command())

    assert result.status == "expired"
    assert repo.draft["revision"] == 1
    assert repo.revisions == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,replacement",
    (
        ("api_key", "rotated-private-key"),
        ("base_url", "https://rotated.private.invalid/v1"),
        ("temperature", Decimal("0.000")),
        ("temperature", Decimal("NaN")),
        ("max_output_tokens", 9000),
    ),
)
async def test_private_provider_authority_drift_expires_without_draft_write(
    field, replacement
):
    repo = FakeRepository()

    def mutate():
        repo.provider[field] = replacement

    gateway = FakeGateway(on_generate=mutate)
    service, repo, _, _, _ = make_service(repo=repo, gateway=gateway)

    result = await service.start(command())

    assert result.status == "expired"
    assert repo.draft["revision"] == 1
    assert repo.revisions == []
    attempt = next(iter(repo.operations.values()))
    manifest_text = json.dumps(attempt["input_manifest"], ensure_ascii=False)
    assert "private-provider-key" not in manifest_text
    assert "private.provider.invalid" not in manifest_text


@pytest.mark.asyncio
async def test_equivalent_decimal_temperature_has_stable_provider_authority():
    repo = FakeRepository()

    def normalize_scale_only():
        repo.provider["temperature"] = Decimal("0.7200")

    gateway = FakeGateway(on_generate=normalize_scale_only)
    service, repo, _, _, _ = make_service(repo=repo, gateway=gateway)

    result = await service.start(command())

    assert result.status == "completed"
    assert repo.draft["revision"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    (
        "current_planning_hash",
        "current_seed_hash",
        "current_creation_hash",
        "current_bible_hash",
        "story_block_hash",
    ),
)
async def test_current_planning_or_baseline_drift_expires_without_draft_write(field):
    repo = FakeRepository()

    def mutate():
        repo.outline[field] = "9" * 64

    gateway = FakeGateway(on_generate=mutate)
    service, repo, _, _, _ = make_service(repo=repo, gateway=gateway)

    result = await service.start(command())

    assert result.status == "expired"
    assert repo.draft["revision"] == 1
    assert repo.revisions == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output,code",
    (
        (ChapterDraftProviderError("safe provider boundary"), "DraftProviderFailed"),
        ("\ud800", "DraftProviderResultInvalid"),
        ("private-provider-key", "DraftProviderResultInvalid"),
    ),
)
async def test_provider_or_validation_failure_records_fixed_failure(output, code):
    gateway = FakeGateway(output)
    service, repo, gateway, _, _ = make_service(gateway=gateway)

    result = await service.start(command())

    assert result.status == "failed"
    assert result.failure_code == code
    assert repo.draft["revision"] == 1
    assert repo.revisions == []
    assert repo.events[-1]["event_type"] == "failed"
    assert repo.events[-1]["closed_payload"] == {"failureCode": code}


@pytest.mark.asyncio
async def test_gateway_mutation_cannot_replace_frozen_secret_scan_or_authority():
    gateway = MutatingGateway()
    service, repo, gateway, _, _ = make_service(gateway=gateway)

    result = await service.start(command())

    assert result.status == "failed"
    assert result.failure_code == "DraftProviderResultInvalid"
    assert repo.draft["revision"] == 1
    assert repo.revisions == []
    operation = next(iter(repo.operations.values()))
    assert operation["status"] == "failed"
    assert operation["provider_id"] == "provider-writing"
    assert repo.provider["api_key"] == "private-provider-key"
    assert repo.provider["base_url"] == "https://private.provider.invalid/v1"
    assert gateway.calls[0]["provider"]["api_key"] == "gateway-mutated-key"


@pytest.mark.asyncio
async def test_unexpected_gateway_exception_raises_fixed_internal_error_and_leaves_recovery():
    from backend.services.draft_operations import DraftOperationUnexpectedProviderError

    gateway = FakeGateway(ValueError("remote body and secret detail"))
    service, repo, _, _, _ = make_service(gateway=gateway)

    with pytest.raises(DraftOperationUnexpectedProviderError) as exc_info:
        await service.start(command())

    assert str(exc_info.value) == "Draft provider failed unexpectedly"
    assert exc_info.value.__cause__ is None
    assert "remote body" not in str(exc_info.value)
    assert next(iter(repo.operations.values()))["status"] == "running"
    assert repo.session["active_draft_operation_id"] is not None


@pytest.mark.asyncio
async def test_gateway_cancellation_is_not_converted_to_provider_failure():
    gateway = FakeGateway(asyncio.CancelledError())
    service, repo, _, _, _ = make_service(gateway=gateway)

    with pytest.raises(asyncio.CancelledError):
        await service.start(command())
    assert next(iter(repo.operations.values()))["status"] == "running"


@pytest.mark.asyncio
async def test_zero_temperature_is_preserved_for_gateway():
    repo = FakeRepository()
    repo.provider["temperature"] = Decimal("0.000")
    service, repo, gateway, _, _ = make_service(repo=repo)

    result = await service.start(command())

    assert result.status == "completed"
    assert gateway.calls[0]["generation_config"]["temperature"] == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    (
        ("temperature", Decimal("NaN")),
        ("temperature", Decimal("Infinity")),
        ("temperature", Decimal("-0.1")),
        ("temperature", True),
        ("max_output_tokens", 0),
        ("max_output_tokens", True),
        ("max_output_tokens", "4500"),
    ),
)
async def test_invalid_provider_generation_config_fails_before_provider(field, value):
    from backend.services.draft_operations import DraftOperationPreconditionFailed

    service, repo, gateway, _, _ = make_service()
    repo.provider[field] = value

    with pytest.raises(DraftOperationPreconditionFailed):
        await service.start(command())
    assert gateway.calls == []
    assert repo.operations == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,value",
    (("snapshot", "before"), ("snapshot", "after"), ("event", 2), ("cas", True)),
)
async def test_settle_storage_failure_rolls_back_every_settle_write(failure, value):
    from backend.services.draft_operations import DraftOperationStorageError

    repo = FakeRepository()
    if failure == "snapshot":
        repo.fail_snapshot_role = value
    elif failure == "event":
        repo.fail_event_sequence = value
    else:
        repo.fail_cas = value
    service, repo, _, tracker, _ = make_service(repo=repo)

    with pytest.raises(DraftOperationStorageError):
        await service.start(command())

    assert tracker.active == 0
    assert repo.draft["revision"] == 1
    assert repo.revisions == []
    assert [row["event_type"] for row in repo.events] == ["started"]
    assert next(iter(repo.operations.values()))["status"] == "running"


@pytest.mark.asyncio
async def test_complete_terminal_failure_rolls_back_snapshots_cas_and_event_two():
    from backend.services.draft_operations import DraftOperationStorageError

    repo = FakeRepository()
    repo.fail_complete = True
    service, repo, _, _, _ = make_service(repo=repo)

    with pytest.raises(DraftOperationStorageError):
        await service.start(command())

    assert repo.draft["revision"] == 1
    assert repo.revisions == []
    assert [row["event_type"] for row in repo.events] == ["started"]
    operation = next(iter(repo.operations.values()))
    assert operation["status"] == "running"
    assert operation["last_event_sequence"] == 1
    assert repo.session["active_draft_operation_id"] == operation["id"]


@pytest.mark.asyncio
async def test_failed_terminal_failure_rolls_back_failed_event_and_status():
    from backend.services.draft_operations import DraftOperationStorageError

    repo = FakeRepository()
    repo.fail_terminal_failure = True
    gateway = FakeGateway(ChapterDraftProviderError("safe boundary failure"))
    service, repo, _, _, _ = make_service(repo=repo, gateway=gateway)

    with pytest.raises(DraftOperationStorageError):
        await service.start(command())

    assert repo.draft["revision"] == 1
    assert repo.revisions == []
    assert [row["event_type"] for row in repo.events] == ["started"]
    operation = next(iter(repo.operations.values()))
    assert operation["status"] == "running"
    assert operation["last_event_sequence"] == 1
    assert repo.session["active_draft_operation_id"] == operation["id"]


@pytest.mark.parametrize(
    "overrides",
    (
        {"project_id": "NOT-A-UUID"},
        {"chapter_session_id": "20000000-0000-4000-8000-00000000000A"},
        {"operation_type": "rewrite_full"},
        {"expected_working_draft_revision": True},
        {"expected_content_hash": "A" * 64},
        {"idempotency_key": "30000000-0000-4000-8000-000000000001 ",},
        {"author_instruction": "x" * 2001},
        {"author_instruction": "\ud800"},
    ),
)
def test_command_validation_is_strict(overrides):
    from backend.services.draft_operations import DraftOperationRequestInvalid

    service, _, _, _, _ = make_service()
    with pytest.raises(DraftOperationRequestInvalid):
        service.validate(command(**overrides))
