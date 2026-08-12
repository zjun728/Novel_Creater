from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.services.draft_operation_execution import (
    DRAFT_OPERATION_LEASE_MS,
    DraftOperationExecution,
)
from backend.services.draft_operations import (
    DraftOperationService,
    DraftOperationStorageError,
    _DraftOperationFenceLost,
)
from backend.tests.integration.test_draft_operation_integrity import (
    PROJECT,
    _Clock,
    _SequentialIds,
    _TransactionLifecycleProbe,
    _attempts,
    _command,
    _draft,
    _events,
    _operation_service,
    _recovery,
    _session_owner,
    _workspace,
)
from backend.tests.integration.test_contract_drafts import PROVIDER


pytestmark = pytest.mark.mysql
_TIMEOUT = 10
_NOW = 2_100_000_000_000
_PARTIAL = "甲" * 256
_COMPLETED = _PARTIAL + "乙"


async def _streaming_workspace(disposable_mysql):
    """Use the shared canonical fixture, then enable only fake-stream selection."""
    workspace, transaction_factory, chapter_service = await _workspace(
        disposable_mysql
    )
    await disposable_mysql.session.execute(
        """UPDATE provider_profiles
              SET stream=1, supports_streaming=1
            WHERE id=%s""",
        (PROVIDER,),
    )
    return workspace, transaction_factory, chapter_service


async def _reserve(service, workspace, key: str):
    command = _command(workspace, key)
    immediate, context = await service._reserve(command)
    assert immediate is None
    assert context is not None
    return command, context


async def _close_services(*services):
    for service in services:
        await service._registry.aclose()


def _payload(row):
    value = row["closed_payload_json"]
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8")
    return json.loads(value) if value is not None else None


async def _persistence_snapshot(session, chapter_session_id, operation_id):
    attempt = next(
        row for row in await _attempts(session, chapter_session_id)
        if row["id"] == operation_id
    )
    draft = await _draft(session, chapter_session_id)
    owner = await _session_owner(session, chapter_session_id)
    events = await _events(session, operation_id)
    recovery = await _recovery(session, chapter_session_id)
    return {
        "attempt": {
            key: attempt[key]
            for key in (
                "status", "active_slot", "lease_expires_at", "heartbeat_at",
                "partial_output_text", "partial_output_hash",
                "partial_output_scalars", "last_event_sequence",
                "result_working_draft_revision", "result_content_hash",
            )
        },
        "draft": {
            key: draft[key] for key in ("revision", "content", "content_hash")
        },
        "owner": {
            key: owner[key]
            for key in ("active_draft_operation_id", "draft_operation_fencing_token")
        },
        "events": [
            (row["sequence_num"], row["event_type"]) for row in events
        ],
        "recovery": [
            (row["working_draft_revision"], row["snapshot_role"], row["content_hash"])
            for row in recovery
        ],
    }


class _RejectingStreamEventRepository(ChapterSessionRepository):
    """Fail one chosen event insertion inside the real disposable transaction."""

    def __init__(self, event_type):
        self._event_type = event_type
        self._remaining_failures = 1

    async def _insert_stream_event(
        self, session, row, *, event_type, closed_payload
    ):
        if event_type == self._event_type and self._remaining_failures:
            self._remaining_failures -= 1
            return False
        return await super()._insert_stream_event(
            session, row, event_type=event_type, closed_payload=closed_payload
        )


def _service_with_repository(
    transaction_factory, gateway, repository, *, ids, clock, execution=None
):
    return DraftOperationService(
        repository,
        provider_gateway=gateway,
        transaction_factory=transaction_factory,
        id_factory=ids,
        clock=clock,
        execution=execution,
    )


