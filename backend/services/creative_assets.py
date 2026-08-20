"""Public composition boundary for global creative assets."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import unicodedata

from backend.config import current_runtime_configuration
from backend.database import connection, transaction
from backend.domain.asset_eligibility import (
    AssetEligibilityEntry,
    AssetEligibilityPackage,
    AssetEligibilityPackageError,
    CreationStage,
    Genre,
    load_asset_eligibility_package,
)
from backend.domain.assets import AssetCategory, AssetPackageError, load_asset_package
from backend.http_errors import AssetCatalogNotReady
from backend.repositories.assets import AssetRepository
from backend.repositories.corpus import CorpusRepository
from backend.gateways.asset_recommendation_provider import (
    AssetRecommendationProviderGateway,
)
from backend.services.assets import (
    AssetReadService,
    AssetRecommendationService,
    AssetRecord,
)
from backend.services.corpus_recommendations import CorpusRecommendationService
from backend.services.corpus_import import CorpusImportService
from backend.services.corpus_library import CorpusLibraryService


_ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets"
_ASSET_MANIFEST = _ASSET_ROOT / "writer-core-v1.1.0" / "manifest.json"
_TAXONOMY_MANIFEST = (
    _ASSET_ROOT / "recommendation-taxonomy-v1.0.0" / "manifest.json"
)


@dataclass(frozen=True)
class CreativeAssetItem:
    record: AssetRecord
    eligibility: AssetEligibilityEntry | None


@dataclass(frozen=True)
class CreativeAssetInventory:
    asset_package_version: str
    taxonomy_package_version: str
    taxonomy_package_hash: str
    style_count: int
    experience_card_count: int
    categories: tuple[str, ...]
    genres: tuple[str, ...]
    channels: tuple[str, ...]
    creation_stages: tuple[str, ...]
    writing_purposes: tuple[str, ...]
    prohibited_directions: tuple[str, ...]
    statuses: tuple[str, ...]


@lru_cache(maxsize=1)
def load_release_taxonomy() -> AssetEligibilityPackage:
    approved = load_asset_package(_ASSET_MANIFEST, mode="release")
    return load_asset_eligibility_package(
        _TAXONOMY_MANIFEST,
        asset_package=approved,
        mode="release",
    )


def _normalized_search(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )


class CreativeAssetService:
    """Compose focused asset reads and corpus commands without duplicating rules."""

    def __init__(
        self,
        asset_service: AssetReadService,
        *,
        taxonomy: AssetEligibilityPackage,
        recommendation_service: AssetRecommendationService | None = None,
        corpus_service: CorpusImportService | None = None,
        corpus_library_service: CorpusLibraryService | None = None,
    ) -> None:
        self.asset_service = asset_service
        self.taxonomy = taxonomy
        self.recommendation_service = recommendation_service
        self.corpus_service = corpus_service
        self.corpus_library_service = corpus_library_service
        self._eligibility = {
            (
                entry.asset_type,
                entry.stable_key,
                entry.asset_content_hash,
            ): entry
            for entry in taxonomy.entries
        }
        if len(self._eligibility) != len(taxonomy.entries):
            raise ValueError("asset eligibility identities must be unique")

    @staticmethod
    def _asset_type(record: AssetRecord) -> str:
        return "style" if hasattr(record.asset, "name") else "experience_card"

    def _item(self, record: AssetRecord) -> CreativeAssetItem:
        identity = (
            self._asset_type(record),
            record.asset.stable_key,
            record.asset.content_hash,
        )
        eligibility = self._eligibility.get(identity)
        if eligibility is None and record.status != "archived":
            raise AssetCatalogNotReady()
        return CreativeAssetItem(record=record, eligibility=eligibility)

    @staticmethod
    def _matches_common(
        item: CreativeAssetItem,
        *,
        search: str | None,
        genre: Genre | None,
        stage: CreationStage | None,
        status: str | None,
    ) -> bool:
        record = item.record
        asset = record.asset
        if status is not None and record.status != status:
            return False
        if genre is not None and (
            item.eligibility is None
            or (
                genre not in item.eligibility.genres
                and "general" not in item.eligibility.genres
            )
        ):
            return False
        if (
            stage is not None
            and (
                item.eligibility is None
                or stage not in item.eligibility.creation_stages
            )
        ):
            return False
        needle = _normalized_search(search)
        if not needle:
            return True
        label = getattr(asset, "name", None) or getattr(asset, "title", "")
        category = getattr(asset, "category", "")
        searchable = _normalized_search(
            " ".join((asset.stable_key, label, category))
        )
        return needle in searchable

    async def _catalog(
        self,
    ) -> tuple[tuple[CreativeAssetItem, ...], tuple[CreativeAssetItem, ...]]:
        styles, cards = await self.asset_service.current_head_catalog()
        return (
            tuple(self._item(record) for record in styles),
            tuple(self._item(record) for record in cards),
        )

    async def inventory(self) -> CreativeAssetInventory:
        styles, cards = await self._catalog()
        all_items = (*styles, *cards)
        return CreativeAssetInventory(
            asset_package_version=self.taxonomy.asset_package_version,
            taxonomy_package_version=self.taxonomy.package_version,
            taxonomy_package_hash=(
                self.taxonomy.manifest.eligibility_file.sha256
            ),
            style_count=len(styles),
            experience_card_count=len(cards),
            categories=tuple(sorted({
                item.record.asset.category for item in cards
            })),
            genres=tuple(sorted({
                genre
                for item in all_items
                if item.eligibility is not None
                for genre in item.eligibility.genres
            })),
            channels=tuple(sorted({
                channel
                for item in all_items
                if item.eligibility is not None
                for channel in item.eligibility.channels
            })),
            creation_stages=tuple(sorted({
                stage
                for item in all_items
                if item.eligibility is not None
                for stage in item.eligibility.creation_stages
            })),
            writing_purposes=tuple(sorted({
                purpose
                for item in all_items
                if item.eligibility is not None
                for purpose in item.eligibility.writing_purposes
            })),
            prohibited_directions=tuple(sorted({
                direction
                for item in all_items
                if item.eligibility is not None
                for direction in item.eligibility.prohibited_directions
            })),
            statuses=tuple(sorted({
                item.record.status for item in all_items
            })),
        )

    async def list_styles(
        self,
        *,
        search: str | None = None,
        genre: Genre | None = None,
        stage: CreationStage | None = None,
        status: str | None = None,
    ) -> tuple[CreativeAssetItem, ...]:
        styles, _ = await self._catalog()
        return tuple(
            item
            for item in styles
            if self._matches_common(
                item,
                search=search,
                genre=genre,
                stage=stage,
                status=status,
            )
        )

    async def list_cards(
        self,
        *,
        search: str | None = None,
        category: AssetCategory | None = None,
        genre: Genre | None = None,
        stage: CreationStage | None = None,
        status: str | None = None,
    ) -> tuple[CreativeAssetItem, ...]:
        _, cards = await self._catalog()
        return tuple(
            item
            for item in cards
            if (
                (category is None or item.record.asset.category == category)
                and self._matches_common(
                    item,
                    search=search,
                    genre=genre,
                    stage=stage,
                    status=status,
                )
            )
        )

    async def get_style(self, revision_id: str) -> CreativeAssetItem:
        return self._item(await self.asset_service.get_style(revision_id))

    async def get_card(self, revision_id: str) -> CreativeAssetItem:
        return self._item(await self.asset_service.get_card(revision_id))

    async def recommend(self, command):
        if self.recommendation_service is None:
            raise AssetCatalogNotReady()
        return await self.recommendation_service.recommend(command)

    def _corpus(self) -> CorpusImportService:
        if self.corpus_service is None:
            raise RuntimeError("corpus service is not configured")
        return self.corpus_service

    async def discovery(self, *, cursor=None, limit=50):
        return await self._corpus().discovery(cursor=cursor, limit=limit)

    async def import_source(
        self, relative_path: str, idempotency_key: str, **metadata
    ):
        return await self._corpus().import_source(
            relative_path, idempotency_key, **metadata
        )

    async def get_import(self, import_id: str):
        return await self._corpus().get_import(import_id)

    def _corpus_library(self) -> CorpusLibraryService:
        if self.corpus_library_service is None:
            raise RuntimeError("corpus library service is not configured")
        return self.corpus_library_service

    async def list_sources(self, search=None, state=None):
        return await self._corpus_library().list_sources(
            search=search, state=state
        )

    async def get_source(self, source_id: str, preview_chars: int):
        return await self._corpus_library().get_source(
            source_id, preview_chars
        )

    async def list_versions(self, source_id: str, cursor=None, limit=50):
        return await self._corpus_library().list_versions(
            source_id, cursor=cursor, limit=limit
        )

    async def archive_source(self, source_id: str, expected_revision: int):
        return await self._corpus_library().archive(
            source_id, expected_revision
        )

    async def restore_source(self, source_id: str, expected_revision: int):
        return await self._corpus_library().restore(
            source_id, expected_revision
        )

    async def permanently_delete_source(
        self,
        source_id: str,
        expected_revision: int,
        confirm_permanent_delete: bool,
    ):
        return await self._corpus_library().permanently_delete(
            source_id,
            expected_revision,
            confirm_permanent_delete,
        )

    async def list_chapters(self, source_id: str):
        return await self._corpus().list_chapters(source_id)

    async def list_fragments(self, chapter_id: str, cursor: int, limit: int):
        return await self._corpus().list_fragments(chapter_id, cursor, limit)


def build_creative_asset_service() -> CreativeAssetService:
    try:
        snapshot = current_runtime_configuration()
        corpus_root = snapshot.corpus_root
        managed_root = snapshot.managed_corpus_root
        taxonomy = load_release_taxonomy()
        asset_repository = AssetRepository()
        corpus_repository = CorpusRepository()
        return CreativeAssetService(
            AssetReadService(asset_repository, transaction_factory=transaction),
            taxonomy=taxonomy,
            recommendation_service=AssetRecommendationService(
                asset_repository,
                transaction_factory=transaction,
                connection_factory=connection,
                provider_gateway=AssetRecommendationProviderGateway(),
                corpus_service=CorpusRecommendationService(
                    corpus_repository,
                    connection_factory=connection,
                ),
                taxonomy=taxonomy,
            ),
            corpus_service=CorpusImportService(
                corpus_repository,
                corpus_root=corpus_root,
                managed_root=managed_root,
                transaction_factory=transaction,
                connection_factory=transaction,
            ),
            corpus_library_service=CorpusLibraryService(
                corpus_repository,
                managed_root=managed_root,
                transaction_factory=transaction,
                connection_factory=transaction,
            ),
        )
    except (AssetEligibilityPackageError, AssetPackageError):
        raise AssetCatalogNotReady() from None


__all__ = (
    "CreativeAssetInventory",
    "CreativeAssetItem",
    "CreativeAssetService",
    "build_creative_asset_service",
    "load_release_taxonomy",
)
