from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from backend.domain.assets import (
    ASSET_CATEGORIES,
    AssetPackage,
    AssetPackageError,
    load_asset_package,
    validate_asset_package,
)
from backend.domain.json_contracts import canonical_hash


def _style(index: int, *, approved: bool = False) -> dict[str, object]:
    payload = {
        "schemaVersion": "style-template-v1",
        "reading_experience": f"Synthetic reading experience {index}.",
        "applicability": [f"Synthetic application {index}"],
        "standard_scene_example": f"Standard scene rendered in style {index}.",
        "complete_application_example": f"Complete original application {index}.",
        "narrative_distance": f"Narrative distance {index}.",
        "rhythm": f"Rhythm {index}.",
        "diction_density": f"Diction density {index}.",
        "dialogue": f"Dialogue strategy {index}.",
        "subtext": f"Subtext strategy {index}.",
        "character_voices": f"Voice strategy {index}.",
        "emotion": f"Emotion strategy {index}.",
        "interiority": f"Interiority strategy {index}.",
        "action": f"Action strategy {index}.",
        "explanation": f"Explanation strategy {index}.",
        "environment": f"Environment strategy {index}.",
        "body_response": f"Body response strategy {index}.",
        "preferred_techniques": [f"Preferred technique {index}"],
        "risks": [f"Risk {index}"],
        "original_anchor": f"Original synthetic anchor {index}.",
    }
    return {
        "stable_key": f"style.synthetic-{index}",
        "revision": 1,
        "name": f"Synthetic Style {index}",
        "payload": payload,
        "provenance": {
            "reviewer": "Synthetic Reviewer" if approved else None,
            "review_time": "2026-07-12T00:00:00+00:00" if approved else None,
            "decision": "approved" if approved else ("candidate", "rewrite", "rejected")[index % 3],
        },
        "content_hash": canonical_hash(payload),
    }


def _card(index: int, *, approved: bool = False) -> dict[str, object]:
    category = ASSET_CATEGORIES[index % len(ASSET_CATEGORIES)]
    payload = {
        "schemaVersion": "experience-card-v1",
        "category": category,
        "method": f"Synthetic method {index}",
        "applicability": [f"Applicable situation {index}"],
        "non_applicability": [f"Non-applicable situation {index}"],
        "risks": [f"Synthetic risk {index}"],
        "original_micro_demo": f"Original synthetic micro-demo {index}.",
    }
    return {
        "stable_key": f"card.synthetic-{index}",
        "revision": 1,
        "title": f"Synthetic Card {index}",
        "category": category,
        "payload": payload,
        "provenance": {
            "reviewer": "Synthetic Reviewer" if approved else None,
            "review_time": "2026-07-12T00:00:00+00:00" if approved else None,
            "decision": "approved" if approved else ("candidate", "rewrite", "rejected")[index % 3],
        },
        "content_hash": canonical_hash(payload),
    }


def valid_values(*, approved: bool = False) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    styles = [_style(index, approved=approved) for index in range(8)]
    cards = [_card(index, approved=approved) for index in range(40)]
    manifest = {
        "package_version": "writer-core-v1.1.0",
        "styles_file": {"path": "style_templates.json", "sha256": "a" * 64},
        "experience_cards_file": {"path": "experience_cards.json", "sha256": "b" * 64},
    }
    return manifest, styles, cards


def package_from_values(*, approved: bool = False) -> AssetPackage:
    manifest, styles, cards = valid_values(approved=approved)
    return AssetPackage.model_validate(
        {"manifest": manifest, "styles": styles, "experience_cards": cards}
    )


def package_dict(*, approved: bool = False) -> dict[str, object]:
    manifest, styles, cards = valid_values(approved=approved)
    return {"manifest": manifest, "styles": styles, "experience_cards": cards}


