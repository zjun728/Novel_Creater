from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import re
from uuid import UUID

import pytest

from backend.gateways.chapter_draft_provider import ChapterDraftProviderError
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.services.chapter_sessions import (
    ChapterSessionConflict,
    ChapterSessionService,
    LoadDraftCandidate,
    SaveDraftCandidate,
    SaveWorkingDraft,
)
from backend.services.draft_operations import (
    DRAFT_OPERATION_LEASE_MS,
    DraftOperationConflict,
    DraftOperationIdempotencyConflict,
    DraftOperationService,
    StartDraftOperation,
    UndoLocalDraft,
)
from backend.tests.integration.test_authoritative_chapter_session import (
    PROJECT,
    _confirmed_outline,
    _create_command,
)
from backend.tests.integration.test_contract_drafts import PROVIDER
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql
_DATABASE_NAME = re.compile(r"novel_creator_test_[0-9a-f]{32}")
_TIMEOUT = 10
_NOW = 2_010_000_000_000
_GENERATED_A = "集成生成稿甲：门轴轻响，来人停在灯影之外。"
_GENERATED_B = "集成生成稿乙：雨线掠过窗棂，新的选择已经生效。"


class _SequentialIds:
    def __init__(self):
        self._value = 10_000

    def __call__(self) -> str:
        self._value += 1
        return str(UUID(int=self._value))


class _Clock:
    def __init__(self, now: int = _NOW):
        self.now = now

    def __call__(self) -> int:
        return self.now


class _ProviderBoundary:
    def __init__(
        self,
        output: str = _GENERATED_A,
        *,
        entered: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
        failure: ChapterDraftProviderError | None = None,
        transaction_probe=None,
    ):
        self.output = output
        self.entered = entered
        self.release = release
        self.failure = failure
        self.transaction_probe = transaction_probe
        self.invocations = 0
        self.active_transaction_observations = []

    async def generate(self, *, provider, messages, generation_config):
        self.invocations += 1
        if self.transaction_probe is not None:
            self.active_transaction_observations.append(
                self.transaction_probe.active
            )
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await asyncio.wait_for(self.release.wait(), timeout=_TIMEOUT)
        if self.transaction_probe is not None:
            self.active_transaction_observations.append(
                self.transaction_probe.active
            )
        if self.failure is not None:
            raise self.failure
        return self.output


class _ObservedTransactionSession:
    def __init__(self, delegate, probe):
        self._delegate = delegate
        self._probe = probe
        self._observed_first_call = False

    def _observe_first_call(self):
        if not self._observed_first_call:
            self._observed_first_call = True
            self._probe.observe_first_call()

    async def execute(self, sql, args=None):
        self._observe_first_call()
        return await self._delegate.execute(sql, args)

    async def fetchone(self, sql, args=None):
        self._observe_first_call()
        return await self._delegate.fetchone(sql, args)

    async def fetchall(self, sql, args=None):
        self._observe_first_call()
        return await self._delegate.fetchall(sql, args)


class _TransactionLifecycleProbe:
    """Observe, but never replace, disposable MySQL transaction lifetimes."""

    def __init__(self, delegate, *, first_call_target: int = 1):
        self._delegate = delegate
        self._first_call_target = first_call_target
        self.first_calls_ready = asyncio.Event()
        self.active = 0
        self.entries = 0
        self.exits = 0
        self.first_calls = 0

    def observe_first_call(self):
        self.first_calls += 1
        if self.first_calls >= self._first_call_target:
            self.first_calls_ready.set()

    @asynccontextmanager
    async def factory(self):
        async with self._delegate() as session:
            self.active += 1
            self.entries += 1
            try:
                yield _ObservedTransactionSession(session, self)
            finally:
                self.active -= 1
                self.exits += 1


async def _prove_owned_database(disposable_mysql) -> None:
    selected = await disposable_mysql.session.fetchone(
        "SELECT DATABASE() AS database_name"
    )
    assert selected == {"database_name": disposable_mysql.database_name}
    assert _DATABASE_NAME.fullmatch(disposable_mysql.database_name)


async def _workspace(disposable_mysql):
    await _prove_owned_database(disposable_mysql)
    _, planning, outline = await _confirmed_outline(disposable_mysql)
    await disposable_mysql.session.execute(
        "UPDATE provider_profiles SET stream=0 WHERE id=%s", (PROVIDER,)
    )
    transaction_factory = transaction_factory_for(
        disposable_mysql.connection_config
    )
    chapter_service = ChapterSessionService(
        ChapterSessionRepository(),
        transaction_factory=transaction_factory,
    )
    workspace = await chapter_service.create_session(
        _create_command(planning, outline)
    )
    return workspace, transaction_factory, chapter_service


