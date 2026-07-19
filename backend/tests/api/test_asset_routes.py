from __future__ import annotations

from inspect import signature
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.assets import load_asset_package
from backend.database import transaction
from backend.http_errors import (
    AssetCatalogNotReady,
    AssetNotFound,
    AssetRecommendationConflict,
)
from backend.routers import assets
from backend.security.redaction import install_error_handlers


PACKAGE = load_asset_package(
    Path(__file__).resolve().parents[2]
    / "assets"
    / "writer-core-v1.1.0"
    / "manifest.json",
    mode="release",
)
STYLE_ID = "11111111-1111-1111-1111-111111111111"
CARD_ID = "22222222-2222-2222-2222-222222222222"
RECOMMENDATION_SCOPE_QUERY = (
    "&genres=fantasy"
    "&channels=male_frequency"
    "&creationStages=drafting"
    "&writingPurposes=style_direction"
    "&writingPurposes=progression_economy"
    "&status=active"
)


def _recommendation_path(project_id="project-1", engine_id="engine-1"):
    return (
        f"/api/projects/{project_id}/asset-recommendations"
        f"?engineOptionId={engine_id}{RECOMMENDATION_SCOPE_QUERY}"
    )


def _record(asset, revision_id):
    return SimpleNamespace(
        id=revision_id,
        status="active",
        asset=asset,
        provenance="SECRET_REVIEWER_SENTINEL",
        source="C:/private/absolute/source.txt",
        raw_response="SECRET_RAW_SENTINEL",
    )


class FakeAssetService:
    def __init__(self):
        self.calls = []
        self.recommendation_scope = None
        self.style = self._item(_record(PACKAGE.styles[0], STYLE_ID))
        self.card = self._item(_record(PACKAGE.experience_cards[0], CARD_ID))
        self.failure = None

    @staticmethod
    def _item(record):
        return SimpleNamespace(
            record=record,
            eligibility=SimpleNamespace(
                genres=("general",),
                channels=("all",),
                creation_stages=("drafting", "revision"),
                writing_purposes=("style_direction",),
                prohibited_directions=(),
            ),
        )

    def _raise(self):
        if self.failure is not None:
            raise self.failure

    async def inventory(self):
        self.calls.append(("inventory",))
        self._raise()
        return SimpleNamespace(
            asset_package_version=PACKAGE.package_version,
            taxonomy_package_version="recommendation-taxonomy-v1.0.0",
            style_count=len(PACKAGE.styles),
            experience_card_count=len(PACKAGE.experience_cards),
            categories=("action_conflict", "dialogue"),
            genres=("general", "xianxia"),
            channels=("all", "male_frequency"),
            creation_stages=("drafting", "revision"),
            writing_purposes=("dialogue", "style_direction"),
            prohibited_directions=("slow_burn",),
            statuses=("active",),
        )

    async def list_styles(
        self, *, search=None, genre=None, stage=None, status=None
    ):
        self.calls.append(("list-styles", search, genre, stage, status))
        self._raise()
        return (self.style,)

    async def get_style(self, revision_id):
        self.calls.append(("get-style", revision_id))
        self._raise()
        return self.style

    async def list_cards(
        self, *, search=None, category=None, genre=None, stage=None, status=None
    ):
        self.calls.append(
            ("list-cards", search, category, genre, stage, status)
        )
        self._raise()
        return (self.card,)

    async def get_card(self, revision_id):
        self.calls.append(("get-card", revision_id))
        self._raise()
        return self.card

    async def recommend(
        self,
        project_id,
        engine_option_id,
        recommendation_scope=None,
    ):
        self.calls.append(("recommend", project_id, engine_option_id))
        self.recommendation_scope = recommendation_scope
        self._raise()
        return SimpleNamespace(
            recommendation_version="asset-recommendation-v1",
            recommendation_hash="a" * 64,
            seed_revision_id="seed-revision-1",
            seed_hash="b" * 64,
            engine_option_id=engine_option_id,
            engine_hash="c" * 64,
            styles=(
                SimpleNamespace(record=_record(style, f"style-{index}"), reason_codes=("semantic-profile",))
                for index, style in enumerate(PACKAGE.styles[:3], 1)
            ),
            experience_cards=(
                SimpleNamespace(record=_record(card, f"card-{index}"), reason_codes=("category-profile",))
                for index, card in enumerate(PACKAGE.experience_cards[:4], 1)
            ),
        )


