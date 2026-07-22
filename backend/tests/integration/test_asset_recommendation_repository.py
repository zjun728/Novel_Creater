from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from backend.domain.asset_eligibility import load_asset_eligibility_package
from backend.domain.assets import load_asset_package
from backend.repositories.assets import AssetRepository
from backend.services.assets import (
    AssetRecommendationService,
    GenerateAssetRecommendations,
)
from backend.services.contracts import SaveContractDraft
from backend.tests.integration.test_asset_seeding import service as asset_seed_service
from backend.tests.integration.test_contract_drafts import (
    ENGINE,
    PROJECT,
    _bootstrap as bootstrap_contract,
    _draft as contract_draft,
    _service as contract_service,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


ASSET_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "writer-core-v1.1.0"
    / "manifest.json"
)
TAXONOMY_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "recommendation-taxonomy-v1.0.0"
    / "manifest.json"
)


class _NoCallGateway:
    def __init__(self):
        self.calls = 0

    async def rank(self, **_kwargs):
        self.calls += 1
        raise AssertionError("disabled provider reached recommendation gateway")


class _NoCallCorpus:
    def __init__(self):
        self.calls = 0

    async def candidates(self, _query_texts):
        self.calls += 1
        raise AssertionError("disabled provider reached corpus candidates")


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_recommendation_engine_locks_parse_in_mysql(disposable_mysql):
    repository = AssetRepository()
    session = disposable_mysql.session

    inputs = await repository.lock_recommendation_inputs(
        session,
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    )
    publication_matches = await repository._publication_inputs_match(
        session,
        {
            "project_id": "00000000-0000-0000-0000-000000000001",
            "input_manifest": {
                "selection": {},
                "engine": {
                    "id": "00000000-0000-0000-0000-000000000002"
                },
                "binding": {},
                "selectedStyles": [],
                "assetCandidates": [],
                "corpusCandidates": [],
            },
        },
    )

    assert inputs["engine"] is None
    assert publication_matches is False


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_disabled_provider_persists_terminal_recommendation_without_gateway(
    disposable_mysql,
):
    session = disposable_mysql.session
    facts = await bootstrap_contract(session)
    for table in (
        "style_template_heads",
        "experience_card_heads",
        "style_templates",
        "experience_cards",
    ):
        await session.execute(f"DELETE FROM {table}")
    package = load_asset_package(ASSET_MANIFEST, mode="release")
    await asset_seed_service(disposable_mysql).seed(package)
    await contract_service(disposable_mysql).save_draft(SaveContractDraft(
        PROJECT,
        0,
        contract_draft(facts, stage="engine"),
    ))
    await session.execute(
        "UPDATE provider_profiles SET enabled=0 WHERE id IS NOT NULL"
    )

    @asynccontextmanager
    async def read_connection():
        yield session

    taxonomy = load_asset_eligibility_package(
        TAXONOMY_MANIFEST,
        asset_package=package,
        mode="release",
    )
    gateway = _NoCallGateway()
    corpus = _NoCallCorpus()
    service = AssetRecommendationService(
        AssetRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        connection_factory=read_connection,
        provider_gateway=gateway,
        corpus_service=corpus,
        taxonomy=taxonomy,
        id_factory=lambda: "83000000-0000-0000-0000-000000000001",
        clock=lambda: 1_900_000_000_200,
    )

    result = await service.recommend(GenerateAssetRecommendations(
        project_id=PROJECT,
        engine_option_id=ENGINE,
        idempotency_key="r" * 64,
        taxonomy_version=taxonomy.package_version,
        taxonomy_hash=taxonomy.manifest.eligibility_file.sha256,
        genre="fantasy",
        creation_stage="drafting",
        status="active",
        prohibited_directions=(),
    ))

    request = await session.fetchone(
        """SELECT status,attempt_id,result_hash,public_error_code,completed_at
             FROM asset_recommendation_requests
            WHERE project_id=%s AND idempotency_key=%s""",
        (PROJECT, "r" * 64),
    )
    attempts = await session.fetchone(
        "SELECT COUNT(*) AS count FROM asset_recommendation_attempts"
    )
    assert result.public_reason == "rankingUnavailable"
    assert result.ranking_unavailable is True
    assert gateway.calls == 0
    assert corpus.calls == 0
    assert request == {
        "status": "failed",
        "attempt_id": None,
        "result_hash": None,
        "public_error_code": "ASSET_RECOMMENDATION_UNAVAILABLE",
        "completed_at": 1_900_000_000_200,
    }
    assert int(attempts["count"]) == 0
