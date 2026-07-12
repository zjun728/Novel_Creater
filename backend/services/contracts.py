"""Recoverable creation-contract drafts and deterministic read-only previews."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath, PureWindowsPath
import time
from typing import Annotated, Literal, Mapping, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.domain.contracts import CreationContractPayload, StyleContractPayload
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import TASK_KEYS, BindingItem
from backend.domain.seeds import SeedPayload
from backend.domain.story_engines import StoryEngineOption
from backend.http_errors import PublicDomainError


MAX_REFS = 20
MAX_PREFERENCES = 20
MAX_TEXT = 2_000
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]
Identifier = Annotated[str, Field(min_length=1, max_length=36)]


class ContractNotFound(PublicDomainError):
    status_code = 404
    code = "ContractNotFound"
    message = "Contract draft or project not found"


class ContractConflict(PublicDomainError):
    status_code = 409
    code = "ContractConflict"
    message = "Contract state changed; refresh and retry"


class ContractPreconditionFailed(PublicDomainError):
    status_code = 422
    code = "ContractPreconditionFailed"
    message = "Contract prerequisites are unavailable"


class _StrictValue(BaseModel):
    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", str_strip_whitespace=True
    )


class AssetRevisionRef(_StrictValue):
    id: Identifier
    revision: int = Field(gt=0)
    contentHash: Hash


class CorpusSourceRef(AssetRevisionRef):
    selectionMode: Literal["author", "system"]


class ContractDraftInput(_StrictValue):
    schemaVersion: Literal["contract-draft-v1"]
    seedRevisionId: Identifier
    seedHash: Hash
    engineOptionId: Identifier
    engineHash: Hash
    channelProfileKey: Text
    genreProfileKey: Text
    qualityCharterVersion: Text
    totalWordRange: tuple[int, int]
    chapterCapacityPolicy: Text
    primaryStyleRef: AssetRevisionRef
    secondaryStyleRef: AssetRevisionRef | None = None
    experienceCardRefs: tuple[AssetRevisionRef, ...] = Field(
        default=(), max_length=MAX_REFS
    )
    corpusSourceRefs: tuple[CorpusSourceRef, ...] = Field(
        default=(), max_length=MAX_REFS
    )
    likes: tuple[Text, ...] = Field(default=(), max_length=MAX_PREFERENCES)
    dislikes: tuple[Text, ...] = Field(default=(), max_length=MAX_PREFERENCES)

    @model_validator(mode="after")
    def validate_contract_draft(self) -> Self:
        low, high = self.totalWordRange
        if low <= 0 or high < low:
            raise ValueError("totalWordRange must be positive and ordered")
        if self.secondaryStyleRef and self.secondaryStyleRef.id == self.primaryStyleRef.id:
            raise ValueError("primary and secondary styles must be different")
        for field_name in ("experienceCardRefs", "corpusSourceRefs"):
            refs = getattr(self, field_name)
            if len({ref.id for ref in refs}) != len(refs):
                raise ValueError(f"{field_name} must not contain duplicate refs")
        for field_name in ("likes", "dislikes"):
            values = getattr(self, field_name)
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must not contain duplicates")
            if any(
                PureWindowsPath(value).is_absolute()
                or PurePosixPath(value).is_absolute()
                for value in values
            ):
                raise ValueError(f"{field_name} must not contain absolute paths")
        return self


class ModelBindingRef(_StrictValue):
    id: Identifier
    revision: int = Field(gt=0)
    contentHash: Hash


class ContractDraftPayload(ContractDraftInput):
    """Persisted draft enriched with a server-frozen binding reference."""

    modelBindingRef: ModelBindingRef


@dataclass(frozen=True)
class SaveContractDraft:
    project_id: str
    expected_draft_version: int
    draft: ContractDraftInput


@dataclass(frozen=True)
class ContractDraftResult:
    id: str
    project_id: str
    base_head_revision: int
    draft_version: int
    content_hash: str
    draft: ContractDraftPayload
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class SeedContractRef:
    id: str
    revision_id: str
    content_hash: str


@dataclass(frozen=True)
class EngineContractRef:
    id: str
    batch_id: str
    content_hash: str


@dataclass(frozen=True)
class BindingContractRef:
    id: str
    revision: int
    content_hash: str
    items: tuple[BindingItem, ...]


@dataclass(frozen=True)
class ResolvedStyleRef:
    role: Literal["primary", "secondary"]
    id: str
    revision: int
    contentHash: str

    def model_dump(self, *, mode="python"):
        return {
            "role": self.role, "id": self.id, "revision": self.revision,
            "contentHash": self.contentHash,
        }

    @property
    def content_hash(self):
        return self.contentHash


@dataclass(frozen=True)
class ResolvedAssetRef:
    id: str
    revision: int
    contentHash: str

    def model_dump(self, *, mode="python"):
        return {
            "id": self.id, "revision": self.revision,
            "contentHash": self.contentHash,
        }

    @property
    def content_hash(self):
        return self.contentHash


@dataclass(frozen=True)
class ResolvedCorpusRef(ResolvedAssetRef):
    selectionMode: Literal["author", "system"] = "author"

    def model_dump(self, *, mode="python"):
        return {**super().model_dump(mode=mode), "selectionMode": self.selectionMode}


@dataclass(frozen=True)
class ContractPreviewResult:
    project_id: str
    draft_version: int
    base_head_revision: int
    expected_revision: int
    contract_ready: bool
    reasons: tuple[str, ...]
    seed_ref: SeedContractRef
    engine_ref: EngineContractRef
    binding_ref: BindingContractRef
    style_refs: tuple[ResolvedStyleRef, ...]
    experience_card_refs: tuple[ResolvedAssetRef, ...]
    corpus_source_refs: tuple[ResolvedCorpusRef, ...]
    creation_contract: CreationContractPayload
    style_contract: StyleContractPayload
    likes: tuple[str, ...]
    dislikes: tuple[str, ...]
    creation_hash: str
    style_hash: str


def _json_object(value) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("stored JSON must be an object")
    return value


def _json_array(value) -> list:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        raise ValueError("stored JSON must be an array")
    return value


def _strict_engine(value) -> StoryEngineOption:
    raw = _json_object(value)
    normalized = dict(raw)
    for key in ("ensembleRoles", "satisfactionSources", "longFormVariation", "risks"):
        if isinstance(normalized.get(key), list):
            normalized[key] = tuple(normalized[key])
    return StoryEngineOption(**normalized)


def _strict_style_from_primary(primary: Mapping, secondary: Mapping | None):
    payload = _json_object(primary["payload_json"])
    secondary_flavor = None
    if secondary is not None:
        secondary_payload = _json_object(secondary["payload_json"])
        secondary_flavor = (
            f"{secondary['name']}：{secondary_payload['reading_experience']}；"
            "仅作局部风味，不覆盖主风格的叙事距离、语言底色和整体阅读体验。"
        )
    return StyleContractPayload(
        schemaVersion="style-contract-v1",
        readingExperience=payload["reading_experience"],
        narrativeDistance=payload["narrative_distance"],
        sentenceParagraphRhythm=payload["sentence_paragraph_rhythm"],
        dictionDensity=payload["diction_density"],
        dialogueAndSubtext=payload["dialogue_and_subtext"],
        characterVoices=tuple(payload["character_voices"]),
        emotionAndInteriority=payload["emotion_and_interiority"],
        actionExplanationEnvironment=payload["action_explanation_environment"],
        primaryRules=tuple(payload["primary_rules"]),
        secondaryFlavor=secondary_flavor,
        risks=tuple(payload["risks"]),
    )


def style_contract_hash(merged_style, likes, dislikes) -> str:
    """Hash all three persisted facts that make up a StyleContract."""

    merged = (
        merged_style.model_dump(mode="json")
        if isinstance(merged_style, BaseModel) else merged_style
    )
    return canonical_hash({
        "mergedStyle": merged,
        "likes": list(likes),
        "dislikes": list(dislikes),
    })


class ContractService:
    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        connection_factory,
        id_factory=lambda: str(uuid4()),
        clock=lambda: int(time.time() * 1000),
    ):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.id_factory = id_factory
        self.clock = clock

    @staticmethod
    def _draft_result(row) -> ContractDraftResult:
        try:
            raw = _json_object(row["draft_json"])
            for key in (
                "totalWordRange", "experienceCardRefs", "corpusSourceRefs",
                "likes", "dislikes",
            ):
                if isinstance(raw.get(key), list):
                    raw[key] = tuple(raw[key])
            draft = ContractDraftPayload(**raw)
        except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise ContractPreconditionFailed() from exc
        if canonical_hash(draft) != row["content_hash"]:
            raise ContractPreconditionFailed()
        return ContractDraftResult(
            id=row["id"], project_id=row["project_id"],
            base_head_revision=int(row["base_head_revision"]),
            draft_version=int(row["draft_version"]),
            content_hash=row["content_hash"], draft=draft,
            created_at=int(row["created_at"]), updated_at=int(row["updated_at"]),
        )

    def _draft_row(
        self, project_id, draft, *, draft_id, base_revision, version, created_at
    ):
        now = self.clock()
        return {
            "project_id": project_id,
            "id": draft_id,
            "base_head_revision": base_revision,
            "seed_revision_id": draft.seedRevisionId,
            "seed_hash": draft.seedHash,
            "engine_option_id": draft.engineOptionId,
            "draft_json": canonical_json(draft),
            "content_hash": canonical_hash(draft),
            "draft_version": version,
            "created_at": created_at,
            "updated_at": now,
        }

    async def save_draft(self, command: SaveContractDraft) -> ContractDraftResult:
        if command.expected_draft_version < 0:
            raise ContractConflict()
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, command.project_id) is None:
                raise ContractNotFound()
            current = await self.repository.lock_draft(session, command.project_id)
            if current is None and command.expected_draft_version != 0:
                raise ContractConflict()
            if (
                current is not None
                and int(current["draft_version"]) != command.expected_draft_version
            ):
                raise ContractConflict()
            head = None
            if current is None:
                head = await self.repository.read_contract_head(
                    session, command.project_id
                )
                if head is None:
                    raise ContractPreconditionFailed()
                if int(head["revision"]) != 0:
                    raise ContractConflict()
            binding = await self.repository.lock_binding_snapshot(
                session, command.project_id
            )
            binding_items = self._binding_items(binding)
            if not self._binding_ready(binding_items, binding):
                raise ContractPreconditionFailed()
            persisted_draft = ContractDraftPayload(
                **command.draft.model_dump(mode="python"),
                modelBindingRef=ModelBindingRef(
                    id=binding["binding_revision_id"],
                    revision=int(binding["revision"]),
                    contentHash=binding["content_hash"],
                ),
            )
            if current is None:
                now = self.clock()
                row = self._draft_row(
                    command.project_id, persisted_draft,
                    draft_id=self.id_factory(),
                    base_revision=int(head["revision"]), version=1,
                    created_at=now,
                )
                await self.repository.insert_draft(session, row)
            else:
                row = self._draft_row(
                    command.project_id, persisted_draft,
                    draft_id=current["id"],
                    base_revision=int(current["base_head_revision"]),
                    version=command.expected_draft_version + 1,
                    created_at=int(current["created_at"]),
                )
                if not await self.repository.cas_update_draft(
                    session, row, command.expected_draft_version
                ):
                    raise ContractConflict()
            return self._draft_result(row)

    async def get_draft(self, project_id: str) -> ContractDraftResult:
        async with self.connection_factory() as session:
            if await self.repository.read_project(session, project_id) is None:
                raise ContractNotFound()
            row = await self.repository.read_draft(session, project_id)
        if row is None:
            raise ContractNotFound()
        return self._draft_result(row)

    @staticmethod
    def _binding_items(binding) -> tuple[BindingItem, ...]:
        if binding is None:
            raise ContractPreconditionFailed()
        try:
            return tuple(
                BindingItem(**{
                    key: item.get(key) for key in (
                        "task_key", "resolution_status", "provider_id",
                        "provider_name_snapshot", "model_name_snapshot",
                    )
                })
                for item in tuple(binding.get("items") or ())
            )
        except (AttributeError, TypeError, ValidationError) as exc:
            raise ContractPreconditionFailed() from exc

    @staticmethod
    def _binding_ready(items, binding) -> bool:
        rows = tuple(binding.get("items") or ()) if binding else ()
        return (
            tuple(item.task_key for item in items) == TASK_KEYS
            and len(rows) == len(items)
            and all(
                item.resolution_status == "bound"
                and int(row.get("provider_ready") or 0) == 1
                for item, row in zip(items, rows)
            )
        )

    @staticmethod
    def _asset_reasons(ref, row, *, kind, role=None):
        suffix = f":{role}" if role else f":{ref.id}"
        reasons = []
        hash_field = "source_hash" if kind == "corpus" else "content_hash"
        if row is None:
            return [f"{kind}_missing{suffix}"]
        if int(row["revision"]) != ref.revision or row[hash_field] != ref.contentHash:
            reasons.append(f"{kind}_invalid{suffix}")
        if kind != "corpus":
            try:
                if canonical_hash(_json_object(row["payload_json"])) != row["content_hash"]:
                    reasons.append(f"{kind}_invalid{suffix}")
            except (TypeError, ValueError, json.JSONDecodeError):
                reasons.append(f"{kind}_invalid{suffix}")
        if row.get("status") not in ({"analyzed"} if kind == "corpus" else {"active"}):
            reasons.append(f"{kind}_inactive{suffix}")
        if (
            row.get("head_id") != row.get("id")
            or int(row.get("head_revision") or 0) != ref.revision
            or row.get("head_hash") != ref.contentHash
        ):
            reasons.append(f"{kind}_drift{suffix}")
        return list(dict.fromkeys(reasons))

    async def preview(self, project_id: str) -> ContractPreviewResult:
        async with self.connection_factory() as session:
            if await self.repository.read_project(session, project_id) is None:
                raise ContractNotFound()
            row = await self.repository.read_draft(session, project_id)
            if row is None:
                raise ContractPreconditionFailed()
            saved = self._draft_result(row)
            draft = saved.draft
            selected = await self.repository.read_selected_seed(session, project_id)
            frozen_seed = await self.repository.read_seed_revision(
                session, project_id, draft.seedRevisionId
            )
            engine = await self.repository.read_engine_option(
                session, project_id, draft.engineOptionId
            )
            binding = await self.repository.read_binding_snapshot(
                session, project_id, draft.modelBindingRef.id
            )
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
                await self.repository.read_corpus_revision(session, ref.id)
                for ref in draft.corpusSourceRefs
            ]

        try:
            seed_payload = SeedPayload(**_json_object(frozen_seed["payload_json"]))
            engine_payload = _strict_engine(engine["payload_json"])
            style_payload = _strict_style_from_primary(primary, secondary)
        except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise ContractPreconditionFailed() from exc

        reasons = []
        if selected is None or frozen_seed is None:
            reasons.append("seed_missing")
        else:
            if (
                selected["seed_revision_id"] != draft.seedRevisionId
                or selected["seed_hash"] != draft.seedHash
            ):
                reasons.append("seed_drift")
            if (
                frozen_seed.get("seed_hash") != draft.seedHash
                or canonical_hash(seed_payload) != draft.seedHash
            ):
                reasons.append("seed_invalid")
        if engine is None:
            reasons.append("engine_missing")
        else:
            if engine["content_hash"] != draft.engineHash or canonical_hash(engine_payload) != draft.engineHash:
                reasons.append("engine_invalid")
            if engine["status"] != "succeeded":
                reasons.append("engine_not_succeeded")
            if (
                engine["seed_revision_id"] != draft.seedRevisionId
                or engine["seed_hash"] != draft.seedHash
            ):
                reasons.append("engine_seed_drift")
        binding_items = self._binding_items(binding)
        if tuple(item.task_key for item in binding_items) != TASK_KEYS:
            reasons.append("binding_incomplete")
        if not self._binding_ready(binding_items, binding):
            reasons.append("binding_not_ready")
        if (
            binding["binding_revision_id"] != draft.modelBindingRef.id
            or int(binding["revision"]) != draft.modelBindingRef.revision
            or binding["content_hash"] != draft.modelBindingRef.contentHash
            or binding.get("head_revision") != draft.modelBindingRef.revision
            or binding.get("head_binding_revision_id") != draft.modelBindingRef.id
            or binding.get("head_hash") != draft.modelBindingRef.contentHash
        ):
            reasons.append("binding_drift")
        reasons.extend(self._asset_reasons(
            draft.primaryStyleRef, primary, kind="style", role="primary"
        ))
        if draft.secondaryStyleRef:
            reasons.extend(self._asset_reasons(
                draft.secondaryStyleRef, secondary, kind="style", role="secondary"
            ))
        for ref, asset in zip(draft.experienceCardRefs, cards):
            reasons.extend(self._asset_reasons(ref, asset, kind="experience"))
        for ref, source in zip(draft.corpusSourceRefs, sources):
            reasons.extend(self._asset_reasons(ref, source, kind="corpus"))
        reasons = list(dict.fromkeys(reasons))

        creation = CreationContractPayload(
            schemaVersion="creation-contract-v1",
            channelProfileKey=draft.channelProfileKey,
            genreProfileKey=draft.genreProfileKey,
            qualityCharterVersion=draft.qualityCharterVersion,
            selectedSeed=seed_payload,
            selectedEngine=engine_payload,
            totalWordRange=draft.totalWordRange,
            chapterCapacityPolicy=draft.chapterCapacityPolicy,
            modelBindingRevision=int(binding["revision"]),
        )
        style_hash = style_contract_hash(
            style_payload, draft.likes, draft.dislikes
        )
        return ContractPreviewResult(
            project_id=project_id, draft_version=saved.draft_version,
            base_head_revision=saved.base_head_revision,
            expected_revision=saved.base_head_revision + 1,
            contract_ready=not reasons, reasons=tuple(reasons),
            seed_ref=SeedContractRef(
                id=frozen_seed["seed_id"], revision_id=draft.seedRevisionId,
                content_hash=draft.seedHash,
            ),
            engine_ref=EngineContractRef(
                id=draft.engineOptionId, batch_id=engine["batch_id"],
                content_hash=draft.engineHash,
            ),
            binding_ref=BindingContractRef(
                id=draft.modelBindingRef.id,
                revision=draft.modelBindingRef.revision,
                content_hash=draft.modelBindingRef.contentHash,
                items=binding_items,
            ),
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
                    ref.id, ref.revision, ref.contentHash, ref.selectionMode
                ) for ref in draft.corpusSourceRefs
            ),
            creation_contract=creation, style_contract=style_payload,
            likes=draft.likes, dislikes=draft.dislikes,
            creation_hash=canonical_hash(creation), style_hash=style_hash,
        )

    async def clone_current(self, project_id: str) -> ContractDraftResult:
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, project_id) is None:
                raise ContractNotFound()
            if await self.repository.lock_draft(session, project_id) is not None:
                raise ContractConflict()
            head = await self.repository.read_contract_head(session, project_id)
            if head is None or int(head["revision"]) == 0:
                raise ContractConflict()
            snapshot = await self.repository.read_confirmed_snapshot(session, project_id)
            if snapshot is None or int(snapshot["revision"]) != int(head["revision"]):
                raise ContractConflict()
            try:
                creation_json = dict(_json_object(snapshot["creation_json"]))
                creation_json["totalWordRange"] = tuple(
                    creation_json["totalWordRange"]
                )
                creation_json["selectedEngine"] = _strict_engine(
                    creation_json["selectedEngine"]
                )
                creation = CreationContractPayload(**creation_json)
                style_json = _json_object(snapshot["style_json"])
                style = StyleContractPayload(**{
                    **style_json,
                    "characterVoices": tuple(style_json["characterVoices"]),
                    "primaryRules": tuple(style_json["primaryRules"]),
                    "risks": tuple(style_json["risks"]),
                })
                style_refs = tuple(snapshot["style_refs"])
                primary = next(ref for ref in style_refs if ref["role"] == "primary")
                secondary = next(
                    (ref for ref in style_refs if ref["role"] == "secondary"), None
                )
                likes = tuple(_json_array(snapshot["likes_json"]))
                dislikes = tuple(_json_array(snapshot["dislikes_json"]))
                if (
                    canonical_hash(creation) != snapshot["creation_hash"]
                    or snapshot["creation_hash"] != head["creation_hash"]
                    or style_contract_hash(style, likes, dislikes)
                    != snapshot["style_hash"]
                    or snapshot["style_hash"] != head["style_hash"]
                    or canonical_hash(creation.selectedSeed) != snapshot["seed_hash"]
                    or canonical_hash(creation.selectedEngine)
                    != snapshot["engine_hash"]
                    or creation.modelBindingRevision
                    != int(snapshot["binding_revision"])
                ):
                    raise ValueError("confirmed contract hash mismatch")
                draft = ContractDraftPayload(
                    schemaVersion="contract-draft-v1",
                    seedRevisionId=snapshot["seed_revision_id"],
                    seedHash=snapshot["seed_hash"],
                    engineOptionId=snapshot["engine_option_id"],
                    engineHash=snapshot["engine_hash"],
                    channelProfileKey=creation.channelProfileKey,
                    genreProfileKey=creation.genreProfileKey,
                    qualityCharterVersion=creation.qualityCharterVersion,
                    totalWordRange=creation.totalWordRange,
                    chapterCapacityPolicy=creation.chapterCapacityPolicy,
                    modelBindingRef=ModelBindingRef(
                        id=snapshot["binding_revision_id"],
                        revision=int(snapshot["binding_revision"]),
                        contentHash=snapshot["binding_hash"],
                    ),
                    primaryStyleRef=AssetRevisionRef(**{
                        key: primary[key] for key in ("id", "revision", "contentHash")
                    }),
                    secondaryStyleRef=AssetRevisionRef(**{
                        key: secondary[key] for key in ("id", "revision", "contentHash")
                    }) if secondary else None,
                    experienceCardRefs=tuple(
                        AssetRevisionRef(**ref)
                        for ref in snapshot["experience_card_refs"]
                    ),
                    corpusSourceRefs=tuple(
                        CorpusSourceRef(**ref) for ref in snapshot["corpus_source_refs"]
                    ),
                    likes=likes,
                    dislikes=dislikes,
                )
                # Parsing StyleContract here makes clone fail closed on a corrupt head.
                _ = style
            except (KeyError, StopIteration, TypeError, ValueError, ValidationError) as exc:
                raise ContractPreconditionFailed() from exc
            now = self.clock()
            row = self._draft_row(
                project_id, draft, draft_id=self.id_factory(),
                base_revision=int(head["revision"]), version=1, created_at=now,
            )
            await self.repository.insert_draft(session, row)
            return self._draft_result(row)
