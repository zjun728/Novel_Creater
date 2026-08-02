from __future__ import annotations

import asyncio
import copy
from decimal import Decimal
import hashlib
import json
from uuid import UUID

import pytest

from backend.domain.json_contracts import canonical_hash, canonical_json
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


def _stored_attempt(row):
    stored = copy.deepcopy(row)
    partial = stored.setdefault("partial_output_text", "")
    stored.setdefault("partial_output_hash", hashlib.sha256(partial.encode()).hexdigest())
    stored.setdefault("partial_output_scalars", len(partial))
    stored.setdefault("heartbeat_at", stored.get("created_at", 0))
    stored.setdefault("cancelled_at", None)
    manifest = stored.get("input_manifest")
    if manifest == {}:
        manifest = {
            "schemaVersion": 1,
            "operationType": stored.get("operation_type", "generate_new"),
            "draft": {
                "revision": stored.get("base_working_draft_revision", 1),
                "contentHash": stored.get("base_working_draft_hash", EMPTY_HASH),
            },
            "model": {
                "providerId": stored.get("provider_id", "provider-writing"),
                "modelName": stored.get("model_name_snapshot", "fake-writing-model"),
                "stream": False,
                "supportsStreaming": True,
            },
        }
        stored["input_manifest"] = manifest
        stored["input_manifest_hash"] = canonical_hash(manifest)
    if (
        stored.get("status") == "completed"
        and not partial
        and isinstance(stored.get("result_content_hash"), str)
        and len(stored["result_content_hash"]) == 64
    ):
        partial = "stored completion"
        output_hash = hashlib.sha256(partial.encode()).hexdigest()
        stored["partial_output_text"] = partial
        stored["partial_output_hash"] = output_hash
        stored["partial_output_scalars"] = len(partial)
        stored["result_content_hash"] = output_hash
    if "input_manifest" in stored:
        manifest = stored.pop("input_manifest")
        stored["input_manifest_json"] = canonical_json(manifest)
    return stored


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
        self.events = []

    def factory(self):
        tracker = self

        class Transaction:
            async def __aenter__(self):
                self.snapshot = tracker.repository.snapshot()
                tracker.events.append("transaction-enter")
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
        if self.tracker is not None:
            self.tracker.events.append("gateway-return")
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
            "stream": False,
            "supports_streaming": True,
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
        return next((_stored_attempt(row) for row in self.operations.values()
                     if row["chapter_session_id"] == chapter_session_id
                     and row["idempotency_key"] == key), None)

    async def read_draft_operation(self, session, project_id, chapter_session_id, operation_id):
        row = self.operations.get(operation_id)
        if row and row["project_id"] == project_id and row["chapter_session_id"] == chapter_session_id:
            return _stored_attempt(row)
        return None

    async def read_active_draft_operation(self, session, chapter_session_id):
        return next((_stored_attempt(row) for row in self.operations.values()
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
            partial_output_text=row["partial_output_text"],
            partial_output_hash=row["partial_output_hash"],
            partial_output_scalars=row["partial_output_scalars"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )
        self.session["active_draft_operation_id"] = None
        return True

    async def append_draft_operation_delta(self, session, row):
        operation = self.operations[row["draft_operation_id"]]
        if not self._stream_guard_matches(operation, row):
            return False
        operation.update(
            partial_output_text=row["partial_output_text"],
            partial_output_hash=row["partial_output_hash"],
            partial_output_scalars=row["partial_output_scalars"],
            heartbeat_at=row["heartbeat_at"],
            lease_expires_at=row["lease_expires_at"],
            updated_at=row["updated_at"],
            last_event_sequence=row["sequence_num"],
        )
        self.events.append({**copy.deepcopy(row), "event_type": "delta"})
        return True

    async def append_draft_operation_heartbeat(self, session, row):
        operation = self.operations[row["draft_operation_id"]]
        if not self._stream_guard_matches(operation, row):
            return False
        operation.update(
            heartbeat_at=row["heartbeat_at"],
            lease_expires_at=row["lease_expires_at"],
            updated_at=row["updated_at"],
            last_event_sequence=row["sequence_num"],
        )
        self.events.append({**copy.deepcopy(row), "event_type": "heartbeat"})
        return True

    def _stream_guard_matches(self, operation, row):
        return (
            operation["status"] == "running"
            and operation["active_slot"] == 1
            and operation["fencing_token"] == row["fencing_token"]
            and operation["partial_output_hash"]
            == row["previous_partial_output_hash"]
            and operation["last_event_sequence"]
            == row["previous_last_event_sequence"]
            and operation["lease_expires_at"] > row["updated_at"]
        )

    async def cancel_draft_operation(self, session, row):
        operation = self.operations[row["draft_operation_id"]]
        if not self._stream_guard_matches(operation, row):
            return False
        if row["result_working_draft_revision"] is not None:
            if not await self.insert_working_draft_revision(
                session, row["before_revision"]
            ):
                return False
            if not await self.upsert_working_draft(
                session,
                row["working_draft"],
                expected_revision=row["expected_working_draft_revision"],
                expected_content_hash=row["expected_working_draft_hash"],
            ):
                return False
            if not await self.insert_working_draft_revision(
                session, row["after_revision"]
            ):
                return False
        operation.update(
            status="cancelled",
            active_slot=None,
            result_working_draft_revision=row["result_working_draft_revision"],
            result_content_hash=row["result_content_hash"],
            partial_output_text=row["partial_output_text"],
            partial_output_hash=row["partial_output_hash"],
            partial_output_scalars=row["partial_output_scalars"],
            failure_code=None,
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            cancelled_at=row["cancelled_at"],
            last_event_sequence=row["sequence_num"],
        )
        self.session["active_draft_operation_id"] = None
        self.events.append({**copy.deepcopy(row), "event_type": "cancelled"})
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
    registry = CapturingRegistry()
    service = DraftOperationService(
        repo,
        provider_gateway=gateway,
        task_registry=registry,
        transaction_factory=tracker.factory,
        id_factory=SequentialIds(),
        clock=clock,
    )
    service._test_registry = registry
    return (
        service,
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


async def start_and_finish(service, operation_command):
    started = await service.start(operation_command)
    launch = next(
        (
            item
            for item in service._test_registry.launches
            if item[0] == started.operation_id
        ),
        None,
    )
    if launch is None:
        return started
    service._test_registry.launches.remove(launch)
    await launch[1](asyncio.Event())
    return await service.read(
        started.project_id, started.chapter_session_id, started.operation_id
    )


@pytest.mark.asyncio
async def test_generate_new_reserves_calls_outside_transaction_and_atomically_commits():
    service, repo, gateway, tracker, _ = make_service()

    result = await start_and_finish(service, command())

    assert result.status == "completed"
    assert result.result_working_draft_revision == 2
    assert result.result_content_hash == repo.draft["content_hash"]
    assert tracker.active == 0
    assert tracker.entries == 3
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
async def test_public_stored_projection_returns_valid_completed_operation():
    service, repo, _, _, _ = make_service()
    await start_and_finish(service, command())
    stored = _stored_attempt(next(iter(repo.operations.values())))

    result = service.project_stored_result(stored)

    assert result.operation_id == stored["id"]
    assert result.status == "completed"
    assert result.last_event_sequence == 2
    assert result.result_content_hash == stored["result_content_hash"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "required_key",
    (
        "id", "project_id", "chapter_session_id", "operation_type",
        "idempotency_key", "request_fingerprint", "active_slot",
        "fencing_token", "lease_expires_at", "base_working_draft_revision",
        "base_working_draft_hash", "input_manifest_json",
        "input_manifest_hash", "provider_id", "model_name_snapshot",
        "result_working_draft_revision", "result_content_hash",
        "last_event_sequence", "failure_code", "partial_output_text",
        "partial_output_hash", "partial_output_scalars", "heartbeat_at",
        "status", "created_at", "updated_at", "completed_at", "cancelled_at",
    ),
)
async def test_public_stored_projection_requires_every_select_star_column(required_key):
    from backend.services.draft_operations import DraftOperationStorageError

    service, repo, _, _, _ = make_service()
    await start_and_finish(service, command())
    stored = _stored_attempt(next(iter(repo.operations.values())))
    stored.pop(required_key)

    with pytest.raises(DraftOperationStorageError):
        service.project_stored_result(stored)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", (True, "1"))
async def test_public_stored_projection_rejects_coerced_integer_and_time_columns(invalid):
    from backend.services.draft_operations import DraftOperationStorageError

    service, repo, _, _, _ = make_service()
    await start_and_finish(service, command())
    completed = _stored_attempt(next(iter(repo.operations.values())))
    for field in (
        "fencing_token", "lease_expires_at", "base_working_draft_revision",
        "result_working_draft_revision", "last_event_sequence", "created_at",
        "updated_at", "completed_at", "partial_output_scalars", "heartbeat_at",
    ):
        stored = {**completed, field: invalid}
        with pytest.raises(DraftOperationStorageError):
            service.project_stored_result(stored)

    running = {
        **completed,
        "status": "running",
        "active_slot": invalid,
        "last_event_sequence": 1,
        "result_working_draft_revision": None,
        "result_content_hash": None,
        "failure_code": None,
        "completed_at": None,
    }
    with pytest.raises(DraftOperationStorageError):
        service.project_stored_result(running)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    (
        {"input_manifest_json": "not-json"},
        {"input_manifest_json": "[]"},
        {"input_manifest_hash": "f" * 64},
        {"request_fingerprint": "F" * 64},
        {"idempotency_key": "not-a-uuid"},
    ),
)
async def test_public_stored_projection_validates_stored_json_hashes_and_identity(corruption):
    from backend.services.draft_operations import DraftOperationStorageError

    service, repo, _, _, _ = make_service()
    await start_and_finish(service, command())
    stored = {
        **_stored_attempt(next(iter(repo.operations.values()))),
        **corruption,
    }

    with pytest.raises(DraftOperationStorageError):
        service.project_stored_result(stored)


@pytest.mark.asyncio
async def test_public_stored_projection_fails_closed_for_malformed_row():
    from backend.services.draft_operations import DraftOperationStorageError

    service, repo, _, _, _ = make_service()
    await start_and_finish(service, command())
    stored = {
        **_stored_attempt(next(iter(repo.operations.values()))),
        "last_event_sequence": 2049,
    }

    with pytest.raises(DraftOperationStorageError):
        service.project_stored_result(stored)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    (
        "sequence-string",
        "result-revision-string",
        "active-bool",
        "expired-missing-result",
        "expired-missing-failure",
        "terminal-missing-completed-at",
        "terminal-bool-completed-at",
    ),
)
async def test_public_stored_projection_rejects_coerced_or_incomplete_rows(corruption):
    from backend.services.draft_operations import DraftOperationStorageError

    service, repo, _, _, _ = make_service()
    await start_and_finish(service, command())
    stored = _stored_attempt(next(iter(repo.operations.values())))
    if corruption == "sequence-string":
        stored["last_event_sequence"] = "2"
    elif corruption == "result-revision-string":
        stored["result_working_draft_revision"] = "2"
    elif corruption == "active-bool":
        stored.update({
            "status": "running",
            "active_slot": True,
            "last_event_sequence": 1,
            "result_working_draft_revision": None,
            "result_content_hash": None,
            "failure_code": None,
            "completed_at": None,
        })
    elif corruption == "expired-missing-result":
        stored.update({
            "status": "expired", "active_slot": None,
            "last_event_sequence": 1,
            "result_working_draft_revision": None,
            "result_content_hash": None,
            "failure_code": None,
        })
        stored.pop("result_content_hash")
    elif corruption == "expired-missing-failure":
        stored.update({
            "status": "expired", "active_slot": None,
            "last_event_sequence": 1,
            "result_working_draft_revision": None,
            "result_content_hash": None,
            "failure_code": None,
        })
        stored.pop("failure_code")
    elif corruption == "terminal-missing-completed-at":
        stored.pop("completed_at")
    else:
        stored["completed_at"] = True

    with pytest.raises(DraftOperationStorageError):
        service.project_stored_result(stored)


def test_public_stored_projection_requires_mapping():
    from backend.services.draft_operations import (
        DraftOperationService,
        DraftOperationStorageError,
    )

    with pytest.raises(DraftOperationStorageError):
        DraftOperationService.project_stored_result([])


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

    result = await start_and_finish(service, command())

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
        "fencing_token": 1, "lease_expires_at": clock.now + 30_000,
        "base_working_draft_revision": 1, "base_working_draft_hash": EMPTY_HASH,
        "input_manifest": {}, "input_manifest_hash": canonical_hash({}),
        "provider_id": "provider-writing", "model_name_snapshot": "fake-writing-model",
        "result_working_draft_revision": 2 if status == "completed" else None,
        "result_content_hash": "2" * 64 if status == "completed" else None,
        "last_event_sequence": 2 if status in {"completed", "failed"} else 1,
        "failure_code": "DraftProviderFailed" if status == "failed" else None,
        "status": status, "created_at": clock.now, "updated_at": clock.now,
        "heartbeat_at": clock.now,
        "completed_at": clock.now if status in {"completed", "failed"} else None,
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
        "input_manifest_hash": canonical_hash({}), "provider_id": "provider-writing",
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
    clock.now = 40_000
    operation_id = str(UUID(int=906))
    repo.operations[operation_id] = {
        "id": operation_id, "project_id": PROJECT_ID, "chapter_session_id": SESSION_ID,
        "operation_type": "generate_new", "idempotency_key": KEY,
        "request_fingerprint": _fingerprint(), "active_slot": 1, "fencing_token": 1,
        "lease_expires_at": clock.now, "base_working_draft_revision": 1,
        "base_working_draft_hash": EMPTY_HASH, "input_manifest": {},
        "input_manifest_hash": canonical_hash({}), "provider_id": "provider-writing",
        "model_name_snapshot": "fake-writing-model", "result_working_draft_revision": None,
        "result_content_hash": None, "last_event_sequence": 1, "failure_code": None,
        "status": "running", "created_at": 10_000, "updated_at": 10_000,
        "heartbeat_at": 10_000, "completed_at": None,
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
        "input_manifest_hash": canonical_hash({}), "provider_id": "provider-writing",
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
    ((2049, None), (1, "8" * 64)),
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
        "input_manifest_hash": canonical_hash({}), "provider_id": "provider-writing",
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

    result = await start_and_finish(service, command())

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
        repo._expire(operation, 40_000)
        repo.session["draft_operation_fencing_token"] += 1

    gateway = FakeGateway(on_generate=fence_late_result)
    service, repo, gateway, _, _ = make_service(repo=repo, gateway=gateway)

    result = await start_and_finish(service, command())

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
            operation = next(iter(repo.operations.values()))
            operation["input_manifest"] = {**operation["input_manifest"], "drift": True}
            operation["input_manifest_hash"] = canonical_hash(operation["input_manifest"])
        else:
            repo.draft["content_hash"] = "7" * 64

    gateway = FakeGateway(on_generate=mutate)
    service, repo, _, _, _ = make_service(repo=repo, gateway=gateway)

    result = await start_and_finish(service, command())

    assert result.status == "expired"
    assert result.last_event_sequence == 1
    assert repo.draft["revision"] == 1
    assert repo.revisions == []
    assert [event["event_type"] for event in repo.events] == ["started"]


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

    result = await start_and_finish(service, command())

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

    result = await start_and_finish(service, command())

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

    result = await start_and_finish(service, command())

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

    result = await start_and_finish(service, command())

    assert result.status == "failed"
    assert result.failure_code == code
    assert repo.draft["revision"] == 1
    assert repo.revisions == []
    assert repo.events[-1]["event_type"] == "failed"
    assert repo.events[-1]["closed_payload"] == {"failureCode": code}


@pytest.mark.asyncio
async def test_provider_output_scalar_bound_rejects_before_draft_or_recovery_write():
    gateway = FakeGateway("字" * 100_001)
    service, repo, _, tracker, _ = make_service(gateway=gateway)

    result = await start_and_finish(service, command())

    assert result.status == "failed"
    assert result.failure_code == "DraftProviderResultInvalid"
    assert repo.draft["revision"] == 1
    assert repo.revisions == []
    assert [event["event_type"] for event in repo.events] == ["started", "failed"]
    assert tracker.entries == 3


@pytest.mark.asyncio
async def test_provider_output_accepts_100000_astral_unicode_scalars():
    content = "😀" * 100_000
    gateway = FakeGateway(content)
    service, repo, _, _, _ = make_service(gateway=gateway)

    result = await start_and_finish(service, command())

    assert result.status == "completed"
    assert len(repo.draft["content"]) == 100_000
    assert repo.draft["content"] == content


@pytest.mark.asyncio
async def test_provider_output_validation_precedes_success_settlement_transaction():
    events = []

    class ProbeText(str):
        def strip(self, chars=None):
            events.append("content-validation")
            return super().strip(chars)

    gateway = FakeGateway(ProbeText("有效正文"))
    service, _, _, tracker, _ = make_service(gateway=gateway)
    tracker.events = events

    result = await start_and_finish(service, command())

    assert result.status == "completed"
    assert events == [
        "transaction-enter",
        "gateway-return",
        "content-validation",
        "transaction-enter",
        "transaction-enter",
    ]


@pytest.mark.asyncio
async def test_gateway_mutation_cannot_replace_frozen_secret_scan_or_authority():
    gateway = MutatingGateway()
    service, repo, gateway, _, _ = make_service(gateway=gateway)

    result = await start_and_finish(service, command())

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
async def test_unexpected_gateway_exception_records_fixed_invalid_failure():
    gateway = FakeGateway(ValueError("remote body and secret detail"))
    service, repo, _, _, _ = make_service(gateway=gateway)

    result = await start_and_finish(service, command())

    assert result.status == "failed"
    assert result.failure_code == "DraftProviderResultInvalid"
    assert "remote body" not in repr(result)


@pytest.mark.asyncio
async def test_gateway_cancellation_is_not_converted_to_provider_failure():
    gateway = FakeGateway(asyncio.CancelledError())
    service, repo, _, _, _ = make_service(gateway=gateway)

    with pytest.raises(asyncio.CancelledError):
        await start_and_finish(service, command())
    assert next(iter(repo.operations.values()))["status"] == "running"


@pytest.mark.asyncio
async def test_zero_temperature_is_preserved_for_gateway():
    repo = FakeRepository()
    repo.provider["temperature"] = Decimal("0.000")
    service, repo, gateway, _, _ = make_service(repo=repo)

    result = await start_and_finish(service, command())

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
        await start_and_finish(service, command())

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
        await start_and_finish(service, command())

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
        await start_and_finish(service, command())

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


def test_command_validation_counts_unicode_scalar_values():
    from backend.services.draft_operations import DraftOperationRequestInvalid

    service, _, _, _, _ = make_service()
    for size in (1001, 2000):
        validated = service.validate(command(author_instruction="😀" * size))
        assert len(validated.author_instruction) == size
    with pytest.raises(DraftOperationRequestInvalid):
        service.validate(command(author_instruction="😀" * 2001))


class CapturingRegistry:
    def __init__(self, *, failure: Exception | None = None):
        self.failure = failure
        self.launches = []
        self.cancelled = []

    def launch(self, operation_id, worker):
        if self.failure is not None:
            raise self.failure
        self.launches.append((operation_id, worker))
        return asyncio.Event()

    def cancel(self, operation_id):
        self.cancelled.append(operation_id)
        return True


class StreamingGateway(FakeGateway):
    def __init__(self, chunks=(), **kwargs):
        super().__init__(**kwargs)
        self.chunks = tuple(chunks)
        self.stream_calls = []

    async def stream(self, *, provider, messages, generation_config):
        assert self.tracker is None or self.tracker.active == 0
        self.stream_calls.append((dict(provider), list(messages), dict(generation_config)))
        for chunk in self.chunks:
            yield chunk


def make_background_service(*, repo=None, gateway=None, registry=None, clock=None):
    from backend.services.draft_operations import DraftOperationService

    repo = repo or FakeRepository()
    repo.provider.setdefault("stream", True)
    repo.provider.setdefault("supports_streaming", True)
    clock = clock or FakeClock()
    tracker = TransactionTracker(repo)
    gateway = gateway or StreamingGateway(chunks=("正文",), tracker=tracker)
    gateway.tracker = tracker
    registry = registry or CapturingRegistry()
    service = DraftOperationService(
        repo,
        provider_gateway=gateway,
        task_registry=registry,
        transaction_factory=tracker.factory,
        id_factory=SequentialIds(),
        clock=clock,
    )
    return service, repo, gateway, registry, tracker, clock


@pytest.mark.asyncio
async def test_start_is_reserve_only_and_launches_exactly_once_for_new_attempt():
    service, repo, gateway, registry, tracker, _ = make_background_service()

    result = await service.start(command())

    assert result.status == "running"
    assert result.last_event_sequence == 1
    assert result.partial_output == ""
    assert result.partial_output_hash == EMPTY_HASH
    assert result.partial_output_scalars == 0
    assert len(registry.launches) == 1
    assert gateway.calls == []
    assert gateway.stream_calls == []
    assert tracker.entries == 1
    attempt = next(iter(repo.operations.values()))
    assert attempt["lease_expires_at"] == 40_000
    assert attempt["partial_output_hash"] == EMPTY_HASH
    assert attempt["partial_output_scalars"] == 0


@pytest.mark.asyncio
async def test_same_key_running_replay_never_relaunches_or_calls_provider():
    service, repo, gateway, registry, _, _ = make_background_service()
    first = await service.start(command())
    replay = await service.start(command())

    assert replay == first
    assert len(registry.launches) == 1
    assert gateway.calls == []
    assert gateway.stream_calls == []


@pytest.mark.asyncio
async def test_launch_failure_keeps_durable_running_attempt_and_replay_never_relaunches():
    from backend.services.draft_operations import DraftOperationUnexpectedProviderError

    registry = CapturingRegistry(failure=RuntimeError("registry private detail"))
    service, repo, _, _, _, _ = make_background_service(registry=registry)

    with pytest.raises(DraftOperationUnexpectedProviderError):
        await service.start(command())
    operation = next(iter(repo.operations.values()))
    assert operation["status"] == "running"

    registry.failure = None
    replay = await service.start(command())
    assert replay.status == "running"
    assert registry.launches == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested,supported,use_stream",
    ((True, True, True), (True, False, False), (False, True, False), (False, False, False)),
)
async def test_worker_uses_only_frozen_stream_capability_pair(requested, supported, use_stream):
    repo = FakeRepository()
    repo.provider.update(stream=requested, supports_streaming=supported)
    gateway = StreamingGateway(chunks=("正文",), output="非流正文")
    service, repo, gateway, registry, _, _ = make_background_service(
        repo=repo, gateway=gateway
    )

    await service.start(command())
    attempt = next(iter(repo.operations.values()))
    assert attempt["input_manifest"]["model"]["stream"] is requested
    assert attempt["input_manifest"]["model"]["supportsStreaming"] is supported
    repo.provider.update(stream=not requested, supports_streaming=not supported)

    _, worker = registry.launches[0]
    await worker(asyncio.Event())

    assert bool(gateway.stream_calls) is use_stream
    assert bool(gateway.calls) is (not use_stream)
    assert next(iter(repo.operations.values()))["status"] == "expired"
    assert repo.draft["revision"] == 1


@pytest.mark.asyncio
async def test_read_is_owner_scoped_and_expires_elapsed_running_without_event():
    from backend.services.draft_operations import DraftOperationNotFound

    service, repo, _, registry, _, clock = make_background_service()
    started = await service.start(command())
    clock.now = 40_000

    expired = await service.read(PROJECT_ID, SESSION_ID, started.operation_id)
    assert expired.status == "expired"
    assert expired.last_event_sequence == 1
    assert [event["event_type"] for event in repo.events] == ["started"]
    assert len(registry.launches) == 1

    with pytest.raises(DraftOperationNotFound):
        await service.read(str(UUID(int=999)), SESSION_ID, started.operation_id)


@pytest.mark.asyncio
async def test_cancel_uses_only_persisted_partial_normalizes_and_is_idempotent():
    service, repo, _, registry, _, _ = make_background_service()
    started = await service.start(command())
    operation = repo.operations[started.operation_id]
    operation.update(
        partial_output_text="  已持久化片段  \n",
        partial_output_hash=hashlib.sha256("  已持久化片段  \n".encode()).hexdigest(),
        partial_output_scalars=len("  已持久化片段  \n"),
        last_event_sequence=7,
    )

    cancelled = await service.cancel(PROJECT_ID, SESSION_ID, started.operation_id)
    repeated = await service.cancel(PROJECT_ID, SESSION_ID, started.operation_id)

    assert cancelled.status == "cancelled"
    assert cancelled.partial_output == "已持久化片段"
    assert cancelled.result_content_hash == hashlib.sha256("已持久化片段".encode()).hexdigest()
    assert repo.draft["content"] == "已持久化片段"
    assert repeated == cancelled
    assert registry.cancelled == [started.operation_id]
    assert [event["event_type"] for event in repo.events].count("cancelled") == 1


@pytest.mark.asyncio
async def test_cancel_empty_or_whitespace_partial_preserves_working_draft():
    for partial in ("", " \n\t "):
        service, repo, _, _, _, _ = make_background_service()
        started = await service.start(command())
        operation = repo.operations[started.operation_id]
        operation.update(
            partial_output_text=partial,
            partial_output_hash=hashlib.sha256(partial.encode()).hexdigest(),
            partial_output_scalars=len(partial),
            last_event_sequence=2 if partial else 1,
        )
        original = copy.deepcopy(repo.draft)

        result = await service.cancel(PROJECT_ID, SESSION_ID, started.operation_id)

        assert result.status == "cancelled"
        assert result.partial_output == ""
        assert repo.draft == original


@pytest.mark.asyncio
async def test_stream_split_secret_is_rejected_before_any_delta_is_persisted():
    repo = FakeRepository()
    repo.provider.update(stream=True, supports_streaming=True)
    gateway = StreamingGateway(chunks=("private-", "provider-key"))
    service, repo, _, registry, _, _ = make_background_service(
        repo=repo, gateway=gateway
    )

    started = await service.start(command())
    await registry.launches[0][1](asyncio.Event())
    result = await service.read(PROJECT_ID, SESSION_ID, started.operation_id)

    assert result.status == "failed"
    assert result.failure_code == "DraftProviderResultInvalid"
    assert result.partial_output == ""
    assert [event["event_type"] for event in repo.events] == ["started", "failed"]


@pytest.mark.asyncio
async def test_terminal_event_can_use_reserved_sequence_2048():
    service, repo, _, registry, _, _ = make_background_service()
    started = await service.start(command())
    operation = repo.operations[started.operation_id]
    operation["last_event_sequence"] = 2047

    await registry.launches[0][1](asyncio.Event())
    result = await service.read(PROJECT_ID, SESSION_ID, started.operation_id)

    assert result.status == "completed"
    assert result.last_event_sequence == 2048
    assert repo.events[-1]["event_type"] == "completed"
    assert repo.events[-1]["sequence_num"] == 2048


@pytest.mark.asyncio
async def test_completion_replaces_partial_snapshot_with_exact_normalized_terminal():
    gateway = StreamingGateway(chunks=("  exact terminal  \n",))
    repo = FakeRepository()
    repo.provider.update(stream=True, supports_streaming=True)
    service, repo, _, registry, _, _ = make_background_service(
        repo=repo, gateway=gateway
    )

    started = await service.start(command())
    await registry.launches[0][1](asyncio.Event())
    result = await service.read(PROJECT_ID, SESSION_ID, started.operation_id)

    assert result.status == "completed"
    assert result.partial_output == "exact terminal"
    assert result.partial_output == repo.draft["content"]
    assert result.partial_output_hash == result.result_content_hash
    assert result.partial_output_scalars == len("exact terminal")
    delta = next(event for event in repo.events if event["event_type"] == "delta")
    assert delta["closed_payload"] == {
        "text": "  exact terminal  \n",
        "partialOutputHash": hashlib.sha256(
            "  exact terminal  \n".encode()
        ).hexdigest(),
        "partialOutputScalars": len("  exact terminal  \n"),
    }


@pytest.mark.asyncio
async def test_each_persisted_delta_contains_only_its_new_suffix():
    first = "甲" * 256
    second = "乙" * 256
    gateway = StreamingGateway(chunks=(first, second))
    repo = FakeRepository()
    repo.provider.update(stream=True, supports_streaming=True)
    service, repo, _, registry, _, _ = make_background_service(
        repo=repo, gateway=gateway
    )

    await service.start(command())
    await registry.launches[0][1](asyncio.Event())
    deltas = [event for event in repo.events if event["event_type"] == "delta"]

    assert [event["closed_payload"]["text"] for event in deltas] == [
        first,
        second,
    ]
    assert deltas[-1]["closed_payload"]["partialOutputScalars"] == 512
    assert deltas[-1]["closed_payload"]["partialOutputHash"] == hashlib.sha256(
        (first + second).encode("utf-8")
    ).hexdigest()


@pytest.mark.asyncio
async def test_internally_owned_default_registry_starts_launches_and_replay_does_not_relaunch():
    from backend.services.draft_operations import DraftOperationService

    repo = FakeRepository()
    tracker = TransactionTracker(repo)
    gateway = FakeGateway(tracker=tracker)
    service = DraftOperationService(
        repo,
        provider_gateway=gateway,
        transaction_factory=tracker.factory,
        id_factory=SequentialIds(),
        clock=FakeClock(),
    )

    started = await service.start(command())
    for _ in range(100):
        stored = repo.operations[started.operation_id]
        if stored["status"] == "completed":
            break
        await asyncio.sleep(0)
    assert stored["status"] == "completed"
    replay = await service.start(command())
    for _ in range(100):
        if service._registry.size == 0:
            break
        await asyncio.sleep(0)

    assert replay.status == "completed"
    assert len(gateway.calls) == 1
    assert service._registry.size == 0


@pytest.mark.asyncio
async def test_stream_persists_exact_whitespace_then_cancel_normalizes_to_empty():
    class StallingWhitespaceGateway(StreamingGateway):
        def __init__(self):
            super().__init__(chunks=())
            self.release = asyncio.Event()

        async def stream(self, *, provider, messages, generation_config):
            assert self.tracker is None or self.tracker.active == 0
            self.stream_calls.append((dict(provider), list(messages), dict(generation_config)))
            yield " " * 256
            await self.release.wait()

    repo = FakeRepository()
    repo.provider.update(stream=True, supports_streaming=True)
    gateway = StallingWhitespaceGateway()
    service, repo, _, registry, _, _ = make_background_service(
        repo=repo, gateway=gateway
    )
    started = await service.start(command())
    worker = asyncio.create_task(registry.launches[0][1](asyncio.Event()))
    for _ in range(100):
        if repo.operations[started.operation_id]["last_event_sequence"] == 2:
            break
        await asyncio.sleep(0)

    persisted = repo.operations[started.operation_id]
    assert persisted["partial_output_text"] == " " * 256
    assert persisted["partial_output_scalars"] == 256
    assert persisted["partial_output_hash"] == hashlib.sha256(b" " * 256).hexdigest()
    assert persisted["lease_expires_at"] == persisted["heartbeat_at"] + 30_000

    cancelled = await service.cancel(PROJECT_ID, SESSION_ID, started.operation_id)
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker

    assert cancelled.status == "cancelled"
    assert cancelled.partial_output == ""
    assert cancelled.partial_output_hash == EMPTY_HASH
    assert cancelled.partial_output_scalars == 0
    assert repo.draft["revision"] == 1


@pytest.mark.asyncio
async def test_projector_rejects_cancelled_nonempty_revision_not_base_plus_one():
    from backend.services.draft_operations import DraftOperationStorageError

    service, repo, _, registry, _, _ = make_background_service()
    started = await service.start(command())
    operation = repo.operations[started.operation_id]
    partial = "persisted"
    operation.update(
        partial_output_text=partial,
        partial_output_hash=hashlib.sha256(partial.encode()).hexdigest(),
        partial_output_scalars=len(partial),
        last_event_sequence=2,
    )
    await service.cancel(PROJECT_ID, SESSION_ID, started.operation_id)
    stored = _stored_attempt(operation)
    stored["result_working_draft_revision"] = 3

    with pytest.raises(DraftOperationStorageError):
        service.project_stored_result(stored)


@pytest.mark.asyncio
async def test_projector_reserves_sequence_2048_for_nonexpired_terminals():
    from backend.services.draft_operations import DraftOperationStorageError

    service, repo, _, _, _, clock = make_background_service()
    started = await service.start(command())
    stored = _stored_attempt(repo.operations[started.operation_id])
    stored.update(
        status="expired",
        active_slot=None,
        last_event_sequence=2048,
        updated_at=clock.now + 30_000,
        completed_at=clock.now + 30_000,
    )

    with pytest.raises(DraftOperationStorageError):
        service.project_stored_result(stored)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    (
        "lease-duration",
        "running-heartbeat-update",
        "terminal-heartbeat-after-update",
        "terminal-after-lease",
        "expired-completed-mismatch",
    ),
)
async def test_projector_enforces_exact_timing_correlations(corruption):
    from backend.services.draft_operations import DraftOperationStorageError

    service, repo, _, _, _, clock = make_background_service()
    started = await service.start(command())
    stored = _stored_attempt(repo.operations[started.operation_id])
    if corruption == "lease-duration":
        stored["lease_expires_at"] += 1
    elif corruption == "running-heartbeat-update":
        stored["heartbeat_at"] += 1
    elif corruption == "terminal-heartbeat-after-update":
        stored.update(
            status="failed",
            active_slot=None,
            last_event_sequence=2,
            failure_code="DraftProviderFailed",
            completed_at=clock.now + 1,
            updated_at=clock.now + 1,
            heartbeat_at=clock.now + 2,
            lease_expires_at=clock.now + 30_002,
        )
    elif corruption == "terminal-after-lease":
        stored.update(
            status="failed",
            active_slot=None,
            last_event_sequence=2,
            failure_code="DraftProviderFailed",
            completed_at=clock.now + 30_000,
            updated_at=clock.now + 30_000,
        )
    else:
        stored.update(
            status="expired",
            active_slot=None,
            completed_at=clock.now + 1,
            updated_at=clock.now,
        )

    with pytest.raises(DraftOperationStorageError):
        service.project_stored_result(stored)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    ("starting-sequence", "starting-partial", "running-seq1-partial"),
)
async def test_projector_enforces_initial_state_correlations(state):
    from backend.services.draft_operations import DraftOperationStorageError

    service, repo, _, _, _, _ = make_background_service()
    started = await service.start(command())
    stored = _stored_attempt(repo.operations[started.operation_id])
    if state.startswith("starting"):
        stored["status"] = "starting"
    if state == "starting-sequence":
        stored["last_event_sequence"] = 2
    else:
        partial = "unexpected"
        stored.update(
            partial_output_text=partial,
            partial_output_hash=hashlib.sha256(partial.encode()).hexdigest(),
            partial_output_scalars=len(partial),
        )

    with pytest.raises(DraftOperationStorageError):
        service.project_stored_result(stored)


