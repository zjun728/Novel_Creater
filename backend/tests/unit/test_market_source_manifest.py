from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


PACKAGE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "market-sources-v1.1.0"
)
MANIFEST_PATH = PACKAGE_ROOT / "manifest.json"


def _imports():
    from backend.domain.market_sources import (
        MarketSourcePackageError,
        load_market_source_package,
    )

    return MarketSourcePackageError, load_market_source_package


def test_built_in_manifest_is_hash_bound_and_has_exact_verified_registry():
    _, load_market_source_package = _imports()

    package = load_market_source_package(MANIFEST_PATH)

    assert package.package_version == "market-sources-v1.1.0"
    assert {
        source.stable_key: source.adapter_key for source in package.sources
    } == {
        "qq-reading.male-popular": "qq_reading_public_rank",
        "qidian.newsign": "qidian_public_rank",
        "fanqie.reading": "fanqie_public_rank",
        "qimao.public-catalog": "qimao_public_rank",
        "shuqi.public-catalog": "shuqi_manual_snapshot",
        "xxsy.xiaoxiang-ticket": "xxsy_public_rank",
        "zongheng.monthly": "zongheng_public_rank",
        "readnovel.original-monthly-ticket": "readnovel_public_rank",
        "jjwxc.quarterly-score": "jjwxc_public_rank",
        "heiyan.daily-recommendation": "heiyan_public_rank",
    }
    verified = {
        source.adapter_key
        for source in package.sources
        if source.policy.status == "verified_public"
    }
    assert verified == {
        "qq_reading_public_rank",
        "qimao_public_rank",
        "heiyan_public_rank",
        "readnovel_public_rank",
        "xxsy_public_rank",
    }
    assert {
        source.adapter_key
        for source in package.sources
        if source.policy.status == "manual_only"
    } == {
        "qidian_public_rank",
        "fanqie_public_rank",
        "zongheng_public_rank",
        "jjwxc_public_rank",
        "shuqi_manual_snapshot",
    }
    assert len(package.sources) == 10
    assert all(source.policy.enabled is False for source in package.sources)
    assert all(source.can_manual_import for source in package.sources)
    assert {source.adapter_key for source in package.sources if source.can_refresh} == verified
    assert all(not source.can_schedule for source in package.sources)
    assert all(
        set(source.public_config) == {"platform", "rankingName", "category"}
        for source in package.sources
    )
    assert "chapter" not in json.dumps(
        [dict(source.public_config) for source in package.sources],
        ensure_ascii=False,
    ).casefold()
    assert all(
        source.policy_hash == source.policy_content_hash()
        for source in package.sources
    )
    raw_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    child = (PACKAGE_ROOT / raw_manifest["sources_file"]["path"]).read_bytes()
    assert raw_manifest["sources_file"]["sha256"] == sha256(child).hexdigest()

    by_key = {source.stable_key: source for source in package.sources}
    assert by_key["jjwxc.quarterly-score"].display_name == "晋江季度作品积分榜"
    assert by_key["jjwxc.quarterly-score"].public_config["rankingName"] == "quarterly_score"
    assert by_key["jjwxc.quarterly-score"].public_config["category"] == "female"
    assert by_key["jjwxc.quarterly-score"].policy.status == "manual_only"
    assert by_key["heiyan.daily-recommendation"].display_name == "黑岩每日推荐榜"
    assert by_key["heiyan.daily-recommendation"].public_config["rankingName"] == "daily_recommendation"
    assert by_key["readnovel.original-monthly-ticket"].display_name == "小说阅读网原创月票榜"
    assert by_key["readnovel.original-monthly-ticket"].public_config == {
        "platform": "readnovel",
        "rankingName": "monthly_ticket",
        "category": "female",
    }
    assert (
        by_key["readnovel.original-monthly-ticket"].policy.policy_version
        == "readnovel-public-rank-v2"
    )
    assert by_key["zongheng.monthly"].public_config["rankingName"] == "monthly_ticket"
    assert by_key["zongheng.monthly"].policy.status == "manual_only"
    assert by_key["xxsy.xiaoxiang-ticket"].display_name == "潇湘票榜"
    assert by_key["xxsy.xiaoxiang-ticket"].public_config == {
        "platform": "xxsy",
        "rankingName": "xiaoxiang_ticket",
        "category": "female",
    }
    assert {
        by_key[key].policy.policy_version
        for key in (
            "qq-reading.male-popular",
            "qimao.public-catalog",
            "zongheng.monthly",
        )
    } == {
        "qq-reading-public-rank-v2",
        "qimao-public-rank-v2",
        "zongheng-public-rank-v2",
    }
    assert all(source.policy.request_interval_seconds == 3600 for source in package.sources)
    assert set(by_key["qq-reading.male-popular"].policy.path_prefixes) == {
        "/book-rank",
        "/book-detail/",
    }
    assert set(by_key["qimao.public-catalog"].policy.path_prefixes) == {
        "/paihang/",
        "/shuku/",
    }
    assert "/detail/" in by_key["zongheng.monthly"].policy.path_prefixes
    assert "/onebook.php" in by_key["jjwxc.quarterly-score"].policy.path_prefixes
    assert set(by_key["heiyan.daily-recommendation"].policy.path_prefixes) == {
        "/top/monthly/day",
        "/book/",
    }
    assert set(by_key["readnovel.original-monthly-ticket"].policy.path_prefixes) == {
        "/rank/ywyuepiao",
        "/book/",
    }
    assert set(by_key["xxsy.xiaoxiang-ticket"].policy.path_prefixes) == {
        "/rank/xxyuepiao",
        "/book/",
    }