@pytest.mark.asyncio
async def test_delta_snapshot_hash_scalars_event_and_matching_fence_are_atomic(
    disposable_mysql,
):
    workspace, transaction_factory, _ = await _streaming_workspace(disposable_mysql)
    clock = _Clock(_NOW)
    ids = _SequentialIds()
    service = _service_with_repository(
        transaction_factory,
        _NoopGateway(),
        _RejectingStreamEventRepository("delta"),
        ids=ids,
        clock=clock,
    )
    second_service = _operation_service(
        transaction_factory, _NoopGateway(), ids=ids, clock=clock
    )
    try:
        _, context = await _reserve(
            service, workspace, "51000000-0000-4000-8000-000000000001"
        )
        before_failed_delta = await _persistence_snapshot(
            disposable_mysql.session, workspace.session.id, context["attempt"]["id"]
        )
        with pytest.raises(_DraftOperationFenceLost):
            await service._append_delta(context, _PARTIAL)
        assert await _persistence_snapshot(
            disposable_mysql.session, workspace.session.id, context["attempt"]["id"]
        ) == before_failed_delta

        await service._append_delta(context, _PARTIAL)

        attempts = await _attempts(disposable_mysql.session, workspace.session.id)
        events = await _events(disposable_mysql.session, context["attempt"]["id"])
        assert len(attempts) == 1
        attempt = attempts[0]
        expected_hash = hashlib.sha256(_PARTIAL.encode("utf-8")).hexdigest()
        assert attempt["status"] == "running"
        assert attempt["partial_output_text"] == _PARTIAL
        assert attempt["partial_output_hash"] == expected_hash
        assert attempt["partial_output_scalars"] == len(_PARTIAL)
        assert attempt["last_event_sequence"] == 2
        assert attempt["lease_expires_at"] == _NOW + DRAFT_OPERATION_LEASE_MS
        assert [event["event_type"] for event in events] == ["started", "delta"]
        assert events[-1]["sequence_num"] == 2
        assert _payload(events[-1]) == {
            "text": _PARTIAL,
            "partialOutputHash": expected_hash,
            "partialOutputScalars": len(_PARTIAL),
        }

        clock.now += 1
        await service._append_heartbeat(context)
        attempts = await _attempts(disposable_mysql.session, workspace.session.id)
        events = await _events(disposable_mysql.session, context["attempt"]["id"])
        assert attempts[0]["partial_output_hash"] == expected_hash
        assert attempts[0]["partial_output_scalars"] == len(_PARTIAL)
        assert attempts[0]["heartbeat_at"] == clock.now
        assert attempts[0]["lease_expires_at"] == clock.now + DRAFT_OPERATION_LEASE_MS
        assert [event["event_type"] for event in events] == [
            "started", "delta", "heartbeat"
        ]
        assert events[-1]["sequence_num"] == 3
        assert _payload(events[-1]) is None

        clock.now += DRAFT_OPERATION_LEASE_MS + 1
        _, new_context = await _reserve(
            second_service, workspace, "51000000-0000-4000-8000-000000000008"
        )
        old_before = await _persistence_snapshot(
            disposable_mysql.session, workspace.session.id, context["attempt"]["id"]
        )
        new_before = await _persistence_snapshot(
            disposable_mysql.session, workspace.session.id, new_context["attempt"]["id"]
        )
        with pytest.raises(_DraftOperationFenceLost):
            await service._append_heartbeat(context)
        assert await _persistence_snapshot(
            disposable_mysql.session, workspace.session.id, context["attempt"]["id"]
        ) == old_before
        assert await _persistence_snapshot(
            disposable_mysql.session, workspace.session.id, new_context["attempt"]["id"]
        ) == new_before
        assert old_before["attempt"]["status"] == "expired"
        assert new_before["attempt"]["status"] == "running"
    finally:
        await _close_services(service, second_service)


