from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.topics import TopicAssistantResult, TopicFailure
from backend.security.redaction import install_error_handlers


DIRECTION = {
    "title": "县域文运复兴",
    "genreOpportunity": "地方治理与文道升级结合",
    "targetAudience": "男频长篇读者",
    "readerPromise": "治理与成长同步兑现",
    "differentiation": "制度建设推动升级",
    "longFormPotential": "县府州朝逐层展开",
    "risks": "避免说明压过行动",
    "evidenceSummary": "冻结公开榜单仅作参考",
}
CANDIDATE = {
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
}


class FakeDiscussions:
    def __init__(self):
        self.calls = []

    async def list(self, *, offset, limit):
        self.calls.append(("list", offset, limit))
        return ({"id": "discussion-1", "title": "自由讨论", "status": "active",
                 "created_at": 1, "updated_at": 2},)

    async def read(self, discussion_id):
        self.calls.append(("read", discussion_id))
        return {
            "discussion": {"id": discussion_id, "title": "自由讨论",
                           "status": "active", "created_at": 1, "updated_at": 2},
            "messages": ({"id": "message-1", "discussion_id": discussion_id,
                          "sequence_number": 1, "role": "user",
                          "content_text": "我想写地方治理。", "content_hash": "a" * 64,
                          "created_at": 1},),
            "requests": ({
                "id": "request-1", "status": "succeeded",
                "user_message_id": "message-1",
                "assistant_message_id": "message-2", "result": None,
                "result_hash": None, "public_error_code": None,
                "input_manifest": {
                    "evidence": [{"snapshotId": "snapshot-1", "contentHash": "a" * 64}],
                    "subject": None,
                    "provider": {"providerId": "must-not-cross"},
                },
                "created_at": 1, "completed_at": 2,
            },),
        }

    async def create(self, title):
        self.calls.append(("create", title))
        return {"id": "discussion-1", "title": title, "status": "active",
                "created_at": 1, "updated_at": 1}

    async def send(self, command):
        self.calls.append(("send", command))
        return {"status": "succeeded", "requestId": "request-1",
                "assistantMessageId": "message-2",
                "result": TopicAssistantResult(
                    reply="可以从县域治理切入。",
                    directionSuggestions=[], candidateSuggestions=[],
                )}


class FakeLibrary:
    def __init__(self):
        self.calls = []

    async def list_directions(self, **values):
        self.calls.append(("list-directions", values))
        return ()

    async def read_direction(self, value):
        self.calls.append(("read-direction", value))
        return {"direction": {"id": value, "current_version": 1,
                              "created_at": 1, "updated_at": 1},
                "versions": ()}

    async def list_candidates(self, **values):
        self.calls.append(("list-candidates", values))
        return ()

    async def read_candidate(self, value):
        self.calls.append(("read-candidate", value))
        return {"candidate": {"id": value, "status": "active",
                              "current_version": 1, "created_at": 1,
                              "updated_at": 1}, "versions": ()}

    async def save_direction(self, command):
        self.calls.append(("save-direction", command))
        return {"directionId": "direction-1", "versionId": "dv-1",
                "version": 1, "contentHash": "d" * 64,
                "payload": DIRECTION, "basis": {"message": {}, "evidence": []}}

    async def save_candidate(self, command):
        self.calls.append(("save-candidate", command))
        return {"candidateId": "candidate-1", "versionId": "cv-1",
                "version": 1, "contentHash": "c" * 64,
                "payload": CANDIDATE, "basis": {"message": {}, "evidence": []}}

    async def archive_candidate(self, command):
        self.calls.append(("archive", command))
        if command.candidate_id == "missing":
            raise TopicFailure("TOPIC_NOT_FOUND")
        return {"candidateId": command.candidate_id,
                "version": command.expected_version, "status": "archived",
                "updatedAt": 3}


class FakeHandoffs:
    def __init__(self):
        self.calls = []

    async def create_project(self, command):
        self.calls.append(command)
        return {"handoffId": "handoff-1", "candidateId": command.candidate_id,
                "candidateVersion": command.candidate_version,
                "candidateHash": command.candidate_hash, "projectId": "project-1",
                "seedId": "seed-1", "seedRevisionId": "seed-revision-1",
                "seedRevision": 1, "seedHash": "s" * 64, "createdAt": 4}


def _client():
    from backend.domain.routers import topics

    discussions = FakeDiscussions()
    library = FakeLibrary()
    handoffs = FakeHandoffs()
    app = FastAPI()
    app.include_router(topics.router, prefix="/api")
    app.dependency_overrides[topics.get_topic_discussion_service] = lambda: discussions
    app.dependency_overrides[topics.get_topic_library_service] = lambda: library
    app.dependency_overrides[topics.get_topic_handoff_service] = lambda: handoffs
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), discussions, library, handoffs