def _operation_service(
    transaction_factory,
    gateway,
    *,
    ids: _SequentialIds | None = None,
    clock: _Clock | None = None,
):
    return DraftOperationService(
        ChapterSessionRepository(),
        provider_gateway=gateway,
        transaction_factory=transaction_factory,
        id_factory=ids or _SequentialIds(),
        clock=clock or _Clock(),
    )


async def _settled_result(service, started):
    async def worker_finished():
        while service._registry.size:
            await asyncio.sleep(0)

    await asyncio.wait_for(worker_finished(), timeout=_TIMEOUT)
    return await service.read(
        started.project_id, started.chapter_session_id, started.operation_id
    )


async def _cleanup_blocked_workers(release, services, start_tasks):
    release.set()
    for task in start_tasks:
        if not task.done():
            task.cancel()
    if start_tasks:
        try:
            await asyncio.gather(*start_tasks, return_exceptions=True)
        except BaseException:
            pass
    for service in services:
        try:
            await service._registry.aclose()
        except BaseException:
            pass


@asynccontextmanager
async def _blocked_worker_scope(release, *, services, start_tasks=()):
    try:
        yield
    except BaseException:
        await _cleanup_blocked_workers(release, services, start_tasks)
        raise


async def _release_and_settle(release, service, started):
    release.set()
    return await _settled_result(service, started)


def _command(workspace, key: str, *, instruction: str = "增强人物试探"):
    return StartDraftOperation(
        project_id=PROJECT,
        chapter_session_id=workspace.session.id,
        operation_type="generate_new",
        expected_working_draft_revision=workspace.working_draft.revision,
        expected_content_hash=workspace.working_draft.content_hash,
        idempotency_key=key,
        author_instruction=instruction,
    )


def _local_command(workspace, key: str, *, operation_type="rewrite_selection"):
    content = workspace.working_draft.content
    selected = "目标"
    start = content.index(selected)
    return StartDraftOperation(
        project_id=PROJECT,
        chapter_session_id=workspace.session.id,
        operation_type=operation_type,
        expected_working_draft_revision=workspace.working_draft.revision,
        expected_content_hash=workspace.working_draft.content_hash,
        idempotency_key=key,
        author_instruction="保持克制",
        start_offset=start,
        end_offset=start + len(selected),
        selected_text_hash=hashlib.sha256(selected.encode("utf-8")).hexdigest(),
    )


