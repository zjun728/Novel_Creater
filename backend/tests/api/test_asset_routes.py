from __future__ import annotations

from inspect import signature
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.asset_eligibility import (
    AssetEligibilityPackageError,
    load_asset_eligibility_package,
)
from backend.domain.assets import AssetPackageError, load_asset_package
from backend.database import transaction
from backend.http_errors import (
    AssetCatalogNotReady,
    AssetNotFound,
    AssetRecommendationConflict,
    AssetRecommendationInProgress,
)
from backend.routers import assets, corpus
from backend.security.redaction import install_error_handlers
from backend.services import creative_assets as creative_asset_services


PACKAGE = load_asset_package(
    Path(__file__).resolve().parents[2]
    / "assets"
    / "writer-core-v1.1.0"
    / "manifest.json",
    mode="release",
)
STYLE_ID = "11111111-1111-1111-1111-111111111111"
CARD_ID = "22222222-2222-2222-2222-222222222222"
RECOMMENDATION_BODY = {
    "idempotencyKey": "i" * 64,
    "engineOptionId": "engine-1",
    "taxonomyVersion": "recommendation-taxonomy-v1.0.0",
    "taxonomyHash": "a" * 64,
    "genre": "fantasy",
    "creationStage": "drafting",
    "status": "active",
    "prohibitedDirections": [],
}


def _recommendation_path(project_id="project-1"):
    return f"/api/projects/{project_id}/asset-recommendations"


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
        self.recommendation_command = None
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

    async def recommend(self, command):
        self.calls.append(("recommend", command.project_id, command.engine_option_id))
        self.recommendation_command = command
        self._raise()
        return SimpleNamespace(
            attempt_id="attempt-1",
            public_reason="recommendationsAvailable",
            ranking_unavailable=False,
            full_browse_available=True,
            asset_recommendations=(SimpleNamespace(
                asset_revision_id=STYLE_ID,
                asset_type="style",
                stable_key=PACKAGE.styles[0].stable_key,
                revision=PACKAGE.styles[0].revision,
                content_hash=PACKAGE.styles[0].content_hash,
                reason="契合当前叙事距离",
                confidence=0.91,
            ),),
            corpus_recommendations=(SimpleNamespace(
                source_id="source-1",
                source_revision=2,
                source_hash="b" * 64,
                chapter_id="chapter-1",
                fragment_id="fragment-1",
                fragment_hash="c" * 64,
                range_start=100,
                range_end=108,
                use="作为制度试行参照",
                reason="与当前冲突直接相关",
                confidence=0.88,
            ),),
            input_manifest={
                "selection": {"revision": 3, "hash": "d" * 64},
                "binding": {"revisionId": "binding-1", "hash": "e" * 64},
            },
            input_manifest_hash="f" * 64,
            result_hash="1" * 64,
        )


