from __future__ import annotations

import asyncio
from urllib.parse import quote

import pytest

from backend import http_errors


class FakeChapterRepository:
    def __init__(self):
        self.archived = False
        self.provider = {
            "binding_revision_id": "binding-revision-1",
            "binding_revision": 1,
            "binding_hash": "9" * 64,
            "binding_item_hash": "8" * 64,
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
            "planning_revision_id": "planning-revision-1",
            "planning_revision": 1,
            "planning_hash": "a" * 64,
            "story_block_id": "block-1",
            "story_block_revision": 2,
            "story_block_hash": "b" * 64,
            "chapter_outline_revision_id": "outline-revision-1",
            "chapter_outline_revision": 3,
            "chapter_outline_hash": "c" * 64,
            "chapter_num": 1,
            "expected_canon_revision": 0,
            "outline_canon_revision": 0,
            "outline_projection_revision": 0,
            "outline_projection_hash": "d" * 64,
            "chapter_outline": {
                "chapterGoal": "主角第一次用典籍知识解决眼前麻烦",
                "scenes": ["织机故障", "主角判断木轴受潮"],
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
        self.projection_head = {
            "canon_revision_number": 0,
            "projection_revision_number": 0,
            "content_hash": "d" * 64,
        }
        self.candidates = []
        self.upsert_calls = []
        self.cas_calls = []

    async def lock_project(self, session, project_id):
        if self.archived:
            raise http_errors.ProjectArchived()
        return {"id": project_id} if project_id == "p1" else None

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

    async def read_projection_head(self, session, project_id):
        return self.projection_head if project_id == "p1" else None

    async def upsert_working_draft(
        self,
        session,
        row,
        *,
        expected_revision=None,
        expected_content_hash=None,
    ):
        self.upsert_calls.append(row)
        self.cas_calls.append((expected_revision, expected_content_hash))
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


class TransactionTracker:
    def __init__(self):
        self.active = 0
        self.entries = 0

    def factory(self):
        tracker = self

        class TrackingTx:
            async def __aenter__(self):
                tracker.active += 1
                tracker.entries += 1
                return object()

            async def __aexit__(self, exc_type, exc, tb):
                tracker.active -= 1
                return False

        return TrackingTx()


class FakeGateway:
    def __init__(
        self,
        output="沈清源站在织机前，先听见的是木轴发涩的吱呀声。",
        *,
        tracker=None,
        on_generate=None,
    ):
        self.output = output
        self.tracker = tracker
        self.on_generate = on_generate
        self.calls = []

    async def generate(self, *, provider, messages, generation_config):
        if self.tracker is not None:
            assert self.tracker.active == 0
        self.calls.append({
            "provider": dict(provider),
            "messages": list(messages),
            "generation_config": dict(generation_config),
        })
        if self.on_generate is not None:
            self.on_generate()
        if isinstance(self.output, BaseException):
            raise self.output
        return self.output


class BlockingGateway(FakeGateway):
    def __init__(self, tracker):
        super().__init__(tracker=tracker)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, *, provider, messages, generation_config):
        self.entered.set()
        assert self.tracker.active == 0
        self.calls.append({
            "provider": dict(provider),
            "messages": list(messages),
            "generation_config": dict(generation_config),
        })
        await self.release.wait()
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
    assert repo.cas_calls == [(1, "e3b0c44298fc1c149afbf4c8996fb924"
                                "27ae41e4649b934ca495991b7852b855")]
    assert len(gateway.calls) == 1
    rendered_messages = "\n".join(message["content"] for message in gateway.calls[0]["messages"])
    assert "主角第一次用典籍知识解决眼前麻烦" in rendered_messages
    assert "织机故障" in rendered_messages
    assert "多一点市井对话" in rendered_messages
    assert "planning_snapshot" not in rendered_messages
    assert "secret-key" not in rendered_messages


@pytest.mark.asyncio
async def test_generation_releases_transaction_while_provider_is_pending():
    from backend.services.chapter_draft_generation import (
        ChapterDraftGenerationService,
        GenerateWorkingDraft,
    )

    repo = FakeChapterRepository()
    tracker = TransactionTracker()
    gateway = BlockingGateway(tracker)
    service = ChapterDraftGenerationService(
        repo,
        provider_gateway=gateway,
        transaction_factory=tracker.factory,
    )

    pending = asyncio.create_task(service.generate_working_draft(
        GenerateWorkingDraft(
            project_id="p1",
            chapter_session_id="session-1",
            expected_working_draft_revision=1,
        )
    ))
    await gateway.entered.wait()
    assert tracker.active == 0
    async with tracker.factory():
        assert tracker.active == 1
    gateway.release.set()

    result = await pending

    assert result.working_draft.revision == 2
    assert tracker.active == 0
    assert tracker.entries == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift",
    (
        "session-pin",
        "draft-revision",
        "draft-hash",
        "projection-revision",
        "projection-hash",
        "binding-identity",
        "provider-identity",
        "canon-projection-unsynchronized",
    ),
)
async def test_generation_rechecks_frozen_session_and_draft_before_write(drift):
    from backend.services.chapter_draft_generation import (
        ChapterDraftGenerationConflict,
        ChapterDraftGenerationService,
        GenerateWorkingDraft,
    )

    repo = FakeChapterRepository()
    tracker = TransactionTracker()

    def mutate_after_freeze():
        if drift == "session-pin":
            repo.session = {
                **repo.session,
                "chapter_outline_hash": "f" * 64,
            }
        elif drift == "draft-revision":
            repo.working_draft = {
                **repo.working_draft,
                "revision": 2,
            }
        elif drift == "draft-hash":
            repo.working_draft = {
                **repo.working_draft,
                "content_hash": "f" * 64,
            }
        elif drift == "projection-revision":
            repo.projection_head = {
                **repo.projection_head,
                "canon_revision_number": 1,
                "projection_revision_number": 1,
            }
        elif drift == "projection-hash":
            repo.projection_head = {
                **repo.projection_head,
                "content_hash": "f" * 64,
            }
        elif drift == "binding-identity":
            repo.provider = {
                **repo.provider,
                "binding_revision_id": "binding-revision-2",
                "binding_revision": 2,
                "binding_hash": "7" * 64,
            }
        elif drift == "provider-identity":
            repo.provider = {
                **repo.provider,
                "id": "provider-writing-2",
            }
        else:
            repo.projection_head = {
                **repo.projection_head,
                "canon_revision_number": 1,
            }

    gateway = FakeGateway(
        tracker=tracker,
        on_generate=mutate_after_freeze,
    )
    service = ChapterDraftGenerationService(
        repo,
        provider_gateway=gateway,
        transaction_factory=tracker.factory,
    )

    with pytest.raises(
        ChapterDraftGenerationConflict,
        match="^chapter generation inputs changed$",
    ):
        await service.generate_working_draft(GenerateWorkingDraft(
            project_id="p1",
            chapter_session_id="session-1",
            expected_working_draft_revision=1,
        ))

    assert len(gateway.calls) == 1
    assert repo.upsert_calls == []
    assert tracker.active == 0
    assert tracker.entries == 2


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output",
    ("\ud800", "\udfff", {"content": "mapping"}, ["list"]),
    ids=("high-surrogate", "low-surrogate", "mapping", "list"),
)
async def test_generation_rejects_malformed_provider_text_without_raw_exception(output):
    from backend.services.chapter_draft_generation import (
        ChapterDraftGenerationFailed,
        ChapterDraftGenerationService,
        GenerateWorkingDraft,
    )

    repo = FakeChapterRepository()
    gateway = FakeGateway(output)
    service = ChapterDraftGenerationService(
        repo, provider_gateway=gateway, transaction_factory=tx_factory,
    )

    with pytest.raises(ChapterDraftGenerationFailed) as exc_info:
        await service.generate_working_draft(GenerateWorkingDraft(
            project_id="p1",
            chapter_session_id="session-1",
            expected_working_draft_revision=1,
        ))

    assert str(exc_info.value) == "chapter draft generation failed"
    assert exc_info.value.__cause__ is None
    assert len(gateway.calls) == 1
    assert repo.upsert_calls == []
    assert repo.working_draft["revision"] == 1