async def _queue_reservation_race(
    transaction_factory,
    probe,
    service,
    commands,
):
    tasks = []
    async with transaction_factory() as lock_session:
        await lock_session.fetchone(
            "SELECT id FROM projects WHERE id=%s FOR UPDATE",
            (commands[0].project_id,),
        )
        await lock_session.fetchone(
            """SELECT id FROM chapter_sessions
                 WHERE project_id=%s AND id=%s FOR UPDATE""",
            (commands[0].project_id, commands[0].chapter_session_id),
        )
        tasks = [
            asyncio.create_task(service.start(command))
            for command in commands
        ]
        try:
            await asyncio.wait_for(
                probe.first_calls_ready.wait(), timeout=_TIMEOUT
            )
            assert probe.active == len(commands)
            assert probe.first_calls == len(commands)
            assert all(not task.done() for task in tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
    return tasks


async def _attempts(session, chapter_session_id: str):
    return await session.fetchall(
        """SELECT * FROM draft_operation_attempts
             WHERE chapter_session_id=%s ORDER BY fencing_token""",
        (chapter_session_id,),
    )


async def _events(session, operation_id: str):
    return await session.fetchall(
        """SELECT * FROM draft_operation_events
             WHERE draft_operation_id=%s ORDER BY sequence_num""",
        (operation_id,),
    )


async def _recovery(session, chapter_session_id: str):
    return await session.fetchall(
        """SELECT * FROM working_draft_revisions
             WHERE chapter_session_id=%s
             ORDER BY working_draft_revision,snapshot_role""",
        (chapter_session_id,),
    )


async def _draft(session, chapter_session_id: str):
    return await session.fetchone(
        "SELECT * FROM working_drafts WHERE chapter_session_id=%s",
        (chapter_session_id,),
    )


async def _session_owner(session, chapter_session_id: str):
    return await session.fetchone(
        """SELECT active_draft_operation_id,draft_operation_fencing_token
             FROM chapter_sessions WHERE id=%s""",
        (chapter_session_id,),
    )


def _json_object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8")
    return json.loads(value)


@pytest.mark.asyncio
async def test_production_reservation_persists_safe_empty_streaming_state(
    disposable_mysql,
):
    workspace, transaction_factory, _ = await _workspace(disposable_mysql)
    entered = asyncio.Event()
    release = asyncio.Event()
    service = _operation_service(
        transaction_factory,
        _ProviderBoundary(entered=entered, release=release),
    )
    task = asyncio.create_task(service.start(
        _command(workspace, "41000000-0000-4000-8000-000000000000")
    ))

    async with _blocked_worker_scope(
        release, services=(service,), start_tasks=(task,)
    ):
        await asyncio.wait_for(entered.wait(), timeout=_TIMEOUT)
        started = await asyncio.wait_for(task, timeout=_TIMEOUT)
        attempts = await _attempts(disposable_mysql.session, workspace.session.id)
        events = await _events(disposable_mysql.session, attempts[0]["id"])
        result = await _release_and_settle(release, service, started)

    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt["status"] == "running"
    assert attempt["active_slot"] == 1
    assert attempt["last_event_sequence"] == 1
    assert attempt["result_working_draft_revision"] is None
    assert attempt["result_content_hash"] is None
    assert attempt["partial_output_text"] == ""
    assert attempt["partial_output_hash"] == hashlib.sha256(
        attempt["partial_output_text"].encode("utf-8")
    ).hexdigest()
    assert attempt["partial_output_scalars"] == 0
    assert attempt["heartbeat_at"] == attempt["created_at"] == _NOW
    assert events[0]["event_type"] == "started"
    assert events[0]["sequence_num"] == 1
    assert events[0]["closed_payload_json"] is None
    assert started.status == "running"
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_success_commits_one_attempt_recovery_events_and_matching_metadata(
    disposable_mysql,
):
    workspace, transaction_factory, _ = await _workspace(disposable_mysql)
    gateway = _ProviderBoundary()
    service = _operation_service(transaction_factory, gateway)

    started = await service.start(
        _command(workspace, "41000000-0000-4000-8000-000000000001")
    )
    assert started.status == "running"
    result = await _settled_result(service, started)

    attempts = await _attempts(disposable_mysql.session, workspace.session.id)
    events = await _events(disposable_mysql.session, result.operation_id)
    recovery = await _recovery(disposable_mysql.session, workspace.session.id)
    draft = await _draft(disposable_mysql.session, workspace.session.id)
    draft_count = await disposable_mysql.session.fetchone(
        """SELECT COUNT(*) AS total FROM working_drafts
             WHERE chapter_session_id=%s""",
        (workspace.session.id,),
    )
    assert gateway.invocations == 1
    assert len(attempts) == 1
    assert len(recovery) == 2
    assert len(events) == 2
    assert draft_count == {"total": 1}
    assert draft["revision"] == workspace.working_draft.revision + 1
    assert result.status == attempts[0]["status"] == "completed"
    before, after = recovery
    assert [row["snapshot_role"] for row in recovery] == ["before", "after"]
    assert before["working_draft_revision"] == workspace.working_draft.revision
    assert before["content"] == workspace.working_draft.content
    assert before["content_hash"] == workspace.working_draft.content_hash
    assert before["content_hash"] == hashlib.sha256(
        before["content"].encode("utf-8")
    ).hexdigest()
    assert after["working_draft_revision"] == draft["revision"]
    assert after["content"] == draft["content"]
    assert after["content_hash"] == draft["content_hash"]
    assert after["content_hash"] == hashlib.sha256(
        after["content"].encode("utf-8")
    ).hexdigest()
    assert all(row["working_draft_id"] == draft["id"] for row in recovery)
    assert all(
        row["source_operation_id"] == attempts[0]["id"]
        for row in recovery
    )
    assert [row["event_type"] for row in events] == ["started", "completed"]
    assert [row["sequence_num"] for row in events] == [1, 2]
    assert all(row["project_id"] == PROJECT for row in events)
    assert all(
        row["draft_operation_id"] == attempts[0]["id"] for row in events
    )
    assert attempts[0]["last_event_sequence"] == 2
    assert result.last_event_sequence == 2
    assert result.last_event_sequence == events[-1]["sequence_num"]
    assert result.result_working_draft_revision == draft["revision"]
    assert result.result_content_hash == draft["content_hash"]
    assert attempts[0]["result_working_draft_revision"] == draft["revision"]
    assert attempts[0]["result_content_hash"] == draft["content_hash"]
    completed_payload = _json_object(events[1]["closed_payload_json"])
    assert completed_payload == {
        "resultContentHash": draft["content_hash"],
        "resultWorkingDraftRevision": draft["revision"],
    }
    source = _json_object(draft["source_payload_json"])
    assert source["operationId"] == attempts[0]["id"]
    assert source["providerId"] == attempts[0]["provider_id"]
    assert source["modelName"] == attempts[0]["model_name_snapshot"]

    provider = await disposable_mysql.session.fetchone(
        "SELECT api_key,base_url FROM provider_profiles WHERE id=%s",
        (attempts[0]["provider_id"],),
    )
    persisted_coordination = json.dumps(
        [attempts, events], ensure_ascii=False, default=str, sort_keys=True
    )
    assert all(
        sentinel not in persisted_coordination
        for sentinel in (provider["api_key"], provider["base_url"])
    )


@pytest.mark.asyncio
async def test_local_success_replaces_one_range_with_distinct_result_and_partial_hashes(
    disposable_mysql,
):
    workspace, transaction_factory, chapter_service = await _workspace(disposable_mysql)
    original = "左侧目标右侧"
    workspace = await chapter_service.save_working_draft(SaveWorkingDraft(
        PROJECT,
        workspace.session.id,
        workspace.working_draft.revision,
        workspace.working_draft.content_hash,
        original,
    ))
    replacement = "新的🌙片段"
    service = _operation_service(
        transaction_factory, _ProviderBoundary(output=replacement)
    )

    started = await service.start(_local_command(
        workspace, "41000000-0000-4000-8000-000000000010"
    ))
    result = await _settled_result(service, started)

    draft = await _draft(disposable_mysql.session, workspace.session.id)
    attempts = await _attempts(disposable_mysql.session, workspace.session.id)
    recovery = await _recovery(disposable_mysql.session, workspace.session.id)
    expected = "左侧" + replacement + "右侧"
    assert result.status == attempts[0]["status"] == "completed"
    assert draft["content"] == expected
    assert result.result_content_hash == hashlib.sha256(
        expected.encode("utf-8")
    ).hexdigest()
    assert result.partial_output_hash == hashlib.sha256(
        replacement.encode("utf-8")
    ).hexdigest()
    assert result.result_content_hash != result.partial_output_hash
    assert (result.result_selection_start, result.result_selection_end) == (
        2, 2 + len(replacement),
    )
    assert [row["content"] for row in recovery] == [original, expected]
    assert all(
        row["replacement_reason"] == "rewrite_selection" for row in recovery
    )


@pytest.mark.asyncio
async def test_local_undo_restores_before_as_new_revision_without_new_operation(
    disposable_mysql,
):
    workspace, transaction_factory, chapter_service = await _workspace(disposable_mysql)
    original = "左侧目标右侧"
    workspace = await chapter_service.save_working_draft(SaveWorkingDraft(
        PROJECT,
        workspace.session.id,
        workspace.working_draft.revision,
        workspace.working_draft.content_hash,
        original,
    ))
    service = _operation_service(
        transaction_factory, _ProviderBoundary(output="替换片段")
    )
    started = await service.start(_local_command(
        workspace, "41000000-0000-4000-8000-000000000012"
    ))
    completed = await _settled_result(service, started)

    chapter_number = await service.undo_local(UndoLocalDraft(
        project_id=PROJECT,
        chapter_session_id=workspace.session.id,
        expected_working_draft_revision=completed.result_working_draft_revision,
        expected_content_hash=completed.result_content_hash,
        source_operation_id=completed.operation_id,
    ))

    restored = await _draft(disposable_mysql.session, workspace.session.id)
    recovery = await _recovery(disposable_mysql.session, workspace.session.id)
    attempts = await _attempts(disposable_mysql.session, workspace.session.id)
    events = await _events(disposable_mysql.session, completed.operation_id)
    source = _json_object(restored["source_payload_json"])
    assert chapter_number == workspace.session.chapter_num
    assert restored["revision"] == completed.result_working_draft_revision + 1
    assert restored["content"] == original
    assert restored["content_hash"] == hashlib.sha256(
        original.encode("utf-8")
    ).hexdigest()
    assert source == {
        "source": "undo-local",
        "sourceOperationId": completed.operation_id,
        "operationType": "rewrite_selection",
        "baseWorkingDraftRevision": completed.result_working_draft_revision,
    }
    assert len(attempts) == 1
    assert attempts[0]["status"] == "completed"
    assert attempts[0]["result_working_draft_revision"] == (
        completed.result_working_draft_revision
    )
    assert len(events) == 2
    assert [row["replacement_reason"] for row in recovery] == [
        "rewrite_selection", "rewrite_selection", "undo_local",
    ]
    assert recovery[-1]["working_draft_revision"] == (
        completed.result_working_draft_revision
    )
    assert recovery[-1]["content_hash"] == completed.result_content_hash

    with pytest.raises(DraftOperationConflict):
        await service.undo_local(UndoLocalDraft(
            project_id=PROJECT,
            chapter_session_id=workspace.session.id,
            expected_working_draft_revision=restored["revision"],
            expected_content_hash=restored["content_hash"],
            source_operation_id=completed.operation_id,
        ))
    assert len(await _recovery(disposable_mysql.session, workspace.session.id)) == 3


@pytest.mark.asyncio
async def test_local_cancel_with_durable_partial_preserves_original_transactionally(
    disposable_mysql,
):
    workspace, transaction_factory, chapter_service = await _workspace(disposable_mysql)
    original = "左侧目标右侧"
    workspace = await chapter_service.save_working_draft(SaveWorkingDraft(
        PROJECT,
        workspace.session.id,
        workspace.working_draft.revision,
        workspace.working_draft.content_hash,
        original,
    ))
    service = _operation_service(transaction_factory, _ProviderBoundary())
    command = _local_command(
        workspace, "41000000-0000-4000-8000-000000000011"
    )
    immediate, context = await service._reserve(command)
    assert immediate is None
    partial = "尚未提交的局部预览"
    await service._append_delta(context, partial)

    cancelled = await service.cancel(
        PROJECT, workspace.session.id, context["attempt"]["id"]
    )

    draft = await _draft(disposable_mysql.session, workspace.session.id)
    recovery = await _recovery(disposable_mysql.session, workspace.session.id)
    assert cancelled.status == "cancelled"
    assert cancelled.partial_output == partial
    assert cancelled.result_working_draft_revision is None
    assert cancelled.result_content_hash is None
    assert draft["revision"] == workspace.working_draft.revision
    assert draft["content"] == original
    assert not recovery


@pytest.mark.asyncio
async def test_concurrent_same_key_invokes_provider_and_effect_once(disposable_mysql):
    workspace, transaction_factory, _ = await _workspace(disposable_mysql)
    entered = asyncio.Event()
    release = asyncio.Event()
    gateway = _ProviderBoundary(entered=entered, release=release)
    probe = _TransactionLifecycleProbe(
        transaction_factory, first_call_target=2
    )
    service = _operation_service(probe.factory, gateway)
    command = _command(
        workspace, "41000000-0000-4000-8000-000000000002"
    )
    tasks = await _queue_reservation_race(
        transaction_factory, probe, service, (command, command)
    )
    async with _blocked_worker_scope(
        release,
        services=(service,),
        start_tasks=tasks,
    ):
        await asyncio.wait_for(entered.wait(), timeout=_TIMEOUT)
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=_TIMEOUT)
        assert all(result.status == "running" for result in results)
        assert len({result.operation_id for result in results}) == 1
        assert gateway.invocations == 1
        assert len(
            await _attempts(disposable_mysql.session, workspace.session.id)
        ) == 1
        result = await _release_and_settle(release, service, results[0])

    attempts = await _attempts(disposable_mysql.session, workspace.session.id)
    draft = await _draft(disposable_mysql.session, workspace.session.id)
    assert result.status == "completed"
    assert len(attempts) == gateway.invocations == 1
    assert draft["revision"] == workspace.working_draft.revision + 1
    assert len(await _recovery(disposable_mysql.session, workspace.session.id)) == 2
    assert probe.active == 0
    assert probe.entries == probe.exits == 4


