from __future__ import annotations

from copy import deepcopy
from importlib import import_module, util
import json
from pathlib import Path

import pytest

from backend.domain.assets import load_asset_package


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ASSET_MANIFEST = (
    BACKEND_ROOT / "assets" / "writer-core-v1.1.0" / "manifest.json"
)
TAXONOMY_MANIFEST = (
    BACKEND_ROOT
    / "assets"
    / "recommendation-taxonomy-v1.0.0"
    / "manifest.json"
)
APPROVED_ASSETS = load_asset_package(ASSET_MANIFEST, mode="release")


def _domain():
    assert util.find_spec("backend.domain.asset_eligibility") is not None, (
        "typed asset eligibility domain is missing"
    )
    return import_module("backend.domain.asset_eligibility")


def _write_package(tmp_path: Path, eligibility: object, manifest: dict) -> Path:
    eligibility_path = tmp_path / "eligibility.json"
    eligibility_path.write_text(
        json.dumps(eligibility, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return manifest_path


def test_release_taxonomy_maps_all_74_exact_approved_asset_hashes():
    domain = _domain()

    taxonomy = domain.load_asset_eligibility_package(
        TAXONOMY_MANIFEST,
        asset_package=APPROVED_ASSETS,
        mode="release",
    )

    assert taxonomy.package_version == "recommendation-taxonomy-v1.0.0"
    assert taxonomy.asset_package_version == "writer-core-v1.1.0"
    assert len(taxonomy.entries) == 74
    expected = {
        ("style", asset.stable_key, asset.content_hash)
        for asset in APPROVED_ASSETS.styles
    } | {
        ("experience_card", asset.stable_key, asset.content_hash)
        for asset in APPROVED_ASSETS.experience_cards
    }
    actual = {
        (entry.asset_type, entry.stable_key, entry.asset_content_hash)
        for entry in taxonomy.entries
    }
    assert actual == expected
    assert all(entry.genres for entry in taxonomy.entries)
    assert all(entry.channels for entry in taxonomy.entries)
    assert all(entry.creation_stages for entry in taxonomy.entries)
    assert all(entry.writing_purposes for entry in taxonomy.entries)
    assert all(
        isinstance(entry.prohibited_directions, tuple)
        for entry in taxonomy.entries
    )


def test_release_taxonomy_manifest_is_content_addressed_and_fails_closed(
    tmp_path: Path,
):
    domain = _domain()
    raw_manifest = json.loads(TAXONOMY_MANIFEST.read_text(encoding="utf-8"))
    raw_eligibility = json.loads(
        (
            TAXONOMY_MANIFEST.parent
            / raw_manifest["eligibility_file"]["path"]
        ).read_text(encoding="utf-8")
    )

    tampered = deepcopy(raw_eligibility)
    tampered["entries"][0]["genres"] = ["romance"]
    manifest_path = _write_package(tmp_path, tampered, raw_manifest)

    with pytest.raises(domain.AssetEligibilityPackageError) as captured:
        domain.load_asset_eligibility_package(
            manifest_path,
            asset_package=APPROVED_ASSETS,
            mode="release",
        )

    assert captured.value.code == "ASSET_ELIGIBILITY_SHA256_MISMATCH"
    assert str(tmp_path) not in str(captured.value)


def test_release_taxonomy_rejects_asset_hash_drift_even_with_rehashed_child(
    tmp_path: Path,
):
    domain = _domain()
    raw_manifest = json.loads(TAXONOMY_MANIFEST.read_text(encoding="utf-8"))
    raw_eligibility = json.loads(
        (
            TAXONOMY_MANIFEST.parent
            / raw_manifest["eligibility_file"]["path"]
        ).read_text(encoding="utf-8")
    )
    raw_eligibility["entries"][0]["assetContentHash"] = "0" * 64
    child_bytes = json.dumps(
        raw_eligibility,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    from hashlib import sha256

    raw_manifest["eligibility_file"]["sha256"] = sha256(child_bytes).hexdigest()
    manifest_path = _write_package(tmp_path, raw_eligibility, raw_manifest)

    with pytest.raises(domain.AssetEligibilityPackageError) as captured:
        domain.load_asset_eligibility_package(
            manifest_path,
            asset_package=APPROVED_ASSETS,
            mode="release",
        )

    assert captured.value.code == "ASSET_ELIGIBILITY_COVERAGE_MISMATCH"


def test_deterministic_eligibility_uses_only_typed_metadata_and_status():
    domain = _domain()
    taxonomy = domain.load_asset_eligibility_package(
        TAXONOMY_MANIFEST,
        asset_package=APPROVED_ASSETS,
        mode="release",
    )
    entry = taxonomy.entries[0]
    query = domain.AssetEligibilityQuery(
        genre=entry.genres[0],
        channel=entry.channels[0],
        creation_stage=entry.creation_stages[0],
        writing_purpose=entry.writing_purposes[0],
        prohibited_directions=(),
    )

    assert domain.is_asset_eligible(entry, query, status="active") is True
    assert domain.is_asset_eligible(entry, query, status="archived") is False
    if entry.prohibited_directions:
        blocked = query.model_copy(
            update={
                "prohibited_directions": (entry.prohibited_directions[0],)
            }
        )
        assert (
            domain.is_asset_eligible(entry, blocked, status="active") is False
        )

    source = (
        BACKEND_ROOT / "domain" / "asset_eligibility.py"
    ).read_text(encoding="utf-8")
    assert "applicability" not in source.casefold()
    assert "non_applicability" not in source.casefold()


def test_taxonomy_models_are_strict_frozen_and_reject_unknown_typed_values():
    domain = _domain()
    taxonomy = domain.load_asset_eligibility_package(
        TAXONOMY_MANIFEST,
        asset_package=APPROVED_ASSETS,
        mode="release",
    )
    values = taxonomy.entries[0].model_dump(mode="json", by_alias=True)
    values["genres"] = ["not-a-typed-genre"]

    with pytest.raises(Exception):
        domain.AssetEligibilityEntry.model_validate(values)
    with pytest.raises(Exception):
        taxonomy.entries[0].genres = ("general",)