def _write_package(root: Path, *, approved: bool = False) -> Path:
    manifest, styles, cards = valid_values(approved=approved)
    style_bytes = json.dumps(styles, ensure_ascii=False, indent=2).encode("utf-8")
    card_bytes = json.dumps(cards, ensure_ascii=False, indent=2).encode("utf-8")
    (root / "style_templates.json").write_bytes(style_bytes)
    (root / "experience_cards.json").write_bytes(card_bytes)
    manifest["styles_file"]["sha256"] = sha256(style_bytes).hexdigest()
    manifest["experience_cards_file"]["sha256"] = sha256(card_bytes).hexdigest()
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def test_structural_package_accepts_exact_synthetic_inventory_and_decisions():
    package = package_from_values()

    result = validate_asset_package(package, mode="structural")

    assert result is package
    assert len(result.styles) == 8
    assert len(result.experience_cards) == 40
    assert {card.category for card in result.experience_cards} == set(ASSET_CATEGORIES)
    assert len({item.content_hash for item in (*result.styles, *result.experience_cards)}) == 48
    assert {item.provenance.decision for item in (*result.styles, *result.experience_cards)} <= {
        "approved", "candidate", "rewrite", "rejected"
    }


def test_validator_accepts_a_raw_synthetic_package_dict():
    result = validate_asset_package(package_dict(), mode="structural")

    assert isinstance(result, AssetPackage)
    assert result.package_version == "writer-core-v1.1.0"


def test_validator_wraps_raw_dict_validation_errors_as_stable_package_errors():
    values = package_dict()
    values["experience_cards"][0]["payload"]["rawExcerpt"] = "forbidden"

    with pytest.raises(AssetPackageError, match="rawExcerpt"):
        validate_asset_package(values, mode="structural")


@pytest.mark.parametrize("style_count", [7, 9])
def test_structural_package_requires_exactly_eight_styles(style_count: int):
    package = package_from_values()
    changed = package.model_copy(update={"styles": package.styles[:style_count]})
    if style_count == 9:
        extra = deepcopy(package.styles[-1].model_dump(mode="json"))
        extra["stable_key"] = "style.synthetic-extra"
        extra["payload"]["original_anchor"] = "Unique extra anchor."
        extra["content_hash"] = canonical_hash(extra["payload"])
        changed = package.model_copy(
            update={"styles": (*package.styles, type(package.styles[0]).model_validate(extra))}
        )

    with pytest.raises(AssetPackageError, match="exactly 8 styles"):
        validate_asset_package(changed, mode="structural")


@pytest.mark.parametrize("card_count", [39, 61])
def test_structural_package_requires_forty_to_sixty_cards(card_count: int):
    _, _, card_values = valid_values()
    if card_count > len(card_values):
        card_values.extend(_card(index) for index in range(40, card_count))
    package = package_from_values().model_copy(
        update={
            "experience_cards": tuple(
                type(package_from_values().experience_cards[0]).model_validate(value)
                for value in card_values[:card_count]
            )
        }
    )

    with pytest.raises(AssetPackageError, match="40 to 60"):
        validate_asset_package(package, mode="structural")


def test_structural_package_requires_all_eight_categories():
    package = package_from_values()
    cards = tuple(card for card in package.experience_cards if card.category != "suspense")
    replacement_values = _card(100)
    replacement_values["category"] = "plot_organization"
    replacement_values["payload"]["category"] = "plot_organization"
    replacement_values["content_hash"] = canonical_hash(replacement_values["payload"])
    replacement = type(package.experience_cards[0]).model_validate(replacement_values)
    changed = package.model_copy(update={"experience_cards": (*cards, replacement, replacement, replacement, replacement, replacement)[:40]})

    with pytest.raises(AssetPackageError, match="all asset categories"):
        validate_asset_package(changed, mode="structural")


@pytest.mark.parametrize("collection_name", ["styles", "experience_cards"])
def test_structural_package_rejects_duplicate_stable_keys(collection_name: str):
    package = package_from_values()
    values = list(getattr(package, collection_name))
    values[1] = values[1].model_copy(update={"stable_key": values[0].stable_key})
    changed = package.model_copy(update={collection_name: tuple(values)})

    with pytest.raises(AssetPackageError, match="duplicate stable_key"):
        validate_asset_package(changed, mode="structural")