@pytest.mark.asyncio
async def test_concurrent_different_keys_allow_only_one_live_active_slot(
    disposable_mysql,
):
    workspace, transaction_factory, _ = await _workspace(disposable_mysql)
    entered = asyncio.Event()
    release = asyncio.Event()
    gateway = _ProviderBoundary(entered=entered, release=release)
    probe = _TransactionLifecycleProbe(
        transaction_factory, first_call_target=2
    )
    service = _operation_service(probe.factory, gateway)
    commands = (
        _command(workspace, "41000000-0000-4000-8000-000000000003"),
        _command(workspace, "41000000-0000-4000-8000-000000000004"),
    )
    tasks = await _queue_reservation_race(
        transaction_factory, probe, service, commands
    )
    async with _blocked_worker_scope(
        release, services=(service,), start_tasks=tasks
    ):
        await asyncio.wait_for(entered.wait(), timeout=_TIMEOUT)
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=_TIMEOUT
        )
        running = [
            result
            for result in results
            if getattr(result, "status", None) == "running"
        ]
        assert len(running) == 1
        assert sum(isinstance(item, DraftOperationConflict) for item in results) == 1
        active = await disposable_mysql.session.fetchall(
            """SELECT id FROM draft_operation_attempts
                 WHERE chapter_session_id=%s AND active_slot=1""",
            (workspace.session.id,),
        )
        assert len(active) == 1
        assert gateway.invocations == 1
        assert probe.active == 0
        result = await _release_and_settle(release, service, running[0])

    attempts = await _attempts(disposable_mysql.session, workspace.session.id)
    assert result.status == "completed"
    assert len(attempts) == gateway.invocations == 1
    assert attempts[0]["status"] == "completed"
    assert len(await _recovery(disposable_mysql.session, workspace.session.id)) == 2
    assert probe.active == 0
    assert probe.entries == probe.exits == 4


