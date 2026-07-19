from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


PACKAGE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "market-sources-v1.0.0"
)
MANIFEST_PATH = PACKAGE_ROOT / "manifest.json"


def _imports():
    from backend.domain.market_sources import (
        MarketSourcePackageError,
        load_market_source_package,
    )

    return MarketSourcePackageError, load_market_source_package


def test_built_in_manifest_is_hash_bound_and_manual_only():
    _, load_market_source_package = _imports()

    package = load_market_source_package(MANIFEST_PATH)

    assert package.package_version == "market-sources-v1.0.0"
    assert {source.adapter_key for source in package.sources} == {
        "qidian_public_rank",
        "qq_reading_public_rank",
    }
    assert {source.policy.status for source in package.sources} == {"manual_only"}
    assert all(source.policy.enabled is False for source in package.sources)
    assert all(
        source.policy_hash == source.policy_content_hash()
        for source in package.sources
    )
    raw_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    child = (PACKAGE_ROOT / raw_manifest["sources_file"]["path"]).read_bytes()
    assert raw_manifest["sources_file"]["sha256"] == sha256(child).hexdigest()


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
