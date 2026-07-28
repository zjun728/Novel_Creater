from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.drafts import (
    ChapterSessionView,
    ChapterWorkspace,
    DraftCandidateView,
    WorkingDraftView,
)
from backend.routers import chapter_sessions
from backend.security.redaction import install_error_handlers


class FakeChapterSessionService:
    def __init__(self):
        self.saved_content = ""
        self.candidates = ()
        self.create_error = None
        self.session = ChapterSessionView(
            id="session-1",
            project_id="p1",
            planning_revision_id="planning-revision-1",
            planning_revision=1,
            planning_hash="a" * 64,
            story_block_id="block-1",
            story_block_revision=2,
            story_block_hash="b" * 64,
            chapter_outline_revision_id="outline-revision-1",
            chapter_outline_revision=3,
            chapter_outline_hash="c" * 64,
            chapter_num=1,
            expected_canon_revision=0,
            status="drafting",
        )
        self.draft = WorkingDraftView(
            id="draft-1", project_id="p1", chapter_session_id="session-1",
            revision=1, content="", content_hash="e3b0c442" + "0" * 56,
            source_payload={
                "source": "manual-empty",
                "apiKey": "LEAK-SENTINEL",
                "prompt": "LEAK-SENTINEL",
                "raw": "LEAK-SENTINEL",
                "provider": "LEAK-SENTINEL",
            },
            status="drafting",
        )

    def workspace(self):
        return ChapterWorkspace(
            project_id="p1", session=self.session,
            working_draft=self.draft, candidates=self.candidates,
        )

    async def get(self, project_id, chapter_number):
        if project_id == "p1" and chapter_number == 1:
            return self.workspace()
        return None

    async def create_session(self, command):
        if self.create_error is not None:
            raise self.create_error
        return self.workspace()

    async def save_working_draft(self, command):
        self.saved_content = command.content
        self.draft = WorkingDraftView(
            id="draft-1", project_id="p1", chapter_session_id="session-1",
            revision=command.expected_revision + 1,
            content=command.content, content_hash="a" * 64,
            source_payload={"source": "manual-empty"},
            status="drafting",
        )
        return self.workspace()

    async def save_candidate(self, command):
        candidate = DraftCandidateView(
            id="candidate-1", project_id="p1", chapter_session_id="session-1",
            working_draft_revision=command.expected_working_draft_revision,
            content=self.draft.content, content_hash=self.draft.content_hash,
            provenance={
                "source": "explicit-save-candidate",
                "apiKey": "LEAK-SENTINEL",
                "prompt": "LEAK-SENTINEL",
                "raw": "LEAK-SENTINEL",
                "provider": "LEAK-SENTINEL",
            },
            status="drafting",
        )
        self.candidates = (candidate,)
        return self.workspace()


class FakeChapterDraftGenerationService:
    def __init__(self, chapter_service):
        self.chapter_service = chapter_service
        self.commands = []

    async def generate_working_draft(self, command):
        self.commands.append(command)
        self.chapter_service.draft = WorkingDraftView(
            id="draft-1", project_id="p1", chapter_session_id="session-1",
            revision=command.expected_working_draft_revision + 1,
            content="沈清源站在织机前，先听见的是木轴发涩的吱呀声。",
            content_hash="b" * 64,
            source_payload={
                "source": "ai-generation",
                "authorInstruction": command.author_instruction,
            },
            status="drafting",
        )
        return self.chapter_service.workspace()


def make_client():
    service = FakeChapterSessionService()
    generation_service = FakeChapterDraftGenerationService(service)
    app = FastAPI()
    app.include_router(chapter_sessions.router, prefix="/api")
    app.dependency_overrides[chapter_sessions.get_chapter_session_service] = lambda: service
    app.dependency_overrides[
        chapter_sessions.get_chapter_draft_generation_service
    ] = lambda: generation_service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service, generation_service


def test_chapter_session_routes_keep_working_draft_and_candidate_separate():
    client, service, _ = make_client()

    created = client.post("/api/projects/p1/chapter-sessions/1", json={
        "chapterNumber": 1,
        "expectedPlanningRevision": 1,
        "expectedPlanningHash": "a" * 64,
        "expectedOutlineRevision": 3,
        "expectedOutlineHash": "c" * 64,
        "expectedCanonRevision": 0,
    })
    saved = client.put("/api/projects/p1/chapter-sessions/session-1/working-draft", json={
        "expectedRevision": 1,
        "content": "沈清源站在织机前，先听见的是木轴发涩的吱呀声。",
    })
    candidated = client.post("/api/projects/p1/chapter-sessions/session-1/candidates", json={
        "expectedWorkingDraftRevision": 2,
    })

    assert [created.status_code, saved.status_code, candidated.status_code] == [201, 200, 201]
    assert created.json()["session"] == {
        "id": "session-1",
        "projectId": "p1",
        "planningRevisionId": "planning-revision-1",
        "planningRevision": 1,
        "planningHash": "a" * 64,
        "storyBlockId": "block-1",
        "storyBlockRevision": 2,
        "storyBlockHash": "b" * 64,
        "chapterOutlineRevisionId": "outline-revision-1",
        "chapterOutlineRevision": 3,
        "chapterOutlineHash": "c" * 64,
        "chapterNum": 1,
        "expectedCanonRevision": 0,
        "status": "drafting",
    }
    assert created.json()["workingDraft"]["content"] == ""
    assert created.json()["candidates"] == []
    assert saved.json()["workingDraft"]["revision"] == 2
    assert saved.json()["candidates"] == []
    assert candidated.json()["candidates"][0]["workingDraftRevision"] == 2
    assert service.saved_content.startswith("沈清源")


