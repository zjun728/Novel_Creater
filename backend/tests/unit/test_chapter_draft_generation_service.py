from __future__ import annotations

import pytest


class FakeChapterRepository:
    def __init__(self):
        self.provider = {
            "id": "provider-writing",
            "name": "联通云",
            "provider_type": "openai-compatible",
            "model_name": "deepseek-v4-flash",
            "base_url": "https://provider.example/v1",
            "api_key": "secret-key",
            "temperature": 0.78,
            "max_output_tokens": 4500,
        }
        self.session = {
            "id": "session-1",
            "project_id": "p1",
            "story_block_id": "block-1",
            "chapter_num": 1,
            "expected_canon_revision": 0,
            "expected_story_block_revision": 1,
            "planning_snapshot": {
                "storyBlock": {"title": "典籍入山河", "goal": "入局"},
                "stages": [{"purpose": "让主角第一次用知识解决麻烦"}],
                "sceneTasks": [{"task": "织机故障引出沈清源的判断"}],
            },
            "status": "drafting",
        }
        self.working_draft = {
            "id": "draft-1",
            "project_id": "p1",
            "chapter_session_id": "session-1",
            "revision": 1,
            "content": "",
            "content_hash": "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855",
            "source_payload": {"source": "manual-empty"},
            "updated_at": 1,
        }
        self.candidates = []
        self.upsert_calls = []

    async def read_session_by_id(self, session, project_id, chapter_session_id):
        if project_id == "p1" and chapter_session_id == "session-1":
            return self.session
        return None

    async def read_working_draft(self, session, chapter_session_id):
        if chapter_session_id == self.working_draft["chapter_session_id"]:
            return self.working_draft
        return None

    async def resolve_writing_provider(self, session, project_id):
        return self.provider if project_id == "p1" else None

    async def upsert_working_draft(self, session, row):
        self.upsert_calls.append(row)
        self.working_draft = row
        return True

    async def list_candidates(self, session, chapter_session_id):
        return [item for item in self.candidates if item["chapter_session_id"] == chapter_session_id]


class FakeTx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def tx_factory():
    return FakeTx()


class FakeGateway:
    def __init__(self, output="沈清源站在织机前，先听见的是木轴发涩的吱呀声。"):
        self.output = output
        self.calls = []

    async def generate(self, *, provider, messages, generation_config):
        self.calls.append({
            "provider": dict(provider),
            "messages": list(messages),
            "generation_config": dict(generation_config),
        })
        if isinstance(self.output, BaseException):
            raise self.output
        return self.output


@pytest.mark.asyncio
async def test_generation_writes_provider_output_to_working_draft_without_candidate():
    from backend.services.chapter_draft_generation import (
        ChapterDraftGenerationService,
        GenerateWorkingDraft,
    )

    repo = FakeChapterRepository()
    gateway = FakeGateway()
    service = ChapterDraftGenerationService(
        repo, provider_gateway=gateway, transaction_factory=tx_factory,
    )

    result = await service.generate_working_draft(GenerateWorkingDraft(
        project_id="p1",
        chapter_session_id="session-1",
        expected_working_draft_revision=1,
        author_instruction="多一点市井对话",
    ))

    assert result.working_draft.revision == 2
    assert result.working_draft.content.startswith("沈清源")
    assert result.working_draft.source_payload["source"] == "ai-generation"
    assert result.working_draft.source_payload["providerId"] == "provider-writing"
    assert result.working_draft.source_payload["modelName"] == "deepseek-v4-flash"
    assert result.working_draft.source_payload["authorInstruction"] == "多一点市井对话"
    assert result.candidates == ()
    assert repo.candidates == []
    assert len(gateway.calls) == 1
    rendered_messages = "\n".join(message["content"] for message in gateway.calls[0]["messages"])
    assert "典籍入山河" in rendered_messages
    assert "多一点市井对话" in rendered_messages
    assert "secret-key" not in rendered_messages


@pytest.mark.asyncio
async def test_generation_conflict_does_not_call_provider():
    from backend.services.chapter_draft_generation import (
        ChapterDraftGenerationConflict,
        ChapterDraftGenerationService,
        GenerateWorkingDraft,
    )

    repo = FakeChapterRepository()
    gateway = FakeGateway()
    service = ChapterDraftGenerationService(
        repo, provider_gateway=gateway, transaction_factory=tx_factory,
    )

    with pytest.raises(ChapterDraftGenerationConflict):
        await service.generate_working_draft(GenerateWorkingDraft(
            project_id="p1",
            chapter_session_id="session-1",
            expected_working_draft_revision=9,
            author_instruction="不会调用模型",
        ))

    assert gateway.calls == []
    assert repo.upsert_calls == []
    assert repo.working_draft["revision"] == 1


@pytest.mark.asyncio
async def test_generation_provider_failure_does_not_mutate_draft():
    from backend.gateways.chapter_draft_provider import ChapterDraftProviderError
    from backend.services.chapter_draft_generation import (
        ChapterDraftGenerationFailed,
        ChapterDraftGenerationService,
        GenerateWorkingDraft,
    )

    repo = FakeChapterRepository()
    gateway = FakeGateway(ChapterDraftProviderError("provider failed safely"))
    service = ChapterDraftGenerationService(
        repo, provider_gateway=gateway, transaction_factory=tx_factory,
    )

    with pytest.raises(ChapterDraftGenerationFailed):
        await service.generate_working_draft(GenerateWorkingDraft(
            project_id="p1",
            chapter_session_id="session-1",
            expected_working_draft_revision=1,
        ))

    assert len(gateway.calls) == 1
    assert repo.upsert_calls == []
    assert repo.working_draft["revision"] == 1
