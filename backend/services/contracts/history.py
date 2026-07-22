"""Immutable contract snapshot verification, active-head readiness, and history."""

from __future__ import annotations

from dataclasses import replace
import json

from pydantic import ValidationError

from backend.domain.contracts import CreationContractPayload, StyleContractPayload
from backend.domain.json_contracts import canonical_hash, canonical_json
from .drafts import (
    AssetRevisionRef,
    BindingContractRef,
    ContractConflict,
    ContractDraftPayload,
    ContractDraftResult,
    ContractHistoryPage,
    ContractNotFound,
    ContractPreconditionFailed,
    ConfirmedContractResult,
    CorpusSourceRef,
    EngineContractRef,
    ModelBindingRef,
    ResolvedAssetRef,
    ResolvedCorpusFragment,
    ResolvedCorpusRef,
    ResolvedStyleRef,
    SeedContractRef,
    _json_array,
    _json_object,
    _strict_engine,
    style_contract_hash,
)
from .preview import ContractPreviewService


class ContractHistoryService(ContractPreviewService):
    def _result_from_snapshot(self, snapshot) -> ConfirmedContractResult:
        if snapshot is None:
            raise ContractConflict()
        try:
            creation_json = _json_object(snapshot["creation_json"])
            creation_json["chapterWordRangePreference"] = tuple(
                creation_json["chapterWordRangePreference"]
            )
            creation_json["prohibitedDirections"] = tuple(
                creation_json["prohibitedDirections"]
            )
            creation_json["experienceCardRefs"] = tuple(
                creation_json["experienceCardRefs"]
            )
            creation_json["corpusSourceRefs"] = tuple({
                **source,
                "fragments": tuple(source["fragments"]),
            } for source in creation_json["corpusSourceRefs"])
            creation = CreationContractPayload(**{
                **creation_json,
                "selectedEngine": _strict_engine(creation_json["selectedEngine"]),
            })
            style_json = _json_object(snapshot["style_json"])
            style = StyleContractPayload(**{
                **style_json,
                "characterVoices": tuple(style_json["characterVoices"]),
                "primaryRules": tuple(style_json["primaryRules"]),
                "risks": tuple(style_json["risks"]),
            })
            likes = tuple(_json_array(snapshot["likes_json"]))
            dislikes = tuple(_json_array(snapshot["dislikes_json"]))
            capacity = _json_object(snapshot["chapter_capacity_policy"])
            expected_capacity = {
                "expectedVolumeCount": creation.expectedVolumeCount,
                "expectedChapterCount": creation.expectedChapterCount,
                "chapterWordRangePreference": list(
                    creation.chapterWordRangePreference
                ),
            }
            relational_creation_valid = (
                int(snapshot["selection_revision"]) == creation.selectionRevision
                and snapshot["channel_profile_key"] == creation.channelProfileKey
                and snapshot["genre_profile_key"] == creation.genreProfileKey
                and snapshot["quality_charter_version"]
                    == creation.qualityCharterVersion
                and int(snapshot["total_word_min"]) == creation.targetTotalWords
                and int(snapshot["total_word_max"]) == creation.targetTotalWords
                and canonical_json(capacity) == canonical_json(expected_capacity)
            )
            binding_items = (
                self._binding_items({
                    "items": snapshot.get("binding_items") or (),
                })
                if creation.modelBindingRef is not None else ()
            )
            style_refs = tuple(ResolvedStyleRef(
                ref["role"], ref["id"], int(ref["revision"]), ref["contentHash"]
            ) for ref in snapshot["style_refs"])
            if tuple(ref.role for ref in style_refs) not in (
                ("primary",), ("primary", "secondary")
            ):
                raise ValueError("confirmed style refs must have one primary")
            cards = tuple(ResolvedAssetRef(
                ref["id"], int(ref["revision"]), ref["contentHash"]
            ) for ref in snapshot["experience_card_refs"])
            sources = tuple(ResolvedCorpusRef(
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
            ) for ref in creation.corpusSourceRefs)
            expected_style_refs = tuple(
                [creation.primaryStyleRef]
                + ([creation.secondaryStyleRef]
                   if creation.secondaryStyleRef is not None else [])
            )
            relational_style_refs = tuple(
                (ref["id"], int(ref["revision"]), ref["contentHash"])
                for ref in snapshot["style_refs"]
            )
            relational_cards = tuple(
                (ref["id"], int(ref["revision"]), ref["contentHash"])
                for ref in snapshot["experience_card_refs"]
            )
            relational_sources = tuple(
                (
                    ref["id"], ref.get("revisionId"), int(ref["revision"]),
                    ref["contentHash"], ref["selectionMode"],
                )
                for ref in snapshot["corpus_source_refs"]
            )
            relational_fragments = tuple(
                (
                    ref["sourceId"], ref["chapterId"], ref["fragmentId"],
                    ref["fragmentHash"], int(ref["chapterCharStart"]),
                    int(ref["chapterCharEnd"]), ref["referenceUse"],
                )
                for ref in snapshot.get("corpus_fragment_refs") or ()
            )
            expected_fragments = tuple(
                (
                    source.id, fragment.chapterId, fragment.fragmentId,
                    fragment.fragmentHash, fragment.chapterCharStart,
                    fragment.chapterCharEnd, fragment.referenceUse,
                )
                for source in creation.corpusSourceRefs
                for fragment in source.fragments
            )
            binding_valid = (
                creation.modelBindingRef is None
                and snapshot.get("binding_revision_id") is None
                and snapshot.get("binding_revision") is None
                and snapshot.get("binding_hash") is None
                and snapshot.get("actual_binding_hash") is None
                and not binding_items
            ) or (
                creation.modelBindingRef is not None
                and snapshot.get("binding_revision_id")
                    == creation.modelBindingRef.id
                and int(snapshot.get("binding_revision") or 0)
                    == creation.modelBindingRef.revision
                and snapshot.get("binding_hash")
                    == creation.modelBindingRef.contentHash
                and snapshot.get("actual_binding_hash")
                    == creation.modelBindingRef.contentHash
                and self._binding_integrity(binding_items, {
                    "project_id": snapshot["project_id"],
                    "revision": snapshot["binding_revision"],
                    "content_hash": snapshot["binding_hash"],
                    "items": snapshot.get("binding_items") or (),
                })
            )
            if (
                canonical_hash(creation) != snapshot["creation_hash"]
                or style_contract_hash(style, likes, dislikes)
                    != snapshot["style_hash"]
                or canonical_hash(creation.selectedSeed) != snapshot["seed_hash"]
                or canonical_hash(creation.selectedEngine) != snapshot["engine_hash"]
                or creation.seedRevisionId != snapshot["seed_revision_id"]
                or creation.seedHash != snapshot["seed_hash"]
                or creation.engineOptionId != snapshot["engine_option_id"]
                or creation.engineHash != snapshot["engine_hash"]
                or not relational_creation_valid
                or not binding_valid
                or snapshot["seed_hash"] != snapshot.get("actual_seed_hash")
                or snapshot["engine_hash"] != snapshot.get("actual_engine_hash")
                or relational_style_refs != tuple(
                    (ref.id, ref.revision, ref.contentHash)
                    for ref in expected_style_refs
                )
                or relational_cards != tuple(
                    (ref.id, ref.revision, ref.contentHash)
                    for ref in creation.experienceCardRefs
                )
                or relational_sources != tuple(
                    (
                        ref.id, ref.revisionId, ref.revision,
                        ref.contentHash, ref.selectionMode,
                    )
                    for ref in creation.corpusSourceRefs
                )
                or relational_fragments != expected_fragments
                or any(
                    ref.get("contentHash") != ref.get("actualContentHash")
                    for collection in (
                        snapshot["style_refs"], snapshot["experience_card_refs"],
                        snapshot["corpus_source_refs"],
                    ) for ref in collection
                )
                or any(
                    ref.get("fragmentHash") != ref.get("actualContentHash")
                    for ref in snapshot.get("corpus_fragment_refs") or ()
                )
            ):
                raise ValueError("confirmed snapshot hash mismatch")
        except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
            raise ContractPreconditionFailed() from None
        result = ConfirmedContractResult(
            project_id=snapshot.get("project_id", ""),
            revision=int(snapshot["revision"]),
            selection_revision=int(snapshot["selection_revision"]),
            creation_contract_id=snapshot["creation_contract_id"],
            style_contract_id=snapshot["style_contract_id"],
            contract_ready=True, reasons=(),
            seed_ref=SeedContractRef(
                id=snapshot.get("seed_id"),
                revision_id=snapshot["seed_revision_id"],
                content_hash=snapshot["seed_hash"],
            ),
            engine_ref=EngineContractRef(
                id=snapshot["engine_option_id"],
                batch_id=snapshot.get("engine_batch_id"),
                content_hash=snapshot["engine_hash"],
            ),
            binding_ref=(BindingContractRef(
                id=snapshot["binding_revision_id"],
                revision=int(snapshot["binding_revision"]),
                content_hash=snapshot["binding_hash"], items=binding_items,
            ) if creation.modelBindingRef is not None else None),
            style_refs=style_refs, experience_card_refs=cards,
            corpus_source_refs=sources, creation_contract=creation,
            style_contract=style, likes=likes, dislikes=dislikes,
            creation_hash=snapshot["creation_hash"],
            style_hash=snapshot["style_hash"],
        )
        try:
            stored_manifest = _json_object(snapshot["reference_manifest_json"])
            if (
                canonical_hash(stored_manifest)
                != snapshot["reference_manifest_hash"]
                or canonical_json(stored_manifest)
                != canonical_json(self._reference_manifest(result))
            ):
                raise ValueError("confirmed reference manifest mismatch")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ContractPreconditionFailed() from None
        return result

    @staticmethod
    def _with_selection_readiness(result, selected):
        superseded = []
        if selected is None:
            superseded.append("selection_missing")
        else:
            if int(selected.get("selection_revision") or 0) != result.selection_revision:
                superseded.append("selection_revision_changed")
            if selected.get("seed_id") != result.seed_ref.id:
                superseded.append("seed_identity_changed")
            if (
                selected.get("seed_revision_id") != result.seed_ref.revision_id
                or selected.get("seed_hash") != result.seed_ref.content_hash
            ):
                superseded.append("seed_revision_changed")
        if not superseded:
            return result
        return replace(
            result,
            contract_ready=False,
            reasons=("superseded",),
            superseded_reasons=tuple(superseded),
        )

    @classmethod
    def _with_current_head_readiness(cls, result, selected, head):
        checked = cls._with_selection_readiness(result, selected)
        superseded = list(checked.superseded_reasons)
        if (
            head is None
            or int(head.get("revision") or 0) != checked.revision
        ):
            superseded.append("contract_revision_replaced")
        superseded = list(dict.fromkeys(superseded))
        if not superseded:
            return checked
        return replace(
            checked,
            contract_ready=False,
            reasons=("superseded",),
            superseded_reasons=tuple(superseded),
        )

    async def get_head(self, project_id: str):
        async with self.connection_factory() as session:
            if await self.repository.read_project(session, project_id) is None:
                raise ContractNotFound()
            head = await self.repository.read_contract_head(session, project_id)
            if head is None:
                raise ContractPreconditionFailed()
            if int(head["revision"]) == 0:
                return {
                    "project_id": project_id, "revision": 0,
                    "has_contract": False, "contract_ready": False,
                    "reasons": ("contract_missing",),
                }
            snapshot = await self.repository.read_confirmed_snapshot(
                session, project_id, int(head["revision"])
            )
            result = self._result_from_snapshot(snapshot)
            reasons = []
            if (
                result.creation_contract_id != head.get("creation_contract_id")
                or result.style_contract_id != head.get("style_contract_id")
                or result.creation_hash != head.get("creation_hash")
                or result.style_hash != head.get("style_hash")
            ):
                reasons.append("contract_head_drift")
            selected = await self.repository.read_selected_seed(session, project_id)
            if selected is None:
                reasons.append("seed_drift")
            else:
                if int(selected.get("selection_revision") or 0) != result.selection_revision:
                    reasons.append("selection_drift")
                if (
                    selected.get("seed_id") != result.seed_ref.id
                    or selected.get("seed_revision_id") != result.seed_ref.revision_id
                    or selected.get("seed_hash") != result.seed_ref.content_hash
                ):
                    reasons.append("seed_drift")
            engine = await self.repository.read_engine_option(
                session, project_id, result.engine_ref.id
            )
            if (
                engine is None
                or engine.get("content_hash") != result.engine_ref.content_hash
                or int(engine.get("selection_revision") or 0)
                    != result.selection_revision
                or engine.get("seed_revision_id") != result.seed_ref.revision_id
                or engine.get("seed_hash") != result.seed_ref.content_hash
            ):
                reasons.append("engine_drift")
            for ref in result.style_refs:
                row = await self.repository.read_style_revision(session, ref.id)
                reasons.extend(self._asset_reasons(
                    ref, row, kind="style", role=ref.role
                ))
            for ref in result.experience_card_refs:
                row = await self.repository.read_experience_revision(
                    session, ref.id
                )
                reasons.extend(self._asset_reasons(
                    ref, row, kind="experience"
                ))
            for ref in result.corpus_source_refs:
                row = await self.repository.read_corpus_revision(
                    session, ref.id, ref.revisionId
                )
                fragment_rows = await self.repository.read_corpus_fragments(
                    session,
                    ref.id,
                    ref.revisionId,
                    tuple(fragment.fragmentId for fragment in ref.fragments),
                )
                reasons.extend(self._asset_reasons(
                    ref, row, kind="corpus"
                ))
                reasons.extend(self._fragment_reasons(ref, fragment_rows))
            binding = await self.repository.read_binding_snapshot(
                session, project_id
            )
            if result.binding_ref is None:
                if binding is not None:
                    reasons.append("binding_drift")
            elif binding is None or (
                binding.get("binding_revision_id") != result.binding_ref.id
                or int(binding.get("revision") or 0) != result.binding_ref.revision
                or binding.get("content_hash") != result.binding_ref.content_hash
            ):
                reasons.append("binding_drift")
            else:
                try:
                    current_items = self._binding_items(binding)
                    if not self._binding_integrity(current_items, binding):
                        reasons.append("binding_drift")
                except ContractPreconditionFailed:
                    reasons.append("binding_drift")
            reasons = list(dict.fromkeys(reasons))
            return replace(
                result, project_id=project_id,
                contract_ready=not reasons, reasons=tuple(reasons),
            )

    async def history(
        self,
        project_id: str,
        limit: int = 20,
        before_revision: int | None = None,
    ) -> ContractHistoryPage:
        if (
            isinstance(limit, bool)
            or type(limit) is not int
            or not 1 <= limit <= 100
            or (
                before_revision is not None
                and (
                    isinstance(before_revision, bool)
                    or type(before_revision) is not int
                    or before_revision <= 0
                )
            )
        ):
            raise ContractPreconditionFailed()
        async with self.connection_factory() as session:
            if await self.repository.read_project(session, project_id) is None:
                raise ContractNotFound()
            revisions = await self.repository.list_contract_revisions(
                session,
                project_id,
                before_revision=before_revision,
                limit=limit,
            )
            selected = await self.repository.read_selected_seed(
                session, project_id
            )
            head = await self.repository.read_contract_head(session, project_id)
            results = []
            page = revisions[:limit]
            for row in page:
                snapshot = await self.repository.read_confirmed_snapshot(
                    session, project_id, int(row["revision"])
                )
                result = replace(
                    self._result_from_snapshot(snapshot),
                    project_id=project_id,
                )
                results.append(
                    self._with_current_head_readiness(
                        result, selected, head
                    )
                )
            return ContractHistoryPage(
                items=tuple(results),
                next_before_revision=(
                    int(page[-1]["revision"]) if len(revisions) > limit else None
                ),
            )


    async def clone_revision(
        self, project_id: str, source_revision: int
    ) -> ContractDraftResult:
        if (
            isinstance(source_revision, bool)
            or not isinstance(source_revision, int)
            or source_revision <= 0
        ):
            raise ContractPreconditionFailed()
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, project_id) is None:
                raise ContractNotFound()
            if await self.repository.lock_draft(session, project_id) is not None:
                raise ContractConflict()
            selected = await self.repository.lock_selected_seed(session, project_id)
            if selected is None:
                raise ContractConflict()
            snapshot = await self.repository.read_confirmed_snapshot(
                session, project_id, source_revision
            )
            if snapshot is None:
                raise ContractNotFound()
            head = await self.repository.read_contract_head(session, project_id)
            if head is None or int(head["revision"]) == 0:
                raise ContractConflict()
            try:
                verified = self._result_from_snapshot(snapshot)
                if (
                    verified.revision != source_revision
                    or (
                        source_revision == int(head["revision"])
                        and (
                            verified.creation_contract_id
                                != head["creation_contract_id"]
                            or verified.style_contract_id
                                != head["style_contract_id"]
                            or verified.creation_hash != head["creation_hash"]
                            or verified.style_hash != head["style_hash"]
                        )
                    )
                ):
                    raise ValueError("confirmed contract source mismatch")
                if (
                    int(selected.get("selection_revision") or 0)
                    != verified.selection_revision
                    or selected.get("seed_id") != verified.seed_ref.id
                    or selected.get("seed_revision_id")
                    != verified.seed_ref.revision_id
                    or selected.get("seed_hash")
                    != verified.seed_ref.content_hash
                ):
                    raise ContractConflict()
                primary = verified.style_refs[0]
                secondary = (
                    verified.style_refs[1] if len(verified.style_refs) == 2 else None
                )
                creation = verified.creation_contract
                draft = ContractDraftPayload(
                    schemaVersion="contract-draft-v2",
                    draftStage="assets",
                    seedRevisionId=verified.seed_ref.revision_id,
                    seedHash=verified.seed_ref.content_hash,
                    engineOptionId=verified.engine_ref.id,
                    engineHash=verified.engine_ref.content_hash,
                    channelProfileKey=creation.channelProfileKey,
                    genreProfileKey=creation.genreProfileKey,
                    qualityCharterVersion=creation.qualityCharterVersion,
                    targetTotalWords=creation.targetTotalWords,
                    expectedVolumeCount=creation.expectedVolumeCount,
                    expectedChapterCount=creation.expectedChapterCount,
                    chapterWordRangePreference=creation.chapterWordRangePreference,
                    prohibitedDirections=creation.prohibitedDirections,
                    authorNotes=creation.authorNotes,
                    modelBindingRef=(ModelBindingRef(
                        id=verified.binding_ref.id,
                        revision=verified.binding_ref.revision,
                        contentHash=verified.binding_ref.content_hash,
                    ) if verified.binding_ref else None),
                    primaryStyleRef=AssetRevisionRef(
                        id=primary.id, revision=primary.revision,
                        contentHash=primary.contentHash,
                    ),
                    secondaryStyleRef=AssetRevisionRef(
                        id=secondary.id, revision=secondary.revision,
                        contentHash=secondary.contentHash,
                    ) if secondary else None,
                    experienceCardRefs=tuple(
                        AssetRevisionRef(
                            id=ref.id, revision=ref.revision,
                            contentHash=ref.contentHash,
                        ) for ref in verified.experience_card_refs
                    ),
                    corpusSourceRefs=tuple(
                        CorpusSourceRef(
                            id=ref.id, revisionId=ref.revisionId,
                            revision=ref.revision,
                            contentHash=ref.contentHash,
                            selectionMode=ref.selectionMode,
                            fragments=tuple(
                                fragment.model_dump(mode="python")
                                for fragment in ref.fragments
                            ),
                            pinnedHistoricalRevision=
                                ref.pinnedHistoricalRevision,
                        ) for ref in verified.corpus_source_refs
                    ),
                    likes=verified.likes,
                    dislikes=verified.dislikes,
                )
            except (KeyError, TypeError, ValueError, ValidationError):
                raise ContractPreconditionFailed() from None
            now = self.clock()
            row = self._draft_row(
                project_id, draft, draft_id=self.id_factory(),
                selection_revision=verified.selection_revision,
                base_revision=int(head["revision"]), version=1, created_at=now,
            )
            await self.repository.insert_draft(session, row)
            return self._draft_result(row)
__all__ = ("ContractHistoryService",)