def test_topic_queries_are_bounded_camel_case_and_decode_path_ids():
    client, discussions, library, _ = _client()

    responses = (
        client.get("/api/topic-discussions?offset=2&limit=20"),
        client.get("/api/topic-discussions/discussion%20one"),
        client.get("/api/topic-directions?offset=1&limit=10"),
        client.get("/api/topic-directions/direction%20one"),
        client.get("/api/topic-candidates?status=archived&offset=3&limit=8"),
        client.get("/api/topic-candidates/candidate%20one"),
    )

    assert [item.status_code for item in responses] == [200] * 6
    assert responses[0].json()[0] == {
        "id": "discussion-1", "title": "自由讨论", "status": "active",
        "createdAt": 1, "updatedAt": 2,
    }
    assert responses[1].json()["messages"][0]["content"] == "我想写地方治理。"
    assert responses[1].json()["requests"][0]["basis"] == {
        "evidence": [{"snapshotId": "snapshot-1", "contentHash": "a" * 64}],
        "subject": None,
    }
    assert "must-not-cross" not in responses[1].text
    assert discussions.calls[:2] == [("list", 2, 20), ("read", "discussion one")]
    assert library.calls[1] == ("read-direction", "direction one")
    assert library.calls[3] == ("read-candidate", "candidate one")


def test_topic_commands_require_explicit_actions_and_return_strict_public_results():
    client, discussions, library, handoffs = _client()
    evidence = [{"snapshotId": "snapshot-1", "contentHash": "a" * 64}]

    created = client.post("/api/topic-discussions", json={"title": "自由讨论"})
    sent = client.post("/api/topic-discussions/discussion-1/messages", json={
        "content": "我想写地方治理。", "idempotencyKey": "m" * 64,
        "evidence": evidence, "subject": None,
    })
    direction = client.post("/api/topic-discussions/discussion-1/directions", json={
        "messageId": "message-2", "payload": DIRECTION, "evidence": evidence,
        "idempotencyKey": "d" * 64,
    })
    candidate = client.post("/api/topic-discussions/discussion-1/candidates", json={
        "messageId": "message-2", "payload": CANDIDATE, "evidence": [],
        "idempotencyKey": "c" * 64,
    })
    archived = client.post("/api/topic-candidates/candidate-1/archive", json={
        "expectedVersion": 1,
    })
    handoff = client.post(
        "/api/topic-candidates/candidate-1/versions/2/projects",
        json={"candidateHash": "c" * 64, "projectTitle": "典镇山河",
              "idempotencyKey": "h" * 64},
    )

    assert [item.status_code for item in (
        created, sent, direction, candidate, archived, handoff
    )] == [200] * 6
    assert sent.json()["result"] == {
        "reply": "可以从县域治理切入。",
        "directionSuggestions": [], "candidateSuggestions": [],
    }
    assert library.calls[0][1].discussion_id == "discussion-1"
    assert handoff.json() == {
        "project": {"id": "project-1", "title": "典镇山河"},
        "seed": {"id": "seed-1", "revision": 1, "isSelected": False,
                 "selectionRevision": 0},
        "handoff": {"candidateId": "candidate-1", "version": 2},
    }
    assert handoffs.calls[0].candidate_version == 2
    assert discussions.calls[-1][0] == "send"


def test_topic_bodies_reject_unknown_fields_and_query_bounds():
    client, discussions, library, handoffs = _client()

    responses = (
        client.post("/api/topic-discussions", json={"title": "讨论", "projectId": "p1"}),
        client.post("/api/topic-discussions/d1/messages", json={
            "content": "想法", "idempotencyKey": "i" * 64, "providerId": "p1"
        }),
        client.get("/api/topic-candidates?limit=101"),
        client.get("/api/topic-candidates?status=deleted"),
        client.post("/api/topic-discussions/d1/candidates", json={
            "messageId": "m1", "payload": CANDIDATE, "evidence": [],
            "idempotencyKey": "c" * 64, "candidateId": "candidate-1",
        }),
    )

    assert [item.status_code for item in responses] == [422] * 5
    assert discussions.calls == []
    assert library.calls == []
    assert handoffs.calls == []


def test_topic_failures_keep_fixed_public_status_and_no_input_echo():
    client, _, _, _ = _client()

    response = client.post("/api/topic-candidates/missing/archive", json={
        "expectedVersion": 1,
    })

    assert response.status_code == 404
    assert response.json()["code"] == "TOPIC_NOT_FOUND"
    assert set(response.json()) == {"code", "message", "correlationId"}