def test_chapter_session_get_reads_only_the_requested_chapter():
    client, _, _ = make_client()

    chapter_one = client.get("/api/projects/p1/chapter-sessions/1")
    chapter_two = client.get("/api/projects/p1/chapter-sessions/2")

    assert chapter_one.status_code == 200
    assert chapter_one.json()["session"]["chapterNum"] == 1
    assert chapter_two.status_code == 200
    assert chapter_two.json() is None


def test_create_chapter_session_rejects_url_body_chapter_mismatch():
    client, _, _ = make_client()

    response = client.post("/api/projects/p1/chapter-sessions/2", json={
        "chapterNumber": 1,
        "expectedPlanningRevision": 1,
        "expectedPlanningHash": "a" * 64,
        "expectedOutlineRevision": 3,
        "expectedOutlineHash": "c" * 64,
        "expectedCanonRevision": 0,
    })

    assert response.status_code == 422
    assert response.json()["code"] == "ChapterSessionRequestInvalid"


def test_create_chapter_session_strictly_rejects_noncanonical_assertions():
    client, _, _ = make_client()
    invalid_bodies = (
        {
            "chapterNumber": True,
            "expectedPlanningRevision": 1,
            "expectedPlanningHash": "a" * 64,
            "expectedOutlineRevision": 3,
            "expectedOutlineHash": "c" * 64,
            "expectedCanonRevision": 0,
        },
        {
            "chapterNumber": 1,
            "expectedPlanningRevision": "1",
            "expectedPlanningHash": "a" * 64,
            "expectedOutlineRevision": 3,
            "expectedOutlineHash": "c" * 64,
            "expectedCanonRevision": 0,
        },
        {
            "chapterNumber": 1,
            "expectedPlanningRevision": 1,
            "expectedPlanningHash": "A" * 64,
            "expectedOutlineRevision": 3,
            "expectedOutlineHash": "c" * 64,
            "expectedCanonRevision": 0,
        },
    )

    for body in invalid_bodies:
        response = client.post(
            "/api/projects/p1/chapter-sessions/1",
            json=body,
        )
        assert response.status_code == 422
        assert response.json()["code"] == "ChapterSessionRequestInvalid"
        assert "A" * 64 not in response.text


def test_create_chapter_session_returns_fixed_conflict_for_non_authoritative_url():
    client, service, _ = make_client()
    service.create_error = chapter_sessions.ChapterSessionConflict(
        "requested chapter 2 differs from secret raw database state",
    )

    response = client.post("/api/projects/p1/chapter-sessions/2", json={
        "chapterNumber": 2,
        "expectedPlanningRevision": 1,
        "expectedPlanningHash": "a" * 64,
        "expectedOutlineRevision": 3,
        "expectedOutlineHash": "c" * 64,
        "expectedCanonRevision": 0,
    }, follow_redirects=False)

    assert response.status_code == 409
    assert response.headers.get("location") is None
    body = response.json()
    assert body["code"] == "ChapterSessionConflict"
    assert body["message"] == (
        "Chapter session state changed; refresh and retry"
    )
    assert isinstance(body["correlationId"], str)
    assert "secret" not in response.text
    assert "database" not in response.text


def test_chapter_session_routes_reject_unknown_fields():
    client, _, _ = make_client()

    response = client.put("/api/projects/p1/chapter-sessions/session-1/working-draft", json={
        "expectedRevision": 1,
        "content": "正文",
        "apiKey": "must-not-send",
    })

    assert response.status_code == 422
    assert response.json()["code"] == "ChapterSessionRequestInvalid"


def test_generate_working_draft_route_updates_draft_without_candidate():
    client, _, generation_service = make_client()

    response = client.post(
        "/api/projects/p1/chapter-sessions/session-1/generate-working-draft",
        json={
            "expectedWorkingDraftRevision": 1,
            "authorInstruction": "多一点市井对话",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["workingDraft"]["revision"] == 2
    assert body["workingDraft"]["content"].startswith("沈清源")
    assert "sourcePayload" not in body["workingDraft"]
    assert body["candidates"] == []
    assert len(generation_service.commands) == 1
    command = generation_service.commands[0]
    assert command.project_id == "p1"
    assert command.chapter_session_id == "session-1"
    assert command.expected_working_draft_revision == 1


def test_chapter_session_public_workspace_never_exports_internal_metadata():
    client, _, _ = make_client()

    response = client.post(
        "/api/projects/p1/chapter-sessions/session-1/candidates",
        json={"expectedWorkingDraftRevision": 1},
    )

    assert response.status_code == 201
    body = response.json()
    assert "sourcePayload" not in body["workingDraft"]
    assert "provenance" not in body["candidates"][0]
    serialized = response.text
    for forbidden in ("LEAK-SENTINEL", "apiKey", "prompt", "raw", "provider"):
        assert forbidden not in serialized


def test_generate_working_draft_route_rejects_secret_debug_fields():
    client, _, _ = make_client()

    response = client.post(
        "/api/projects/p1/chapter-sessions/session-1/generate-working-draft",
        json={
            "expectedWorkingDraftRevision": 1,
            "authorInstruction": "正文更活一点",
            "apiKey": "must-not-send",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "ChapterSessionRequestInvalid"
