"""Read-only approved writing asset catalog and recommendation routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from backend.database import transaction
from backend.domain.assets import AssetCategory
from backend.repositories.assets import AssetRepository
from backend.services.assets import AssetReadService


router = APIRouter(tags=["assets"])


def get_asset_service() -> AssetReadService:
    return AssetReadService(AssetRepository(), transaction_factory=transaction)


def _style_summary(record) -> dict:
    asset = record.asset
    payload = asset.payload
    return {
        "id": record.id,
        "stableKey": asset.stable_key,
        "revision": asset.revision,
        "contentHash": asset.content_hash,
        "name": asset.name,
        "readingExperience": payload.reading_experience,
        "applicability": list(payload.applicability),
        "nonApplicability": list(payload.non_applicability),
    }


def _card_summary(record) -> dict:
    asset = record.asset
    payload = asset.payload
    return {
        "id": record.id,
        "stableKey": asset.stable_key,
        "revision": asset.revision,
        "contentHash": asset.content_hash,
        "title": asset.title,
        "category": asset.category,
        "method": payload.method,
        "applicability": list(payload.applicability),
        "nonApplicability": list(payload.non_applicability),
    }


def _style_payload(record) -> dict:
    payload = record.asset.payload
    return {
        "schemaVersion": payload.schemaVersion,
        "readingExperience": payload.reading_experience,
        "applicability": list(payload.applicability),
        "nonApplicability": list(payload.non_applicability),
        "standardSceneExample": payload.standard_scene_example,
        "completeApplicationExample": payload.complete_application_example,
        "narrativeDistance": payload.narrative_distance,
        "rhythm": payload.rhythm,
        "dictionDensity": payload.diction_density,
        "dialogue": payload.dialogue,
        "subtext": payload.subtext,
        "characterVoices": payload.character_voices,
        "emotion": payload.emotion,
        "interiority": payload.interiority,
        "action": payload.action,
        "explanation": payload.explanation,
        "environment": payload.environment,
        "bodyResponse": payload.body_response,
        "preferredTechniques": list(payload.preferred_techniques),
        "risks": list(payload.risks),
        "originalAnchor": payload.original_anchor,
    }


def _card_payload(record) -> dict:
    payload = record.asset.payload
    return {
        "schemaVersion": payload.schemaVersion,
        "category": payload.category,
        "method": payload.method,
        "applicability": list(payload.applicability),
        "nonApplicability": list(payload.non_applicability),
        "risks": list(payload.risks),
        "originalMicroDemo": payload.original_micro_demo,
    }


@router.get("/assets/style-templates")
async def list_style_templates(service=Depends(get_asset_service)):
    return [_style_summary(record) for record in await service.list_styles()]


@router.get("/assets/style-templates/{revision_id}")
async def get_style_template(
    revision_id: str = Path(min_length=1, max_length=36),
    service=Depends(get_asset_service),
):
    record = await service.get_style(revision_id)
    return {**_style_summary(record), "payload": _style_payload(record)}


@router.get("/assets/experience-cards")
async def list_experience_cards(
    category: AssetCategory | None = Query(default=None),
    service=Depends(get_asset_service),
):
    return [
        _card_summary(record)
        for record in await service.list_cards(category=category)
    ]


@router.get("/assets/experience-cards/{revision_id}")
async def get_experience_card(
    revision_id: str = Path(min_length=1, max_length=36),
    service=Depends(get_asset_service),
):
    record = await service.get_card(revision_id)
    return {**_card_summary(record), "payload": _card_payload(record)}


@router.get("/projects/{pid}/asset-recommendations")
async def get_asset_recommendations(
    pid: str = Path(min_length=1, max_length=36),
    engineOptionId: str = Query(min_length=1, max_length=36),
    service=Depends(get_asset_service),
):
    recommendation = await service.recommend(pid, engineOptionId)
    styles = []
    for item in recommendation.styles:
        styles.append(
            {**_style_summary(item.record), "reasonCodes": list(item.reason_codes)}
        )
    cards = []
    for item in recommendation.experience_cards:
        cards.append(
            {**_card_summary(item.record), "reasonCodes": list(item.reason_codes)}
        )
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
