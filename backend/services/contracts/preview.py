"""Read-only complete-contract preview and dependency drift aggregation."""

from __future__ import annotations

import json

from pydantic import ValidationError

from backend.domain.contracts import CreationContractPayload
from backend.domain.json_contracts import canonical_hash
from backend.domain.model_bindings import TASK_KEYS
from backend.domain.seeds import decode_seed_revision, seed_payload_hash
from .drafts import (
    BindingContractRef,
    ContractConflict,
    ContractDraftIncomplete,
    ContractDraftService,
    ContractNotFound,
    ContractPreconditionFailed,
    ContractPreviewResult,
    ConfirmedContractResult,
    EngineContractRef,
    ResolvedAssetRef,
    ResolvedCorpusFragment,
    ResolvedCorpusRef,
    ResolvedStyleRef,
    SeedContractRef,
    _json_object,
    _strict_engine,
    _strict_style_from_primary,
    style_contract_hash,
)


class ContractPreviewService(ContractDraftService):
    @staticmethod
    def _asset_reasons(ref, row, *, kind, role=None):
        suffix = f":{role}" if role else f":{ref.id}"
        reasons = []
        hash_field = "source_hash" if kind == "corpus" else "content_hash"
        if row is None:
            return [f"{kind}_missing{suffix}"]
        if (
            int(row["revision"]) != ref.revision
            or row[hash_field] != ref.contentHash
            or (
                kind == "corpus"
                and row.get("revision_id") != ref.revisionId
            )
        ):
            reasons.append(f"{kind}_invalid{suffix}")
        if kind != "corpus":
            try:
                if canonical_hash(_json_object(row["payload_json"])) != row["content_hash"]:
                    reasons.append(f"{kind}_invalid{suffix}")
            except (TypeError, ValueError, json.JSONDecodeError):
                reasons.append(f"{kind}_invalid{suffix}")
        if row.get("status") not in ({"analyzed"} if kind == "corpus" else {"active"}):
            reasons.append(f"{kind}_inactive{suffix}")
        current = (
            row.get("head_id")
            != row.get("revision_id" if kind == "corpus" else "id")
            or int(row.get("head_revision") or 0) != ref.revision
            or row.get("head_hash") != ref.contentHash
        )
        if current and not (
            kind == "corpus" and ref.pinnedHistoricalRevision
        ):
            reasons.append(f"{kind}_drift{suffix}")
        if (
            kind == "corpus"
            and row.get("archived_at") is not None
            and not ref.pinnedHistoricalRevision
        ):
            reasons.append(f"{kind}_inactive{suffix}")
        return list(dict.fromkeys(reasons))

    @staticmethod
    def _fragment_reasons(source_ref, rows):
        by_id = {row.get("fragment_id"): row for row in tuple(rows or ())}
        expected_ids = {
            fragment.fragmentId for fragment in source_ref.fragments
        }
        reasons = []
        for fragment in source_ref.fragments:
            row = by_id.get(fragment.fragmentId)
            suffix = f":{fragment.fragmentId}"
            if row is None:
                reasons.append(f"corpus_fragment_missing{suffix}")
                continue
            if (
                row.get("source_id") != source_ref.id
                or row.get("source_revision_id") != source_ref.revisionId
                or int(row.get("source_revision") or 0) != source_ref.revision
                or row.get("source_hash") != source_ref.contentHash
                or row.get("chapter_id") != fragment.chapterId
                or row.get("fragment_hash") != fragment.fragmentHash
                or fragment.chapterCharStart
                    < int(row.get("fragment_char_start") or 0)
                or fragment.chapterCharEnd
                    > int(row.get("fragment_char_end") or 0)
            ):
                reasons.append(f"corpus_fragment_invalid{suffix}")
        if set(by_id) != expected_ids:
            reasons.append(f"corpus_fragment_set_drift:{source_ref.id}")
        return list(dict.fromkeys(reasons))

    async def preview(self, project_id: str) -> ContractPreviewResult:
        async with self.connection_factory() as session:
            if await self.repository.read_active_project(session, project_id) is None:
                raise ContractNotFound()
            row = await self.repository.read_draft(session, project_id)
            if row is None:
                raise ContractPreconditionFailed()
            saved = self._draft_result(row)
            draft = saved.draft
            if not draft.is_complete:
                raise ContractDraftIncomplete()
            selected = await self.repository.read_selected_seed(session, project_id)
            frozen_seed = await self.repository.read_seed_revision(
                session, project_id, draft.seedRevisionId
            )
            engine = await self.repository.read_engine_option(
                session, project_id, draft.engineOptionId
            )
            binding = await self.repository.read_binding_snapshot(
                session, project_id,
                draft.modelBindingRef.id if draft.modelBindingRef else None,
            )
            current_binding_when_unbound = (
                binding if draft.modelBindingRef is None else None
            )
            if draft.modelBindingRef is None:
                binding = None
            primary = await self.repository.read_style_revision(
                session, draft.primaryStyleRef.id
            )
            secondary = (
                await self.repository.read_style_revision(
                    session, draft.secondaryStyleRef.id
                )
                if draft.secondaryStyleRef else None
            )
            cards = [
                await self.repository.read_experience_revision(session, ref.id)
                for ref in draft.experienceCardRefs
            ]
            sources = [
                await self.repository.read_corpus_revision(
                    session, ref.id, ref.revisionId
                )
                for ref in draft.corpusSourceRefs
            ]
            fragments = [
                await self.repository.read_corpus_fragments(
                    session,
                    ref.id,
                    ref.revisionId,
                    tuple(fragment.fragmentId for fragment in ref.fragments),
                )
                for ref in draft.corpusSourceRefs
            ]
            head = await self.repository.read_contract_head(session, project_id)
            head_snapshot = (
                await self.repository.read_confirmed_snapshot(
                    session, project_id, int(head["revision"])
                )
                if head is not None and int(head.get("revision") or 0) > 0
                else None
            )

        reasons = []
        seed_payload = None
        if frozen_seed is None:
            reasons.append("seed_missing")
        else:
            try:
                seed_payload, _ = decode_seed_revision(frozen_seed["payload_json"])
            except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
                reasons.append("seed_invalid")
            if (
                seed_payload is not None
                and (
                frozen_seed.get("seed_hash") != draft.seedHash
                or seed_payload_hash(seed_payload) != draft.seedHash
                )
            ):
                reasons.append("seed_invalid")
        if selected is None:
            reasons.append("seed_not_selected")
        else:
            if (
                int(selected.get("selection_revision") or 0)
                != saved.selection_revision
            ):
                reasons.append("selection_drift")
            if (
                selected.get("seed_revision_id") != draft.seedRevisionId
                or selected.get("seed_hash") != draft.seedHash
            ):
                reasons.append("seed_drift")

        engine_payload = None
        if engine is None:
            reasons.append("engine_missing")
        else:
            try:
                engine_payload = _strict_engine(engine["payload_json"])
            except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
                reasons.append("engine_invalid")
            if (
                engine_payload is not None
                and (
                    engine.get("content_hash") != draft.engineHash
                    or canonical_hash(engine_payload) != draft.engineHash
                )
            ):
                reasons.append("engine_invalid")
            if engine.get("status") != "succeeded":
                reasons.append("engine_not_succeeded")
            if (
                int(engine.get("selection_revision") or 0)
                != saved.selection_revision
                or engine.get("seed_revision_id") != draft.seedRevisionId
                or engine.get("seed_hash") != draft.seedHash
            ):
                reasons.append("engine_seed_drift")

        binding_items = ()
        binding_usable = True
        if (
            draft.modelBindingRef is None
            and current_binding_when_unbound is not None
        ):
            reasons.append("binding_drift")
        if draft.modelBindingRef is not None:
            binding_usable = binding is not None
            if binding is None:
                reasons.append("binding_missing")
            else:
                try:
                    binding_items = self._binding_items(binding)
                except ContractPreconditionFailed:
                    reasons.append("binding_invalid")
                    binding_usable = False
                if (
                    not self._binding_integrity(binding_items, binding)
                    or tuple(item.task_key for item in binding_items) != TASK_KEYS
                ):
                    reasons.append("binding_invalid")
                if (
                    binding.get("binding_revision_id") != draft.modelBindingRef.id
                    or int(binding.get("revision") or 0)
                        != draft.modelBindingRef.revision
                    or binding.get("content_hash")
                        != draft.modelBindingRef.contentHash
                    or binding.get("head_revision")
                        != draft.modelBindingRef.revision
                    or binding.get("head_binding_revision_id")
                        != draft.modelBindingRef.id
                    or binding.get("head_hash")
                        != draft.modelBindingRef.contentHash
                ):
                    reasons.append("binding_drift")
        if (
            head is None and saved.base_head_revision != 0
        ) or (
            head is not None
            and int(head.get("revision") or 0) != saved.base_head_revision
        ):
            reasons.append("draft_base_drift")
        if head is not None and int(head.get("revision") or 0) > 0 and (
            head_snapshot is None
            or head_snapshot.get("creation_contract_id")
                != head.get("creation_contract_id")
            or head_snapshot.get("style_contract_id")
                != head.get("style_contract_id")
            or head_snapshot.get("creation_hash") != head.get("creation_hash")
            or head_snapshot.get("style_hash") != head.get("style_hash")
        ):
            reasons.append("contract_head_drift")

        style_payload = None
        if primary is not None and (
            draft.secondaryStyleRef is None or secondary is not None
        ):
            try:
                style_payload = _strict_style_from_primary(primary, secondary)
            except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
                reasons.append("style_invalid:primary")
        reasons.extend(self._asset_reasons(
            draft.primaryStyleRef, primary, kind="style", role="primary"
        ))
        if draft.secondaryStyleRef:
            reasons.extend(self._asset_reasons(
                draft.secondaryStyleRef, secondary, kind="style", role="secondary"
            ))
        for ref, asset in zip(draft.experienceCardRefs, cards):
            reasons.extend(self._asset_reasons(ref, asset, kind="experience"))
        for ref, source, source_fragments in zip(
            draft.corpusSourceRefs, sources, fragments
        ):
            reasons.extend(self._asset_reasons(ref, source, kind="corpus"))
            reasons.extend(self._fragment_reasons(ref, source_fragments))
        reasons = list(dict.fromkeys(reasons))

        creation = None
        if seed_payload is not None and engine_payload is not None and binding_usable:
            try:
                creation = CreationContractPayload(
                    schemaVersion="creation-contract-v1",
                    channelProfileKey=draft.channelProfileKey,
                    genreProfileKey=draft.genreProfileKey,
                    qualityCharterVersion=draft.qualityCharterVersion,
                    selectionRevision=saved.selection_revision,
                    selectedSeed=seed_payload,
                    seedRevisionId=draft.seedRevisionId,
                    seedHash=draft.seedHash,
                    selectedEngine=engine_payload,
                    engineOptionId=draft.engineOptionId,
                    engineHash=draft.engineHash,
                    primaryStyleRef=draft.primaryStyleRef.model_dump(mode="python"),
                    secondaryStyleRef=(
                        draft.secondaryStyleRef.model_dump(mode="python")
                        if draft.secondaryStyleRef else None
                    ),
                    experienceCardRefs=tuple(
                        ref.model_dump(mode="python")
                        for ref in draft.experienceCardRefs
                    ),
                    corpusSourceRefs=tuple(
                        ref.model_dump(mode="python")
                        for ref in draft.corpusSourceRefs
                    ),
                    targetTotalWords=draft.targetTotalWords,
                    expectedVolumeCount=draft.expectedVolumeCount,
                    expectedChapterCount=draft.expectedChapterCount,
                    chapterWordRangePreference=draft.chapterWordRangePreference,
                    prohibitedDirections=draft.prohibitedDirections,
                    authorNotes=draft.authorNotes,
                    modelBindingRef=(
                        draft.modelBindingRef.model_dump(mode="python")
                        if draft.modelBindingRef else None
                    ),
                )
            except ValidationError:
                reasons.append("creation_invalid")
        style_hash = (
            style_contract_hash(style_payload, draft.likes, draft.dislikes)
            if style_payload is not None else None
        )
        reasons = list(dict.fromkeys(reasons))
        return ContractPreviewResult(
            project_id=project_id,
            selection_revision=saved.selection_revision,
            draft_version=saved.draft_version,
            base_head_revision=saved.base_head_revision,
            expected_revision=saved.base_head_revision + 1,
            contract_ready=not reasons, reasons=tuple(reasons),
            seed_ref=SeedContractRef(
                id=(frozen_seed or selected or {}).get("seed_id"),
                revision_id=draft.seedRevisionId,
                content_hash=draft.seedHash,
            ),
            engine_ref=EngineContractRef(
                id=draft.engineOptionId,
                batch_id=engine.get("batch_id") if engine else None,
                content_hash=draft.engineHash,
            ),
            binding_ref=(BindingContractRef(
                id=draft.modelBindingRef.id,
                revision=draft.modelBindingRef.revision,
                content_hash=draft.modelBindingRef.contentHash,
                items=binding_items,
            ) if draft.modelBindingRef else None),
            style_refs=tuple(
                [ResolvedStyleRef(
                    "primary", draft.primaryStyleRef.id,
                    draft.primaryStyleRef.revision, draft.primaryStyleRef.contentHash,
                )] + ([ResolvedStyleRef(
                    "secondary", draft.secondaryStyleRef.id,
                    draft.secondaryStyleRef.revision,
                    draft.secondaryStyleRef.contentHash,
                )] if draft.secondaryStyleRef else [])
            ),
            experience_card_refs=tuple(
                ResolvedAssetRef(ref.id, ref.revision, ref.contentHash)
                for ref in draft.experienceCardRefs
            ),
            corpus_source_refs=tuple(
                ResolvedCorpusRef(
                    id=ref.id,
                    revision=ref.revision,
                    contentHash=ref.contentHash,
                    revisionId=ref.revisionId,
                    selectionMode=ref.selectionMode,
                    fragments=tuple(ResolvedCorpusFragment(
                        chapterId=fragment.chapterId,
                        fragmentId=fragment.fragmentId,
                        fragmentHash=fragment.fragmentHash,
                        chapterCharStart=fragment.chapterCharStart,
                        chapterCharEnd=fragment.chapterCharEnd,
                        referenceUse=fragment.referenceUse,
                    ) for fragment in ref.fragments),
                    pinnedHistoricalRevision=ref.pinnedHistoricalRevision,
                ) for ref in draft.corpusSourceRefs
            ),
            creation_contract=creation, style_contract=style_payload,
            likes=draft.likes, dislikes=draft.dislikes,
            creation_hash=canonical_hash(creation) if creation is not None else None,
            style_hash=style_hash,
        )

    @staticmethod
    def _request_hash(
        command: ConfirmContracts, *, draft_id: str,
        base_head_revision: int, result,
    ) -> str:
        return canonical_hash({
            "projectId": command.project_id,
            "draftId": draft_id,
            "draftVersion": command.expected_draft_version,
            "draftHash": command.expected_draft_hash,
            "baseHeadRevision": base_head_revision,
            "expectedRevision": base_head_revision + 1,
            "selectionRevision": result.selection_revision,
            "seedRef": {
                "revisionId": result.seed_ref.revision_id,
                "contentHash": result.seed_ref.content_hash,
            },
            "engineRef": {
                "id": result.engine_ref.id,
                "contentHash": result.engine_ref.content_hash,
            },
            "bindingRef": ({
                "id": result.binding_ref.id,
                "revision": result.binding_ref.revision,
                "contentHash": result.binding_ref.content_hash,
            } if result.binding_ref else None),
            "styleRefs": [
                ref.model_dump(mode="json") for ref in result.style_refs
            ],
            "experienceCardRefs": [
                ref.model_dump(mode="json")
                for ref in result.experience_card_refs
            ],
            "corpusSourceRefs": [
                ref.model_dump(mode="json") for ref in result.corpus_source_refs
            ],
        })

    def _assemble_confirmation(
        self, saved, selected, frozen_seed, engine, binding,
        primary, secondary, cards, sources, fragments,
    ) -> ContractPreviewResult:
        draft = saved.draft
        try:
            seed_payload, _ = decode_seed_revision(frozen_seed["payload_json"])
            engine_payload = _strict_engine(engine["payload_json"])
            binding_items = (
                self._binding_items(binding) if binding is not None else ()
            )
            style_payload = _strict_style_from_primary(primary, secondary)
        except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
            raise ContractPreconditionFailed() from None
        invalid = (
            selected is None
            or frozen_seed is None
            or engine is None
            or selected.get("seed_revision_id") != draft.seedRevisionId
            or int(selected.get("selection_revision") or 0)
                != saved.selection_revision
            or selected.get("seed_hash") != draft.seedHash
            or frozen_seed.get("seed_revision_id") != draft.seedRevisionId
            or frozen_seed.get("seed_hash") != draft.seedHash
            or seed_payload_hash(seed_payload) != draft.seedHash
            or engine.get("status") != "succeeded"
            or int(engine.get("selection_revision") or 0)
                != saved.selection_revision
            or engine.get("seed_revision_id") != draft.seedRevisionId
            or engine.get("seed_hash") != draft.seedHash
            or engine.get("content_hash") != draft.engineHash
            or canonical_hash(engine_payload) != draft.engineHash
            or (
                draft.modelBindingRef is None and binding is not None
            )
            or (
                draft.modelBindingRef is not None
                and (
                    binding is None
                    or binding.get("binding_revision_id")
                        != draft.modelBindingRef.id
                    or int(binding.get("revision") or 0)
                        != draft.modelBindingRef.revision
                    or binding.get("content_hash")
                        != draft.modelBindingRef.contentHash
                    or binding.get("head_revision")
                        != draft.modelBindingRef.revision
                    or binding.get("head_binding_revision_id")
                        != draft.modelBindingRef.id
                    or binding.get("head_hash")
                        != draft.modelBindingRef.contentHash
                    or tuple(item.task_key for item in binding_items) != TASK_KEYS
                    or not self._binding_integrity(binding_items, binding)
                )
            )
        )
        if invalid:
            raise ContractConflict()
        asset_reasons = self._asset_reasons(
            draft.primaryStyleRef, primary, kind="style", role="primary"
        )
        if draft.secondaryStyleRef:
            asset_reasons += self._asset_reasons(
                draft.secondaryStyleRef, secondary, kind="style", role="secondary"
            )
        for ref, asset in zip(draft.experienceCardRefs, cards):
            asset_reasons += self._asset_reasons(ref, asset, kind="experience")
        for ref, source, source_fragments in zip(
            draft.corpusSourceRefs, sources, fragments
        ):
            asset_reasons += self._asset_reasons(ref, source, kind="corpus")
            asset_reasons += self._fragment_reasons(ref, source_fragments)
        if asset_reasons:
            raise ContractConflict()
        try:
            creation = CreationContractPayload(
                schemaVersion="creation-contract-v1",
                channelProfileKey=draft.channelProfileKey,
                genreProfileKey=draft.genreProfileKey,
                qualityCharterVersion=draft.qualityCharterVersion,
                selectionRevision=saved.selection_revision,
                selectedSeed=seed_payload,
                seedRevisionId=draft.seedRevisionId,
                seedHash=draft.seedHash,
                selectedEngine=engine_payload,
                engineOptionId=draft.engineOptionId,
                engineHash=draft.engineHash,
                primaryStyleRef=draft.primaryStyleRef.model_dump(mode="python"),
                secondaryStyleRef=(
                    draft.secondaryStyleRef.model_dump(mode="python")
                    if draft.secondaryStyleRef else None
                ),
                experienceCardRefs=tuple(
                    ref.model_dump(mode="python")
                    for ref in draft.experienceCardRefs
                ),
                corpusSourceRefs=tuple(
                    ref.model_dump(mode="python")
                    for ref in draft.corpusSourceRefs
                ),
                targetTotalWords=draft.targetTotalWords,
                expectedVolumeCount=draft.expectedVolumeCount,
                expectedChapterCount=draft.expectedChapterCount,
                chapterWordRangePreference=draft.chapterWordRangePreference,
                prohibitedDirections=draft.prohibitedDirections,
                authorNotes=draft.authorNotes,
                modelBindingRef=(
                    draft.modelBindingRef.model_dump(mode="python")
                    if draft.modelBindingRef else None
                ),
            )
        except ValidationError:
            raise ContractPreconditionFailed() from None
        creation_hash = canonical_hash(creation)
        style_hash = style_contract_hash(style_payload, draft.likes, draft.dislikes)
        return ContractPreviewResult(
            project_id=saved.project_id,
            selection_revision=saved.selection_revision,
            draft_version=saved.draft_version,
            base_head_revision=saved.base_head_revision,
            expected_revision=saved.base_head_revision + 1,
            contract_ready=True,
            reasons=(),
            seed_ref=SeedContractRef(
                id=frozen_seed.get("seed_id"),
                revision_id=draft.seedRevisionId,
                content_hash=draft.seedHash,
            ),
            engine_ref=EngineContractRef(
                id=draft.engineOptionId,
                batch_id=engine.get("batch_id"),
                content_hash=draft.engineHash,
            ),
            binding_ref=(BindingContractRef(
                id=draft.modelBindingRef.id,
                revision=draft.modelBindingRef.revision,
                content_hash=draft.modelBindingRef.contentHash,
                items=binding_items,
            ) if draft.modelBindingRef else None),
            style_refs=tuple(
                [ResolvedStyleRef(
                    "primary", draft.primaryStyleRef.id,
                    draft.primaryStyleRef.revision, draft.primaryStyleRef.contentHash,
                )] + ([ResolvedStyleRef(
                    "secondary", draft.secondaryStyleRef.id,
                    draft.secondaryStyleRef.revision,
                    draft.secondaryStyleRef.contentHash,
                )] if draft.secondaryStyleRef else [])
            ),
            experience_card_refs=tuple(
                ResolvedAssetRef(ref.id, ref.revision, ref.contentHash)
                for ref in draft.experienceCardRefs
            ),
            corpus_source_refs=tuple(
                ResolvedCorpusRef(
                    id=ref.id,
                    revision=ref.revision,
                    contentHash=ref.contentHash,
                    revisionId=ref.revisionId,
                    selectionMode=ref.selectionMode,
                    fragments=tuple(ResolvedCorpusFragment(
                        chapterId=fragment.chapterId,
                        fragmentId=fragment.fragmentId,
                        fragmentHash=fragment.fragmentHash,
                        chapterCharStart=fragment.chapterCharStart,
                        chapterCharEnd=fragment.chapterCharEnd,
                        referenceUse=fragment.referenceUse,
                    ) for fragment in ref.fragments),
                    pinnedHistoricalRevision=ref.pinnedHistoricalRevision,
                )
                for ref in draft.corpusSourceRefs
            ),
            creation_contract=creation,
            style_contract=style_payload,
            likes=draft.likes,
            dislikes=draft.dislikes,
            creation_hash=creation_hash,
            style_hash=style_hash,
        )

    @staticmethod
    def _reference_manifest(result) -> dict:
        """Canonical immutable source for every confirmed reference."""

        return {
            "schemaVersion": "contract-reference-manifest-v1",
            "seedRef": {
                "id": result.seed_ref.id,
                "revisionId": result.seed_ref.revision_id,
                "contentHash": result.seed_ref.content_hash,
            },
            "engineRef": {
                "id": result.engine_ref.id,
                "batchId": result.engine_ref.batch_id,
                "contentHash": result.engine_ref.content_hash,
            },
            "bindingRef": ({
                "id": result.binding_ref.id,
                "revision": result.binding_ref.revision,
                "contentHash": result.binding_ref.content_hash,
            } if result.binding_ref else None),
            "styleRefs": [ref.model_dump(mode="json") for ref in result.style_refs],
            "experienceCardRefs": [
                ref.model_dump(mode="json") for ref in result.experience_card_refs
            ],
            "corpusSourceRefs": [
                ref.model_dump(mode="json") for ref in result.corpus_source_refs
            ],
        }

    async def _lock_contract_asset_references(
        self,
        session,
        *,
        style_refs,
        experience_refs,
        corpus_refs,
    ):
        lock_requests = [
            *(("style", ref.id) for ref in style_refs),
            *(("experience", ref.id) for ref in experience_refs),
            *(("corpus", ref.id) for ref in corpus_refs),
        ]
        locked_assets = {}
        for kind, asset_id in sorted(lock_requests):
            if kind == "style":
                row = await self.repository.read_style_revision(
                    session, asset_id, lock=True
                )
            elif kind == "experience":
                row = await self.repository.read_experience_revision(
                    session, asset_id, lock=True
                )
            else:
                row = await self.repository.read_corpus_revision(
                    session,
                    asset_id,
                    next(
                        ref.revisionId
                        for ref in corpus_refs
                        if ref.id == asset_id
                    ),
                    lock=True,
                )
            locked_assets[(kind, asset_id)] = row
        fragments_by_source = {}
        for ref in sorted(
            corpus_refs,
            key=lambda item: (item.id, item.revisionId),
        ):
            fragments_by_source[(ref.id, ref.revisionId)] = (
                await self.repository.read_corpus_fragments(
                    session,
                    ref.id,
                    ref.revisionId,
                    tuple(sorted(
                        fragment.fragmentId for fragment in ref.fragments
                    )),
                    lock=True,
                )
            )
        return locked_assets, fragments_by_source

    async def _lock_contract_assets(self, session, draft):
        style_refs = (
            draft.primaryStyleRef,
            *((draft.secondaryStyleRef,) if draft.secondaryStyleRef else ()),
        )
        locked_assets, fragments_by_source = (
            await self._lock_contract_asset_references(
                session,
                style_refs=style_refs,
                experience_refs=draft.experienceCardRefs,
                corpus_refs=draft.corpusSourceRefs,
            )
        )
        sources = tuple(
            locked_assets[("corpus", ref.id)] for ref in draft.corpusSourceRefs
        )
        fragments = tuple(
            fragments_by_source[(ref.id, ref.revisionId)]
            for ref in draft.corpusSourceRefs
        )
        return (
            locked_assets[("style", draft.primaryStyleRef.id)],
            (locked_assets[("style", draft.secondaryStyleRef.id)]
             if draft.secondaryStyleRef else None),
            tuple(locked_assets[("experience", ref.id)]
                  for ref in draft.experienceCardRefs),
            sources,
            fragments,
        )

    @staticmethod
    def _confirmed_result(preview, creation_id, style_id):
        return ConfirmedContractResult(
            project_id=preview.project_id,
            revision=preview.expected_revision,
            selection_revision=preview.selection_revision,
            creation_contract_id=creation_id,
            style_contract_id=style_id,
            contract_ready=True,
            reasons=(),
            seed_ref=preview.seed_ref,
            engine_ref=preview.engine_ref,
            binding_ref=preview.binding_ref,
            style_refs=preview.style_refs,
            experience_card_refs=preview.experience_card_refs,
            corpus_source_refs=preview.corpus_source_refs,
            creation_contract=preview.creation_contract,
            style_contract=preview.style_contract,
            likes=preview.likes,
            dislikes=preview.dislikes,
            creation_hash=preview.creation_hash,
            style_hash=preview.style_hash,
        )
__all__ = ("ContractPreviewService", "style_contract_hash")
