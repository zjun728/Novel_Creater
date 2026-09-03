"""Strict contract draft values and recoverable draft persistence."""

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

from backend.domain.contracts import (
    ChapterWordRangeValue,
    CreationContractPayload,
    ExpectedChapterCount,
    ExpectedVolumeCount,
    FrozenAssetRef,
    FrozenBindingRef,
    FrozenCorpusSourceRef,
    StyleContractPayload,
    TargetTotalWords,
)
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import TASK_KEYS, BindingItem, BindingRevision
from backend.domain.seeds import decode_seed_revision
from backend.domain.story_engines import StoryEngineOption
from backend.http_errors import PublicDomainError


MAX_REFS = 20
MAX_PREFERENCES = 20
MAX_TEXT = 2_000
MAX_CORPUS_EXCERPT_CHARS = 4_000
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


class ContractAlreadyConfirmed(PublicDomainError):
    status_code = 409
    code = "contract_already_confirmed"
    message = "Creation Contract is already confirmed"


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


class AssetRevisionRef(FrozenAssetRef):
    pass


class CorpusSourceRef(FrozenCorpusSourceRef):
    pass


class ContractDraftInput(_StrictValue):
    schemaVersion: Literal["contract-draft-v2"]
    draftStage: Literal["engine", "style", "assets"]
    engineOptionId: Identifier
    engineHash: Hash
    channelProfileKey: ProfileOrVersionKey
    genreProfileKey: ProfileOrVersionKey
    qualityCharterVersion: ProfileOrVersionKey
    targetTotalWords: TargetTotalWords
    expectedVolumeCount: ExpectedVolumeCount
    expectedChapterCount: ExpectedChapterCount
    chapterWordRangePreference: tuple[
        ChapterWordRangeValue, ChapterWordRangeValue
    ]
    prohibitedDirections: tuple[Text, ...] = Field(max_length=MAX_PREFERENCES)
    authorNotes: Text | None = None
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
        low, high = self.chapterWordRangePreference
        if high < low:
            raise ValueError("chapterWordRangePreference must be ordered")
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
        if len(set(self.prohibitedDirections)) != len(self.prohibitedDirections):
            raise ValueError("prohibitedDirections must not contain duplicates")
        if self.corpusSourceRefs is not None:
            total_excerpt_chars = sum(
                fragment.chapterCharEnd - fragment.chapterCharStart
                for source in self.corpusSourceRefs
                for fragment in source.fragments
            )
            if total_excerpt_chars > MAX_CORPUS_EXCERPT_CHARS:
                raise ValueError("corpus fragment budget exceeds 4000 characters")
            if any(
                fragment.chapterCharEnd - fragment.chapterCharStart > 300
                for source in self.corpusSourceRefs
                for fragment in source.fragments
            ):
                raise ValueError("corpus fragment range exceeds 300 characters")
        return self


class ModelBindingRef(FrozenBindingRef):
    pass


class ContractDraftPayload(ContractDraftInput):
    """Persisted draft enriched with a server-frozen binding reference."""

    seedRevisionId: Identifier
    seedHash: Hash
    modelBindingRef: ModelBindingRef | None = None


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
    document_projection: "ContractDraftDocumentProjection | None" = None


@dataclass(frozen=True)
class ContractStyleDisplay:
    id: str
    revision: int
    content_hash: str
    name: str
    reading_experience: str
    narrative_distance: str
    sentence_paragraph_rhythm: str


@dataclass(frozen=True)
class ContractDraftDocumentProjection:
    selected_engine: StoryEngineOption | None
    primary_style: ContractStyleDisplay | None
    secondary_style: ContractStyleDisplay | None
    unavailable_reasons: tuple[str, ...] = ()


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
    revisionId: str = ""
    selectionMode: Literal["author", "system"] = "author"
    fragments: tuple["ResolvedCorpusFragment", ...] = ()
    pinnedHistoricalRevision: bool = False

    def model_dump(self, *, mode="python"):
        return {
            **super().model_dump(mode=mode),
            "revisionId": self.revisionId,
            "selectionMode": self.selectionMode,
            "fragments": [
                fragment.model_dump(mode=mode) for fragment in self.fragments
            ],
            "pinnedHistoricalRevision": self.pinnedHistoricalRevision,
        }


@dataclass(frozen=True)
class ResolvedCorpusFragment:
    chapterId: str
    fragmentId: str
    fragmentHash: str
    chapterCharStart: int
    chapterCharEnd: int
    referenceUse: Literal["inspiration", "structure", "style", "fact_check"]

    def model_dump(self, *, mode="python"):
        return {
            "chapterId": self.chapterId,
            "fragmentId": self.fragmentId,
            "fragmentHash": self.fragmentHash,
            "chapterCharStart": self.chapterCharStart,
            "chapterCharEnd": self.chapterCharEnd,
            "referenceUse": self.referenceUse,
        }


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
    binding_ref: BindingContractRef | None
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
    binding_ref: BindingContractRef | None
    style_refs: tuple[ResolvedStyleRef, ...]
    experience_card_refs: tuple[ResolvedAssetRef, ...]
    corpus_source_refs: tuple[ResolvedCorpusRef, ...]
    creation_contract: CreationContractPayload
    style_contract: StyleContractPayload
    likes: tuple[str, ...]
    dislikes: tuple[str, ...]
    creation_hash: str
    style_hash: str
    superseded_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContractHistoryPage:
    items: tuple[ConfirmedContractResult, ...]
    next_before_revision: int | None


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