def test_legacy_v1_package_remains_parseable():
    _, load_market_source_package = _imports()
    legacy = PACKAGE_ROOT.parent / "market-sources-v1.0.0" / "manifest.json"

    assert load_market_source_package(legacy).package_version == "market-sources-v1.0.0"


def test_old_checked_at_remains_audit_data_not_a_refresh_kill_switch():
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import SourcePolicy
    from backend.services.market_sources import MarketSourceService

    policy = SourcePolicy(
        status="verified_public",
        checkedAt=1_700_000_000_000,
        evidenceURL="https://book.qq.com/book-rank",
        evidenceHash="0" * 64,
        allowedOrigins=("https://book.qq.com",),
        pathPrefixes=("/book-rank", "/book-detail/"),
        requestIntervalSeconds=3600,
        policyVersion="qq-reading-public-rank-v2",
        enabled=False,
    )
    service = MarketSourceService(
        object(),
        object(),
        connection_factory=lambda: None,
        clock=lambda: 1_900_000_000_000,
    )
    row = {
        "id": "source-id",
        "stable_key": "qq-reading.male-popular",
        "display_name": "QQ 阅读男生人气榜",
        "adapter_key": "qq_reading_public_rank",
        "public_config": {
            "platform": "qq_reading",
            "rankingName": "male_popular",
            "category": "male",
        },
        "policy": policy,
        "policy_hash": canonical_hash(policy),
        "policy_revision": 1,
    }

    assert service._public_source(row)["automatic_refresh_allowed"] is True


def test_source_public_config_is_deeply_frozen_and_hash_stable():
    from backend.domain.json_contracts import canonical_hash
    from backend.domain.market_sources import MarketSourceDefinition

    values = json.loads(
        (PACKAGE_ROOT / "sources.json").read_text(encoding="utf-8")
    )[0]
    original_config = values["publicConfig"]
    source = MarketSourceDefinition.model_validate(values)
    expected_hash = canonical_hash(source)

    original_config["platform"] = "mutated"

    assert source.public_config["platform"] == "qidian"
    with pytest.raises(TypeError):
        source.public_config["platform"] = "mutated"
    assert canonical_hash(source) == expected_hash
    assert source.model_dump(mode="json", by_alias=True)["publicConfig"] == {
        "platform": "qidian",
        "rankingName": "newsign",
        "category": "male",
    }


def test_registry_contains_no_credentials_headers_or_executable_urls():
    _, load_market_source_package = _imports()

    package = load_market_source_package(MANIFEST_PATH)
    rendered = json.dumps(
        package.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
    ).casefold()

    for forbidden in (
        "cookie",
        "authorization",
        "api_key",
        "apikey",
        "credential",
        "headers",
        "javascript:",
    ):
        assert forbidden not in rendered
    assert all("url" not in key.casefold() for source in package.sources for key in source.public_config)


def test_loader_rejects_child_hash_mismatch_before_parsing():
    MarketSourcePackageError, load_market_source_package = _imports()
    with TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
        root = Path(temporary)
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (root / manifest["sources_file"]["path"]).write_text(
            "not-json", encoding="utf-8"
        )

        with pytest.raises(MarketSourcePackageError) as captured:
            load_market_source_package(root / "manifest.json")

    assert captured.value.code == "MARKET_SOURCE_FILE_HASH_INVALID"
    assert "not-json" not in str(captured.value)


def test_loader_rejects_unbounded_or_extra_source_configuration():
    MarketSourcePackageError, load_market_source_package = _imports()
    with TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
        root = Path(temporary)
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        sources = json.loads(
            (PACKAGE_ROOT / "sources.json").read_text(encoding="utf-8")
        )
        sources[0]["publicConfig"]["headers"] = {"Cookie": "secret"}
        raw = json.dumps(sources, ensure_ascii=False).encode("utf-8")
        (root / "sources.json").write_bytes(raw)
        manifest["sources_file"]["sha256"] = sha256(raw).hexdigest()
        (root / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

        with pytest.raises(MarketSourcePackageError) as captured:
            load_market_source_package(root / "manifest.json")

        assert captured.value.code == "MARKET_SOURCE_PACKAGE_INVALID"
