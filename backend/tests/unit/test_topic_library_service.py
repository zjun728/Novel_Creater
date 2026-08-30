from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy

import pytest

from backend.domain.topics import TopicFailure


def _direction_payload(title="县域文运复兴"):
    return {
        "title": title,
        "genreOpportunity": "地方治理与文道升级结合",
        "targetAudience": "偏好稳健升级的男频读者",
        "readerPromise": "治理成果与个人成长同步兑现",
        "differentiation": "以制度建设替代单纯打怪",
        "longFormPotential": "可按县府州朝逐层展开",
        "risks": "需避免政策说明压过人物行动",
        "evidenceSummary": "来自作者讨论与冻结榜单快照",
    }


def _candidate_payload(title="典镇山河"):
    return {
        "title": title,
        "genre": "东方奇幻",
        "logline": "落魄典吏以文契镇守山河。",
        "targetAudience": "男频长篇读者",
        "protagonist": "谨慎但有担当的县衙典吏",
        "desire": "守住故乡并重建秩序",
        "coreConflict": "旧秩序崩坏与地方豪强争权",
        "worldPressure": "妖灾与王朝失序同时逼近",
        "openingHook": "一纸失效地契引出山神索命",
        "differentiation": "用契约和治理推动力量成长",
        "storyPromise": "从一镇治理到重定天下山河",
        "longFormPotential": "镇县府州朝五级递进可承载长篇",
        "marketBasis": "结合治理升级与东方奇幻阅读期待",
    }


class FakeRepository:
    def __init__(self):
        self.discussions = {"discussion-1": {"id": "discussion-1"}}
        self.messages = {
            ("discussion-1", "message-1"): {
                "id": "message-1",
                "discussion_id": "discussion-1",
                "role": "assistant",
                "content_text": "建议采用地方治理与文道升级结合。",
                "content_hash": "m" * 64,
            }
        }
        self.directions = {}
        self.direction_versions = []
        self.candidates = {}
        self.candidate_versions = []
        self.events = []

    async def lock_discussion(self, session, discussion_id):
        return self.discussions.get(discussion_id)

    async def lock_message(self, session, *, discussion_id, message_id):
        return self.messages.get((discussion_id, message_id))

    async def lock_snapshot_evidence(self, session, refs):
        return tuple(
            {
                "id": ref.snapshot_id,
                "source_id": "source-1",
                "content_hash": ref.content_hash,
                "captured_at": 100,
                "platform": "fanqie",
                "ranking_name": "reading",
                "category": "male",
            }
            for ref in refs
        )

    async def find_direction_version_by_key(self, session, key):
        return next(
            (row for row in self.direction_versions if row["idempotency_key"] == key),
            None,
        )

    async def find_candidate_version_by_key(self, session, key):
        return next(
            (row for row in self.candidate_versions if row["idempotency_key"] == key),
            None,
        )

    async def lock_direction(self, session, direction_id):
        return self.directions.get(direction_id)

    async def lock_candidate(self, session, candidate_id):
        return self.candidates.get(candidate_id)

    async def insert_direction_identity(self, session, row):
        self.directions[row["id"]] = dict(row)

    async def insert_direction_version(self, session, row):
        self.direction_versions.append(_decode_row(row))

    async def insert_candidate_identity(self, session, row):
        self.candidates[row["id"]] = dict(row)

    async def insert_candidate_version(self, session, row):
        self.candidate_versions.append(_decode_row(row))

    async def advance_direction(self, session, **values):
        row = self.directions.get(values["direction_id"])
        if row is None or row["current_version"] != values["expected_version"]:
            return False
        row.update(
            current_version=values["version"],
            updated_at=values["updated_at"],
        )
        return True

    async def advance_candidate(self, session, **values):
        row = self.candidates.get(values["candidate_id"])
        if (
            row is None
            or row["status"] != "active"
            or row["current_version"] != values["expected_version"]
        ):
            return False
        row.update(
            current_version=values["version"],
            updated_at=values["updated_at"],
        )
        return True

    async def archive_candidate(self, session, **values):
        row = self.candidates.get(values["candidate_id"])
        if (
            row is None
            or row["status"] != "active"
            or row["current_version"] != values["expected_version"]
        ):
            return False
        row.update(status="archived", updated_at=values["updated_at"])
        return True

    async def list_directions(self, session, **values):
        return tuple(self.direction_versions)

    async def read_direction(self, session, direction_id):
        if direction_id not in self.directions:
            return None
        return {"direction": self.directions[direction_id], "versions": tuple(
            row for row in self.direction_versions if row["direction_id"] == direction_id
        )}

    async def list_candidates(self, session, *, status, **values):
        return tuple(
            row for row in self.candidate_versions
            if self.candidates[row["candidate_id"]]["status"] == status
        )

    async def read_candidate(self, session, candidate_id):
        if candidate_id not in self.candidates:
            return None
        return {"candidate": self.candidates[candidate_id], "versions": tuple(
            row for row in self.candidate_versions if row["candidate_id"] == candidate_id
        )}


def _decode_row(row):
    import json

    value = dict(row)
    value["payload"] = json.loads(value["payload_json"])
    value["basis"] = json.loads(value["basis_json"])
    return value


def _contexts(repository):
    @asynccontextmanager
    async def transaction():
        before = deepcopy(
            (
                repository.directions,
                repository.direction_versions,
                repository.candidates,
                repository.candidate_versions,
            )
        )
        repository.events.append("transaction-enter")
        try:
            yield object()
        except BaseException:
            (
                repository.directions,
                repository.direction_versions,
                repository.candidates,
                repository.candidate_versions,
            ) = before
            repository.events.append("transaction-rollback")
            raise
        else:
            repository.events.append("transaction-commit")

    @asynccontextmanager
    async def connection():
        repository.events.append("connection-enter")
        yield object()
        repository.events.append("connection-exit")

    return transaction, connection


