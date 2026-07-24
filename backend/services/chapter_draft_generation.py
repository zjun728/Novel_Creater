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
    validate_provider_response_text,
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
    _INPUTS_CHANGED = "chapter generation inputs changed"

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
            projection_head = await self.repository.read_projection_head(
                session,
                command.project_id,
            )
            frozen_projection_identity = self._projection_identity(
                chapter_session,
                projection_head,
            )
            provider = await self.repository.resolve_writing_provider(
                session, command.project_id,
            )
            if provider is None:
                raise ChapterDraftGenerationPreconditionFailed("writing provider is required")
            frozen_session_identity = self._session_identity(chapter_session)
            frozen_draft_identity = self._draft_identity(draft)
            frozen_provider = dict(provider)
            frozen_provider_identity = self._provider_identity(provider)
            messages = build_chapter_draft_messages(
                chapter_session=chapter_session,
                working_draft=draft,
                author_instruction=command.author_instruction,
            )

        try:
            generated = await self.provider_gateway.generate(
                provider=frozen_provider,
                messages=messages,
                generation_config=self._generation_config(frozen_provider),
            )
        except ChapterDraftProviderError as exc:
            raise ChapterDraftGenerationFailed("chapter draft generation failed") from exc
        try:
            content = validate_provider_response_text(
                generated,
                strip=True,
            )
            secrets = (
                frozen_provider.get("api_key"),
                frozen_provider.get("base_url"),
            )
            if (
                provider_response_text_contains_secret(content, secrets)
                or provider_response_value_contains_secret(content, secrets)
            ):
                raise ValueError("provider response rejected")
        except (TypeError, ValueError, RecursionError):
            raise ChapterDraftGenerationFailed(
                "chapter draft generation failed"
            ) from None

        async with self.transaction_factory() as session:
            if await self.repository.lock_project(
                session, command.project_id
            ) is None:
                raise ProjectNotFound()
            current_session = await self.repository.read_session_by_id(
                session,
                command.project_id,
                command.chapter_session_id,
            )
            current_draft = await self.repository.read_working_draft(
                session,
                command.chapter_session_id,
            )
            current_projection_head = await self.repository.read_projection_head(
                session,
                command.project_id,
            )
            current_provider = await self.repository.resolve_writing_provider(
                session,
                command.project_id,
            )
            if (
                current_session is None
                or current_draft is None
                or current_provider is None
                or self._session_identity(current_session)
                != frozen_session_identity
                or self._draft_identity(current_draft)
                != frozen_draft_identity
                or self._projection_identity(
                    current_session,
                    current_projection_head,
                ) != frozen_projection_identity
                or self._provider_identity(current_provider)
                != frozen_provider_identity
            ):
                raise ChapterDraftGenerationConflict(
                    self._INPUTS_CHANGED,
                )
            row = {
                "id": current_draft["id"],
                "project_id": command.project_id,
                "chapter_session_id": command.chapter_session_id,
                "revision": command.expected_working_draft_revision + 1,
                "content": content,
                "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "source_payload": {
                    "source": "ai-generation",
                    "providerId": frozen_provider["id"],
                    "modelName": frozen_provider["model_name"],
                    "authorInstruction": str(command.author_instruction or "").strip(),
                    "workingDraftRevision": int(current_draft["revision"]),
                },
                "updated_at": int(time.time() * 1000),
            }
            if not await self.repository.upsert_working_draft(
                session,
                row,
                expected_revision=int(current_draft["revision"]),
                expected_content_hash=current_draft["content_hash"],
            ):
                raise ChapterSessionConflict("working draft was not saved")
            return await ChapterSessionService(
                self.repository,
                transaction_factory=self.transaction_factory,
            )._workspace(session, current_session)

    def _session_identity(self, chapter_session: Mapping[str, object]) -> tuple[object, ...]:
        return tuple(chapter_session.get(key) for key in (
            "id",
            "project_id",
            "planning_revision_id",
            "planning_revision",
            "planning_hash",
            "story_block_id",
            "story_block_revision",
            "story_block_hash",
            "chapter_outline_revision_id",
            "chapter_outline_revision",
            "chapter_outline_hash",
            "chapter_num",
            "expected_canon_revision",
            "outline_canon_revision",
            "outline_projection_revision",
            "outline_projection_hash",
            "status",
        ))

    def _draft_identity(self, draft: Mapping[str, object]) -> tuple[object, ...]:
        return tuple(draft.get(key) for key in (
            "id",
            "project_id",
            "chapter_session_id",
            "revision",
            "content",
            "content_hash",
        ))

    def _projection_identity(
        self,
        chapter_session: Mapping[str, object],
        projection_head: Mapping[str, object] | None,
    ) -> tuple[int, int, object]:
        try:
            canon_revision = int(projection_head["canon_revision_number"])
            projection_revision = int(
                projection_head["projection_revision_number"],
            )
            projection_hash = projection_head["content_hash"]
            outline_canon_revision = int(
                chapter_session["outline_canon_revision"],
            )
            outline_projection_revision = int(
                chapter_session["outline_projection_revision"],
            )
            outline_projection_hash = chapter_session[
                "outline_projection_hash"
            ]
            expected_canon_revision = int(
                chapter_session["expected_canon_revision"],
            )
        except (KeyError, TypeError, ValueError):
            raise ChapterDraftGenerationConflict(self._INPUTS_CHANGED) from None
        if (
            canon_revision != projection_revision
            or canon_revision != expected_canon_revision
            or canon_revision != outline_canon_revision
            or projection_revision != outline_projection_revision
            or projection_hash != outline_projection_hash
        ):
            raise ChapterDraftGenerationConflict(self._INPUTS_CHANGED)
        return canon_revision, projection_revision, projection_hash

    def _provider_identity(
        self,
        provider: Mapping[str, object],
    ) -> tuple[object, ...]:
        return tuple(provider.get(key) for key in (
            "binding_revision_id",
            "binding_revision",
            "binding_hash",
            "binding_item_hash",
            "id",
            "provider_type",
            "model_name",
            "base_url",
            "api_key",
            "temperature",
            "max_output_tokens",
        ))

    def _generation_config(self, provider: Mapping[str, object]) -> dict[str, object]:
        return {
            "temperature": float(provider.get("temperature") or 0.82),
            "maxOutputTokens": int(provider.get("max_output_tokens") or 4500),
        }
