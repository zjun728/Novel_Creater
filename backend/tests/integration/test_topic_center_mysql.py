from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import aiomysql
import pytest

from backend.domain.topics import TopicAssistantResult, TopicFailure
from backend.repositories.chapter_outlines import ChapterOutlineRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.projects import ProjectRepository
from backend.repositories.seeds import SeedRepository
from backend.repositories.topics import TopicRepository
from backend.services.model_bindings import ModelBindingService
from backend.services.project_lifecycle import ProjectLifecycleService
from backend.services.seeds import SeedService
from backend.services.topic_discussions import DiscussTopic, TopicDiscussionService
from backend.services.topic_library import (
    ArchiveTopicCandidate,
    SaveTopicCandidate,
    TopicLibraryService,
)
from backend.services.topic_project_handoffs import (
    HandoffTopicCandidate,
    TopicProjectHandoffService,
)
from backend.tests.support.disposable_mysql import (
    _TestDatabaseSession,
    transaction_factory_for,
)


pytestmark = pytest.mark.mysql


def connection_factory_for(config):
    config = {**config, "autocommit": True}

    @asynccontextmanager
    async def factory():
        raw = await aiomysql.connect(**config)
        try:
            yield _TestDatabaseSession(raw)
        finally:
            raw.close()

    return factory


def candidate_payload(title: str) -> dict[str, str]:
    return {
        "title": title,
        "genre": "东方玄幻",
        "logline": "少年执掌残典，在诡异王朝重建一县秩序。",
        "targetAudience": "偏爱建设流与成长升级的长篇读者",
        "protagonist": "守典人沈砚",
        "desire": "保住故乡并查清典籍真相",
        "coreConflict": "每次借典改制都会惊动更高层势力",
        "worldPressure": "王朝崩解与诡异复苏同时逼近",
        "openingHook": "县城一夜从舆图上消失",
        "differentiation": "以基层制度建设推动玄幻升级",
        "storyPromise": "每卷解决一层秩序危机并揭开大典真相",
        "longFormPotential": "县州国天下四级扩张，可支撑二百万字",
        "marketBasis": "合成公开榜单显示建设流拥有稳定读者",
    }


class FakeTopicGateway:
    def __init__(self):
        self.calls = 0

    async def generate(self, **_values):
        self.calls += 1
        return TopicAssistantResult(
            reply="这个方向可以继续收束成长承诺与长期冲突。",
            directionSuggestions=(),
            candidateSuggestions=(candidate_payload("典镇山河"),),
        )


class FailingSeedService(SeedService):
    async def create_in_session(self, session, **values):
        await super().create_in_session(session, **values)
        raise RuntimeError("forced handoff rollback")


