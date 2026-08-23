"""Single-transaction idempotent confirmation of complete creation contracts."""

from __future__ import annotations

import re

from backend.domain.json_contracts import canonical_hash, canonical_json
from .drafts import (
    ConfirmContracts,
    ConfirmedContractResult,
    ContractConflict,
    ContractDraftIncomplete,
    ContractNotFound,
    ContractPreconditionFailed,
    _reject_path_shaped_text,
)
from .history import ContractHistoryService


class ContractService(ContractHistoryService):
    async def confirm(self, command: ConfirmContracts) -> ConfirmedContractResult:
        if (
            not isinstance(command.idempotency_key, str)
            or not 1 <= len(command.idempotency_key) <= 64
            or _reject_path_shaped_text(command.idempotency_key)
                != command.idempotency_key
            or command.expected_draft_version <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", command.expected_draft_hash)
        ):
            raise ContractPreconditionFailed()
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, command.project_id) is None:
                raise ContractNotFound()
            draft_row = await self.repository.lock_draft(session, command.project_id)
            draft_matches = draft_row is not None and (
                int(draft_row.get("draft_version") or 0)
                == command.expected_draft_version
                and draft_row.get("content_hash") == command.expected_draft_hash
            )
            if not draft_matches:
                head = await self.repository.lock_contract_head(
                    session, command.project_id
                )
                if head is None:
                    raise ContractPreconditionFailed()
                existing = await self.repository.read_confirmation_request(
                    session, command.project_id, command.idempotency_key
                )
                if existing is None or existing.get("status") != "succeeded":
                    raise ContractConflict()
                snapshot = await self.repository.read_confirmed_snapshot(
                    session, command.project_id, int(existing["result_revision"])
                )
                replay = self._result_from_snapshot(snapshot)
                replay_hash = self._request_hash(
                    command, draft_id=existing["id"],
                    base_head_revision=replay.revision - 1, result=replay,
                )
                if existing.get("request_hash") != replay_hash:
                    raise ContractConflict()
                selected = await self.repository.lock_selected_seed(
                    session, command.project_id
                )
                return self._with_current_head_readiness(
                    replay, selected, head
                )
            saved = self._draft_result(draft_row)
            if not saved.draft.is_complete:
                raise ContractDraftIncomplete()
            selected = frozen_seed = engine = binding = primary = secondary = None
            cards = sources = fragments = ()
            draft = saved.draft
            selected = await self.repository.lock_selected_seed(
                session, command.project_id
            )
            frozen_seed = await self.repository.read_seed_revision(
                session, command.project_id, draft.seedRevisionId, lock=True
            )
            engine = await self.repository.read_engine_option(
                session, command.project_id, draft.engineOptionId, lock=True
            )
            binding = await self.repository.lock_binding_snapshot(
                session, command.project_id
            )
            primary, secondary, cards, sources, fragments = (
                await self._lock_contract_assets(session, draft)
            )
            head = await self.repository.lock_contract_head(
                session, command.project_id
            )
            if head is None:
                raise ContractPreconditionFailed()
            existing = await self.repository.read_confirmation_request(
                session, command.project_id, command.idempotency_key
            )
            if existing is not None:
                if existing.get("status") != "succeeded":
                    raise ContractConflict()
                snapshot = await self.repository.read_confirmed_snapshot(
                    session, command.project_id, int(existing["result_revision"])
                )
                replay = self._result_from_snapshot(snapshot)
                replay_hash = self._request_hash(
                    command, draft_id=existing["id"],
                    base_head_revision=replay.revision - 1, result=replay,
                )
                if existing.get("request_hash") != replay_hash:
                    raise ContractConflict()
                return self._with_current_head_readiness(
                    replay, selected, head
                )
            if int(head["revision"]) != saved.base_head_revision:
                raise ContractConflict()
            preview = self._assemble_confirmation(
                saved, selected, frozen_seed, engine, binding,
                primary, secondary, cards, sources, fragments,
            )
            request_hash = self._request_hash(
                command, draft_id=saved.id,
                base_head_revision=saved.base_head_revision, result=preview,
            )
            now = self.clock()
            request_id = saved.id
            creation_id, style_id = self.id_factory(), self.id_factory()
            if not await self.repository.insert_confirmation_request(session, {
                "id": request_id, "project_id": command.project_id,
                "selection_revision": saved.selection_revision,
                "idempotency_key": command.idempotency_key,
                "request_hash": request_hash, "created_at": now,
            }):
                raise ContractConflict()
            self.failpoint("after_confirmation_reserve")
            reference_manifest = self._reference_manifest(preview)
            if not await self.repository.insert_creation_contract(session, {
                "id": creation_id, "project_id": command.project_id,
                "revision": preview.expected_revision,
                "selection_revision": saved.selection_revision,
                "seed_id": preview.seed_ref.id,
                "seed_revision_id": preview.seed_ref.revision_id,
                "seed_hash": preview.seed_ref.content_hash,
                "binding_revision_id": (
                    preview.binding_ref.id if preview.binding_ref else None
                ),
                "binding_hash": (
                    preview.binding_ref.content_hash
                    if preview.binding_ref else None
                ),
                "channel_profile_key": saved.draft.channelProfileKey,
                "genre_profile_key": saved.draft.genreProfileKey,
                "quality_charter_version": saved.draft.qualityCharterVersion,
                "total_word_min": saved.draft.targetTotalWords,
                "total_word_max": saved.draft.targetTotalWords,
                "chapter_capacity_policy": canonical_json({
                    "expectedVolumeCount": saved.draft.expectedVolumeCount,
                    "expectedChapterCount": saved.draft.expectedChapterCount,
                    "chapterWordRangePreference": list(
                        saved.draft.chapterWordRangePreference
                    ),
                }),
                "reference_manifest_json": canonical_json(reference_manifest),
                "reference_manifest_hash": canonical_hash(reference_manifest),
                "content_json": canonical_json(preview.creation_contract),
                "content_hash": preview.creation_hash, "confirmed_at": now,
            }):
                raise ContractConflict()
            self.failpoint("after_creation_insert")
            if not await self.repository.insert_style_contract(session, {
                "id": style_id, "project_id": command.project_id,
                "creation_contract_id": creation_id,
                "revision": preview.expected_revision,
                "merged_style_json": canonical_json(preview.style_contract),
                "likes_json": canonical_json(preview.likes),
                "dislikes_json": canonical_json(preview.dislikes),
                "content_hash": preview.style_hash, "confirmed_at": now,
            }):
                raise ContractConflict()
            self.failpoint("after_style_insert")
            if not await self.repository.insert_engine_ref(session, {
                "creation_contract_id": creation_id,
                "project_id": command.project_id,
                "engine_option_id": preview.engine_ref.id,
                "engine_hash": preview.engine_ref.content_hash,
            }):
                raise ContractConflict()
            self.failpoint("after_engine_refs")
            style_rows = tuple({
                "style_contract_id": style_id, "role": ref.role,
                "style_template_id": ref.id, "asset_revision": ref.revision,
                "asset_hash": ref.contentHash, "sort_order": index,
            } for index, ref in enumerate(preview.style_refs, 1))
            if not await self.repository.insert_style_refs(session, style_rows):
                raise ContractConflict()
            self.failpoint("after_style_refs")
            card_rows = tuple({
                "creation_contract_id": creation_id,
                "experience_card_id": ref.id, "asset_revision": ref.revision,
                "asset_hash": ref.contentHash, "sort_order": index,
            } for index, ref in enumerate(preview.experience_card_refs, 1))
            if not await self.repository.insert_experience_refs(session, card_rows):
                raise ContractConflict()
            self.failpoint("after_card_refs")
            corpus_rows = tuple({
                "creation_contract_id": creation_id,
                "corpus_source_id": ref.id, "source_revision": ref.revision,
                "source_hash": ref.contentHash,
                "selection_mode": ref.selectionMode, "sort_order": index,
            } for index, ref in enumerate(preview.corpus_source_refs, 1))
            if not await self.repository.insert_corpus_refs(session, corpus_rows):
                raise ContractConflict()
            self.failpoint("after_corpus_refs")
            fragment_rows = tuple({
                "creation_contract_id": creation_id,
                "corpus_source_id": source.id,
                "source_revision": source.revision,
                "source_hash": source.contentHash,
                "corpus_chapter_id": fragment.chapterId,
                "corpus_fragment_id": fragment.fragmentId,
                "fragment_hash": fragment.fragmentHash,
                "chapter_char_start": fragment.chapterCharStart,
                "chapter_char_end": fragment.chapterCharEnd,
                "reference_use": fragment.referenceUse,
                "sort_order": index,
            } for index, (source, fragment) in enumerate(
                (
                    (source, fragment)
                    for source in preview.corpus_source_refs
                    for fragment in source.fragments
                ),
                1,
            ))
            if not await self.repository.insert_corpus_fragment_refs(
                session, fragment_rows
            ):
                raise ContractConflict()
            self.failpoint("after_corpus_fragment_refs")
            if not await self.repository.cas_contract_head(session, {
                "project_id": command.project_id,
                "base_revision": saved.base_head_revision,
                "revision": preview.expected_revision,
                "creation_contract_id": creation_id,
                "style_contract_id": style_id,
                "creation_hash": preview.creation_hash,
                "style_hash": preview.style_hash, "updated_at": now,
            }):
                raise ContractConflict()
            self.failpoint("after_head_cas")
            if not await self.repository.sync_project_contract_targets(
                session,
                project_id=command.project_id,
                target_words=saved.draft.targetTotalWords,
                target_chapters=saved.draft.expectedChapterCount,
                updated_at=now,
            ):
                raise ContractConflict()
            if not await self.repository.delete_draft_cas(
                session, command.project_id, saved.draft_version,
                saved.content_hash,
            ):
                raise ContractConflict()
            self.failpoint("after_draft_delete")
            self.failpoint("before_request_success")
            if not await self.repository.succeed_confirmation_request(session, {
                "project_id": command.project_id,
                "idempotency_key": command.idempotency_key,
                "request_hash": request_hash,
                "creation_contract_id": creation_id,
                "style_contract_id": style_id,
                "result_revision": preview.expected_revision,
                "completed_at": now,
            }):
                raise ContractConflict()
            return self._confirmed_result(preview, creation_id, style_id)
__all__ = ("ContractService",)