@pytest.mark.asyncio
async def test_projector_accepts_running_heartbeat_sequence_with_empty_partial():
    service, repo, _, _, _, clock = make_background_service()
    started = await service.start(command())
    stored = _stored_attempt(repo.operations[started.operation_id])
    stored.update(
        last_event_sequence=2,
        heartbeat_at=clock.now + 10_000,
        updated_at=clock.now + 10_000,
        lease_expires_at=clock.now + 40_000,
    )

    projected = service.project_stored_result(stored)

    assert projected.status == "running"
    assert projected.last_event_sequence == 2
    assert projected.partial_output == ""


@pytest.mark.asyncio
async def test_cancel_nonempty_partial_rejects_external_working_draft_drift_atomically():
    from backend.services.draft_operations import DraftOperationConflict

    service, repo, _, registry, _, _ = make_background_service()
    started = await service.start(command())
    attempt = repo.operations[started.operation_id]
    partial = "persisted recovery"
    attempt.update(
        partial_output_text=partial,
        partial_output_hash=hashlib.sha256(partial.encode()).hexdigest(),
        partial_output_scalars=len(partial),
        last_event_sequence=2,
    )
    external_content = "用户在 operation 运行期间保存的新稿"
    external_hash = hashlib.sha256(external_content.encode()).hexdigest()
    repo.draft.update(
        revision=2,
        content=external_content,
        content_hash=external_hash,
        updated_at=9_999,
    )
    external_draft = copy.deepcopy(repo.draft)

    with pytest.raises(DraftOperationConflict):
        await service.cancel(PROJECT_ID, SESSION_ID, started.operation_id)

    assert repo.draft == external_draft
    assert repo.revisions == []
    assert attempt["status"] == "running"
    assert attempt["result_working_draft_revision"] is None
    assert attempt["result_content_hash"] is None
    assert registry.cancelled == []
    readable = await service.read(PROJECT_ID, SESSION_ID, started.operation_id)
    assert readable.status == "running"
    assert readable.partial_output == partial


