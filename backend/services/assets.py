"""Release-only validation, planning, and atomic immutable asset seeding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import time
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError

from backend.domain.asset_eligibility import (
    AssetEligibilityEntry,
    AssetEligibilityScope,
    canonical_recommendation_scope,
    eligible_asset_identities,
)
from backend.domain.asset_recommendations import (
    RecommendationInputError,
    recommend_assets,
    validate_recommendation_inventory,
)
from backend.domain.assets import (
    AssetInventory,
    AssetPackage,
    AssetPackageError,
    ExperienceCardRevision,
    StyleTemplateRevision,
    validate_asset_package,
)
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.seeds import SeedPayload, decode_seed_revision
from backend.http_errors import (
    AssetCatalogNotReady,
    AssetNotFound,
    AssetRecommendationConflict,
)
from backend.services.contracts import ContractDraftPayload


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


@dataclass(frozen=True)
class RecommendedAsset:
    record: AssetRecord
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class AssetRecommendationView:
    recommendation_version: str
    recommendation_hash: str
    seed_revision_id: str
    seed_hash: str
    engine_option_id: str
    engine_hash: str
    styles: tuple[RecommendedAsset, ...]
    experience_cards: tuple[RecommendedAsset, ...]


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
            inventory = validate_recommendation_inventory(
                AssetInventory(
                    styles=tuple(record.asset for record in styles),
                    experience_cards=tuple(record.asset for record in cards),
                )
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

    @staticmethod
    def _trusted_eligibility_scope(
        requested_scope: AssetEligibilityScope | object,
        *,
        selected: Mapping,
        engine: Mapping,
        draft_row: Mapping,
    ) -> AssetEligibilityScope:
        try:
            if isinstance(requested_scope, AssetEligibilityScope):
                requested = requested_scope
            else:
                requested = AssetEligibilityScope.model_validate(
                    vars(requested_scope)
                )
            raw_draft = _json_mapping(draft_row["draft_json"])
            draft = ContractDraftPayload.model_validate_json(
                canonical_json(raw_draft)
            )
            if (
                draft_row["engine_option_id"] != engine["id"]
                or int(draft_row["selection_revision"])
                != int(selected["selection_revision"])
                or draft_row["seed_hash"] != selected["seed_hash"]
                or canonical_hash(raw_draft) != draft_row["content_hash"]
                or draft.engineOptionId != engine["id"]
                or draft.engineHash != engine["content_hash"]
                or draft.seedRevisionId != selected["seed_revision_id"]
                or draft.seedHash != selected["seed_hash"]
            ):
                raise ValueError("contract recommendation context drift")
            trusted = canonical_recommendation_scope(
                genre_profile_key=draft.genreProfileKey,
                channel_profile_key=draft.channelProfileKey,
                dislikes=draft.dislikes or (),
            )
            if requested != trusted:
                raise ValueError("recommendation scope differs from trusted facts")
            return trusted
        except (
            ValidationError,
            ValueError,
            TypeError,
            KeyError,
            UnicodeError,
            json.JSONDecodeError,
        ):
            raise AssetRecommendationConflict() from None

    async def recommend(
        self,
        project_id: str,
        engine_option_id: str,
        *,
        eligibility_scope: AssetEligibilityScope | object | None = None,
        eligibility_entries: tuple[AssetEligibilityEntry, ...] | None = None,
    ) -> AssetRecommendationView:
        if (eligibility_scope is None) != (eligibility_entries is None):
            raise AssetRecommendationConflict()
        async with self._transaction() as session:
            if await self.repository.read_project(session, project_id) is None:
                raise AssetNotFound()
            selected = await self.repository.read_selected_seed(session, project_id)
            if selected is None:
                raise AssetRecommendationConflict()
            engine = await self.repository.read_engine_option(
                session, project_id, engine_option_id
            )
            if engine is None:
                raise AssetNotFound()
            seed, engine_payload = self._recommendation_inputs(selected, engine)
            allowed_style_identities = None
            allowed_card_identities = None
            if eligibility_scope is not None and eligibility_entries is not None:
                draft = await self.repository.read_contract_draft(
                    session, project_id, engine_option_id
                )
                if draft is None:
                    raise AssetRecommendationConflict()
                trusted_scope = self._trusted_eligibility_scope(
                    eligibility_scope,
                    selected=selected,
                    engine=engine,
                    draft_row=draft,
                )
                allowed_style_identities = eligible_asset_identities(
                    eligibility_entries,
                    trusted_scope,
                    asset_type="style",
                )
                allowed_card_identities = eligible_asset_identities(
                    eligibility_entries,
                    trusted_scope,
                    asset_type="experience_card",
                )
            styles, cards, inventory = await self._catalog(session)

        try:
            result = recommend_assets(
                seed,
                engine_payload,
                inventory,
                seed_hash=selected["seed_hash"],
                engine_hash=engine["content_hash"],
                allowed_style_identities=allowed_style_identities,
                allowed_card_identities=allowed_card_identities,
            )
        except (RecommendationInputError, AssetPackageError, ValidationError):
            raise AssetRecommendationConflict() from None

        style_index = {
            (record.asset.stable_key, record.asset.revision, record.asset.content_hash): record
            for record in styles
        }
        card_index = {
            (record.asset.stable_key, record.asset.revision, record.asset.content_hash): record
            for record in cards
        }
        try:
            recommended_styles = tuple(
                RecommendedAsset(
                    record=style_index[(ref.stable_key, ref.revision, ref.content_hash)],
                    reason_codes=tuple(ref.reason_codes),
                )
                for ref in result.styles
            )
            recommended_cards = tuple(
                RecommendedAsset(
                    record=card_index[(ref.stable_key, ref.revision, ref.content_hash)],
                    reason_codes=tuple(ref.reason_codes),
                )
                for ref in result.experience_cards
            )
        except KeyError:
            raise AssetCatalogNotReady() from None
        return AssetRecommendationView(
            recommendation_version=result.recommendation_version,
            recommendation_hash=result.recommendation_hash,
            seed_revision_id=selected["seed_revision_id"],
            seed_hash=result.seed_hash,
            engine_option_id=engine["id"],
            engine_hash=result.engine_hash,
            styles=recommended_styles,
            experience_cards=recommended_cards,
        )
