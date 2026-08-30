from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json

import pytest

from backend.domain.topics import TopicFailure


class FakeRepository:
    def __init__(self, *, ready: bool = True, fail_complete: bool = False):
        self.ready = ready
        self.fail_complete = fail_complete
        self.discussions = {}
        self.messages = []
        self.requests = {}
        self.events = []

    async def insert_discussion(self, session, row):
        self.events.append(("insert-discussion", row["id"]))
        self.discussions[row["id"]] = dict(row)

    async def lock_discussion(self, session, discussion_id):
        self.events.append(("lock-discussion", discussion_id))
        return self.discussions.get(discussion_id)

    async def lock_request_by_key(
        self,
        session,
        *,
        discussion_id,
        idempotency_key,
    ):
        self.events.append(("lock-request", idempotency_key))
        return self.requests.get((discussion_id, idempotency_key))

    async def lock_snapshot_evidence(self, session, refs):
        self.events.append(("lock-evidence", tuple(ref.snapshot_id for ref in refs)))
        return tuple(
            {
                "id": ref.snapshot_id,
                "source_id": "source-1",
                "content_hash": ref.content_hash,
                "captured_at": 100,
                "platform": "qidian",
                "ranking_name": "newsign",
                "category": "male",
                "entries": (),
            }
            for ref in refs
        )

    async def lock_generation_inputs(self, session):
        self.events.append(("lock-generation",))
        if not self.ready:
            return None
        return {
            "runtime": {
                "provider_id": "provider-1",
                "provider_name": "默认模型",
                "provider_type": "openai-compatible",
                "model_name": "topic-model",
                "base_url": "https://provider.example/v1",
                "api_key": "PRIVATE_TOPIC_KEY",
                "enabled": 1,
                "lifecycle_status": "active",
                "max_context_tokens": 131_072,
                "max_output_tokens": 16_384,
                "temperature": "0.600",
                "top_p": "0.900",
                "supports_json": 1,
            },
            "manifest": {
                "settingsRevision": 4,
                "providerId": "provider-1",
                "providerName": "默认模型",
                "providerType": "openai-compatible",
                "modelName": "topic-model",
                "baseUrlHash": "b" * 64,
                "providerConfigHash": "c" * 64,
                "generation": {
                    "maxContextTokens": 131_072,
                    "maxOutputTokens": 16_384,
                    "temperature": "0.600",
                    "topP": "0.900",
                    "supportsJson": True,
                },
            },
        }

    async def list_messages_for_prompt(self, session, discussion_id, *, limit):
        self.events.append(("list-prompt", discussion_id, limit))
        return tuple(
            row for row in self.messages if row["discussion_id"] == discussion_id
        )[-limit:]

    async def next_message_sequence(self, session, discussion_id):
        owned = [
            row["sequence_number"]
            for row in self.messages
            if row["discussion_id"] == discussion_id
        ]
        return max(owned, default=0) + 1

    async def insert_message(self, session, row):
        self.events.append(("insert-message", row["role"], row["id"]))
        self.messages.append(dict(row))

    async def insert_request(self, session, row):
        value = dict(row)
        value.update(
            result=None,
            result_hash=None,
            assistant_message_id=None,
            public_error_code=None,
            completed_at=None,
        )
        self.requests[(row["discussion_id"], row["idempotency_key"])] = value
        self.events.append(("insert-request", row["id"]))

    async def touch_discussion(self, session, *, discussion_id, updated_at):
        self.discussions[discussion_id]["updated_at"] = updated_at

    async def complete_request(self, session, **values):
        if self.fail_complete:
            self.fail_complete = False
            raise ConnectionError("uncertain commit")
        row = next(
            item for item in self.requests.values() if item["id"] == values["request_id"]
        )
        row.update(
            status="succeeded",
            assistant_message_id=values["assistant_message_id"],
            result=json.loads(values["result_json"]),
            result_json=values["result_json"],
            result_hash=values["result_hash"],
            completed_at=values["completed_at"],
        )
        self.events.append(("complete-request", row["id"]))
        return True

    async def fail_request(self, session, **values):
        row = next(
            item for item in self.requests.values() if item["id"] == values["request_id"]
        )
        row.update(
            status=values["status"],
            public_error_code=values["public_error_code"],
            completed_at=values["completed_at"],
        )
        self.events.append(("fail-request", values["public_error_code"]))
        return True