@pytest.mark.asyncio
async def test_cancel_and_completion_race_commit_exactly_one_terminal_winner(
    disposable_mysql,
):
    workspace, transaction_factory, _ = await _streaming_workspace(disposable_mysql)
    clock = _Clock(_NOW)
    ids = _SequentialIds()
    preparation_service = _operation_service(
        transaction_factory, _NoopGateway(), ids=ids, clock=clock
    )
    try:
        _, context = await _reserve(
            preparation_service, workspace, "51000000-0000-4000-8000-000000000002"
        )
        await preparation_service._append_delta(context, _PARTIAL)
    except BaseException:
        await _close_services(preparation_service)
        raise
    probe = _TransactionLifecycleProbe(
        transaction_factory, first_call_target=2
    )
    race_service = _operation_service(
        probe.factory, _NoopGateway(), ids=ids, clock=clock
    )
    try:
        tasks = []
        try:
            async with transaction_factory() as lock_session:
                await lock_session.fetchone(
                    "SELECT id FROM projects WHERE id=%s FOR UPDATE", (PROJECT,)
                )
                await lock_session.fetchone(
                    """SELECT id FROM chapter_sessions
                         WHERE project_id=%s AND id=%s FOR UPDATE""",
                    (PROJECT, workspace.session.id),
                )
                tasks = [
                    asyncio.create_task(race_service.cancel(
                        PROJECT, workspace.session.id, context["attempt"]["id"]
                    )),
                    asyncio.create_task(
                        race_service._settle_success(context, _COMPLETED)
                    ),
                ]
                await asyncio.wait_for(probe.first_calls_ready.wait(), timeout=_TIMEOUT)
                assert probe.active == 2
                assert all(not task.done() for task in tasks)
            cancelled, completed = await asyncio.wait_for(
                asyncio.gather(*tasks), timeout=_TIMEOUT
            )
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            raise
        attempt = (await _attempts(disposable_mysql.session, workspace.session.id))[0]
        events = await _events(disposable_mysql.session, attempt["id"])
        terminal_events = [
            event for event in events
            if event["event_type"] in {"cancelled", "completed"}
        ]
        draft = await _draft(disposable_mysql.session, workspace.session.id)
        recovery = await _recovery(disposable_mysql.session, workspace.session.id)
        assert attempt["status"] in {"cancelled", "completed"}
        assert cancelled.status == completed.status == attempt["status"]
        assert len(terminal_events) == 1
        assert terminal_events[0]["sequence_num"] == attempt["last_event_sequence"]
        assert draft["revision"] == workspace.working_draft.revision + 1
        assert len(recovery) == 2
        assert {row["snapshot_role"] for row in recovery} == {"before", "after"}
        if attempt["status"] == "cancelled":
            assert draft["content"] == _PARTIAL
        else:
            assert draft["content"] == _COMPLETED
        assert probe.active == 0
        assert probe.entries == probe.exits
    finally:
        await _close_services(preparation_service, race_service)


@pytest.mark.asyncio
async def test_nonempty_cancel_commits_one_revision_recovery_pair_and_is_idempotent(
    disposable_mysql,
):
    workspace, transaction_factory, _ = await _streaming_workspace(disposable_mysql)
    service = _service_with_repository(
        transaction_factory,
        _NoopGateway(),
        _RejectingStreamEventRepository("cancelled"),
        ids=_SequentialIds(),
        clock=_Clock(_NOW),
    )
    try:
        _, context = await _reserve(
            service, workspace, "51000000-0000-4000-8000-000000000003"
        )
        await service._append_delta(context, _PARTIAL)
        before_failed_cancel = await _persistence_snapshot(
            disposable_mysql.session, workspace.session.id, context["attempt"]["id"]
        )
        assert before_failed_cancel["owner"] == {
            "active_draft_operation_id": context["attempt"]["id"],
            "draft_operation_fencing_token": context["attempt"]["fencing_token"],
        }
        with pytest.raises(DraftOperationStorageError):
            await service.cancel(PROJECT, workspace.session.id, context["attempt"]["id"])
        assert await _persistence_snapshot(
            disposable_mysql.session, workspace.session.id, context["attempt"]["id"]
        ) == before_failed_cancel
        first = await service.cancel(PROJECT, workspace.session.id, context["attempt"]["id"])
        repeated = await service.cancel(
            PROJECT, workspace.session.id, context["attempt"]["id"]
        )
        attempt = (await _attempts(disposable_mysql.session, workspace.session.id))[0]
        events = await _events(disposable_mysql.session, attempt["id"])
        recovery = await _recovery(disposable_mysql.session, workspace.session.id)
        draft = await _draft(disposable_mysql.session, workspace.session.id)
        assert first == repeated
        assert first.status == attempt["status"] == "cancelled"
        assert first.result_working_draft_revision == workspace.working_draft.revision + 1
        assert draft["revision"] == workspace.working_draft.revision + 1
        assert draft["content"] == _PARTIAL
        assert [(row["working_draft_revision"], row["snapshot_role"]) for row in recovery] == [
            (workspace.working_draft.revision, "before"),
            (workspace.working_draft.revision + 1, "after"),
        ]
        assert [event["event_type"] for event in events].count("cancelled") == 1
    finally:
        await _close_services(service)


