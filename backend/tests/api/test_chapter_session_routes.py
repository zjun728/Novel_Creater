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
        self.session = ChapterSessionView(
            id="session-1", project_id="p1", story_block_id="block-1",
            chapter_num=1, expected_canon_revision=0,
            expected_story_block_revision=1,
            planning_snapshot={"storyBlockId": "block-1"},
            status="drafting",
        )
        self.draft = WorkingDraftView(
            id="draft-1", project_id="p1", chapter_session_id="session-1",
            revision=1, content="", content_hash="e3b0c442" + "0" * 56,
            source_payload={"source": "manual-empty"},
        )

    def workspace(self):
        return ChapterWorkspace(
            project_id="p1", session=self.session,
            working_draft=self.draft, candidates=self.candidates,
        )

    async def get_current(self, project_id):
        return self.workspace()

    async def create_session(self, command):
        return self.workspace()

    async def save_working_draft(self, command):
        self.saved_content = command.content
        self.draft = WorkingDraftView(
            id="draft-1", project_id="p1", chapter_session_id="session-1",
            revision=command.expected_revision + 1,
            content=command.content, content_hash="a" * 64,
            source_payload={"source": "manual-empty"},
        )
        return self.workspace()

    async def save_candidate(self, command):
        candidate = DraftCandidateView(
            id="candidate-1", project_id="p1", chapter_session_id="session-1",
            working_draft_revision=command.expected_working_draft_revision,
            content=self.draft.content, content_hash=self.draft.content_hash,
            provenance={"source": "explicit-save-candidate"},
        )
        self.candidates = (candidate,)
        return self.workspace()


def make_client():
    service = FakeChapterSessionService()
    app = FastAPI()
    app.include_router(chapter_sessions.router, prefix="/api")
    app.dependency_overrides[chapter_sessions.get_chapter_session_service] = lambda: service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def test_chapter_session_routes_keep_working_draft_and_candidate_separate():
    client, service = make_client()

    created = client.post("/api/projects/p1/chapter-sessions", json={
        "expectedStoryBlockRevision": 1,
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
    assert created.json()["workingDraft"]["content"] == ""
    assert created.json()["candidates"] == []
    assert saved.json()["workingDraft"]["revision"] == 2
    assert saved.json()["candidates"] == []
    assert candidated.json()["candidates"][0]["workingDraftRevision"] == 2
    assert service.saved_content.startswith("沈清源")


def test_chapter_session_routes_reject_unknown_fields():
    client, _ = make_client()

    response = client.put("/api/projects/p1/chapter-sessions/session-1/working-draft", json={
        "expectedRevision": 1,
        "content": "正文",
        "apiKey": "must-not-send",
    })

    assert response.status_code == 422
    assert response.json()["code"] == "ChapterSessionRequestInvalid"