class ContractDraftService:
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
                "chapterWordRangePreference", "prohibitedDirections",
                "experienceCardRefs", "corpusSourceRefs", "likes", "dislikes",
            ):
                if isinstance(raw.get(key), list):
                    raw[key] = tuple(raw[key])
            if isinstance(raw.get("corpusSourceRefs"), tuple):
                raw["corpusSourceRefs"] = tuple(
                    {
                        **source,
                        "fragments": tuple(source.get("fragments") or ()),
                    }
                    for source in raw["corpusSourceRefs"]
                )
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
            head = await self.repository.lock_contract_head(
                session, command.project_id
            )
            if head is None:
                raise ContractPreconditionFailed()
            if int(head["revision"]) > 0:
                raise ContractAlreadyConfirmed()
            if current is None and command.expected_draft_version != 0:
                raise ContractConflict()
            if (
                current is not None
                and int(current["draft_version"]) != command.expected_draft_version
            ):
                raise ContractConflict()
            selected = await self.repository.lock_selected_seed(
                session, command.project_id
            )
            if selected is None:
                raise ContractPreconditionFailed()
            binding = await self.repository.lock_binding_snapshot(
                session, command.project_id
            )
            model_binding_ref = None
            if binding is not None:
                binding_items = self._binding_items(binding)
                if (
                    tuple(item.task_key for item in binding_items) != TASK_KEYS
                    or not self._binding_integrity(binding_items, binding)
                ):
                    raise ContractPreconditionFailed()
                model_binding_ref = ModelBindingRef(
                    id=binding["binding_revision_id"],
                    revision=int(binding["revision"]),
                    contentHash=binding["content_hash"],
                )
            persisted_draft = ContractDraftPayload(
                **command.draft.model_dump(mode="python"),
                seedRevisionId=selected["seed_revision_id"],
                seedHash=selected["seed_hash"],
                modelBindingRef=model_binding_ref,
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
            result = self._draft_result(row)
            engine = await self.repository.read_engine_option(
                session, project_id, result.draft.engineOptionId
            )
            primary = (
                await self.repository.read_style_revision(
                    session, result.draft.primaryStyleRef.id
                )
                if result.draft.primaryStyleRef else None
            )
            secondary = (
                await self.repository.read_style_revision(
                    session, result.draft.secondaryStyleRef.id
                )
                if result.draft.secondaryStyleRef else None
            )
        return replace(
            result,
            document_projection=self._document_projection(
                result, engine, primary, secondary
            ),
        )

    @staticmethod
    def _project_engine(result, row):
        if row is None:
            return None
        try:
            payload = _strict_engine(row["payload_json"])
            exact = (
                row.get("id") == result.draft.engineOptionId
                and row.get("project_id") == result.project_id
                and row.get("content_hash") == result.draft.engineHash
                and canonical_hash(payload) == result.draft.engineHash
                and row.get("status") == "succeeded"
                and int(row.get("selection_revision") or 0)
                    == result.selection_revision
                and row.get("seed_revision_id")
                    == result.draft.seedRevisionId
                and row.get("seed_hash") == result.draft.seedHash
            )
            return payload if exact else None
        except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
            return None

    @staticmethod
    def _project_style(row, reference):
        if row is None or reference is None:
            return None
        try:
            payload = _json_object(row["payload_json"])
            exact = (
                row.get("id") == reference.id
                and int(row.get("revision") or 0) == reference.revision
                and row.get("content_hash") == reference.contentHash
                and canonical_hash(payload) == reference.contentHash
            )
            if not exact:
                return None
            return ContractStyleDisplay(
                id=reference.id,
                revision=reference.revision,
                content_hash=reference.contentHash,
                name=str(row["name"]),
                reading_experience=str(payload["reading_experience"]),
                narrative_distance=str(payload["narrative_distance"]),
                sentence_paragraph_rhythm=str(payload["rhythm"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    @classmethod
    def _document_projection(cls, result, engine, primary, secondary):
        selected_engine = cls._project_engine(result, engine)
        primary_style = cls._project_style(
            primary, result.draft.primaryStyleRef
        )
        secondary_style = cls._project_style(
            secondary, result.draft.secondaryStyleRef
        )
        reasons = []
        if selected_engine is None:
            reasons.append("engine_identity_unavailable")
        if result.draft.primaryStyleRef is not None and primary_style is None:
            reasons.append("primary_style_identity_unavailable")
        if result.draft.secondaryStyleRef is not None and secondary_style is None:
            reasons.append("secondary_style_identity_unavailable")
        return ContractDraftDocumentProjection(
            selected_engine=selected_engine,
            primary_style=primary_style,
            secondary_style=secondary_style,
            unavailable_reasons=tuple(reasons),
        )

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

__all__ = (
    "AssetRevisionRef", "BindingContractRef", "ConfirmContracts",
    "ConfirmedContractResult", "ContractAlreadyConfirmed", "ContractConflict", "ContractDraftIncomplete",
    "ContractDraftDocumentProjection", "ContractDraftInput", "ContractDraftPayload", "ContractDraftResult",
    "ContractHistoryPage",
    "ContractDraftService", "ContractNotFound", "ContractPreconditionFailed",
    "CorpusSourceRef", "EngineContractRef", "ModelBindingRef",
    "ResolvedAssetRef", "ResolvedCorpusFragment", "ResolvedCorpusRef",
    "ResolvedStyleRef", "ContractStyleDisplay", "SaveContractDraft", "SeedContractRef",
)
