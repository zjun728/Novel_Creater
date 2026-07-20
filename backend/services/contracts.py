"""Recoverable creation-contract drafts and deterministic read-only previews."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import re
from pathlib import PurePosixPath, PureWindowsPath
import time
from typing import Annotated, Literal, Mapping, Self
from uuid import uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from backend.domain.contracts import CreationContractPayload, StyleContractPayload
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import TASK_KEYS, BindingItem, BindingRevision
from backend.domain.seeds import decode_seed_revision
from backend.domain.story_engines import StoryEngineOption
from backend.http_errors import PublicDomainError


MAX_REFS = 20
MAX_PREFERENCES = 20
MAX_TEXT = 2_000
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _reject_path_shaped_text(value: str) -> str:
    normalized_parts = value.replace("\\", "/").split("/")
    if (
        value.startswith(("/", "\\"))
        or bool(PureWindowsPath(value).drive)
        or PurePosixPath(value).is_absolute()
        or ".." in normalized_parts
    ):
        raise ValueError("text must not contain a path")
    return value


Text = Annotated[
    str,
    Field(min_length=1, max_length=MAX_TEXT),
    AfterValidator(_reject_path_shaped_text),
]
ProfileOrVersionKey = Annotated[
    str,
    Field(min_length=1, max_length=120),
    AfterValidator(_reject_path_shaped_text),
]
Identifier = Annotated[
    str,
    Field(min_length=1, max_length=36, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"),
]


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


class ContractDraftIncomplete(PublicDomainError):
    status_code = 422
    code = "ContractDraftIncomplete"
    message = "Contract draft is not complete"


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
    schemaVersion: Literal["contract-draft-v2"]
    draftStage: Literal["engine", "style", "assets"]
    engineOptionId: Identifier
    engineHash: Hash
    channelProfileKey: ProfileOrVersionKey
    genreProfileKey: ProfileOrVersionKey
    qualityCharterVersion: ProfileOrVersionKey
    totalWordRange: tuple[int, int]
    chapterCapacityPolicy: Text
    primaryStyleRef: AssetRevisionRef | None = None
    secondaryStyleRef: AssetRevisionRef | None = None
    experienceCardRefs: tuple[AssetRevisionRef, ...] | None = Field(
        default=None, max_length=MAX_REFS
    )
    corpusSourceRefs: tuple[CorpusSourceRef, ...] | None = Field(
        default=None, max_length=MAX_REFS
    )
    likes: tuple[Text, ...] | None = Field(
        default=None, max_length=MAX_PREFERENCES
    )
    dislikes: tuple[Text, ...] | None = Field(
        default=None, max_length=MAX_PREFERENCES
    )

    @property
    def is_complete(self) -> bool:
        return self.draftStage == "assets"

    @model_validator(mode="after")
    def validate_contract_draft(self) -> Self:
        low, high = self.totalWordRange
        if low <= 0 or high < low:
            raise ValueError("totalWordRange must be positive and ordered")
        if (
            self.primaryStyleRef
            and self.secondaryStyleRef
            and self.secondaryStyleRef.id == self.primaryStyleRef.id
        ):
            raise ValueError("primary and secondary styles must be different")
        if self.draftStage == "engine":
            if any(value is not None for value in (
                self.primaryStyleRef,
                self.secondaryStyleRef,
                self.experienceCardRefs,
                self.corpusSourceRefs,
                self.likes,
                self.dislikes,
            )):
                raise ValueError("engine draft must not retain downstream choices")
        elif self.draftStage == "style":
            if (
                self.primaryStyleRef is None
                or self.likes is None
                or self.dislikes is None
                or self.experienceCardRefs is not None
                or self.corpusSourceRefs is not None
            ):
                raise ValueError("style draft fields are incomplete")
        elif (
            self.primaryStyleRef is None
            or self.likes is None
            or self.dislikes is None
            or self.experienceCardRefs is None
            or self.corpusSourceRefs is None
        ):
            raise ValueError("asset draft fields are incomplete")
        for field_name in ("experienceCardRefs", "corpusSourceRefs"):
            refs = getattr(self, field_name)
            if refs is None:
                continue
            if len({ref.id for ref in refs}) != len(refs):
                raise ValueError(f"{field_name} must not contain duplicate refs")
        for field_name in ("likes", "dislikes"):
            values = getattr(self, field_name)
            if values is None:
                continue
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must not contain duplicates")
        return self


class ModelBindingRef(_StrictValue):
    id: Identifier
    revision: int = Field(gt=0)
    contentHash: Hash


class ContractDraftPayload(ContractDraftInput):
    """Persisted draft enriched with a server-frozen binding reference."""

    seedRevisionId: Identifier
    seedHash: Hash
    modelBindingRef: ModelBindingRef


@dataclass(frozen=True)
class SaveContractDraft:
    project_id: str
    expected_draft_version: int
    draft: ContractDraftInput


@dataclass(frozen=True)
class ConfirmContracts:
    project_id: str
    idempotency_key: str
    expected_draft_version: int
    expected_draft_hash: str


@dataclass(frozen=True)
class ContractDraftResult:
    id: str
    project_id: str
    selection_revision: int
    base_head_revision: int
    draft_version: int
    content_hash: str
    draft: ContractDraftPayload
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class SeedContractRef:
    id: str | None
    revision_id: str
    content_hash: str


@dataclass(frozen=True)
class EngineContractRef:
    id: str
    batch_id: str | None
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
    selection_revision: int
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
    creation_contract: CreationContractPayload | None
    style_contract: StyleContractPayload | None
    likes: tuple[str, ...]
    dislikes: tuple[str, ...]
    creation_hash: str | None
    style_hash: str | None


@dataclass(frozen=True)
class ConfirmedContractResult:
    project_id: str
    revision: int
    selection_revision: int
    creation_contract_id: str
    style_contract_id: str
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
        sentenceParagraphRhythm=payload["rhythm"],
        dictionDensity=payload["diction_density"],
        dialogueAndSubtext=(
            f"对白：{payload['dialogue']}；潜台词：{payload['subtext']}"
        ),
        characterVoices=(payload["character_voices"],),
        emotionAndInteriority=(
            f"情绪：{payload['emotion']}；内心：{payload['interiority']}"
        ),
        actionExplanationEnvironment=(
            f"动作：{payload['action']}；说明：{payload['explanation']}；"
            f"环境：{payload['environment']}；身体反应：{payload['body_response']}"
        ),
        primaryRules=tuple(payload["preferred_techniques"]),
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
        failpoint=lambda _stage: None,
    ):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.id_factory = id_factory
        self.clock = clock
        self.failpoint = failpoint

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
            raise ContractPreconditionFailed() from None
        if canonical_hash(draft) != row["content_hash"]:
            raise ContractPreconditionFailed()
        if (
            row.get("seed_revision_id") != draft.seedRevisionId
            or row.get("seed_hash") != draft.seedHash
            or row.get("engine_option_id") != draft.engineOptionId
        ):
            raise ContractPreconditionFailed() from None
        return ContractDraftResult(
            id=row["id"], project_id=row["project_id"],
            selection_revision=int(row["selection_revision"]),
            base_head_revision=int(row["base_head_revision"]),
            draft_version=int(row["draft_version"]),
            content_hash=row["content_hash"], draft=draft,
            created_at=int(row["created_at"]), updated_at=int(row["updated_at"]),
        )

    def _draft_row(
        self, project_id, draft, *, selection_revision, draft_id,
        base_revision, version, created_at
    ):
        now = self.clock()
        return {
            "project_id": project_id,
            "id": draft_id,
            "base_head_revision": base_revision,
            "selection_revision": int(selection_revision),
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
            selected = await self.repository.lock_selected_seed(
                session, command.project_id
            )
            if selected is None:
                raise ContractPreconditionFailed()
            binding = await self.repository.lock_binding_snapshot(
                session, command.project_id
            )
            binding_items = self._binding_items(binding)
            if (
                tuple(item.task_key for item in binding_items) != TASK_KEYS
                or not self._binding_integrity(binding_items, binding)
            ):
                raise ContractPreconditionFailed()
            persisted_draft = ContractDraftPayload(
                **command.draft.model_dump(mode="python"),
                seedRevisionId=selected["seed_revision_id"],
                seedHash=selected["seed_hash"],
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
                    selection_revision=int(selected["selection_revision"]),
                    draft_id=self.id_factory(),
                    base_revision=int(head["revision"]), version=1,
                    created_at=now,
                )
                await self.repository.insert_draft(session, row)
            else:
                row = self._draft_row(
                    command.project_id, persisted_draft,
                    selection_revision=int(selected["selection_revision"]),
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
            raise ContractPreconditionFailed() from None

    @staticmethod
    def _binding_integrity(items, binding) -> bool:
        """Verify the persisted binding with the M2A canonical hash contract."""

        try:
            rows = tuple(binding.get("items") or ())
            revision = BindingRevision(
                project_id=binding["project_id"],
                revision=int(binding["revision"]),
                items=tuple(items),
            )
            return (
                len(rows) == len(items)
                and all(
                    row.get("item_hash") == canonical_hash(item)
                    for item, row in zip(items, rows)
                )
                and binding.get("content_hash") == canonical_hash(revision)
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            return False

    @staticmethod
    def _binding_ready(items, binding) -> bool:
        rows = tuple(binding.get("items") or ()) if binding else ()
        return (
            tuple(item.task_key for item in items) == TASK_KEYS
            and len(rows) == len(items)
            and ContractService._binding_integrity(items, binding)
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
            row.get("head_id")
            != row.get("revision_id" if kind == "corpus" else "id")
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

        reasons = []
        seed_payload = None
        if frozen_seed is None:
            reasons.append("seed_missing")
        else:
            try:
                seed_payload, _ = decode_seed_revision(frozen_seed["payload_json"])
            except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
                reasons.append("seed_invalid")
            if selected is None:
                reasons.append("seed_not_selected")
            elif (
                int(selected.get("selection_revision") or 0)
                != saved.selection_revision
                or
                selected["seed_revision_id"] != draft.seedRevisionId
                or selected["seed_hash"] != draft.seedHash
            ):
                reasons.append("seed_drift")
            if (
                seed_payload is not None
                and (
                frozen_seed.get("seed_hash") != draft.seedHash
                or canonical_hash(seed_payload) != draft.seedHash
                )
            ):
                reasons.append("seed_invalid")

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
        binding_usable = binding is not None
        if binding is None:
            reasons.append("binding_missing")
        else:
            try:
                binding_items = self._binding_items(binding)
            except ContractPreconditionFailed:
                reasons.append("binding_invalid")
                binding_usable = False
            if tuple(item.task_key for item in binding_items) != TASK_KEYS:
                reasons.append("binding_incomplete")
            if not self._binding_ready(binding_items, binding):
                reasons.append("binding_not_ready")
            if (
                binding.get("binding_revision_id") != draft.modelBindingRef.id
                or int(binding.get("revision") or 0) != draft.modelBindingRef.revision
                or binding.get("content_hash") != draft.modelBindingRef.contentHash
                or binding.get("head_revision") != draft.modelBindingRef.revision
                or binding.get("head_binding_revision_id") != draft.modelBindingRef.id
                or binding.get("head_hash") != draft.modelBindingRef.contentHash
            ):
                reasons.append("binding_drift")

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
        for ref, source in zip(draft.corpusSourceRefs, sources):
            reasons.extend(self._asset_reasons(ref, source, kind="corpus"))
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
                    selectedEngine=engine_payload,
                    totalWordRange=draft.totalWordRange,
                    chapterCapacityPolicy=draft.chapterCapacityPolicy,
                    modelBindingRevision=draft.modelBindingRef.revision,
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
            "bindingRef": {
                "id": result.binding_ref.id,
                "revision": result.binding_ref.revision,
                "contentHash": result.binding_ref.content_hash,
            },
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
        primary, secondary, cards, sources,
    ) -> ContractPreviewResult:
        draft = saved.draft
        try:
            seed_payload, _ = decode_seed_revision(frozen_seed["payload_json"])
            engine_payload = _strict_engine(engine["payload_json"])
            binding_items = self._binding_items(binding)
            style_payload = _strict_style_from_primary(primary, secondary)
        except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
            raise ContractPreconditionFailed() from None
        invalid = (
            selected is None
            or frozen_seed is None
            or engine is None
            or binding is None
            or selected.get("seed_revision_id") != draft.seedRevisionId
            or int(selected.get("selection_revision") or 0)
                != saved.selection_revision
            or selected.get("seed_hash") != draft.seedHash
            or frozen_seed.get("seed_revision_id") != draft.seedRevisionId
            or frozen_seed.get("seed_hash") != draft.seedHash
            or canonical_hash(seed_payload) != draft.seedHash
            or engine.get("status") != "succeeded"
            or int(engine.get("selection_revision") or 0)
                != saved.selection_revision
            or engine.get("seed_revision_id") != draft.seedRevisionId
            or engine.get("seed_hash") != draft.seedHash
            or engine.get("content_hash") != draft.engineHash
            or canonical_hash(engine_payload) != draft.engineHash
            or binding.get("binding_revision_id") != draft.modelBindingRef.id
            or int(binding.get("revision") or 0) != draft.modelBindingRef.revision
            or binding.get("content_hash") != draft.modelBindingRef.contentHash
            or binding.get("head_revision") != draft.modelBindingRef.revision
            or binding.get("head_binding_revision_id") != draft.modelBindingRef.id
            or binding.get("head_hash") != draft.modelBindingRef.contentHash
            or not self._binding_ready(binding_items, binding)
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
        for ref, source in zip(draft.corpusSourceRefs, sources):
            asset_reasons += self._asset_reasons(ref, source, kind="corpus")
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
                selectedEngine=engine_payload,
                totalWordRange=draft.totalWordRange,
                chapterCapacityPolicy=draft.chapterCapacityPolicy,
                modelBindingRevision=draft.modelBindingRef.revision,
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
                ResolvedCorpusRef(ref.id, ref.revision, ref.contentHash,
                                  ref.selectionMode)
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
            "bindingRef": {
                "id": result.binding_ref.id,
                "revision": result.binding_ref.revision,
                "contentHash": result.binding_ref.content_hash,
            },
            "styleRefs": [ref.model_dump(mode="json") for ref in result.style_refs],
            "experienceCardRefs": [
                ref.model_dump(mode="json") for ref in result.experience_card_refs
            ],
            "corpusSourceRefs": [
                ref.model_dump(mode="json") for ref in result.corpus_source_refs
            ],
        }

    async def _lock_contract_assets(self, session, draft):
        lock_requests = [
            ("style", draft.primaryStyleRef.id),
            *(((("style", draft.secondaryStyleRef.id),)
               if draft.secondaryStyleRef else ())),
            *(("experience", ref.id) for ref in draft.experienceCardRefs),
            *(("corpus", ref.id) for ref in draft.corpusSourceRefs),
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
                    session, asset_id, lock=True
                )
            locked_assets[(kind, asset_id)] = row
        return (
            locked_assets[("style", draft.primaryStyleRef.id)],
            (locked_assets[("style", draft.secondaryStyleRef.id)]
             if draft.secondaryStyleRef else None),
            tuple(locked_assets[("experience", ref.id)]
                  for ref in draft.experienceCardRefs),
            tuple(locked_assets[("corpus", ref.id)]
                  for ref in draft.corpusSourceRefs),
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

    def _result_from_snapshot(self, snapshot) -> ConfirmedContractResult:
        if snapshot is None:
            raise ContractConflict()
        try:
            creation_json = _json_object(snapshot["creation_json"])
            creation = CreationContractPayload(**{
                **creation_json,
                "totalWordRange": tuple(creation_json["totalWordRange"]),
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
            binding_items = self._binding_items({
                "items": snapshot.get("binding_items") or (),
            })
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
                ref["id"], int(ref["revision"]), ref["contentHash"],
                ref["selectionMode"],
            ) for ref in snapshot["corpus_source_refs"])
            if (
                canonical_hash(creation) != snapshot["creation_hash"]
                or style_contract_hash(style, likes, dislikes)
                    != snapshot["style_hash"]
                or canonical_hash(creation.selectedSeed) != snapshot["seed_hash"]
                or canonical_hash(creation.selectedEngine) != snapshot["engine_hash"]
                or creation.modelBindingRevision != int(snapshot["binding_revision"])
                or snapshot["binding_hash"] != snapshot.get("actual_binding_hash")
                or not self._binding_integrity(binding_items, {
                    "project_id": snapshot["project_id"],
                    "revision": snapshot["binding_revision"],
                    "content_hash": snapshot["binding_hash"],
                    "items": snapshot.get("binding_items") or (),
                })
                or snapshot["seed_hash"] != snapshot.get("actual_seed_hash")
                or snapshot["engine_hash"] != snapshot.get("actual_engine_hash")
                or any(
                    ref.get("contentHash") != ref.get("actualContentHash")
                    for collection in (
                        snapshot["style_refs"], snapshot["experience_card_refs"],
                        snapshot["corpus_source_refs"],
                    ) for ref in collection
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
            binding_ref=BindingContractRef(
                id=snapshot["binding_revision_id"],
                revision=int(snapshot["binding_revision"]),
                content_hash=snapshot["binding_hash"], items=binding_items,
            ),
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
        current = selected is not None and (
            int(selected.get("selection_revision") or 0)
                == result.selection_revision
            and selected.get("seed_id") == result.seed_ref.id
            and selected.get("seed_revision_id")
                == result.seed_ref.revision_id
            and selected.get("seed_hash") == result.seed_ref.content_hash
        )
        if current:
            return result
        return replace(
            result,
            contract_ready=False,
            reasons=("superseded",),
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
            if selected is None or (
                int(selected.get("selection_revision") or 0)
                    != result.selection_revision
                or selected.get("seed_revision_id") != result.seed_ref.revision_id
                or selected.get("seed_hash") != result.seed_ref.content_hash
            ):
                reasons.append("seed_drift")
            binding = await self.repository.read_binding_snapshot(session, project_id)
            if binding is None or (
                binding.get("binding_revision_id") != result.binding_ref.id
                or int(binding.get("revision") or 0) != result.binding_ref.revision
                or binding.get("content_hash") != result.binding_ref.content_hash
            ):
                reasons.append("binding_drift")
            else:
                try:
                    current_items = self._binding_items(binding)
                    if not self._binding_ready(current_items, binding):
                        reasons.append("binding_not_ready")
                except ContractPreconditionFailed:
                    reasons.append("binding_not_ready")
            return replace(
                result, project_id=project_id,
                contract_ready=not reasons, reasons=tuple(reasons),
            )

    async def history(self, project_id: str, limit: int = 20):
        if not 1 <= limit <= 100:
            raise ContractPreconditionFailed()
        async with self.connection_factory() as session:
            if await self.repository.read_project(session, project_id) is None:
                raise ContractNotFound()
            revisions = await self.repository.list_contract_revisions(
                session, project_id, limit
            )
            selected = await self.repository.read_selected_seed(
                session, project_id
            )
            results = []
            for row in revisions:
                snapshot = await self.repository.read_confirmed_snapshot(
                    session, project_id, int(row["revision"])
                )
                result = replace(
                    self._result_from_snapshot(snapshot),
                    project_id=project_id,
                )
                results.append(
                    self._with_selection_readiness(result, selected)
                )
            return tuple(results)

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
                return self._with_selection_readiness(replay, selected)
            saved = self._draft_result(draft_row)
            if not saved.draft.is_complete:
                raise ContractDraftIncomplete()
            selected = frozen_seed = engine = binding = primary = secondary = None
            cards = sources = ()
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
            primary, secondary, cards, sources = (
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
                return self._with_selection_readiness(replay, selected)
            if int(head["revision"]) != saved.base_head_revision:
                raise ContractConflict()
            preview = self._assemble_confirmation(
                saved, selected, frozen_seed, engine, binding,
                primary, secondary, cards, sources,
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
                "binding_revision_id": preview.binding_ref.id,
                "binding_hash": preview.binding_ref.content_hash,
                "channel_profile_key": saved.draft.channelProfileKey,
                "genre_profile_key": saved.draft.genreProfileKey,
                "quality_charter_version": saved.draft.qualityCharterVersion,
                "total_word_min": saved.draft.totalWordRange[0],
                "total_word_max": saved.draft.totalWordRange[1],
                "chapter_capacity_policy": saved.draft.chapterCapacityPolicy,
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

    async def clone_current(self, project_id: str) -> ContractDraftResult:
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, project_id) is None:
                raise ContractNotFound()
            if await self.repository.lock_draft(session, project_id) is not None:
                raise ContractConflict()
            selected = await self.repository.lock_selected_seed(session, project_id)
            if selected is None:
                raise ContractConflict()
            head = await self.repository.read_contract_head(session, project_id)
            if head is None or int(head["revision"]) == 0:
                raise ContractConflict()
            snapshot = await self.repository.read_confirmed_snapshot(session, project_id)
            if snapshot is None or int(snapshot["revision"]) != int(head["revision"]):
                raise ContractConflict()
            try:
                verified = self._result_from_snapshot(snapshot)
                if (
                    verified.creation_contract_id != head["creation_contract_id"]
                    or verified.style_contract_id != head["style_contract_id"]
                    or verified.creation_hash != head["creation_hash"]
                    or verified.style_hash != head["style_hash"]
                ):
                    raise ValueError("confirmed contract head mismatch")
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
                    totalWordRange=creation.totalWordRange,
                    chapterCapacityPolicy=creation.chapterCapacityPolicy,
                    modelBindingRef=ModelBindingRef(
                        id=verified.binding_ref.id,
                        revision=verified.binding_ref.revision,
                        contentHash=verified.binding_ref.content_hash,
                    ),
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
                            id=ref.id, revision=ref.revision,
                            contentHash=ref.contentHash,
                            selectionMode=ref.selectionMode,
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