@pytest.mark.asyncio
@pytest.mark.parametrize("native_error", (RuntimeError, ValueError))
async def test_raw_delta_storage_exception_does_not_become_provider_failure(
    native_error
):
    from backend.services.draft_operations import DraftOperationStorageError

    class ExplodingDeltaRepository(FakeRepository):
        async def append_draft_operation_delta(self, session, row):
            raise native_error("private database detail")

    repo = ExplodingDeltaRepository()
    repo.provider.update(stream=True, supports_streaming=True)
    gateway = StreamingGateway(chunks=("x" * 256,))
    service, repo, _, registry, _, _ = make_background_service(
        repo=repo, gateway=gateway
    )
    started = await service.start(command())

    with pytest.raises(DraftOperationStorageError):
        await registry.launches[0][1](asyncio.Event())

    attempt = repo.operations[started.operation_id]
    assert attempt["status"] == "running"
    assert attempt["failure_code"] is None
    assert [event["event_type"] for event in repo.events] == ["started"]


@pytest.mark.asyncio
async def test_reserve_locks_active_attempt_before_working_draft():
    class RecordingReserveRepository(FakeRepository):
        def __init__(self):
            super().__init__()
            self.lock_order = []

        async def lock_project(self, session, project_id):
            self.lock_order.append("project")
            return await super().lock_project(session, project_id)

        async def lock_session_for_operation(
            self, session, project_id, chapter_session_id
        ):
            self.lock_order.append("session")
            return await super().lock_session_for_operation(
                session, project_id, chapter_session_id
            )

        async def read_active_draft_operation(self, session, chapter_session_id):
            self.lock_order.append("attempt")
            return await super().read_active_draft_operation(
                session, chapter_session_id
            )

        async def lock_working_draft_for_operation(
            self, session, project_id, chapter_session_id
        ):
            self.lock_order.append("draft")
            return await super().lock_working_draft_for_operation(
                session, project_id, chapter_session_id
            )

    repo = RecordingReserveRepository()
    service, repo, _, _, _ = make_service(repo=repo)

    await service.start(command())

    assert repo.lock_order[:2] == ["project", "session"]
    assert repo.lock_order.index("attempt") < repo.lock_order.index("draft")