@pytest.mark.asyncio
async def test_expired_attempt_late_result_cannot_cross_new_fencing_token(
    disposable_mysql,
):
    workspace, transaction_factory, _ = await _workspace(disposable_mysql)
    clock = _Clock()
    ids = _SequentialIds()
    entered = asyncio.Event()
    release = asyncio.Event()
    first_gateway = _ProviderBoundary(entered=entered, release=release)
    second_gateway = _ProviderBoundary(output=_GENERATED_B)
    first_service = _operation_service(
        transaction_factory, first_gateway, ids=ids, clock=clock
    )
    second_service = _operation_service(
        transaction_factory, second_gateway, ids=ids, clock=clock
    )
    first_task = asyncio.create_task(first_service.start(_command(
        workspace, "41000000-0000-4000-8000-000000000005"
    )))
    async with _blocked_worker_scope(
        release,
        services=(first_service, second_service),
        start_tasks=(first_task,),
    ):
        await asyncio.wait_for(entered.wait(), timeout=_TIMEOUT)
        first_started = await asyncio.wait_for(first_task, timeout=_TIMEOUT)
        assert first_started.status == "running"
        clock.now += DRAFT_OPERATION_LEASE_MS + 1
        second_started = await asyncio.wait_for(second_service.start(_command(
            workspace, "41000000-0000-4000-8000-000000000006"
        )), timeout=_TIMEOUT)
        assert second_started.status == "running"
        first = await _release_and_settle(release, first_service, first_started)
        second = await _settled_result(second_service, second_started)

    attempts = await _attempts(disposable_mysql.session, workspace.session.id)
    draft = await _draft(disposable_mysql.session, workspace.session.id)
    assert [row["fencing_token"] for row in attempts] == [1, 2]
    assert [row["status"] for row in attempts] == ["expired", "completed"]
    assert first.status == "expired"
    assert second.status == "completed"
    assert first_gateway.invocations == second_gateway.invocations == 1
    assert draft["content_hash"] == hashlib.sha256(
        _GENERATED_B.encode("utf-8")
    ).hexdigest()
    assert {row["source_operation_id"] for row in await _recovery(
        disposable_mysql.session, workspace.session.id
    )} == {attempts[1]["id"]}