def _service(repository=None):
    from backend.services.topic_library import TopicLibraryService

    repository = repository or FakeRepository()
    transaction, connection = _contexts(repository)
    counter = iter(f"id-{index}" for index in range(1, 30))
    return TopicLibraryService(
        repository,
        transaction_factory=transaction,
        connection_factory=connection,
        id_factory=lambda: next(counter),
        clock=lambda: 1_721_000_000_000,
    ), repository


def _direction_command(**changes):
    from backend.services.topic_library import SaveTopicDirection

    values = {
        "discussionId": "discussion-1",
        "messageId": "message-1",
        "payload": _direction_payload(),
        "evidence": [{"snapshotId": "snapshot-1", "contentHash": "a" * 64}],
        "idempotencyKey": "d" * 64,
    }
    values.update(changes)
    return SaveTopicDirection(**values)


def _candidate_command(**changes):
    from backend.services.topic_library import SaveTopicCandidate

    values = {
        "discussionId": "discussion-1",
        "messageId": "message-1",
        "payload": _candidate_payload(),
        "evidence": [],
        "idempotencyKey": "c" * 64,
    }
    values.update(changes)
    return SaveTopicCandidate(**values)


@pytest.mark.asyncio
async def test_new_direction_locks_explicit_message_and_freezes_evidence_basis():
    service, repository = _service()

    result = await service.save_direction(_direction_command())

    assert result["directionId"] == "id-1"
    assert result["version"] == 1
    assert result["payload"]["title"] == "县域文运复兴"
    assert result["basis"]["message"] == {
        "id": "message-1",
        "contentHash": "m" * 64,
    }
    assert result["basis"]["evidence"] == [{
        "snapshotId": "snapshot-1",
        "contentHash": "a" * 64,
        "sourceId": "source-1",
    }]
    assert repository.events == ["transaction-enter", "transaction-commit"]


@pytest.mark.asyncio
async def test_message_must_exist_inside_the_named_discussion():
    service, repository = _service()
    repository.messages[("other", "message-1")] = repository.messages.pop(
        ("discussion-1", "message-1")
    )

    with pytest.raises(TopicFailure) as raised:
        await service.save_candidate(_candidate_command())

    assert raised.value.code == "TOPIC_NOT_FOUND"
    assert repository.candidates == {}


@pytest.mark.asyncio
async def test_exact_expected_version_appends_and_stale_version_conflicts():
    service, repository = _service()
    first = await service.save_direction(_direction_command())
    second = await service.save_direction(_direction_command(
        directionId=first["directionId"],
        expectedVersion=1,
        idempotencyKey="e" * 64,
        payload=_direction_payload("府域文运复兴"),
    ))

    assert second["version"] == 2
    assert repository.directions[first["directionId"]]["current_version"] == 2
    with pytest.raises(TopicFailure) as raised:
        await service.save_direction(_direction_command(
            directionId=first["directionId"],
            expectedVersion=1,
            idempotencyKey="f" * 64,
        ))
    assert raised.value.code == "TOPIC_VERSION_CONFLICT"
    assert len(repository.direction_versions) == 2


@pytest.mark.asyncio
async def test_idempotency_replays_same_version_and_rejects_different_content():
    service, repository = _service()
    command = _candidate_command()

    first = await service.save_candidate(command)
    replay = await service.save_candidate(command)

    assert replay == first
    assert len(repository.candidate_versions) == 1
    with pytest.raises(TopicFailure) as raised:
        await service.save_candidate(_candidate_command(
            payload=_candidate_payload("不同种子"),
        ))
    assert raised.value.code == "TOPIC_REQUEST_CONFLICT"


@pytest.mark.asyncio
async def test_archive_hides_active_candidate_but_preserves_readable_versions():
    from backend.services.topic_library import ArchiveTopicCandidate

    service, repository = _service()
    saved = await service.save_candidate(_candidate_command())
    archived = await service.archive_candidate(ArchiveTopicCandidate(
        candidateId=saved["candidateId"],
        expectedVersion=1,
    ))

    assert archived["status"] == "archived"
    assert await service.list_candidates(status="active") == ()
    detail = await service.read_candidate(saved["candidateId"])
    assert detail["candidate"]["status"] == "archived"
    assert len(detail["versions"]) == 1
    assert repository.events[-4:] == [
        "connection-enter", "connection-exit",
        "connection-enter", "connection-exit",
    ]


@pytest.mark.asyncio
async def test_archived_candidate_rejects_new_versions_without_project_writes():
    from backend.services.topic_library import ArchiveTopicCandidate

    service, repository = _service()
    saved = await service.save_candidate(_candidate_command())
    await service.archive_candidate(ArchiveTopicCandidate(
        candidateId=saved["candidateId"],
        expectedVersion=1,
    ))

    with pytest.raises(TopicFailure) as raised:
        await service.save_candidate(_candidate_command(
            candidateId=saved["candidateId"],
            expectedVersion=1,
            idempotencyKey="n" * 64,
        ))
    assert raised.value.code == "TOPIC_CANDIDATE_ARCHIVED"
    assert not any("project" in str(event).casefold() for event in repository.events)


@pytest.mark.asyncio
async def test_new_version_requires_id_and_expected_version_together():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _candidate_command(candidateId="candidate-1")
    with pytest.raises(ValidationError):
        _direction_command(expectedVersion=1)
