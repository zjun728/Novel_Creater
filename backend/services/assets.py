"""Release-only validation, planning, and atomic immutable asset seeding."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from backend.domain.asset_eligibility import (
    CreationStage,
    Genre,
    ProhibitedDirection,
)
from backend.domain.asset_recommendations import (
    AssetCandidateSummary,
    AssetRecommendationScope,
    ProviderRankingOutput,
    RecommendationInputError,
    SelectedStyleCandidate,
    StyleRevisionRef,
    filter_eligible_candidates,
)
from backend.domain.assets import (
    AssetInventory,
    AssetPackage,
    AssetPackageError,
    ExperienceCardRevision,
    StyleTemplateRevision,
    validate_asset_inventory,
    validate_asset_package,
)
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.seeds import SeedPayload, decode_seed_revision
from backend.domain.provider_policy import provider_is_generation_ready
from backend.gateways.asset_recommendation_provider import (
    AssetRecommendationProviderError,
)
from backend.http_errors import (
    AssetCatalogNotReady,
    AssetNotFound,
    AssetRecommendationConflict,
    AssetRecommendationInProgress,
)
from backend.prompts.asset_recommendation import (
    build_asset_recommendation_messages,
)


AssetType = Literal["style", "card"]
ActionName = Literal["insert", "replay", "advance"]


class AssetSeedConflict(RuntimeError):
    """The database cannot be reconciled with the approved immutable package."""


@dataclass(frozen=True)
class AssetSeedReport:
    package_version: str
    package_hash: str
    style_count: int
    card_count: int
    inserted: int
    replayed: int
    advanced: int


@dataclass(frozen=True)
class _Action:
    asset_type: AssetType
    asset: object
    name: ActionName
    head: dict | None


def _json_document(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalized_json(value: object) -> object:
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


class AssetSeedService:
    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        connection_factory=None,
        id_factory=None,
        clock=None,
    ) -> None:
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.clock = clock or (lambda: int(time.time() * 1000))

    @staticmethod
    def _validated(package: AssetPackage) -> AssetPackage:
        return validate_asset_package(package, mode="release")

    @staticmethod
    def _collections(package: AssetPackage):
        return (
            ("style", tuple(sorted(package.styles, key=lambda row: row.stable_key))),
            (
                "card",
                tuple(sorted(package.experience_cards, key=lambda row: row.stable_key)),
            ),
        )

    @staticmethod
    def _row_values(asset_type: AssetType, asset) -> dict:
        return {
            "stable_key": asset.stable_key,
            "revision": int(asset.revision),
            "label": asset.name if asset_type == "style" else asset.title,
            "category": None if asset_type == "style" else asset.category,
            "payload_json": _json_document(asset.payload.model_dump(mode="json")),
            "provenance_json": _json_document(
                asset.provenance.model_dump(mode="json")
            ),
            "content_hash": asset.content_hash,
        }

    @classmethod
    def _same_immutable_row(cls, asset_type: AssetType, asset, row: dict) -> bool:
        expected = cls._row_values(asset_type, asset)
        actual = {
            "stable_key": row.get("stable_key"),
            "revision": int(row.get("revision") or 0),
            "label": row.get("label"),
            "category": row.get("category"),
            "payload_json": _json_document(_normalized_json(row.get("payload_json"))),
            "provenance_json": _json_document(
                _normalized_json(row.get("provenance_json"))
            ),
            "content_hash": row.get("content_hash"),
        }
        return actual == expected

    async def _actions(self, session, package: AssetPackage, *, for_update: bool):
        collections = self._collections(package)
        head_rows = {
            asset_type: await self.repository.list_heads(
                session, asset_type, for_update=for_update
            )
            for asset_type, _ in collections
        }

        first_seed = all(not rows for rows in head_rows.values())
        for asset_type, assets in collections:
            heads = head_rows[asset_type]
            keys = {asset.stable_key for asset in assets}
            existing = {row["stable_key"] for row in heads}
            if not first_seed and existing != keys:
                raise AssetSeedConflict(
                    f"{asset_type} head set differs from approved package"
                )

        actions: list[_Action] = []
        for asset_type, assets in collections:
            heads = {row["stable_key"]: row for row in head_rows[asset_type]}
            for asset in assets:
                head = heads.get(asset.stable_key)
                history = await self.repository.list_revisions_for_key(
                    session,
                    asset_type,
                    asset.stable_key,
                    for_update=for_update,
                )
                if head is None:
                    if asset.revision != 1:
                        raise AssetSeedConflict(
                            f"{asset_type}:{asset.stable_key} must begin at revision 1"
                        )
                    if history:
                        raise AssetSeedConflict(
                            f"{asset_type}:{asset.stable_key} orphan history exists"
                        )
                    actions.append(_Action(asset_type, asset, "insert", None))
                    continue

                head_revision = int(head["revision"])
                revisions = [int(row.get("revision") or 0) for row in history]
                if revisions != list(range(1, head_revision + 1)):
                    raise AssetSeedConflict(
                        f"{asset_type}:{asset.stable_key} revision history is invalid"
                    )
                for row in history:
                    revision = int(row.get("revision") or 0)
                    expected_status = (
                        "active" if revision == head_revision else "archived"
                    )
                    if (
                        row.get("stable_key") != asset.stable_key
                        or row.get("status") != expected_status
                    ):
                        raise AssetSeedConflict(
                            f"{asset_type}:{asset.stable_key} revision history is invalid"
                        )
                current_identity = history[-1]
                if (
                    current_identity.get("id") != head.get("id")
                    or int(current_identity.get("revision") or 0) != head_revision
                    or current_identity.get("content_hash")
                    != head.get("content_hash")
                ):
                    raise AssetSeedConflict(
                        f"{asset_type}:{asset.stable_key} head revision is invalid"
                    )
                if asset.revision == head_revision:
                    current = await self.repository.fetch_revision(
                        session, asset_type, asset.stable_key, head_revision
                    )
                    if current is None:
                        raise AssetSeedConflict(
                            f"{asset_type}:{asset.stable_key} head revision is invalid"
                        )
                    if not self._same_immutable_row(asset_type, asset, current):
                        raise AssetSeedConflict(
                            f"{asset_type}:{asset.stable_key} immutable revision differs"
                        )
                    actions.append(_Action(asset_type, asset, "replay", head))
                elif asset.revision == head_revision + 1:
                    actions.append(_Action(asset_type, asset, "advance", head))
                else:
                    raise AssetSeedConflict(
                        f"{asset_type}:{asset.stable_key} must use the next revision"
                    )
        return tuple(actions)

    @staticmethod
    def _report(package: AssetPackage, actions: tuple[_Action, ...]) -> AssetSeedReport:
        counts = {
            name: sum(action.name == name for action in actions)
            for name in ("insert", "replay", "advance")
        }
        return AssetSeedReport(
            package_version=package.package_version,
            package_hash=canonical_hash(package.manifest),
            style_count=len(package.styles),
            card_count=len(package.experience_cards),
            inserted=counts["insert"],
            replayed=counts["replay"],
            advanced=counts["advance"],
        )

    async def dry_run(self, package: AssetPackage) -> AssetSeedReport:
        package = self._validated(package)
        if self.connection_factory is None:
            raise RuntimeError("read connection factory is not configured")
        async with self.connection_factory() as session:
            actions = await self._actions(session, package, for_update=False)
        return self._report(package, actions)


    async def seed(self, package: AssetPackage) -> AssetSeedReport:
        package = self._validated(package)
        if self.transaction_factory is None:
            raise RuntimeError("transaction factory is not configured")
        async with self.transaction_factory() as session:
            await self.repository.lock_schema_guard(session)
            actions = await self._actions(session, package, for_update=True)
            for action in actions:
                if action.name == "replay":
                    continue
                asset = action.asset
                now = self.clock()
                row = {
                    **self._row_values(action.asset_type, asset),
                    "id": self.id_factory(),
                    "status": "active",
                    "created_at": now,
                }
                await self.repository.insert_revision(
                    session, action.asset_type, row
                )
                head = {
                    "stable_key": asset.stable_key,
                    "id": row["id"],
                    "revision": asset.revision,
                    "content_hash": asset.content_hash,
                    "updated_at": now,
                }
                if action.name == "insert":
                    await self.repository.insert_head(
                        session, action.asset_type, head
                    )
                    continue
                assert action.head is not None
                if await self.repository.archive_revision(
                    session, action.asset_type, action.head["id"]
                ) != 1:
                    raise AssetSeedConflict("previous active asset revision changed")
                if await self.repository.move_head(
                    session,
                    action.asset_type,
                    head,
                    expected=action.head,
                ) != 1:
                    raise AssetSeedConflict("asset head changed during seed")
        return self._report(package, actions)


@dataclass(frozen=True)
class AssetRecord:
    id: str
    status: str
    asset: StyleTemplateRevision | ExperienceCardRevision


def _json_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8")
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("database JSON document must be an object")
    return value


class AssetReadService:
    """Read immutable approved assets using one explicit connection session."""

    def __init__(self, repository, *, transaction_factory) -> None:
        self.repository = repository
        self.transaction_factory = transaction_factory

    def _transaction(self):
        if self.transaction_factory is None:
            raise RuntimeError("read transaction factory is not configured")
        return self.transaction_factory()

    @staticmethod
    def _record(asset_type: AssetType, row: Mapping) -> AssetRecord:
        if row.get("status") not in ("active", "archived"):
            raise ValueError("asset revision status is invalid")
        values = {
            "stable_key": row["stable_key"],
            "revision": int(row["revision"]),
            "name" if asset_type == "style" else "title": row["label"],
            "payload": _json_mapping(row["payload_json"]),
            "provenance": _json_mapping(row["provenance_json"]),
            "content_hash": row["content_hash"],
        }
        if asset_type == "card":
            values["category"] = row["category"]
            asset = ExperienceCardRevision.model_validate(values)
        else:
            asset = StyleTemplateRevision.model_validate(values)
        if canonical_hash(asset.payload) != asset.content_hash:
            raise ValueError("asset payload hash mismatch")
        return AssetRecord(id=row["id"], status=row["status"], asset=asset)

    @classmethod
    def _validated_catalog(cls, style_rows, card_rows):
        try:
            styles = tuple(
                sorted(
                    (cls._record("style", row) for row in style_rows),
                    key=lambda record: record.asset.stable_key,
                )
            )
            cards = tuple(
                sorted(
                    (cls._record("card", row) for row in card_rows),
                    key=lambda record: record.asset.stable_key,
                )
            )
            inventory = validate_asset_inventory(
                AssetInventory(
                    styles=tuple(record.asset for record in styles),
                    experience_cards=tuple(record.asset for record in cards),
                ),
                mode="release",
            )
            return styles, cards, inventory
        except (AssetPackageError, ValidationError, ValueError, TypeError, KeyError):
            raise AssetCatalogNotReady() from None

    async def _catalog(self, session):
        style_rows = await self.repository.list_active_revisions(
            session, "style"
        )
        card_rows = await self.repository.list_active_revisions(
            session, "card"
        )
        return self._validated_catalog(style_rows, card_rows)

    async def _current_head_catalog(self, session):
        style_rows = await self.repository.list_current_revisions(
            session, "style"
        )
        card_rows = await self.repository.list_current_revisions(
            session, "card"
        )
        return self._validated_catalog(style_rows, card_rows)

    async def list_styles(self) -> tuple[AssetRecord, ...]:
        styles, _ = await self.catalog()
        return styles

    async def list_cards(self, category=None) -> tuple[AssetRecord, ...]:
        _, cards = await self.catalog()
        if category is not None:
            cards = tuple(
                record for record in cards if record.asset.category == category
            )
        return cards

    async def catalog(
        self,
    ) -> tuple[tuple[AssetRecord, ...], tuple[AssetRecord, ...]]:
        """Return one validated seeded-head snapshot for composition services."""

        async with self._transaction() as session:
            styles, cards, _ = await self._catalog(session)
        return styles, cards

    async def current_head_catalog(
        self,
    ) -> tuple[tuple[AssetRecord, ...], tuple[AssetRecord, ...]]:
        """Return the current head of every approved stable key."""

        async with self._transaction() as session:
            styles, cards, _ = await self._current_head_catalog(session)
        return styles, cards

    async def _detail(self, asset_type: AssetType, revision_id: str) -> AssetRecord:
        async with self._transaction() as session:
            row = await self.repository.fetch_revision_by_id(
                session, asset_type, revision_id
            )
        if row is None:
            raise AssetNotFound()
        try:
            status = row["status"]
        except (TypeError, KeyError):
            raise AssetCatalogNotReady() from None
        if status not in ("active", "archived"):
            raise AssetNotFound()
        try:
            record = self._record(asset_type, row)
        except (ValidationError, ValueError, TypeError, KeyError):
            raise AssetCatalogNotReady() from None
        if (
            record.asset.provenance.decision != "approved"
            or record.asset.provenance.reviewer is None
            or record.asset.provenance.review_time is None
        ):
            raise AssetNotFound()
        return record

    async def get_style(self, revision_id: str) -> AssetRecord:
        return await self._detail("style", revision_id)

    async def get_card(self, revision_id: str) -> AssetRecord:
        return await self._detail("card", revision_id)

    @staticmethod
    def _recommendation_inputs(selected: Mapping, engine: Mapping):
        if engine.get("batch_status") != "succeeded":
            raise AssetRecommendationConflict()
        if engine.get("selection_revision") != selected.get("selection_revision"):
            raise AssetRecommendationConflict()
        if any(
            engine.get(field) != selected.get(field)
            for field in ("seed_id", "seed_revision_id", "seed_hash")
        ):
            raise AssetRecommendationConflict()
        try:
            seed = decode_seed_revision(selected["payload_json"])[0]
            engine_payload = _json_mapping(engine["payload_json"])
            if canonical_hash(seed) != selected["seed_hash"]:
                raise ValueError("selected seed hash mismatch")
            revision_hash = selected.get("revision_hash")
            if revision_hash is not None and revision_hash != selected["seed_hash"]:
                raise ValueError("selected seed revision hash mismatch")
            if canonical_hash(engine_payload) != engine["content_hash"]:
                raise ValueError("engine option hash mismatch")
        except (ValidationError, ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
            raise AssetRecommendationConflict() from None
        return seed, engine_payload

ASSET_RECOMMENDATION_POLICY_VERSION = "asset-recommendation-policy-v2"
ASSET_RECOMMENDATION_CONFIDENCE_THRESHOLD = 0.70
_NO_CANDIDATES = "ASSET_RECOMMENDATION_NO_CANDIDATES"
_UNAVAILABLE = "ASSET_RECOMMENDATION_UNAVAILABLE"
_RECOMMENDATION_STALE_AFTER_MS = 240_000


class _StrictRecommendationModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class GenerateAssetRecommendations(_StrictRecommendationModel):
    project_id: str = Field(min_length=1, max_length=36)
    engine_option_id: str = Field(min_length=1, max_length=36)
    idempotency_key: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]{64}$",
    )
    taxonomy_version: str = Field(min_length=1, max_length=64)
    taxonomy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    genre: Genre
    creation_stage: CreationStage
    status: Literal["active", "archived"]
    prohibited_directions: tuple[ProhibitedDirection, ...] = Field(
        default=(),
        max_length=7,
    )

    @field_validator("prohibited_directions", mode="before")
    @classmethod
    def freeze_prohibited_directions(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @field_validator("prohibited_directions")
    @classmethod
    def unique_prohibited_directions(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("prohibited directions must be unique")
        return value


class AcceptedAssetRecommendation(_StrictRecommendationModel):
    asset_revision_id: str = Field(min_length=1, max_length=36)
    asset_type: Literal["style", "experience_card"]
    stable_key: str = Field(min_length=1, max_length=160)
    revision: int = Field(gt=0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=160)
    confidence: float = Field(ge=0, le=1)


class AcceptedCorpusRecommendation(_StrictRecommendationModel):
    source_id: str = Field(min_length=1, max_length=36)
    source_revision: int = Field(gt=0)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    chapter_id: str = Field(min_length=1, max_length=36)
    fragment_id: str = Field(min_length=1, max_length=36)
    fragment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    range_start: int = Field(ge=0)
    range_end: int = Field(gt=0)
    use: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=160)
    confidence: float = Field(ge=0, le=1)


class AssetRecommendationAttemptResult(_StrictRecommendationModel):
    attempt_id: str | None
    public_reason: Literal[
        "recommendationsAvailable",
        "noEligibleCandidates",
        "rankingUnavailable",
    ]
    ranking_unavailable: bool
    full_browse_available: Literal[True] = True
    asset_recommendations: tuple[AcceptedAssetRecommendation, ...]
    corpus_recommendations: tuple[AcceptedCorpusRecommendation, ...]
    input_manifest: dict | None
    input_manifest_hash: str | None
    result_hash: str | None


def _empty_recommendation(
    public_reason: Literal["noEligibleCandidates", "rankingUnavailable"],
) -> AssetRecommendationAttemptResult:
    return AssetRecommendationAttemptResult(
        attempt_id=None,
        public_reason=public_reason,
        ranking_unavailable=public_reason == "rankingUnavailable",
        full_browse_available=True,
        asset_recommendations=(),
        corpus_recommendations=(),
        input_manifest=None,
        input_manifest_hash=None,
        result_hash=None,
    )


class AssetRecommendationService:
    """Idempotently rank eligible assets with one provider call outside SQL."""

    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        connection_factory,
        provider_gateway,
        corpus_service,
        taxonomy,
        id_factory=None,
        clock=None,
    ) -> None:
        self.repository = repository
        self._transaction = transaction_factory
        self._connection = connection_factory
        self._gateway = provider_gateway
        self._corpus = corpus_service
        self.taxonomy = taxonomy
        self._id = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))

    @staticmethod
    def _request_hash(command: GenerateAssetRecommendations) -> str:
        return canonical_hash({
            "projectId": command.project_id,
            "engineOptionId": command.engine_option_id,
            "taxonomyVersion": command.taxonomy_version,
            "taxonomyHash": command.taxonomy_hash,
            "genre": command.genre,
            "creationStage": command.creation_stage,
            "status": command.status,
            "prohibitedDirections": list(command.prohibited_directions),
            "policyVersion": ASSET_RECOMMENDATION_POLICY_VERSION,
        })

    @staticmethod
    def _provider_ready(inputs: dict) -> bool:
        provider = inputs.get("provider")
        return bool(
            isinstance(provider, dict)
            and inputs.get("resolution_status") == "bound"
            and inputs.get("provider_id") == provider.get("id")
            and inputs.get("model_name_snapshot") == provider.get("model_name")
            and type(provider.get("revision")) is int
            and provider["revision"] >= 0
            and provider_is_generation_ready(provider)
        )

    @staticmethod
    def _generation_config(provider: dict) -> dict:
        temperature = float(provider["temperature"])
        max_tokens = int(provider["max_output_tokens"])
        if not math.isfinite(temperature) or temperature < 0 or max_tokens <= 0:
            raise ValueError("provider generation configuration is invalid")
        return {"temperature": temperature, "maxOutputTokens": max_tokens}

    @staticmethod
    def _candidate(record: AssetRecord) -> AssetCandidateSummary:
        asset = record.asset
        if isinstance(asset, StyleTemplateRevision):
            facts = "；".join((
                asset.payload.reading_experience,
                *asset.payload.applicability,
                *asset.payload.non_applicability,
            ))[:600]
            asset_type = "style"
            label = asset.name
            category = None
        else:
            facts = "；".join((
                asset.payload.method,
                *asset.payload.applicability,
                *asset.payload.non_applicability,
            ))[:600]
            asset_type = "experience_card"
            label = asset.title
            category = asset.category
        return AssetCandidateSummary(
            asset_revision_id=record.id,
            asset_type=asset_type,
            stable_key=asset.stable_key,
            revision=asset.revision,
            content_hash=asset.content_hash,
            status=record.status,
            label=label,
            category=category,
            facts=facts,
        )

    @staticmethod
    def _query_texts(seed: SeedPayload, engine: Mapping[str, object]) -> tuple[str, ...]:
        values = [getattr(seed, field) for field in SeedPayload.model_fields]
        pending = list(engine.values())
        while pending and len(values) < 20:
            value = pending.pop(0)
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, Mapping):
                pending.extend(value.values())
            elif isinstance(value, (tuple, list)):
                pending.extend(value)
        return tuple(value[:2_000] for value in values if value)[:20]

    @staticmethod
    def _selected_styles(draft: object, candidates: tuple[AssetCandidateSummary, ...]):
        document = _json_mapping(draft["draft_json"]) if draft else {
            "primaryStyleRef": None,
            "secondaryStyleRef": None,
        }
        by_id = {item.asset_revision_id: item for item in candidates}
        selected = []
        for role, field in (
            ("primary", "primaryStyleRef"),
            ("secondary", "secondaryStyleRef"),
        ):
            if field not in document:
                raise ValueError("selected style facts are invalid")
            raw_ref = document[field]
            if raw_ref is None:
                continue
            ref = StyleRevisionRef.model_validate(raw_ref, strict=True)
            candidate = by_id.get(ref.id)
            if (
                candidate is None
                or candidate.asset_type != "style"
                or candidate.revision != ref.revision
                or candidate.content_hash != ref.content_hash
            ):
                raise ValueError("selected style facts are invalid")
            selected.append(SelectedStyleCandidate(
                **candidate.model_dump(mode="python"),
                role=role,
            ))
        return tuple(selected)

    def _prepared_inputs(self, command, inputs: dict) -> dict:
        try:
            seed, engine_payload = AssetReadService._recommendation_inputs(
                inputs["selected"], inputs["engine"]
            )
            styles, cards, _ = AssetReadService._validated_catalog(
                inputs["styles"], inputs["cards"]
            )
            all_candidates = tuple(
                self._candidate(record) for record in (*styles, *cards)
            )
            scope = AssetRecommendationScope(
                genre=command.genre,
                creation_stage=command.creation_stage,
                status=command.status,
                prohibited_directions=command.prohibited_directions,
            )
            asset_candidates = filter_eligible_candidates(
                all_candidates,
                taxonomy_entries=self.taxonomy.entries,
                taxonomy_version=self.taxonomy.package_version,
                taxonomy_hash=self.taxonomy.manifest.eligibility_file.sha256,
                expected_taxonomy_version=command.taxonomy_version,
                expected_taxonomy_hash=command.taxonomy_hash,
                scope=scope,
            )
            selected_styles = self._selected_styles(
                inputs.get("draft"), all_candidates
            )
        except (
            KeyError, TypeError, ValueError, ValidationError,
            RecommendationInputError, AssetPackageError,
        ):
            raise AssetRecommendationConflict() from None
        return {
            "inputs": inputs,
            "seed": seed,
            "engine_payload": engine_payload,
            "all_candidates": all_candidates,
            "asset_candidates": asset_candidates,
            "selected_styles": selected_styles,
            "query_texts": self._query_texts(seed, engine_payload),
        }

    @staticmethod
    def _reservation_fingerprint(prepared: dict) -> str:
        inputs = prepared["inputs"]
        selected = inputs["selected"]
        engine = inputs["engine"]
        return canonical_hash({
            "selection": {
                "revision": selected["selection_revision"],
                "seedId": selected["seed_id"],
                "seedRevisionId": selected["seed_revision_id"],
                "seedHash": selected["seed_hash"],
                "revisionHash": selected["revision_hash"],
                "payload": prepared["seed"].model_dump(mode="json"),
            },
            "engine": {
                "id": engine["id"],
                "hash": engine["content_hash"],
                "batchStatus": engine["batch_status"],
                "selectionRevision": engine["selection_revision"],
                "seedId": engine["seed_id"],
                "seedRevisionId": engine["seed_revision_id"],
                "seedHash": engine["seed_hash"],
                "payload": prepared["engine_payload"],
            },
            "binding": {
                "revisionId": inputs["binding_revision_id"],
                "hash": inputs["binding_hash"],
                "resolutionStatus": inputs["resolution_status"],
                "providerId": inputs["provider_id"],
                "modelNameSnapshot": inputs["model_name_snapshot"],
            },
            "provider": inputs.get("provider"),
            "selectedStyles": [
                item.model_dump(mode="json")
                for item in prepared["selected_styles"]
            ],
            "assetFacts": [
                item.model_dump(mode="json")
                for item in prepared["all_candidates"]
            ],
            "eligibleAssetFacts": [
                item.model_dump(mode="json")
                for item in prepared["asset_candidates"]
            ],
        })

    def _manifest(
        self,
        command,
        inputs,
        asset_candidates,
        corpus_candidates,
        selected_styles,
    ) -> dict:
        selected = inputs["selected"]
        engine = inputs["engine"]
        provider = inputs["provider"]
        return {
            "selection": {
                "revision": int(selected["selection_revision"]),
                "seedRevisionId": selected["seed_revision_id"],
                "hash": selected["seed_hash"],
            },
            "engine": {"id": engine["id"], "hash": engine["content_hash"]},
            "binding": {
                "revisionId": inputs["binding_revision_id"],
                "hash": inputs["binding_hash"],
                "taskKey": "seed",
            },
            "provider": {
                "providerId": provider["id"],
                "modelName": provider["model_name"],
                "providerProfileRevision": int(provider["revision"]),
                "providerType": provider["provider_type"],
            },
            "taxonomy": {
                "version": command.taxonomy_version,
                "hash": command.taxonomy_hash,
            },
            "scope": {
                "genre": command.genre,
                "creationStage": command.creation_stage,
                "status": command.status,
                "prohibitedDirections": list(command.prohibited_directions),
            },
            "selectedStyles": [{
                "role": item.role,
                "id": item.asset_revision_id,
                "revision": item.revision,
                "hash": item.content_hash,
            } for item in selected_styles],
            "assetCandidates": [{
                "id": item.asset_revision_id,
                "type": item.asset_type,
                "revision": item.revision,
                "hash": item.content_hash,
            } for item in asset_candidates],
            "corpusCandidates": [{
                "sourceId": item.source_id,
                "sourceRevisionId": item.source_revision_id,
                "sourceRevision": item.source_revision,
                "sourceHash": item.source_hash,
                "chapterId": item.chapter_id,
                "fragmentId": item.fragment_id,
                "fragmentHash": item.fragment_hash,
                "windowStart": item.window_start,
                "windowEnd": item.window_end,
            } for item in corpus_candidates],
            "policyVersion": ASSET_RECOMMENDATION_POLICY_VERSION,
        }

    @staticmethod
    def _accepted(
        output: ProviderRankingOutput,
        asset_candidates,
        corpus_candidates,
    ):
        choices = (
            *output.asset_recommendations,
            *output.corpus_recommendations,
        )
        if not choices or any(
            item.confidence < ASSET_RECOMMENDATION_CONFIDENCE_THRESHOLD
            for item in choices
        ):
            raise ValueError("asset ranking confidence is insufficient")
        assets = {item.asset_revision_id: item for item in asset_candidates}
        corpus = {item.fragment_id: item for item in corpus_candidates}
        accepted_assets = []
        for item in output.asset_recommendations:
            candidate = assets.get(item.asset_revision_id)
            if candidate is None:
                raise ValueError("asset ranking references an unknown candidate")
            accepted_assets.append(AcceptedAssetRecommendation(
                asset_revision_id=candidate.asset_revision_id,
                asset_type=candidate.asset_type,
                stable_key=candidate.stable_key,
                revision=candidate.revision,
                content_hash=candidate.content_hash,
                reason=item.reason,
                confidence=item.confidence,
            ))
        accepted_corpus = []
        for item in output.corpus_recommendations:
            candidate = corpus.get(item.fragment_id)
            if (
                candidate is None
                or not candidate.window_start <= item.range_start
                or not item.range_start < item.range_end <= candidate.window_end
            ):
                raise ValueError("corpus ranking range is invalid")
            accepted_corpus.append(AcceptedCorpusRecommendation(
                source_id=candidate.source_id,
                source_revision=candidate.source_revision,
                source_hash=candidate.source_hash,
                chapter_id=candidate.chapter_id,
                fragment_id=candidate.fragment_id,
                fragment_hash=candidate.fragment_hash,
                range_start=item.range_start,
                range_end=item.range_end,
                use=item.use,
                reason=item.reason,
                confidence=item.confidence,
            ))
        return tuple(accepted_assets), tuple(accepted_corpus)

    @staticmethod
    def _stored_result(result: AssetRecommendationAttemptResult) -> dict:
        return {
            "assetRecommendations": [
                item.model_dump(mode="json")
                for item in result.asset_recommendations
            ],
            "corpusRecommendations": [
                item.model_dump(mode="json")
                for item in result.corpus_recommendations
            ],
        }

    @classmethod
    def _success_from_attempt(cls, attempt: Mapping) -> AssetRecommendationAttemptResult:
        result = attempt["result_json"]
        manifest = attempt["input_manifest_json"]
        if isinstance(result, str):
            result = json.loads(result)
        if isinstance(manifest, str):
            manifest = json.loads(manifest)
        return AssetRecommendationAttemptResult(
            attempt_id=attempt["id"],
            public_reason="recommendationsAvailable",
            ranking_unavailable=False,
            full_browse_available=True,
            asset_recommendations=tuple(
                AcceptedAssetRecommendation.model_validate(item, strict=True)
                for item in result["assetRecommendations"]
            ),
            corpus_recommendations=tuple(
                AcceptedCorpusRecommendation.model_validate(item, strict=True)
                for item in result["corpusRecommendations"]
            ),
            input_manifest=manifest,
            input_manifest_hash=attempt["input_manifest_hash"],
            result_hash=attempt["result_hash"],
        )

    async def _terminal_empty(self, command, context, code):
        async with self._transaction() as session:
            await self.repository.fail_recommendation(
                session,
                project_id=command.project_id,
                idempotency_key=command.idempotency_key,
                attempt_id=context["attempt"]["id"],
                public_error_code=code,
                completed_at=self._clock(),
            )
        return _empty_recommendation(
            "noEligibleCandidates" if code == _NO_CANDIDATES
            else "rankingUnavailable"
        )

    async def _cleanup_cancelled_reservation(
        self,
        command,
        request_hash: str,
    ) -> bool:
        async with self._transaction() as session:
            return await self.repository.cleanup_cancelled_recommendation(
                session,
                project_id=command.project_id,
                idempotency_key=command.idempotency_key,
                request_hash=request_hash,
                public_error_code=_UNAVAILABLE,
                completed_at=self._clock(),
            )

    @staticmethod
    async def _wait_for_cleanup(task: asyncio.Task):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.done():
                    continue
        return task.result()

    async def _finish_cancellation(
        self,
        command,
        request_hash: str,
        cancellation: asyncio.CancelledError,
    ) -> None:
        cleanup_task = asyncio.create_task(
            self._cleanup_cancelled_reservation(command, request_hash)
        )
        try:
            await self._wait_for_cleanup(cleanup_task)
        except BaseException as cleanup_error:
            raise BaseExceptionGroup(
                "asset recommendation cancellation cleanup also failed",
                [cancellation, cleanup_error],
            ) from cancellation
        raise cancellation

    async def _replay(self, session, command, request_hash, existing):
        if existing["request_hash"] != request_hash:
            raise AssetRecommendationConflict()
        status = existing["status"]
        if status == "succeeded":
            attempt = await self.repository.read_recommendation_attempt(
                session, command.project_id, existing["attempt_id"]
            )
            return self._success_from_attempt(attempt)
        if status in {"failed", "outcome_unknown"}:
            code = existing.get("public_error_code")
            return _empty_recommendation(
                "noEligibleCandidates" if code == _NO_CANDIDATES
                else "rankingUnavailable"
            )
        if status != "running" or not existing.get("attempt_id"):
            raise RuntimeError("asset recommendation request state is invalid")
        attempt = await self.repository.read_recommendation_attempt(
            session, command.project_id, existing["attempt_id"]
        )
        if attempt is None or attempt["status"] != "running":
            raise RuntimeError("asset recommendation attempt state is invalid")
        if self._clock() - int(attempt["created_at"]) < _RECOMMENDATION_STALE_AFTER_MS:
            raise AssetRecommendationInProgress()
        await self.repository.mark_recommendation_outcome_unknown(
            session,
            project_id=command.project_id,
            idempotency_key=command.idempotency_key,
            attempt_id=attempt["id"],
            public_error_code=_UNAVAILABLE,
            completed_at=self._clock(),
        )
        return _empty_recommendation("rankingUnavailable")

    async def _complete_reserved_recommendation(
        self,
        command,
        request_hash: str,
        context: dict,
    ) -> AssetRecommendationAttemptResult:
        try:
            messages = build_asset_recommendation_messages(
                selection={
                    "selectionRevision": context["inputs"]["selected"][
                        "selection_revision"
                    ],
                    "seedRevisionId": context["inputs"]["selected"][
                        "seed_revision_id"
                    ],
                    "seedHash": context["inputs"]["selected"]["seed_hash"],
                    "seed": context["seed"].model_dump(mode="json"),
                },
                engine={
                    "id": context["inputs"]["engine"]["id"],
                    "hash": context["inputs"]["engine"]["content_hash"],
                    "payload": context["engine_payload"],
                },
                selected_styles=context["selected_styles"],
                asset_candidates=context["asset_candidates"],
                corpus_candidates=context["corpus_candidates"],
            )
            output = await self._gateway.rank(
                provider=context["provider"],
                messages=messages,
                generation_config=self._generation_config(context["provider"]),
            )
            accepted_assets, accepted_corpus = self._accepted(
                output,
                context["asset_candidates"],
                context["corpus_candidates"],
            )
        except (AssetRecommendationProviderError, ValueError, TypeError, KeyError):
            return await self._terminal_empty(command, context, _UNAVAILABLE)

        provisional = AssetRecommendationAttemptResult(
            attempt_id=context["attempt"]["id"],
            public_reason="recommendationsAvailable",
            ranking_unavailable=False,
            full_browse_available=True,
            asset_recommendations=accepted_assets,
            corpus_recommendations=accepted_corpus,
            input_manifest=context["manifest"],
            input_manifest_hash=context["attempt"]["input_manifest_hash"],
            result_hash=None,
        )
        stored = self._stored_result(provisional)
        result_hash = canonical_hash(stored)
        completed_at = self._clock()
        async with self._transaction() as session:
            published = await self.repository.publish_recommendation(
                session,
                project_id=command.project_id,
                idempotency_key=command.idempotency_key,
                request_hash=request_hash,
                attempt_id=context["attempt"]["id"],
                selection_revision=context["attempt"]["selection_revision"],
                binding_revision_id=context["attempt"]["binding_revision_id"],
                binding_hash=context["attempt"]["binding_hash"],
                input_manifest=context["manifest"],
                result_json=canonical_json(stored),
                result_hash=result_hash,
                completed_at=completed_at,
            )
        if not published:
            return _empty_recommendation("rankingUnavailable")
        return provisional.model_copy(update={"result_hash": result_hash})

    async def recommend(
        self,
        command: GenerateAssetRecommendations,
    ) -> AssetRecommendationAttemptResult:
        request_hash = self._request_hash(command)
        context: dict = {}
        async with self._transaction() as session:
            project = await self.repository.lock_recommendation_project(
                session, command.project_id
            )
            if project is None:
                raise AssetNotFound()
            existing = await self.repository.lock_recommendation_request(
                session, command.project_id, command.idempotency_key
            )
            if existing is not None:
                return await self._replay(
                    session, command, request_hash, existing
                )
            inputs = await self.repository.lock_recommendation_inputs(
                session, command.project_id, command.engine_option_id
            )
            prepared = self._prepared_inputs(command, inputs)
            fingerprint = self._reservation_fingerprint(prepared)
            if not self._provider_ready(inputs):
                completed_at = self._clock()
                request = {
                    "id": self._id(),
                    "project_id": command.project_id,
                    "idempotency_key": command.idempotency_key,
                    "request_hash": request_hash,
                    "status": "failed",
                    "attempt_id": None,
                    "result_hash": None,
                    "public_error_code": _UNAVAILABLE,
                    "created_at": completed_at,
                    "completed_at": completed_at,
                }
                await self.repository.insert_failed_recommendation_request(
                    session, request
                )
                return _empty_recommendation("rankingUnavailable")

        corpus_candidates = await self._corpus.candidates(
            prepared["query_texts"]
        )
        async with self._transaction() as session:
            project = await self.repository.lock_recommendation_project(
                session, command.project_id
            )
            if project is None:
                raise AssetNotFound()
            existing = await self.repository.lock_recommendation_request(
                session, command.project_id, command.idempotency_key
            )
            if existing is not None:
                return await self._replay(
                    session, command, request_hash, existing
                )
            locked_inputs = await self.repository.lock_recommendation_inputs(
                session, command.project_id, command.engine_option_id
            )
            try:
                locked_prepared = self._prepared_inputs(command, locked_inputs)
            except AssetCatalogNotReady:
                raise AssetRecommendationConflict() from None
            if self._reservation_fingerprint(locked_prepared) != fingerprint:
                raise AssetRecommendationConflict()
            if not self._provider_ready(locked_inputs):
                raise AssetRecommendationConflict()
            prepared = locked_prepared
            inputs = locked_inputs
            asset_candidates = prepared["asset_candidates"]
            selected_styles = prepared["selected_styles"]
            seed = prepared["seed"]
            engine_payload = prepared["engine_payload"]
            created_at = self._clock()
            request_id = self._id()
            if not asset_candidates and not corpus_candidates:
                request = {
                    "id": request_id,
                    "project_id": command.project_id,
                    "idempotency_key": command.idempotency_key,
                    "request_hash": request_hash,
                    "status": "failed",
                    "attempt_id": None,
                    "result_hash": None,
                    "public_error_code": _NO_CANDIDATES,
                    "created_at": created_at,
                    "completed_at": created_at,
                }
                await self.repository.insert_failed_recommendation_request(
                    session, request
                )
                return _empty_recommendation("noEligibleCandidates")
            manifest = self._manifest(
                command, inputs, asset_candidates, corpus_candidates,
                selected_styles,
            )
            attempt = {
                "id": self._id(),
                "project_id": command.project_id,
                "selection_revision": int(
                    inputs["selected"]["selection_revision"]
                ),
                "binding_revision_id": inputs["binding_revision_id"],
                "binding_hash": inputs["binding_hash"],
                "input_manifest_json": canonical_json(manifest),
                "input_manifest_hash": canonical_hash(manifest),
                "status": "running",
                "result_json": None,
                "result_hash": None,
                "public_error_code": None,
                "created_at": created_at,
                "completed_at": None,
            }
            request = {
                "id": request_id,
                "project_id": command.project_id,
                "idempotency_key": command.idempotency_key,
                "request_hash": request_hash,
                "status": "running",
                "attempt_id": attempt["id"],
                "result_hash": None,
                "public_error_code": None,
                "created_at": created_at,
                "completed_at": None,
            }
            await self.repository.insert_recommendation_attempt(session, attempt)
            await self.repository.insert_recommendation_request(session, request)
            context = {
                "request": request,
                "attempt": attempt,
                "inputs": inputs,
                "seed": seed,
                "engine_payload": engine_payload,
                "asset_candidates": asset_candidates,
                "corpus_candidates": corpus_candidates,
                "selected_styles": selected_styles,
                "manifest": manifest,
                "provider": dict(inputs["provider"]),
            }

        try:
            return await self._complete_reserved_recommendation(
                command, request_hash, context
            )
        except asyncio.CancelledError as cancellation:
            await self._finish_cancellation(
                command, request_hash, cancellation
            )
            raise AssertionError("cancellation cleanup must re-raise")