@pytest.mark.asyncio
async def test_same_key_different_request_rejects_without_new_rows(disposable_mysql):
    workspace, transaction_factory, _ = await _workspace(disposable_mysql)
    entered = asyncio.Event()
    release = asyncio.Event()
    gateway = _ProviderBoundary(entered=entered, release=release)
    service = _operation_service(transaction_factory, gateway)
    key = "41000000-0000-4000-8000-000000000007"
    first_task = asyncio.create_task(service.start(_command(
        workspace, key, instruction="第一种要求"
    )))
    async with _blocked_worker_scope(
        release, services=(service,), start_tasks=(first_task,)
    ):
        await asyncio.wait_for(entered.wait(), timeout=_TIMEOUT)
        first_started = await asyncio.wait_for(first_task, timeout=_TIMEOUT)
        assert first_started.status == "running"
        with pytest.raises(DraftOperationIdempotencyConflict):
            await asyncio.wait_for(service.start(_command(
                workspace, key, instruction="另一种要求"
            )), timeout=_TIMEOUT)
        attempts = await _attempts(disposable_mysql.session, workspace.session.id)
        assert len(attempts) == 1
        assert len(await _events(disposable_mysql.session, attempts[0]["id"])) == 1
        assert len(await _recovery(
            disposable_mysql.session, workspace.session.id
        )) == 0
        await _release_and_settle(release, service, first_started)