def _contexts(repository: FakeRepository):
    active = {"value": False}

    @asynccontextmanager
    async def transaction():
        assert active["value"] is False
        before = deepcopy(
            (repository.discussions, repository.messages, repository.requests)
        )
        active["value"] = True
        repository.events.append(("transaction-enter",))
        try:
            yield object()
        except BaseException:
            (
                repository.discussions,
                repository.messages,
                repository.requests,
            ) = before
            repository.events.append(("transaction-rollback",))
            raise
        else:
            repository.events.append(("transaction-commit",))
        finally:
            active["value"] = False

    @asynccontextmanager
    async def connection():
        assert active["value"] is False
        repository.events.append(("connection-enter",))
        yield object()
        repository.events.append(("connection-exit",))

    return transaction, connection, active


class FakeGateway:
    def __init__(self, active, *, error=None):
        self.active = active
        self.error = error
        self.calls = []

    async def generate(self, **values):
        assert self.active["value"] is False
        self.calls.append(values)
        if self.error is not None:
            raise self.error
        from backend.domain.topics import TopicAssistantResult

        return TopicAssistantResult(
            reply="这个方向适合用地方治理承载长篇升级。",
            directionSuggestions=[],
            candidateSuggestions=[],
        )


def _service(repository, gateway=None):
    from backend.services.topic_discussions import TopicDiscussionService

    transaction, connection, active = _contexts(repository)
    ids = iter(
        (
            "discussion-1",
            "message-user-1",
            "request-1",
            "message-assistant-1",
            "unused-1",
        )
    )
    gateway = gateway or FakeGateway(active)
    return (
        TopicDiscussionService(
            repository,
            transaction_factory=transaction,
            connection_factory=connection,
            provider_gateway=gateway,
            id_factory=lambda: next(ids),
            clock=lambda: 1_721_000_000_000,
        ),
        gateway,
        active,
    )


def _command(*, content="我想写地方治理题材。", key="k" * 64):
    from backend.services.topic_discussions import DiscussTopic

    return DiscussTopic(
        discussionId="discussion-1",
        content=content,
        idempotencyKey=key,
        evidence=[],
        subject=None,
    )


@pytest.mark.asyncio
async def test_create_blank_discussion_has_no_project_or_evidence_dependency():
    repository = FakeRepository()
    service, gateway, _ = _service(repository)

    result = await service.create("自由讨论")

    assert result["id"] == "discussion-1"
    assert result["title"] == "自由讨论"
    assert gateway.calls == []
    assert repository.events == [
        ("transaction-enter",),
        ("insert-discussion", "discussion-1"),
        ("transaction-commit",),
    ]


@pytest.mark.asyncio
async def test_send_reserves_then_calls_provider_outside_transaction_and_publishes():
    repository = FakeRepository()
    service, gateway, _ = _service(repository)
    await service.create("自由讨论")
    repository.events.clear()

    result = await service.send(_command())

    assert result["status"] == "succeeded"
    assert result["result"].reply.startswith("这个方向")
    assert len(gateway.calls) == 1
    assert [row["role"] for row in repository.messages] == ["user", "assistant"]
    assert [row["sequence_number"] for row in repository.messages] == [1, 2]
    manifest = repository.requests[("discussion-1", "k" * 64)][
        "input_manifest"
    ]
    rendered = repr(manifest)
    assert "PRIVATE_TOPIC_KEY" not in rendered
    assert "provider.example" not in rendered
    assert repository.events.index(("transaction-commit",)) < next(
        index
        for index, event in enumerate(repository.events)
        if event[:1] == ("insert-message",) and event[1] == "assistant"
    )