@pytest.mark.asyncio
async def test_raw_transaction_exception_is_fixed_storage_error():
    from contextlib import asynccontextmanager

    from backend.services.draft_operations import (
        DraftOperationService,
        DraftOperationStorageError,
    )

    @asynccontextmanager
    async def broken_transaction():
        raise RuntimeError("private transaction detail")
        yield  # pragma: no cover

    service = DraftOperationService(
        FakeRepository(), transaction_factory=broken_transaction
    )

    with pytest.raises(DraftOperationStorageError) as exc_info:
        await service.read(PROJECT_ID, SESSION_ID, str(UUID(int=31)))

    assert str(exc_info.value) == "draft operation storage transaction failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ("delta", "read"))
async def test_operation_writes_lock_project_then_session_then_attempt(path):
    class RecordingLockRepository(FakeRepository):
        def __init__(self):
            super().__init__()
            self.lock_order = []

        async def lock_project(self, session, project_id):
            self.lock_order.append("project")
            return await super().lock_project(session, project_id)

        async def lock_session_for_operation(
            self, session, project_id, chapter_session_id
        ):
            self.lock_order.append("session")
            return await super().lock_session_for_operation(
                session, project_id, chapter_session_id
            )

        async def read_draft_operation(
            self, session, project_id, chapter_session_id, operation_id
        ):
            self.lock_order.append("attempt")
            return await super().read_draft_operation(
                session, project_id, chapter_session_id, operation_id
            )

    repo = RecordingLockRepository()
    repo.provider.update(stream=True, supports_streaming=True)
    gateway = StreamingGateway(chunks=("x" * 256,))
    service, repo, _, registry, _, _ = make_background_service(
        repo=repo, gateway=gateway
    )
    started = await service.start(command())
    repo.lock_order.clear()

    if path == "delta":
        await registry.launches[0][1](asyncio.Event())
    else:
        await service.read(PROJECT_ID, SESSION_ID, started.operation_id)

    assert repo.lock_order[:3] == ["project", "session", "attempt"]
