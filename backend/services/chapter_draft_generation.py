from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from collections.abc import Mapping

from backend.gateways.chapter_draft_provider import (
    ChapterDraftProviderError,
    ChapterDraftProviderGateway,
)
from backend.http_errors import ProjectNotFound
from backend.prompts.chapter_draft import build_chapter_draft_messages
from backend.security.provider_secrets import (
    provider_response_text_contains_secret,
    provider_response_value_contains_secret,
)
from backend.services.chapter_sessions import (
    ChapterSessionConflict,
    ChapterSessionNotFound,
    ChapterSessionPreconditionFailed,
    ChapterSessionService,
)


class ChapterDraftGenerationError(RuntimeError):
    pass


class ChapterDraftGenerationFailed(ChapterDraftGenerationError):
    pass


class ChapterDraftGenerationConflict(ChapterDraftGenerationError):
    pass


class ChapterDraftGenerationPreconditionFailed(ChapterDraftGenerationError):
    pass


@dataclass(frozen=True)
class GenerateWorkingDraft:
    project_id: str
    chapter_session_id: str
    expected_working_draft_revision: int
    author_instruction: str = ""


class ChapterDraftGenerationService:
    def __init__(
        self,
        repository,
        *,
        provider_gateway=None,
        transaction_factory,
    ):
        self.repository = repository
        self.provider_gateway = provider_gateway or ChapterDraftProviderGateway()
        self.transaction_factory = transaction_factory

    async def generate_working_draft(self, command: GenerateWorkingDraft):
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(
                session, command.project_id
            ) is None:
                raise ProjectNotFound()
            chapter_session = await self.repository.read_session_by_id(
                session, command.project_id, command.chapter_session_id,
            )
            if chapter_session is None:
                raise ChapterSessionNotFound("Chapter session not found")
            if chapter_session["status"] != "drafting":
                raise ChapterDraftGenerationConflict("Chapter session is not drafting")
            draft = await self.repository.read_working_draft(
                session, command.chapter_session_id,
            )
            if draft is None:
                raise ChapterSessionPreconditionFailed("working draft is required")
            if int(draft["revision"]) != command.expected_working_draft_revision:
                raise ChapterDraftGenerationConflict("working draft revision drift")
            provider = await self.repository.resolve_writing_provider(
                session, command.project_id,
            )
            if provider is None:
                raise ChapterDraftGenerationPreconditionFailed("writing provider is required")
            messages = build_chapter_draft_messages(
                chapter_session=chapter_session,
                working_draft=draft,
                author_instruction=command.author_instruction,
            )
            try:
                generated = await self.provider_gateway.generate(
                    provider=provider,
                    messages=messages,
                    generation_config=self._generation_config(provider),
                )
            except ChapterDraftProviderError as exc:
                raise ChapterDraftGenerationFailed("chapter draft generation failed") from exc
            content = str(generated or "").strip()
            secrets = (provider.get("api_key"), provider.get("base_url"))
            if (
                provider_response_text_contains_secret(content, secrets)
                or provider_response_value_contains_secret(content, secrets)
            ):
                raise ChapterDraftGenerationFailed(
                    "chapter draft generation failed"
                )
            if not content:
                raise ChapterDraftGenerationFailed("chapter draft generation returned empty content")
            row = {
                "id": draft["id"],
                "project_id": command.project_id,
                "chapter_session_id": command.chapter_session_id,
                "revision": command.expected_working_draft_revision + 1,
                "content": content,
                "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "source_payload": {
                    "source": "ai-generation",
                    "providerId": provider["id"],
                    "modelName": provider["model_name"],
                    "authorInstruction": str(command.author_instruction or "").strip(),
                    "workingDraftRevision": int(draft["revision"]),
                },
                "updated_at": int(time.time() * 1000),
            }
            if not await self.repository.upsert_working_draft(session, row):
                raise ChapterSessionConflict("working draft was not saved")
            return await ChapterSessionService(
                self.repository,
                transaction_factory=self.transaction_factory,
            )._workspace(session, chapter_session)

    def _generation_config(self, provider: Mapping[str, object]) -> dict[str, object]:
        return {
            "temperature": float(provider.get("temperature") or 0.82),
            "maxOutputTokens": int(provider.get("max_output_tokens") or 4500),
        }