def make_client():
    service = FakeAssetService()
    app = FastAPI()
    app.include_router(assets.router, prefix="/api")
    app.dependency_overrides[assets.get_asset_service] = lambda: service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def _assert_no_private_keys(value):
    banned = {
        "provenance", "reviewer", "reviewtime", "source", "source_",
        "raw", "apikey", "api_key", "secret", "baseurl", "base_url",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            folded = key.casefold()
            assert not any(token in folded for token in banned), key
            _assert_no_private_keys(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_private_keys(item)
    elif isinstance(value, str):
        assert "C:/private/absolute" not in value
        assert "SECRET_" not in value


def test_asset_routes_have_exact_methods_paths_and_camel_case_allowlists():
    client, service = make_client()

    style_list = client.get("/api/assets/style-templates")
    style_detail = client.get(f"/api/assets/style-templates/{STYLE_ID}")
    card_list = client.get("/api/assets/experience-cards?category=dialogue")
    card_detail = client.get(f"/api/assets/experience-cards/{CARD_ID}")
    recommendation = client.get(
        _recommendation_path()
    )

    assert [response.status_code for response in (
        style_list, style_detail, card_list, card_detail, recommendation
    )] == [200] * 5
    style = style_list.json()[0]
    assert set(style) == {
        "id", "stableKey", "revision", "contentHash", "name",
        "readingExperience", "applicability", "nonApplicability",
        "eligibility",
    }
    card = card_list.json()[0]
    assert set(card) == {
        "id", "stableKey", "revision", "contentHash", "title", "category",
        "method", "applicability", "nonApplicability", "eligibility",
    }
    assert service.calls == [
        ("list-styles", None, None, None, None), ("get-style", STYLE_ID),
        ("list-cards", None, "dialogue", None, None, None),
        ("get-card", CARD_ID),
        ("recommend", "project-1", "engine-1"),
    ]
    methods = {
        route.path: route.methods
        for route in assets.router.routes
    }
    assert methods == {
        "/assets/inventory": {"GET"},
        "/assets/style-templates": {"GET"},
        "/assets/style-templates/{revision_id}": {"GET"},
        "/assets/experience-cards": {"GET"},
        "/assets/experience-cards/{revision_id}": {"GET"},
        "/projects/{pid}/asset-recommendations": {"GET"},
    }
    assert "limit" not in signature(assets.list_experience_cards).parameters
    assert "limit" not in signature(assets.list_style_templates).parameters


def test_details_return_complete_approved_payload_and_preserve_20k_examples():
    client, service = make_client()
    long_text = "边" * 20_000
    service.style = service._item(_record(
        PACKAGE.styles[0].model_copy(
            update={
                "payload": PACKAGE.styles[0].payload.model_copy(
                    update={
                        "standard_scene_example": long_text,
                        "complete_application_example": long_text,
                    }
                )
            }
        ),
        STYLE_ID,
    ))
    service.card = service._item(_record(
        PACKAGE.experience_cards[0].model_copy(
            update={
                "payload": PACKAGE.experience_cards[0].payload.model_copy(
                    update={"original_micro_demo": long_text}
                )
            }
        ),
        CARD_ID,
    ))

    style = client.get(f"/api/assets/style-templates/{STYLE_ID}").json()
    card = client.get(f"/api/assets/experience-cards/{CARD_ID}").json()

    assert set(style["payload"]) == {
        "schemaVersion", "readingExperience", "applicability",
        "nonApplicability", "standardSceneExample",
        "completeApplicationExample", "narrativeDistance", "rhythm",
        "dictionDensity", "dialogue", "subtext", "characterVoices",
        "emotion", "interiority", "action", "explanation", "environment",
        "bodyResponse", "preferredTechniques", "risks", "originalAnchor",
    }
    assert 0 < len(style["payload"]["standardSceneExample"]) <= 2_400
    assert 0 < len(style["payload"]["completeApplicationExample"]) <= 2_400
    assert set(card["payload"]) == {
        "schemaVersion", "category", "method", "applicability",
        "nonApplicability", "risks", "originalMicroDemo",
    }
    assert 0 < len(card["payload"]["originalMicroDemo"]) <= 1_600
    _assert_no_private_keys(style)
    _assert_no_private_keys(card)


def test_recommendation_returns_three_styles_two_to_four_cards_and_never_inventory():
    client, _ = make_client()

    response = client.get(
        _recommendation_path()
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "recommendationVersion", "recommendationHash", "seedRevisionId",
        "seedHash", "engineOptionId", "engineHash", "styles",
        "experienceCards",
    }
    assert len(body["styles"]) == 3
    assert 2 <= len(body["experienceCards"]) <= 4
    assert all(set(item) == {
        "id", "stableKey", "revision", "contentHash", "name",
        "readingExperience", "applicability", "nonApplicability",
        "reasonCodes",
    } for item in body["styles"])
    assert all(set(item) == {
        "id", "stableKey", "revision", "contentHash", "title", "category",
        "method", "applicability", "nonApplicability", "reasonCodes",
    } for item in body["experienceCards"])
    assert len(body["experienceCards"]) != 64
    assert "score" not in json.dumps(body).casefold()
    _assert_no_private_keys(body)


@pytest.mark.parametrize(
    ("error", "status", "code", "path"),
    (
        (AssetNotFound(), 404, "AssetNotFound", f"/api/assets/style-templates/{STYLE_ID}"),
        (
            AssetRecommendationConflict(),
            409,
            "AssetRecommendationConflict",
            _recommendation_path("p", "e"),
        ),
        (AssetCatalogNotReady(), 503, "AssetCatalogNotReady", "/api/assets/style-templates"),
    ),
)
def test_asset_public_errors_use_safe_handler(error, status, code, path):
    client, service = make_client()
    service.failure = error

    response = client.get(path)

    assert response.status_code == status
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert response.json()["code"] == code
    assert response.json()["message"] == error.message


def test_invalid_category_and_missing_engine_option_are_422():
    client, _ = make_client()

    invalid_category = client.get(
        "/api/assets/experience-cards?category=not-approved"
    )
    missing_engine = client.get(
        "/api/projects/project-1/asset-recommendations"
    )

    assert invalid_category.status_code == 422
    assert missing_engine.status_code == 422


def test_production_asset_service_uses_transaction_and_main_registers_read_routes():
    service = assets.get_asset_service()

    assert service.asset_service.transaction_factory is transaction
    from backend import main

    registered = {route.path for route in main.app.routes}
    assert "/api/assets/inventory" in registered
    assert "/api/assets/style-templates" in registered
    assert "/api/assets/experience-cards" in registered
    assert "/api/projects/{pid}/asset-recommendations" in registered


def test_inventory_and_search_filters_are_forwarded_with_bounded_public_metadata():
    client, service = make_client()

    inventory = client.get("/api/assets/inventory")
    styles = client.get(
        "/api/assets/style-templates"
        "?search=direct&genre=xianxia&stage=drafting&status=active"
    )
    cards = client.get(
        "/api/assets/experience-cards"
        "?search=dialogue&category=dialogue&genre=general"
        "&stage=revision&status=active"
    )

    assert inventory.status_code == 200
    assert inventory.json() == {
        "assetPackageVersion": "writer-core-v1.1.0",
        "taxonomyPackageVersion": "recommendation-taxonomy-v1.0.0",
        "styleCount": 10,
        "experienceCardCount": 64,
        "categories": ["action_conflict", "dialogue"],
        "genres": ["general", "xianxia"],
        "channels": ["all", "male_frequency"],
        "creationStages": ["drafting", "revision"],
        "writingPurposes": ["dialogue", "style_direction"],
        "prohibitedDirections": ["slow_burn"],
        "statuses": ["active"],
    }
    assert styles.status_code == 200
    assert cards.status_code == 200
    assert styles.json()[0]["eligibility"]["genres"] == ["general"]
    assert cards.json()[0]["eligibility"]["creationStages"] == [
        "drafting", "revision"
    ]
    assert service.calls == [
        ("inventory",),
        ("list-styles", "direct", "xianxia", "drafting", "active"),
        (
            "list-cards", "dialogue", "dialogue", "general", "revision",
            "active",
        ),
    ]


def test_recommendation_requires_and_forwards_explicit_typed_eligibility_scope():
    client, service = make_client()

    response = client.get(
        "/api/projects/project-1/asset-recommendations",
        params=[
            ("engineOptionId", "engine-1"),
            ("genres", "fantasy"),
            ("channels", "male_frequency"),
            ("creationStages", "drafting"),
            ("writingPurposes", "style_direction"),
            ("writingPurposes", "progression_economy"),
            ("prohibitedDirections", "slow_burn"),
            ("status", "active"),
        ],
    )

    assert response.status_code == 200
    assert service.recommendation_scope is not None
    assert service.recommendation_scope.genres == ("fantasy",)
    assert service.recommendation_scope.channels == ("male_frequency",)
    assert service.recommendation_scope.creation_stages == ("drafting",)
    assert service.recommendation_scope.writing_purposes == (
        "style_direction",
        "progression_economy",
    )
    assert service.recommendation_scope.prohibited_directions == ("slow_burn",)
    assert service.recommendation_scope.status == "active"


@pytest.mark.parametrize(
    "path",
    (
        "/api/assets/style-templates/" + "s" * 37,
        "/api/assets/experience-cards/" + "c" * 37,
        "/api/projects/" + "p" * 37 + "/asset-recommendations?engineOptionId=e",
        "/api/projects/p/asset-recommendations?engineOptionId=" + "e" * 37,
    ),
)
def test_asset_route_identifiers_are_bounded_to_36_characters(path):
    client, _ = make_client()

    response = client.get(path)

    assert response.status_code == 422


def test_catalog_not_ready_is_503_for_both_lists_and_recommendation():
    client, service = make_client()
    service.failure = AssetCatalogNotReady()

    responses = (
        client.get("/api/assets/style-templates"),
        client.get("/api/assets/experience-cards"),
        client.get(
            _recommendation_path()
        ),
    )

    assert [response.status_code for response in responses] == [503, 503, 503]
    assert [response.json()["code"] for response in responses] == [
        "AssetCatalogNotReady",
        "AssetCatalogNotReady",
        "AssetCatalogNotReady",
    ]