def make_client():
    service = FakeAssetService()
    app = FastAPI()
    app.include_router(assets.router, prefix="/api")
    app.dependency_overrides[assets.get_asset_service] = lambda: service
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def make_production_dependency_client():
    app = FastAPI()
    app.include_router(assets.router, prefix="/api")
    app.include_router(corpus.router, prefix="/api")
    install_error_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def _assert_no_private_keys(value):
    banned = {
        "provenance", "reviewer", "reviewtime", "storage", "path",
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
    recommendation = client.post(
        _recommendation_path(), json=RECOMMENDATION_BODY
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
        "/projects/{pid}/asset-recommendations": {"POST"},
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


def test_recommendation_returns_variable_refs_and_never_auto_selects_or_leaks_text():
    client, _ = make_client()

    response = client.post(
        _recommendation_path(), json=RECOMMENDATION_BODY
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "attemptId", "publicReason", "rankingUnavailable",
        "fullBrowseAvailable", "assetRecommendations",
        "corpusRecommendations", "inputManifest", "inputManifestHash",
        "resultHash",
    }
    assert len(body["assetRecommendations"]) == 1
    assert set(body["assetRecommendations"][0]) == {
        "assetRevisionId", "assetType", "stableKey", "revision",
        "contentHash", "reason", "confidence",
    }
    assert set(body["corpusRecommendations"][0]) == {
        "sourceId", "sourceRevision", "sourceHash", "chapterId",
        "fragmentId", "fragmentHash", "rangeStart", "rangeEnd",
        "use", "reason", "confidence",
    }
    assert body["fullBrowseAvailable"] is True
    rendered = json.dumps(body).casefold()
    assert not any(token in rendered for token in (
        "selected", "default-rank", "prompt", "normalized_text"
    ))
    _assert_no_private_keys(body)

    assert client.get(_recommendation_path()).status_code == 405


@pytest.mark.parametrize(
    ("error", "status", "code", "path"),
    (
        (AssetNotFound(), 404, "AssetNotFound", f"/api/assets/style-templates/{STYLE_ID}"),
        (
            AssetRecommendationConflict(),
            409,
            "AssetRecommendationConflict",
            _recommendation_path("p"),
        ),
        (
            AssetRecommendationInProgress(),
            409,
            "AssetRecommendationInProgress",
            _recommendation_path("p"),
        ),
        (AssetCatalogNotReady(), 503, "AssetCatalogNotReady", "/api/assets/style-templates"),
    ),
)
def test_asset_public_errors_use_safe_handler(error, status, code, path):
    client, service = make_client()
    service.failure = error

    response = (
        client.post(path, json=RECOMMENDATION_BODY)
        if "asset-recommendations" in path
        else client.get(path)
    )

    assert response.status_code == status
    assert set(response.json()) == {"code", "message", "correlationId"}
    assert response.json()["code"] == code
    assert response.json()["message"] == error.message


@pytest.mark.parametrize(
    "loader_name",
    ("load_asset_package", "load_asset_eligibility_package"),
)
def test_production_composition_package_failures_are_safe_503_on_asset_and_corpus_routes(
    monkeypatch,
    tmp_path,
    loader_name,
):
    if loader_name == "load_asset_package":
        with pytest.raises(AssetPackageError) as captured:
            load_asset_package(
                tmp_path / "private-approved-assets" / "manifest.json",
                mode="release",
            )
    else:
        with pytest.raises(AssetEligibilityPackageError) as captured:
            load_asset_eligibility_package(
                tmp_path / "private-taxonomy" / "manifest.json",
                asset_package=PACKAGE,
                mode="release",
            )
    loader_error = captured.value

    def fail_loader(*_args, **_kwargs):
        raise loader_error

    creative_asset_services.load_release_taxonomy.cache_clear()
    monkeypatch.setattr(
        creative_asset_services,
        loader_name,
        fail_loader,
    )
    client = make_production_dependency_client()
    try:
        responses = tuple(client.get(path) for path in (
            "/api/assets/inventory",
            "/api/assets/style-templates",
            f"/api/assets/style-templates/{STYLE_ID}",
            "/api/corpus/discovery",
        ))
    finally:
        creative_asset_services.load_release_taxonomy.cache_clear()

    assert [response.status_code for response in responses] == [503] * 4
    for response in responses:
        body = response.json()
        assert set(body) == {"code", "message", "correlationId"}
        assert body["code"] == "AssetCatalogNotReady"
        assert body["message"] == AssetCatalogNotReady.message
        rendered = json.dumps(body, ensure_ascii=False)
        assert str(loader_error) not in rendered
        assert str(tmp_path) not in rendered
        _assert_no_private_keys(body)


def test_invalid_category_and_missing_recommendation_body_are_422():
    client, _ = make_client()

    invalid_category = client.get(
        "/api/assets/experience-cards?category=not-approved"
    )
    missing_engine = client.post(
        "/api/projects/project-1/asset-recommendations", json={}
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


def test_recommendation_requires_and_forwards_idempotency_and_four_typed_dimensions():
    client, service = make_client()

    body = {
        **RECOMMENDATION_BODY,
        "genre": "fantasy",
        "creationStage": "drafting",
        "prohibitedDirections": ["slow_burn"],
    }
    response = client.post(
        "/api/projects/project-1/asset-recommendations",
        json=body,
    )

    assert response.status_code == 200
    command = service.recommendation_command
    assert command is not None
    assert command.idempotency_key == "i" * 64
    assert command.engine_option_id == "engine-1"
    assert command.taxonomy_version == "recommendation-taxonomy-v1.0.0"
    assert command.taxonomy_hash == "a" * 64
    assert command.genre == "fantasy"
    assert command.creation_stage == "drafting"
    assert command.prohibited_directions == ("slow_burn",)
    assert command.status == "active"


def test_recommendation_duplicate_prohibited_directions_are_safe_422_before_service():
    client, service = make_client()
    response = client.post(
        "/api/projects/project-1/asset-recommendations",
        json={
            **RECOMMENDATION_BODY,
            "prohibitedDirections": ["slow_burn", "slow_burn"],
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail", "correlationId"}
    assert len(body["detail"]) == 1
    error = body["detail"][0]
    assert error["type"] == "value_error"
    assert error["loc"] == ["body", "prohibitedDirections"]
    assert error["msg"] == "Value error, prohibited directions must be unique"
    assert service.calls == []
    _assert_no_private_keys(body)


@pytest.mark.parametrize(
    "path",
    (
        "/api/assets/style-templates/" + "s" * 37,
        "/api/assets/experience-cards/" + "c" * 37,
        "/api/projects/" + "p" * 37 + "/asset-recommendations",
    ),
)
def test_asset_route_identifiers_are_bounded_to_36_characters(path):
    client, _ = make_client()

    response = (
        client.post(path, json=RECOMMENDATION_BODY)
        if "asset-recommendations" in path
        else client.get(path)
    )

    assert response.status_code == 422


def test_catalog_not_ready_is_503_for_both_lists_and_recommendation():
    client, service = make_client()
    service.failure = AssetCatalogNotReady()

    responses = (
        client.get("/api/assets/style-templates"),
        client.get("/api/assets/experience-cards"),
        client.post(_recommendation_path(), json=RECOMMENDATION_BODY),
    )

    assert [response.status_code for response in responses] == [503, 503, 503]
    assert [response.json()["code"] for response in responses] == [
        "AssetCatalogNotReady",
        "AssetCatalogNotReady",
        "AssetCatalogNotReady",
    ]