@pytest.mark.asyncio
async def test_empty_cancel_is_idempotent_and_does_not_create_revision_or_recovery(
    disposable_mysql,
):
    workspace, transaction_factory, _ = await _streaming_workspace(disposable_mysql)
    service = _operation_service(
        transaction_factory, _NoopGateway(), ids=_SequentialIds(), clock=_Clock(_NOW)
    )
    try:
        _, context = await _reserve(
            service, workspace, "51000000-0000-4000-8000-000000000004"
        )
        first = await service.cancel(PROJECT, workspace.session.id, context["attempt"]["id"])
        repeated = await service.cancel(
            PROJECT, workspace.session.id, context["attempt"]["id"]
        )
        attempt = (await _attempts(disposable_mysql.session, workspace.session.id))[0]
        draft = await _draft(disposable_mysql.session, workspace.session.id)
        events = await _events(disposable_mysql.session, attempt["id"])
        assert first == repeated
        assert first.status == attempt["status"] == "cancelled"
        assert first.result_working_draft_revision is None
        assert draft["revision"] == workspace.working_draft.revision
        assert not await _recovery(disposable_mysql.session, workspace.session.id)
        assert [event["event_type"] for event in events].count("cancelled") == 1
    finally:
        await _close_services(service)


@pytest.mark.asyncio
async def test_restart_expiry_rejects_late_delta_and_completion_at_old_fence(
    disposable_mysql,
):
    workspace, transaction_factory, _ = await _streaming_workspace(disposable_mysql)
    clock = _Clock(_NOW)
    ids = _SequentialIds()
    first_service = _operation_service(
        transaction_factory, _NoopGateway(), ids=ids, clock=clock
    )
    second_service = _operation_service(
        transaction_factory, _NoopGateway(), ids=ids, clock=clock
    )
    try:
        _, first_context = await _reserve(
            first_service, workspace, "51000000-0000-4000-8000-000000000005"
        )
        clock.now += DRAFT_OPERATION_LEASE_MS + 1
        _, second_context = await _reserve(
            second_service, workspace, "51000000-0000-4000-8000-000000000006"
        )
        with pytest.raises(_DraftOperationFenceLost):
            await first_service._append_delta(first_context, _PARTIAL)
        late_completion = await first_service._settle_success(first_context, _COMPLETED)
        attempts = await _attempts(disposable_mysql.session, workspace.session.id)
        first, second = attempts
        assert late_completion.status == "expired"
        assert [row["fencing_token"] for row in attempts] == [1, 2]
        assert [row["status"] for row in attempts] == ["expired", "running"]
        assert first["partial_output_text"] == ""
        assert first["last_event_sequence"] == 1
        assert second["id"] == second_context["attempt"]["id"]
        assert not await _recovery(disposable_mysql.session, workspace.session.id)
    finally:
        await _close_services(first_service, second_service)


