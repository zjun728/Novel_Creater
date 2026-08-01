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


FREEZE_KEY = "11111111-1111-1111-1111-111111111111"


class FakeChapterSessionService:
    def __init__(self):
        self.saved_content = ""
        self.saved_expected_content_hash = None
        self.candidate_commands = []
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
        self.saved_expected_content_hash = command.expected_content_hash
        self.draft = WorkingDraftView(
            id="draft-1", project_id="p1", chapter_session_id="session-1",
            revision=command.expected_revision + 1,
            content=command.content, content_hash="a" * 64,
            source_payload={"source": "manual-empty"},
            status="drafting",
        )
        return self.workspace()

    async def save_candidate(self, command):
        from backend.services.chapter_sessions import CandidateSaveResult

        self.candidate_commands.append(command)
        candidate = DraftCandidateView(
            id="candidate-1", project_id="p1", chapter_session_id="session-1",
            working_draft_revision=command.expected_working_draft_revision,
            content=self.draft.content, content_hash=self.draft.content_hash,
            outline_revision_id="outline-revision-3",
            outline_revision=3,
            outline_hash="c" * 64,
            planning_revision_id="planning-revision-1",
            planning_revision=1,
            planning_hash="a" * 64,
            canon_revision=0,
            projection_revision=0,
            projection_hash="d" * 64,
            basis_status="current",
            status="drafting",
        )
        self.candidates = (candidate,)
        return CandidateSaveResult(self.workspace(), candidate.id)


def make_client():
    service = FakeChapterSessionService()
    app = FastAPI()
    app.include_router(chapter_sessions.router, prefix="/api")
    app.dependency_overrides[chapter_sessions.get_chapter_session_service] = lambda: service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def test_chapter_session_routes_keep_working_draft_and_candidate_separate():
    client, service = make_client()

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
        "expectedContentHash": "e3b0c442" + "0" * 56,
        "content": "沈清源站在织机前，先听见的是木轴发涩的吱呀声。",
    })
    candidated = client.post("/api/projects/p1/chapter-sessions/session-1/candidates", json={
        "expectedWorkingDraftRevision": 2,
        "expectedContentHash": "a" * 64,
        "idempotencyKey": FREEZE_KEY,
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
    assert candidated.json()["savedCandidateId"] == "candidate-1"
    assert service.saved_content.startswith("沈清源")
    assert service.saved_expected_content_hash == "e3b0c442" + "0" * 56
    assert service.candidate_commands[0].expected_content_hash == "a" * 64
    assert service.candidate_commands[0].idempotency_key == FREEZE_KEY


def test_chapter_session_get_reads_only_the_requested_chapter():
    client, _ = make_client()

    chapter_one = client.get("/api/projects/p1/chapter-sessions/1")
    chapter_two = client.get("/api/projects/p1/chapter-sessions/2")

    assert chapter_one.status_code == 200
    assert chapter_one.json()["session"]["chapterNum"] == 1
    assert chapter_two.status_code == 200
    assert chapter_two.json() is None


def test_create_chapter_session_rejects_url_body_chapter_mismatch():
    client, _ = make_client()

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
    client, _ = make_client()
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
    client, service = make_client()
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
    client, _ = make_client()

    response = client.put("/api/projects/p1/chapter-sessions/session-1/working-draft", json={
        "expectedRevision": 1,
        "expectedContentHash": "e3b0c442" + "0" * 56,
        "content": "正文",
        "apiKey": "must-not-send",
    })

    assert response.status_code == 422
    assert response.json()["code"] == "ChapterSessionRequestInvalid"


def test_save_working_draft_route_requires_canonical_content_hash():
    client, _ = make_client()

    for body in (
        {"expectedRevision": 1, "content": "正文"},
        {
            "expectedRevision": 1,
            "expectedContentHash": "A" * 64,
            "content": "正文",
        },
    ):
        response = client.put(
            "/api/projects/p1/chapter-sessions/session-1/working-draft",
            json=body,
        )

        assert response.status_code == 422
        assert response.json()["code"] == "ChapterSessionRequestInvalid"


def test_save_candidate_route_requires_canonical_lowercase_uuid_idempotency_key():
    client, _ = make_client()

    for idempotency_key in (
        "secret-shaped-token-which-was-previously-allowed",
        "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",
    ):
        response = client.post(
            "/api/projects/p1/chapter-sessions/session-1/candidates",
            json={
                "expectedWorkingDraftRevision": 1,
                "expectedContentHash": "e3b0c442" + "0" * 56,
                "idempotencyKey": idempotency_key,
            },
        )

        assert response.status_code == 422
        assert response.json()["code"] == "ChapterSessionRequestInvalid"


def test_chapter_session_public_workspace_never_exports_internal_metadata():
    client, _ = make_client()

    response = client.post(
        "/api/projects/p1/chapter-sessions/session-1/candidates",
        json={
            "expectedWorkingDraftRevision": 1,
            "expectedContentHash": "e3b0c442" + "0" * 56,
            "idempotencyKey": FREEZE_KEY,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "sourcePayload" not in body["workingDraft"]
    assert "provenance" not in body["candidates"][0]
    assert body["savedCandidateId"] == "candidate-1"
    serialized = response.text
    for forbidden in (
        "LEAK-SENTINEL", "apiKey", "prompt", "raw", "provider",
        "idempotencyKey", "freeze_requests",
    ):
        assert forbidden not in serialized


def test_chapter_session_public_workspace_exports_only_candidate_basis_fields():
    client, _ = make_client()

    response = client.post(
        "/api/projects/p1/chapter-sessions/session-1/candidates",
        json={
            "expectedWorkingDraftRevision": 1,
            "expectedContentHash": "e3b0c442" + "0" * 56,
            "idempotencyKey": FREEZE_KEY,
        },
    )

    assert response.status_code == 201
    candidate = response.json()["candidates"][0]
    assert candidate["outlineRevisionId"] == "outline-revision-3"
    assert candidate["outlineRevision"] == 3
    assert candidate["outlineHash"] == "c" * 64
    assert candidate["planningRevisionId"] == "planning-revision-1"
    assert candidate["planningRevision"] == 1
    assert candidate["planningHash"] == "a" * 64
    assert candidate["canonRevision"] == 0
    assert candidate["projectionRevision"] == 0
    assert candidate["projectionHash"] == "d" * 64
    assert candidate["basisStatus"] == "current"
    assert "provenance" not in candidate
    assert "basisHash" not in candidate
    assert "provider" not in candidate
    assert "prompt" not in candidate