@pytest.mark.asyncio
async def test_generation_accepts_valid_astral_and_chinese_provider_text():
    from backend.services.chapter_draft_generation import (
        ChapterDraftGenerationService,
        GenerateWorkingDraft,
    )

    repo = FakeChapterRepository()
    output = "星河😀中文"
    gateway = FakeGateway(output)
    service = ChapterDraftGenerationService(
        repo, provider_gateway=gateway, transaction_factory=tx_factory,
    )

    result = await service.generate_working_draft(GenerateWorkingDraft(
        project_id="p1",
        chapter_session_id="session-1",
        expected_working_draft_revision=1,
    ))

    assert result.working_draft.content == output
    assert len(repo.upsert_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_key", "output", "rejected"),
    (
        ("short", "short", True),
        ("a", "ordinary a chapter prose", False),
        ("secret-key", "prefix secret-key suffix", True),
    ),
)
async def test_generation_scans_provider_secrets_without_short_substring_false_positives(
    api_key, output, rejected
):
    from backend.services.chapter_draft_generation import (
        ChapterDraftGenerationFailed,
        ChapterDraftGenerationService,
        GenerateWorkingDraft,
    )

    repo = FakeChapterRepository()
    repo.provider["api_key"] = api_key
    gateway = FakeGateway(output)
    service = ChapterDraftGenerationService(
        repo, provider_gateway=gateway, transaction_factory=tx_factory,
    )
    command = GenerateWorkingDraft(
        project_id="p1",
        chapter_session_id="session-1",
        expected_working_draft_revision=1,
    )

    if rejected:
        with pytest.raises(ChapterDraftGenerationFailed):
            await service.generate_working_draft(command)
        assert repo.upsert_calls == []
        assert repo.working_draft["revision"] == 1
    else:
        result = await service.generate_working_draft(command)
        assert result.working_draft.content == output
        assert len(repo.upsert_calls) == 1

    assert len(gateway.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    ("normalized-short", "encoded-long", "encoded-long-mixed"),
)
async def test_generation_rejects_secrets_after_content_normalization(mode):
    from backend.services.chapter_draft_generation import (
        ChapterDraftGenerationFailed,
        ChapterDraftGenerationService,
        GenerateWorkingDraft,
    )

    repo = FakeChapterRepository()
    if mode == "normalized-short":
        repo.provider["api_key"] = "short"
        output = "  short  "
    else:
        output = quote(repo.provider["base_url"], safe="")
        if mode == "encoded-long-mixed":
            output = output.replace("%3A", "%3a").replace("%2F", "%2f", 1)
    gateway = FakeGateway(output)
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


@pytest.mark.asyncio
async def test_archived_generation_stops_before_provider_and_draft_reads():
    from backend.services.chapter_draft_generation import (
        ChapterDraftGenerationService,
        GenerateWorkingDraft,
    )

    repo = FakeChapterRepository()
    repo.archived = True
    gateway = FakeGateway()
    service = ChapterDraftGenerationService(
        repo, provider_gateway=gateway, transaction_factory=tx_factory,
    )

    with pytest.raises(http_errors.ProjectArchived):
        await service.generate_working_draft(GenerateWorkingDraft(
            project_id="p1",
            chapter_session_id="session-1",
            expected_working_draft_revision=1,
        ))

    assert gateway.calls == []
    assert repo.upsert_calls == []
