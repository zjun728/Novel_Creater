"""Read-only global creative-asset catalog and recommendation routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query

from backend.domain.asset_eligibility import (
    CHANNELS,
    CREATION_STAGES,
    GENRES,
    PROHIBITED_DIRECTIONS,
    WRITING_PURPOSES,
    AssetEligibilityScope,
    Channel,
    CreationStage,
    Genre,
    ProhibitedDirection,
    WritingPurpose,
)
from backend.domain.assets import AssetCategory
from backend.services.creative_assets import (
    CreativeAssetService,
    build_creative_asset_service,
)


router = APIRouter(tags=["assets"])


def get_asset_service() -> CreativeAssetService:
    return build_creative_asset_service()


def _record_and_eligibility(value):
    return getattr(value, "record", value), getattr(value, "eligibility", None)


def _bounded_text(value, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


def _bounded_list(values, *, limit: int = 400) -> list[str]:
    return [_bounded_text(value, limit) for value in values]


def _eligibility_payload(eligibility) -> dict | None:
    if eligibility is None:
        return None
    return {
        "genres": list(eligibility.genres),
        "channels": list(eligibility.channels),
        "creationStages": list(eligibility.creation_stages),
        "writingPurposes": list(eligibility.writing_purposes),
        "prohibitedDirections": list(eligibility.prohibited_directions),
    }


def _style_summary(value) -> dict:
    record, eligibility = _record_and_eligibility(value)
    asset = record.asset
    payload = asset.payload
    result = {
        "id": record.id,
        "stableKey": asset.stable_key,
        "revision": asset.revision,
        "contentHash": asset.content_hash,
        "name": asset.name,
        "readingExperience": _bounded_text(payload.reading_experience, 800),
        "applicability": _bounded_list(payload.applicability),
        "nonApplicability": _bounded_list(payload.non_applicability),
    }
    if eligibility is not None:
        result["eligibility"] = _eligibility_payload(eligibility)
    return result


def _card_summary(value) -> dict:
    record, eligibility = _record_and_eligibility(value)
    asset = record.asset
    payload = asset.payload
    result = {
        "id": record.id,
        "stableKey": asset.stable_key,
        "revision": asset.revision,
        "contentHash": asset.content_hash,
        "title": asset.title,
        "category": asset.category,
        "method": _bounded_text(payload.method, 800),
        "applicability": _bounded_list(payload.applicability),
        "nonApplicability": _bounded_list(payload.non_applicability),
    }
    if eligibility is not None:
        result["eligibility"] = _eligibility_payload(eligibility)
    return result


def _style_payload(value) -> dict:
    record, _ = _record_and_eligibility(value)
    payload = record.asset.payload
    return {
        "schemaVersion": payload.schemaVersion,
        "readingExperience": _bounded_text(payload.reading_experience, 800),
        "applicability": _bounded_list(payload.applicability),
        "nonApplicability": _bounded_list(payload.non_applicability),
        "standardSceneExample": _bounded_text(
            payload.standard_scene_example, 2_400
        ),
        "completeApplicationExample": _bounded_text(
            payload.complete_application_example, 2_400
        ),
        "narrativeDistance": _bounded_text(payload.narrative_distance, 800),
        "rhythm": _bounded_text(payload.rhythm, 800),
        "dictionDensity": _bounded_text(payload.diction_density, 800),
        "dialogue": _bounded_text(payload.dialogue, 800),
        "subtext": _bounded_text(payload.subtext, 800),
        "characterVoices": _bounded_text(payload.character_voices, 800),
        "emotion": _bounded_text(payload.emotion, 800),
        "interiority": _bounded_text(payload.interiority, 800),
        "action": _bounded_text(payload.action, 800),
        "explanation": _bounded_text(payload.explanation, 800),
        "environment": _bounded_text(payload.environment, 800),
        "bodyResponse": _bounded_text(payload.body_response, 800),
        "preferredTechniques": _bounded_list(payload.preferred_techniques),
        "risks": _bounded_list(payload.risks),
        "originalAnchor": _bounded_text(payload.original_anchor, 800),
    }


def _card_payload(value) -> dict:
    record, _ = _record_and_eligibility(value)
    payload = record.asset.payload
    return {
        "schemaVersion": payload.schemaVersion,
        "category": payload.category,
        "method": _bounded_text(payload.method, 800),
        "applicability": _bounded_list(payload.applicability),
        "nonApplicability": _bounded_list(payload.non_applicability),
        "risks": _bounded_list(payload.risks),
        "originalMicroDemo": _bounded_text(payload.original_micro_demo, 1_600),
    }


@router.get("/assets/inventory")
async def get_asset_inventory(service=Depends(get_asset_service)):
    inventory = await service.inventory()
    return {
        "assetPackageVersion": inventory.asset_package_version,
        "taxonomyPackageVersion": inventory.taxonomy_package_version,
        "styleCount": inventory.style_count,
        "experienceCardCount": inventory.experience_card_count,
        "categories": list(inventory.categories),
        "genres": list(inventory.genres),
        "channels": list(inventory.channels),
        "creationStages": list(inventory.creation_stages),
        "writingPurposes": list(inventory.writing_purposes),
        "prohibitedDirections": list(inventory.prohibited_directions),
        "statuses": list(inventory.statuses),
    }


@router.get("/assets/style-templates")
async def list_style_templates(
    search: str | None = Query(default=None, min_length=1, max_length=120),
    genre: Genre | None = Query(default=None),
    stage: CreationStage | None = Query(default=None),
    status: Literal["active", "archived"] | None = Query(default=None),
    service=Depends(get_asset_service),
):
    return [
        _style_summary(item)
        for item in await service.list_styles(
            search=search,
            genre=genre,
            stage=stage,
            status=status,
        )
    ]


@router.get("/assets/style-templates/{revision_id}")
async def get_style_template(
    revision_id: str = Path(min_length=1, max_length=36),
    service=Depends(get_asset_service),
):
    item = await service.get_style(revision_id)
    return {**_style_summary(item), "payload": _style_payload(item)}


@router.get("/assets/experience-cards")
async def list_experience_cards(
    search: str | None = Query(default=None, min_length=1, max_length=120),
    category: AssetCategory | None = Query(default=None),
    genre: Genre | None = Query(default=None),
    stage: CreationStage | None = Query(default=None),
    status: Literal["active", "archived"] | None = Query(default=None),
    service=Depends(get_asset_service),
):
    return [
        _card_summary(item)
        for item in await service.list_cards(
            search=search,
            category=category,
            genre=genre,
            stage=stage,
            status=status,
        )
    ]


@router.get("/assets/experience-cards/{revision_id}")
async def get_experience_card(
    revision_id: str = Path(min_length=1, max_length=36),
    service=Depends(get_asset_service),
):
    item = await service.get_card(revision_id)
    return {**_card_summary(item), "payload": _card_payload(item)}


@router.get("/projects/{pid}/asset-recommendations")
async def get_asset_recommendations(
    pid: str = Path(min_length=1, max_length=36),
    engineOptionId: str = Query(min_length=1, max_length=36),
    genres: list[Genre] = Query(
        min_length=1,
        max_length=len(GENRES),
    ),
    channels: list[Channel] = Query(
        min_length=1,
        max_length=len(CHANNELS),
    ),
    creationStages: list[CreationStage] = Query(
        min_length=1,
        max_length=len(CREATION_STAGES),
    ),
    writingPurposes: list[WritingPurpose] = Query(
        min_length=1,
        max_length=len(WRITING_PURPOSES),
    ),
    status: Literal["active", "archived"] = Query(),
    prohibitedDirections: list[ProhibitedDirection] = Query(
        default=[],
        max_length=len(PROHIBITED_DIRECTIONS),
    ),
    service=Depends(get_asset_service),
):
    scope = AssetEligibilityScope(
        genres=tuple(genres),
        channels=tuple(channels),
        creation_stages=tuple(creationStages),
        writing_purposes=tuple(writingPurposes),
        prohibited_directions=tuple(prohibitedDirections),
        status=status,
    )
    recommendation = await service.recommend(pid, engineOptionId, scope)
    styles = [
        {
            **_style_summary(item.record),
            "reasonCodes": list(item.reason_codes),
        }
        for item in recommendation.styles
    ]
    cards = [
        {
            **_card_summary(item.record),
            "reasonCodes": list(item.reason_codes),
        }
        for item in recommendation.experience_cards
    ]
    return {
        "recommendationVersion": recommendation.recommendation_version,
        "recommendationHash": recommendation.recommendation_hash,
        "seedRevisionId": recommendation.seed_revision_id,
        "seedHash": recommendation.seed_hash,
        "engineOptionId": recommendation.engine_option_id,
        "engineHash": recommendation.engine_hash,
        "styles": styles,
        "experienceCards": cards,
    }