@pytest.mark.asyncio
async def test_provider_failure_preserves_draft_and_clears_active_ownership(
    disposable_mysql,
):
    workspace, transaction_factory, _ = await _workspace(disposable_mysql)
    gateway = _ProviderBoundary(
        failure=ChapterDraftProviderError("closed provider failure")
    )
    service = _operation_service(transaction_factory, gateway)
    started = await service.start(
        _command(workspace, "41000000-0000-4000-8000-000000000008")
    )
    assert started.status == "running"
    result = await _settled_result(service, started)

    attempts = await _attempts(disposable_mysql.session, workspace.session.id)
    draft = await _draft(disposable_mysql.session, workspace.session.id)
    owner = await _session_owner(disposable_mysql.session, workspace.session.id)
    assert result.status == attempts[0]["status"] == "failed"
    assert attempts[0]["active_slot"] is None
    assert owner["active_draft_operation_id"] is None
    assert draft["revision"] == workspace.working_draft.revision
    assert draft["content_hash"] == workspace.working_draft.content_hash
    assert len(await _recovery(disposable_mysql.session, workspace.session.id)) == 0
    assert [row["event_type"] for row in await _events(
        disposable_mysql.session, attempts[0]["id"]
    )] == ["started", "failed"]


@pytest.mark.asyncio
async def test_working_draft_cas_drift_expires_without_recovery(
    disposable_mysql,
):
    workspace, transaction_factory, chapter_service = await _workspace(
        disposable_mysql
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    gateway = _ProviderBoundary(entered=entered, release=release)
    service = _operation_service(transaction_factory, gateway)
    task = asyncio.create_task(service.start(_command(
        workspace, "41000000-0000-4000-8000-000000000009"
    )))
    async with _blocked_worker_scope(
        release, services=(service,), start_tasks=(task,)
    ):
        await asyncio.wait_for(entered.wait(), timeout=_TIMEOUT)
        started = await asyncio.wait_for(task, timeout=_TIMEOUT)
        assert started.status == "running"
        drifted = await chapter_service.save_working_draft(SaveWorkingDraft(
            PROJECT,
            workspace.session.id,
            workspace.working_draft.revision,
            workspace.working_draft.content_hash,
            "作者在模型等待期间保存的版本",
        ))
        result = await _release_and_settle(release, service, started)

    attempts = await _attempts(disposable_mysql.session, workspace.session.id)
    draft = await _draft(disposable_mysql.session, workspace.session.id)
    owner = await _session_owner(disposable_mysql.session, workspace.session.id)
    assert result.status == attempts[0]["status"] == "expired"
    assert attempts[0]["active_slot"] is None
    assert owner["active_draft_operation_id"] is None
    assert draft["revision"] == drifted.working_draft.revision
    assert draft["content_hash"] == drifted.working_draft.content_hash
    assert len(await _recovery(disposable_mysql.session, workspace.session.id)) == 0


@pytest.mark.asyncio
async def test_provider_wait_leaves_second_connection_readable(disposable_mysql):
    workspace, transaction_factory, _ = await _workspace(disposable_mysql)
    entered = asyncio.Event()
    release = asyncio.Event()
    probe = _TransactionLifecycleProbe(transaction_factory)
    gateway = _ProviderBoundary(
        entered=entered,
        release=release,
        transaction_probe=probe,
    )
    service = _operation_service(probe.factory, gateway)
    task = asyncio.create_task(service.start(_command(
        workspace, "41000000-0000-4000-8000-000000000010"
    )))
    async with _blocked_worker_scope(
        release, services=(service,), start_tasks=(task,)
    ):
        await asyncio.wait_for(entered.wait(), timeout=_TIMEOUT)
        started = await asyncio.wait_for(task, timeout=_TIMEOUT)
        assert started.status == "running"
        assert service._registry.size == 1
        assert gateway.active_transaction_observations == [0]
        assert probe.active == 0
        assert probe.entries == probe.exits == 1

        async def read_on_second_connection():
            async with transaction_factory() as session:
                selected = await session.fetchone(
                    "SELECT DATABASE() AS database_name"
                )
                unrelated = await session.fetchone(
                    "SELECT COUNT(*) AS total FROM style_templates"
                )
                return selected, unrelated

        selected, unrelated = await asyncio.wait_for(
            read_on_second_connection(), timeout=_TIMEOUT
        )
        assert selected == {"database_name": disposable_mysql.database_name}
        assert _DATABASE_NAME.fullmatch(selected["database_name"])
        assert unrelated["total"] > 0
        assert service._registry.size == 1
        assert probe.active == 0
        result = await _release_and_settle(release, service, started)

    assert result.status == "completed"
    assert gateway.active_transaction_observations == [0, 0]
    assert probe.active == 0
    assert probe.entries == probe.exits == 3


@pytest.mark.asyncio
async def test_candidate_load_commits_both_snapshots_or_rolls_back_all(
    disposable_mysql,
):
    workspace, transaction_factory, chapter_service = await _workspace(
        disposable_mysql
    )
    first = await chapter_service.save_working_draft(SaveWorkingDraft(
        PROJECT,
        workspace.session.id,
        workspace.working_draft.revision,
        workspace.working_draft.content_hash,
        "候选稿甲",
    ))
    saved = await chapter_service.save_candidate(SaveDraftCandidate(
        PROJECT,
        workspace.session.id,
        first.working_draft.revision,
        first.working_draft.content_hash,
        "51000000-0000-4000-8000-000000000001",
    ))
    candidate_before = await disposable_mysql.session.fetchone(
        "SELECT * FROM draft_candidates WHERE id=%s",
        (saved.saved_candidate_id,),
    )
    current = await chapter_service.save_working_draft(SaveWorkingDraft(
        PROJECT,
        workspace.session.id,
        first.working_draft.revision,
        first.working_draft.content_hash,
        "当前工作稿乙",
    ))
    loaded = await chapter_service.load_candidate(LoadDraftCandidate(
        PROJECT,
        workspace.session.id,
        saved.saved_candidate_id,
        current.working_draft.revision,
        current.working_draft.content_hash,
    ))

    recovery = await _recovery(disposable_mysql.session, workspace.session.id)
    assert loaded.working_draft.revision == current.working_draft.revision + 1
    assert loaded.working_draft.content == "候选稿甲"
    assert [row["snapshot_role"] for row in recovery] == ["before", "after"]
    assert {row["source_operation_id"] for row in recovery} == {None}
    assert {row["source_candidate_id"] for row in recovery} == {
        saved.saved_candidate_id
    }
    candidate_after = await disposable_mysql.session.fetchone(
        "SELECT * FROM draft_candidates WHERE id=%s",
        (saved.saved_candidate_id,),
    )
    assert candidate_after == candidate_before

    before_failure = await chapter_service.save_working_draft(SaveWorkingDraft(
        PROJECT,
        workspace.session.id,
        loaded.working_draft.revision,
        loaded.working_draft.content_hash,
        "事务失败前的工作稿",
    ))

    class FailAfterDraftRepository(ChapterSessionRepository):
        def __init__(self):
            self.recovery_calls = 0

        async def insert_working_draft_revision(self, session, row):
            self.recovery_calls += 1
            if self.recovery_calls == 2:
                return False
            return await super().insert_working_draft_revision(session, row)

    failing_service = ChapterSessionService(
        FailAfterDraftRepository(), transaction_factory=transaction_factory
    )
    with pytest.raises(
        ChapterSessionConflict, match="candidate load recovery conflict"
    ):
        await failing_service.load_candidate(LoadDraftCandidate(
            PROJECT,
            workspace.session.id,
            saved.saved_candidate_id,
            before_failure.working_draft.revision,
            before_failure.working_draft.content_hash,
        ))

    persisted = await _draft(disposable_mysql.session, workspace.session.id)
    assert persisted["revision"] == before_failure.working_draft.revision
    assert persisted["content_hash"] == before_failure.working_draft.content_hash
    assert len(await _recovery(
        disposable_mysql.session, workspace.session.id
    )) == 2
