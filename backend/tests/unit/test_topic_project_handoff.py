from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy

import pytest

from backend.domain.topics import TopicFailure


class FakeTopicRepository:
    def __init__(self):
        self.events = []
        self.receipts = {}
        self.candidate = {
            "id": "candidate-1",
            "status": "active",
            "current_version": 2,
        }
        self.version = {
            "id": "candidate-version-2",
            "candidate_id": "candidate-1",
            "version": 2,
            "content_hash": "c" * 64,
            "payload": {
                "title": "典镇山河",
                "genre": "东方奇幻",
                "logline": "落魄典吏以文契镇守山河。",
                "targetAudience": "男频长篇读者",
                "protagonist": "谨慎的县衙典吏",
                "desire": "守住故乡",
                "coreConflict": "地方豪强争权",
                "worldPressure": "妖灾与王朝失序",
                "openingHook": "地契引出山神索命",
                "differentiation": "契约治理驱动力量成长",
                "storyPromise": "从一镇治理到重定山河",
                "longFormPotential": "镇县府州朝五级递进",
                "marketBasis": "治理升级与东方奇幻结合",
            },
            "basis": {
                "evidence": [{
                    "snapshotId": "snapshot-1",
                    "contentHash": "a" * 64,
                    "sourceId": "source-1",
                }]
            },
        }
        self.snapshot = {
            "id": "snapshot-1",
            "source_id": "source-1",
            "source_url": "https://fanqienovel.com/rank/1",
            "captured_at": 100,
            "content_hash": "a" * 64,
        }

    async def lock_handoff_by_key(self, session, key):
        self.events.append("lock-handoff")
        return self.receipts.get(key)

    async def lock_candidate(self, session, candidate_id):
        self.events.append("lock-candidate")
        return self.candidate if candidate_id == "candidate-1" else None

    async def lock_candidate_version(self, session, **values):
        self.events.append("lock-version")
        if (
            values["candidate_id"] == "candidate-1"
            and values["version"] == 2
            and values["content_hash"] == "c" * 64
        ):
            return deepcopy(self.version)
        return None

    async def lock_snapshot_evidence(self, session, refs):
        self.events.append("lock-snapshots")
        if tuple((item.snapshot_id, item.content_hash) for item in refs) != (
            ("snapshot-1", "a" * 64),
        ):
            raise TopicFailure("TOPIC_NOT_FOUND")
        return (dict(self.snapshot),)

    async def insert_handoff(self, session, row):
        self.events.append("insert-handoff")
        self.receipts[row["idempotency_key"]] = dict(row)


class FakeProjectService:
    def __init__(self, topic):
        self.topic = topic
        self.projects = {}

    async def create_in_session(self, session, command):
        self.topic.events.append("project-foundation")
        self.projects[command.id] = command
        return command


class FakeSeedService:
    def __init__(self, topic):
        self.topic = topic
        self.seeds = {}

    async def create_in_session(self, session, **values):
        self.topic.events.append("seed-foundation")
        self.seeds[values["seed_id"]] = dict(values)
        return type("SeedResult", (), {
            "id": values["seed_id"],
            "revision_id": values["revision_id"],
            "revision": 1,
            "content_hash": __import__(
                "backend.domain.json_contracts", fromlist=["canonical_hash"]
            ).canonical_hash(values["payload"]),
        })()


class Harness:
    def __init__(self):
        from backend.services.topic_project_handoffs import TopicProjectHandoffService

        self.topic = FakeTopicRepository()
        self.projects = FakeProjectService(self.topic)
        self.seeds = FakeSeedService(self.topic)
        self.commits = 0
        self.rollbacks = 0
        self.service = TopicProjectHandoffService(
            self.topic,
            project_service=self.projects,
            seed_service=self.seeds,
            transaction_factory=self.transaction,
            clock=lambda: 1234,
        )

    @asynccontextmanager
    async def transaction(self):
        before = deepcopy((
            self.topic.receipts,
            self.projects.projects,
            self.seeds.seeds,
        ))
        try:
            yield object()
        except BaseException:
            self.topic.receipts, self.projects.projects, self.seeds.seeds = before
            self.rollbacks += 1
            raise
        else:
            self.commits += 1


def _command(**changes):
    from backend.services.topic_project_handoffs import HandoffTopicCandidate

    values = {
        "candidateId": "candidate-1",
        "candidateVersion": 2,
        "candidateHash": "c" * 64,
        "projectTitle": "典镇山河",
        "idempotencyKey": "h" * 64,
    }
    values.update(changes)
    return HandoffTopicCandidate(**values)


@pytest.mark.asyncio
async def test_handoff_locks_authorities_then_creates_unselected_seed_atomically():
    harness = Harness()

    result = await harness.service.create_project(_command())

    assert harness.topic.events == [
        "lock-handoff", "lock-candidate", "lock-version", "lock-snapshots",
        "project-foundation", "seed-foundation", "insert-handoff",
    ]
    assert harness.commits == 1
    assert result["candidateId"] == "candidate-1"
    assert result["seedRevision"] == 1
    seed = next(iter(harness.seeds.seeds.values()))
    assert seed["payload"].title == "典镇山河"
    assert seed["payload"].targetAudience == "男频长篇读者"
    assert seed["provenance"].kind == "topic_candidate"
    assert seed["provenance"].topic_candidate.version == 2
    assert harness.projects.projects[next(iter(harness.projects.projects))].target_words == 2_400_000


@pytest.mark.asyncio
async def test_same_key_replays_and_different_input_conflicts():
    harness = Harness()

    first = await harness.service.create_project(_command())
    replay = await harness.service.create_project(_command())

    assert replay == first
    assert len(harness.projects.projects) == 1
    with pytest.raises(TopicFailure) as raised:
        await harness.service.create_project(_command(projectTitle="不同项目"))
    assert raised.value.code == "TOPIC_REQUEST_CONFLICT"


@pytest.mark.asyncio
async def test_archived_or_mismatched_candidate_is_rejected_before_project_write():
    harness = Harness()
    harness.topic.candidate["status"] = "archived"
    with pytest.raises(TopicFailure) as raised:
        await harness.service.create_project(_command())
    assert raised.value.code == "TOPIC_CANDIDATE_ARCHIVED"
    assert harness.projects.projects == {}

    harness = Harness()
    with pytest.raises(TopicFailure) as raised:
        await harness.service.create_project(_command(candidateHash="d" * 64))
    assert raised.value.code == "TOPIC_NOT_FOUND"
    assert harness.projects.projects == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failed_event",
    ("project-foundation", "seed-foundation", "insert-handoff"),
)
async def test_every_foundation_failure_rolls_back_all_outputs(failed_event):
    harness = Harness()

    if failed_event == "project-foundation":
        original = harness.projects.create_in_session
        async def fail(session, command):
            await original(session, command)
            raise RuntimeError("failed")
        harness.projects.create_in_session = fail
    elif failed_event == "seed-foundation":
        original = harness.seeds.create_in_session
        async def fail(session, **values):
            await original(session, **values)
            raise RuntimeError("failed")
        harness.seeds.create_in_session = fail
    else:
        original = harness.topic.insert_handoff
        async def fail(session, row):
            await original(session, row)
            raise RuntimeError("failed")
        harness.topic.insert_handoff = fail

    with pytest.raises(RuntimeError):
        await harness.service.create_project(_command())

    assert harness.rollbacks == 1
    assert harness.projects.projects == {}
    assert harness.seeds.seeds == {}
    assert harness.topic.receipts == {}