@pytest.mark.asyncio
async def test_cancelled_operation_rejects_late_worker_writes_without_mutation(
    disposable_mysql,
):
    workspace, transaction_factory, _ = await _streaming_workspace(disposable_mysql)
    service = _operation_service(
        transaction_factory, _NoopGateway(), ids=_SequentialIds(), clock=_Clock(_NOW)
    )
    try:
        _, context = await _reserve(
            service, workspace, "51000000-0000-4000-8000-000000000009"
        )
        await service._append_delta(context, _PARTIAL)
        cancelled = await service.cancel(
            PROJECT, workspace.session.id, context["attempt"]["id"]
        )
        before_late_write = await _persistence_snapshot(
            disposable_mysql.session, workspace.session.id, context["attempt"]["id"]
        )
        with pytest.raises(_DraftOperationFenceLost):
            await service._append_delta(context, _COMPLETED)
        late_completion = await service._settle_success(context, _COMPLETED)
        assert cancelled.status == late_completion.status == "cancelled"
        assert await _persistence_snapshot(
            disposable_mysql.session, workspace.session.id, context["attempt"]["id"]
        ) == before_late_write
    finally:
        await _close_services(service)


class _NoopGateway:
    async def generate(self, *, provider, messages, generation_config):
        return _COMPLETED

    async def stream(self, *, provider, messages, generation_config):
        if False:
            yield ""


class _GatedStreamingGateway(_NoopGateway):
    def __init__(self, transaction_probe):
        self._transaction_probe = transaction_probe
        self.provider_waiting = asyncio.Event()
        self.provider_release = asyncio.Event()
        self.provider_active_observations = []

    async def stream(self, *, provider, messages, generation_config):
        yield _PARTIAL
        self.provider_active_observations.append(self._transaction_probe.active)
        self.provider_waiting.set()
        await asyncio.wait_for(self.provider_release.wait(), timeout=_TIMEOUT)


@pytest.mark.asyncio
async def test_provider_and_timer_waits_leave_second_disposable_connection_readable(
    disposable_mysql,
):
    workspace, transaction_factory, _ = await _streaming_workspace(disposable_mysql)
    probe = _TransactionLifecycleProbe(transaction_factory)
    gateway = _GatedStreamingGateway(probe)
    timer_waiting = asyncio.Event()
    timer_release = asyncio.Event()
    timer_active_observations = []

    async def controlled_sleep(_seconds):
        timer_active_observations.append(probe.active)
        timer_waiting.set()
        await asyncio.wait_for(timer_release.wait(), timeout=_TIMEOUT)

    clock = _Clock(_NOW)
    service = _service_with_repository(
        probe.factory,
        gateway,
        ChapterSessionRepository(),
        ids=_SequentialIds(),
        clock=clock,
        execution=DraftOperationExecution(clock=clock, sleep=controlled_sleep),
    )
    try:
        started = await service.start(
            _command(workspace, "51000000-0000-4000-8000-000000000007")
        )
        await asyncio.wait_for(gateway.provider_waiting.wait(), timeout=_TIMEOUT)
        await asyncio.wait_for(timer_waiting.wait(), timeout=_TIMEOUT)
        assert gateway.provider_active_observations == [0]
        assert timer_active_observations
        assert all(active == 0 for active in timer_active_observations)
        assert probe.active == 0
        async def lock_second_connection():
            async with transaction_factory() as second_connection:
                locked_session = await second_connection.fetchone(
                    """SELECT id FROM chapter_sessions
                         WHERE project_id=%s AND id=%s FOR UPDATE""",
                    (PROJECT, workspace.session.id),
                )
                locked_attempt = await second_connection.fetchone(
                    """SELECT id FROM draft_operation_attempts
                         WHERE project_id=%s AND chapter_session_id=%s
                           AND active_slot=1 FOR UPDATE""",
                    (PROJECT, workspace.session.id),
                )
                return locked_session, locked_attempt

        locked_session, locked_attempt = await asyncio.wait_for(
            lock_second_connection(), timeout=_TIMEOUT
        )
        assert locked_session == {"id": workspace.session.id}
        assert locked_attempt == {"id": started.operation_id}
        assert service._registry.size == 1
        gateway.provider_release.set()
        timer_release.set()
        async def registry_drained():
            while service._registry.size:
                await asyncio.sleep(0)

        await asyncio.wait_for(registry_drained(), timeout=_TIMEOUT)
        result = await service.read(
            PROJECT, workspace.session.id, started.operation_id
        )
        assert result.status == "completed"
    finally:
        gateway.provider_release.set()
        timer_release.set()
        await _close_services(service)