@pytest.mark.asyncio
async def test_same_request_replays_without_second_provider_call():
    repository = FakeRepository()
    service, gateway, _ = _service(repository)
    await service.create("自由讨论")

    first = await service.send(_command())
    replay = await service.send(_command())

    assert replay["requestId"] == first["requestId"]
    assert replay["result"] == first["result"]
    assert len(gateway.calls) == 1
    assert len(repository.messages) == 2


@pytest.mark.asyncio
async def test_same_key_with_different_content_conflicts():
    repository = FakeRepository()
    service, _, _ = _service(repository)
    await service.create("自由讨论")
    await service.send(_command())

    with pytest.raises(TopicFailure) as raised:
        await service.send(_command(content="换一个完全不同的想法。"))
    assert raised.value.code == "TOPIC_REQUEST_CONFLICT"


@pytest.mark.asyncio
async def test_missing_fallback_provider_fails_before_user_message_write():
    repository = FakeRepository(ready=False)
    service, gateway, _ = _service(repository)
    await service.create("自由讨论")

    with pytest.raises(TopicFailure) as raised:
        await service.send(_command())

    assert raised.value.code == "TOPIC_PROVIDER_NOT_READY"
    assert repository.messages == []
    assert repository.requests == {}
    assert gateway.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_name", "expected_code"),
    (
        ("provider", "TOPIC_PROVIDER_FAILED"),
        ("invalid", "TOPIC_INVALID_RESPONSE"),
    ),
)
async def test_fixed_provider_failures_never_create_assistant_message(
    error_name,
    expected_code,
):
    from backend.gateways.topic_discussion_provider import (
        TopicDiscussionInvalidResponse,
        TopicDiscussionProviderError,
    )

    repository = FakeRepository()
    transaction, connection, active = _contexts(repository)
    error = (
        TopicDiscussionProviderError("safe")
        if error_name == "provider"
        else TopicDiscussionInvalidResponse("safe")
    )
    gateway = FakeGateway(active, error=error)
    from backend.services.topic_discussions import TopicDiscussionService

    ids = iter(("discussion-1", "message-user-1", "request-1"))
    service = TopicDiscussionService(
        repository,
        transaction_factory=transaction,
        connection_factory=connection,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=lambda: 1_721_000_000_000,
    )
    await service.create("自由讨论")

    with pytest.raises(TopicFailure) as raised:
        await service.send(_command())

    assert raised.value.code == expected_code
    assert [row["role"] for row in repository.messages] == ["user"]
    request = repository.requests[("discussion-1", "k" * 64)]
    assert request["status"] == "failed"
    assert request["public_error_code"] == expected_code


@pytest.mark.asyncio
async def test_cancellation_and_uncertain_publish_never_fabricate_assistant():
    repository = FakeRepository()
    transaction, connection, active = _contexts(repository)
    gateway = FakeGateway(active, error=asyncio.CancelledError())
    from backend.services.topic_discussions import TopicDiscussionService

    ids = iter(("discussion-1", "message-user-1", "request-1"))
    service = TopicDiscussionService(
        repository,
        transaction_factory=transaction,
        connection_factory=connection,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=lambda: 1_721_000_000_000,
    )
    await service.create("自由讨论")
    with pytest.raises(asyncio.CancelledError):
        await service.send(_command())
    assert [row["role"] for row in repository.messages] == ["user"]

    uncertain = FakeRepository(fail_complete=True)
    service, _, _ = _service(uncertain)
    await service.create("自由讨论")
    with pytest.raises(TopicFailure) as raised:
        await service.send(_command())
    assert raised.value.code == "TOPIC_OUTCOME_UNKNOWN"
    assert [row["role"] for row in uncertain.messages] == ["user"]
    request = uncertain.requests[("discussion-1", "k" * 64)]
    assert request["status"] == "outcome_unknown"