@pytest.mark.parametrize("field", ["method", "original_micro_demo"])
def test_structural_package_rejects_normalized_method_or_demo_duplicates(field: str):
    package = package_from_values()
    values = list(package.experience_cards)
    payload = values[1].payload.model_dump(mode="json")
    payload[field] = "  " + getattr(values[0].payload, field).upper() + "  "
    values[1] = values[1].model_copy(
        update={"payload": type(values[1].payload).model_validate(payload)}
    )
    changed = package.model_copy(update={"experience_cards": tuple(values)})

    with pytest.raises(AssetPackageError, match=f"duplicate normalized {field}"):
        validate_asset_package(changed, mode="structural")


def test_structural_package_rejects_content_hash_mismatch_and_duplicates():
    package = package_from_values()
    styles = list(package.styles)
    styles[0] = styles[0].model_copy(update={"content_hash": "0" * 64})
    mismatch = package.model_copy(update={"styles": tuple(styles)})
    with pytest.raises(AssetPackageError, match="content_hash mismatch"):
        validate_asset_package(mismatch, mode="structural")

    styles = list(package.styles)
    styles[1] = styles[1].model_copy(update={"content_hash": styles[0].content_hash})
    duplicate = package.model_copy(update={"styles": tuple(styles)})
    with pytest.raises(AssetPackageError, match="duplicate content_hash"):
        validate_asset_package(duplicate, mode="structural")


def test_release_requires_approved_decision_reviewer_and_review_time():
    with pytest.raises(AssetPackageError, match="release review metadata"):
        validate_asset_package(package_from_values(), mode="release")

    approved = package_from_values(approved=True)
    assert validate_asset_package(approved, mode="release") is approved


def test_release_rejects_invalid_or_timezone_naive_review_time():
    for review_time in ("not-a-time", "2026-07-12T00:00:00"):
        values = package_dict(approved=True)
        values["styles"][0]["provenance"]["review_time"] = review_time

        with pytest.raises(AssetPackageError, match="review_time"):
            validate_asset_package(values, mode="release")


def test_unknown_validation_mode_is_rejected():
    with pytest.raises(AssetPackageError, match="validation mode"):
        validate_asset_package(package_from_values(), mode="preview")


def test_loader_checks_child_sha256_before_json_parsing(tmp_path: Path):
    manifest_path = _write_package(tmp_path)
    (tmp_path / "style_templates.json").write_text("not-json", encoding="utf-8")

    with pytest.raises(AssetPackageError, match="styles_file sha256 mismatch"):
        load_asset_package(manifest_path, mode="structural")


def test_loader_checks_canonical_content_hash_after_parsing(tmp_path: Path):
    manifest_path = _write_package(tmp_path)
    styles_path = tmp_path / "style_templates.json"
    styles = json.loads(styles_path.read_text(encoding="utf-8"))
    styles[0]["content_hash"] = "0" * 64
    style_bytes = json.dumps(styles, ensure_ascii=False).encode("utf-8")
    styles_path.write_bytes(style_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["styles_file"]["sha256"] = sha256(style_bytes).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AssetPackageError, match="content_hash mismatch"):
        load_asset_package(manifest_path, mode="structural")


def test_loader_returns_same_deterministic_package_for_repeated_reads(tmp_path: Path):
    manifest_path = _write_package(tmp_path, approved=True)

    first = load_asset_package(manifest_path, mode="release")
    second = load_asset_package(manifest_path, mode="release")

    assert first == second


def test_loader_wraps_forbidden_raw_excerpt_as_stable_package_error(tmp_path: Path):
    manifest_path = _write_package(tmp_path)
    cards_path = tmp_path / "experience_cards.json"
    cards = json.loads(cards_path.read_text(encoding="utf-8"))
    cards[0]["payload"]["rawExcerpt"] = "forbidden source text"
    card_bytes = json.dumps(cards, ensure_ascii=False).encode("utf-8")
    cards_path.write_bytes(card_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["experience_cards_file"]["sha256"] = sha256(card_bytes).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AssetPackageError, match="rawExcerpt"):
        load_asset_package(manifest_path, mode="structural")