async def install_provider(session):
    provider_id = "c0000000-0000-4000-8000-000000000001"
    now = 1_780_000_000_000
    await session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
            stream,max_context_tokens,max_output_tokens,temperature,top_p,
            supports_json,supports_streaming,notes,thinking,lifecycle_status,
            revision,deleted_at,created_at,updated_at)
           VALUES (%s,'P0C Integration Provider','openai-compatible','fake-json',
                   'http://127.0.0.1:9/v1','integration-only',1,0,0,128000,8192,
                   0.7,0.95,1,0,'',NULL,'active',1,NULL,%s,%s)""",
        (provider_id, now, now),
    )
    await session.execute(
        """UPDATE application_settings
              SET fallback_provider_id=%s,revision=revision+1,updated_at=%s
            WHERE singleton_id=1""",
        (provider_id, now),
    )


def handoff_service(topic_repository, tx, connections, seed_service=None):
    model_bindings = ModelBindingService(
        ModelBindingRepository(),
        transaction_factory=tx,
        connection_factory=connections,
    )
    projects = ProjectLifecycleService(
        ProjectRepository(
            chapter_session_repository=ChapterSessionRepository(),
            chapter_outline_repository=ChapterOutlineRepository(),
        ),
        tx,
        connections,
        model_binding_service=model_bindings,
    )
    return TopicProjectHandoffService(
        topic_repository,
        project_service=projects,
        seed_service=seed_service or SeedService(
            SeedRepository(), transaction_factory=tx,
            connection_factory=connections,
        ),
        transaction_factory=tx,
        clock=lambda: 1_780_000_001_000,
    )


@pytest.mark.asyncio
async def test_topic_center_atomicity_versioning_archive_and_handoff(disposable_mysql):
    tx = transaction_factory_for(disposable_mysql.connection_config)
    connections = connection_factory_for(disposable_mysql.connection_config)
    topics = TopicRepository()
    gateway = FakeTopicGateway()
    discussions = TopicDiscussionService(
        topics,
        transaction_factory=tx,
        connection_factory=connections,
        provider_gateway=gateway,
        clock=lambda: 1_780_000_000_100,
    )
    library = TopicLibraryService(
        topics,
        transaction_factory=tx,
        connection_factory=connections,
        clock=lambda: 1_780_000_000_200,
    )

    async with tx() as session:
        await install_provider(session)
    inventory = await disposable_mysql.session.fetchall(
        """SELECT TABLE_NAME AS name FROM information_schema.TABLES
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME LIKE 'topic_%'"""
    )
    assert {row["name"] for row in inventory} >= {
        "topic_discussions", "topic_discussion_messages",
        "topic_discussion_requests", "topic_candidates",
        "topic_candidate_versions", "topic_project_handoffs",
    }

    discussion = await discussions.create("从县城秩序重建讨论长篇东方玄幻")
    command = DiscussTopic(
        discussionId=discussion["id"],
        content="主角的能力必须持续制造政治代价。",
        idempotencyKey="m" * 64,
        evidence=(),
    )
    first = await discussions.send(command)
    replay = await discussions.send(command)
    assert first["result"] == replay["result"]
    assert gateway.calls == 1
    message_count = await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM topic_discussion_messages WHERE discussion_id=%s",
        (discussion["id"],),
    )
    assert message_count == {"count": 2}

    saved = await library.save_candidate(SaveTopicCandidate(
        discussionId=discussion["id"],
        messageId=first["assistantMessageId"],
        payload=candidate_payload("典镇山河"),
        evidence=(),
        idempotencyKey="c" * 64,
    ))
    candidate_id = saved["candidateId"]

    async def revise(title: str, key: str):
        return await library.save_candidate(SaveTopicCandidate(
            discussionId=discussion["id"],
            messageId=first["assistantMessageId"],
            payload=candidate_payload(title),
            evidence=(),
            idempotencyKey=key * 64,
            candidateId=candidate_id,
            expectedVersion=1,
        ))

    outcomes = await asyncio.gather(
        revise("典镇山河·修订甲", "a"),
        revise("典镇山河·修订乙", "b"),
        return_exceptions=True,
    )
    winners = [value for value in outcomes if isinstance(value, dict)]
    conflicts = [value for value in outcomes if isinstance(value, TopicFailure)]
    assert len(winners) == 1 and winners[0]["version"] == 2
    assert len(conflicts) == 1 and conflicts[0].code == "TOPIC_VERSION_CONFLICT", repr(outcomes)

    candidate = await library.read_candidate(candidate_id)
    current_version = next(
        row for row in candidate["versions"]
        if row["version"] == candidate["candidate"]["current_version"]
    )
    rollback_key = "r" * 64
    failing = handoff_service(
        topics, tx, connections,
        seed_service=FailingSeedService(
            SeedRepository(), transaction_factory=tx,
            connection_factory=connections,
        ),
    )
    rollback_command = HandoffTopicCandidate(
        candidateId=candidate_id,
        candidateVersion=current_version["version"],
        candidateHash=current_version["content_hash"],
        projectTitle="必须回滚的项目",
        idempotencyKey=rollback_key,
    )
    with pytest.raises(RuntimeError, match="forced handoff rollback"):
        await failing.create_project(rollback_command)
    rollback_rows = await disposable_mysql.session.fetchone(
        """SELECT
             (SELECT COUNT(*) FROM topic_project_handoffs WHERE idempotency_key=%s) AS receipts,
             (SELECT COUNT(*) FROM projects WHERE title='必须回滚的项目') AS projects,
             (SELECT COUNT(*) FROM creative_seeds s JOIN projects p ON p.id=s.project_id
               WHERE p.title='必须回滚的项目') AS seeds""",
        (rollback_key,),
    )
    assert rollback_rows == {"receipts": 0, "projects": 0, "seeds": 0}

    service = handoff_service(topics, tx, connections)
    handoff_command = rollback_command.model_copy(update={
        "project_title": "典镇山河",
        "idempotency_key": "h" * 64,
    })
    handed = await service.create_project(handoff_command)
    assert await service.create_project(handoff_command) == handed

    await library.archive_candidate(ArchiveTopicCandidate(
        candidateId=candidate_id,
        expectedVersion=current_version["version"],
    ))
    facts = await disposable_mysql.session.fetchone(
        """SELECT
          (SELECT COUNT(*) FROM creative_seed_heads h JOIN creative_seeds s ON s.id=h.seed_id
            WHERE s.project_id=%s) AS seed_heads,
          (SELECT COUNT(*) FROM project_selected_seeds WHERE project_id=%s) AS selected,
          (SELECT canon_revision_number FROM projection_heads WHERE project_id=%s) AS projection_revision,
          (SELECT revision FROM project_contract_heads WHERE project_id=%s) AS contract_revision,
          (SELECT revision FROM project_bible_heads WHERE project_id=%s) AS bible_revision,
          (SELECT revision FROM project_planning_heads WHERE project_id=%s) AS planning_revision,
          (SELECT COUNT(*) FROM topic_project_handoffs h
             JOIN topic_candidate_versions v
               ON v.candidate_id=h.candidate_id AND v.version=h.candidate_version
            WHERE h.project_id=%s) AS preserved_handoff,
          (SELECT status FROM topic_candidates WHERE id=%s) AS candidate_status""",
        (handed["projectId"],) * 7 + (candidate_id,),
    )
    assert facts == {
        "seed_heads": 1,
        "selected": 0,
        "projection_revision": 0,
        "contract_revision": 0,
        "bible_revision": 0,
        "planning_revision": 0,
        "preserved_handoff": 1,
        "candidate_status": "archived",
    }
