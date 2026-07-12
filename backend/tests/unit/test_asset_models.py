from __future__ import annotations

from datetime import datetime, timezone
import traceback
from typing import get_args

import pytest
from pydantic import ValidationError

from backend.domain import assets
from backend.domain.assets import (
    ASSET_CATEGORIES,
    PACKAGE_VERSION,
    AssetCategory,
    AssetFile,
    AssetManifest,
    AssetPackage,
    ExperienceCardRevision,
    StyleTemplateRevision,
)
from backend.domain.json_contracts import canonical_hash


def style_payload() -> dict[str, object]:
    return {
        "schemaVersion": "style-template-v1",
        "reading_experience": "Measured tension with lucid emotional stakes.",
        "applicability": ["Long-form ensemble fantasy"],
        "non_applicability": ["A neutral reference entry without a scene"],
        "standard_scene_example": "The same gate closes while three witnesses disagree.",
        "complete_application_example": "A complete original scene built around delayed recognition.",
        "narrative_distance": "Close third person with controlled pull-backs.",
        "rhythm": "Alternating compressed action and reflective pauses.",
        "diction_density": "Concrete and medium-density.",
        "dialogue": "Dialogue changes the balance of power.",
        "subtext": "Characters conceal the cost they fear most.",
        "character_voices": "Each speaker uses a distinct decision vocabulary.",
        "emotion": "Emotion appears through choices and sensory attention.",
        "interiority": "Interior thought remains selective and consequential.",
        "action": "Actions expose priorities.",
        "explanation": "Explanation follows reader need.",
        "environment": "Setting applies pressure to choices.",
        "body_response": "Physical response is specific and non-repetitive.",
        "preferred_techniques": ["Escalate through irreversible choices"],
        "risks": ["Over-compression"],
        "original_anchor": "Synthetic anchor style-1.",
    }


def provenance(*, approved: bool = True) -> dict[str, object]:
    return {
        "reviewer": "Synthetic Reviewer" if approved else None,
        "review_time": (
            datetime(2026, 7, 12, tzinfo=timezone.utc).isoformat()
            if approved
            else None
        ),
        "decision": "approved" if approved else "candidate",
    }


def style_values() -> dict[str, object]:
    payload = style_payload()
    return {
        "stable_key": "style.synthetic-1",
        "revision": 1,
        "name": "Synthetic Style One",
        "payload": payload,
        "provenance": provenance(),
        "content_hash": canonical_hash(payload),
    }


def card_values() -> dict[str, object]:
    payload = {
        "schemaVersion": "experience-card-v1",
        "category": "plot_organization",
        "method": "Synthetic method one",
        "applicability": ["Stories with competing goals"],
        "non_applicability": ["Static reference material"],
        "risks": ["Mechanical alternation"],
        "original_micro_demo": "A courier burns one map and quietly keeps another.",
    }
    return {
        "stable_key": "card.synthetic-1",
        "revision": 1,
        "title": "Synthetic Card One",
        "category": "plot_organization",
        "payload": payload,
        "provenance": provenance(),
        "content_hash": canonical_hash(payload),
    }


def test_revision_models_are_strict_frozen_and_forbid_unknown_fields():
    style = StyleTemplateRevision.model_validate(style_values())
    card = ExperienceCardRevision.model_validate(card_values())

    assert style.model_config["strict"] is True
    assert style.model_config["frozen"] is True
    assert style.model_config["extra"] == "forbid"
    assert card.model_config == style.model_config

    with pytest.raises(ValidationError):
        style.revision = 2
    with pytest.raises(ValidationError):
        StyleTemplateRevision.model_validate({**style_values(), "unknown": True})
    with pytest.raises(ValidationError):
        StyleTemplateRevision.model_validate({**style_values(), "revision": "1"})


def test_prompt_payloads_forbid_source_leaks_and_unknown_fields():
    values = style_values()
    values["payload"] = {**values["payload"], "rawExcerpt": "forbidden"}

    with pytest.raises(ValidationError, match="rawExcerpt"):
        StyleTemplateRevision.model_validate(values)

    card = card_values()
    card["payload"] = {**card["payload"], "sourcePath": "C:/private/book.txt"}
    with pytest.raises(ValidationError, match="sourcePath"):
        ExperienceCardRevision.model_validate(card)


@pytest.mark.parametrize("asset_values", [style_values, card_values])
def test_prompt_payload_requires_schema_version(asset_values):
    values = asset_values()
    values["payload"].pop("schemaVersion")
    model = (
        StyleTemplateRevision
        if asset_values is style_values
        else ExperienceCardRevision
    )

    with pytest.raises(ValidationError, match="schemaVersion"):
        model.model_validate(values)


def test_review_metadata_is_allowed_only_in_provenance():
    style = style_values()
    style["payload"] = {**style["payload"], "reviewer": "leak"}
    with pytest.raises(ValidationError, match="reviewer"):
        StyleTemplateRevision.model_validate(style)

    parsed = StyleTemplateRevision.model_validate(style_values())
    assert parsed.provenance.reviewer == "Synthetic Reviewer"
    assert "reviewer" not in parsed.payload.model_dump()


def test_experience_category_must_match_prompt_payload():
    values = card_values()
    values["category"] = "dialogue"

    with pytest.raises(ValidationError, match="category"):
        ExperienceCardRevision.model_validate(values)


def test_required_strings_reject_whitespace_only_values():
    values = card_values()
    values["payload"] = {**values["payload"], "method": "   "}

    with pytest.raises(ValidationError, match="method"):
        ExperienceCardRevision.model_validate(values)


@pytest.mark.parametrize(
    ("value", "match"),
    [(["   "], "applicability"), (["item"] * 33, "applicability")],
)
def test_prompt_tuple_fields_reject_blank_elements_and_excess_items(value, match):
    values = card_values()
    values["payload"] = {**values["payload"], "applicability": value}

    with pytest.raises(ValidationError, match=match):
        ExperienceCardRevision.model_validate(values)


def test_style_non_applicability_is_required_bounded_and_frozen():
    values = style_values()
    values["payload"].pop("non_applicability")
    with pytest.raises(ValidationError, match="non_applicability"):
        StyleTemplateRevision.model_validate(values)

    for invalid in ([], ["   "], ["boundary"] * 33):
        values = style_values()
        values["payload"]["non_applicability"] = invalid
        with pytest.raises(ValidationError, match="non_applicability"):
            StyleTemplateRevision.model_validate(values)

    parsed = StyleTemplateRevision.model_validate(style_values())
    assert parsed.payload.non_applicability == (
        "A neutral reference entry without a scene",
    )


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (lambda values: values.update(stable_key="k" * 161), "stable_key"),
        (
            lambda values: values["payload"].update(
                complete_application_example="x" * 20_001
            ),
            "complete_application_example",
        ),
    ],
)
def test_asset_fields_enforce_stable_key_and_large_text_limits(mutator, match):
    values = style_values()
    mutator(values)

    with pytest.raises(ValidationError, match=match):
        StyleTemplateRevision.model_validate(values)


def test_manifest_and_package_are_strict_frozen_models():
    manifest = AssetManifest.model_validate(
        {
            "package_version": "writer-core-v1.1.0",
            "styles_file": {"path": "styles.json", "sha256": "a" * 64},
            "experience_cards_file": {"path": "cards.json", "sha256": "b" * 64},
        }
    )
    style = StyleTemplateRevision.model_validate(style_values())
    card = ExperienceCardRevision.model_validate(card_values())
    package = AssetPackage(
        manifest=manifest,
        styles=(style,) * 10,
        experience_cards=(card,) * 64,
    )

    for model in (manifest, package):
        assert model.model_config["strict"] is True
        assert model.model_config["frozen"] is True
        assert model.model_config["extra"] == "forbid"
    assert package.package_version == "writer-core-v1.1.0"

    with pytest.raises(ValidationError):
        AssetManifest.model_validate(
            {
                **manifest.model_dump(mode="json"),
                "package_version": "writer-core-v1.0.0",
            }
        )


@pytest.mark.parametrize(
    "malicious_path",
    [
        "/absolute/SECRET_PATH.json",
        "../SECRET_PATH.json",
        "nested/../../SECRET_PATH.json",
        "..\\SECRET_PATH.json",
        "C:/absolute/SECRET_PATH.json",
        "C:\\absolute\\SECRET_PATH.json",
        "C:drive-relative-SECRET_PATH.json",
        "\\SECRET_PATH.json",
        "\\\\server\\share\\SECRET_PATH.json",
    ],
)
def test_asset_file_rejects_posix_and_windows_non_relative_paths_without_echo(
    malicious_path: str,
):
    with pytest.raises(ValidationError) as captured:
        AssetFile.model_validate({"path": malicious_path, "sha256": "a" * 64})

    rendered = str(captured.value) + "".join(
        traceback.format_exception(captured.value)
    )
    assert malicious_path not in rendered
    assert "SECRET_PATH" not in rendered


def test_asset_file_accepts_portable_relative_json_path():
    parsed = AssetFile.model_validate(
        {"path": "nested/assets/styles.json", "sha256": "a" * 64}
    )

    assert parsed.path == "nested/assets/styles.json"


def test_asset_package_model_enforces_inventory_lengths_directly():
    manifest = AssetManifest.model_validate(
        {
            "package_version": PACKAGE_VERSION,
            "styles_file": {"path": "styles.json", "sha256": "a" * 64},
            "experience_cards_file": {"path": "cards.json", "sha256": "b" * 64},
        }
    )
    style = StyleTemplateRevision.model_validate(style_values())
    card = ExperienceCardRevision.model_validate(card_values())

    for style_count in (9, 11):
        with pytest.raises(ValidationError):
            AssetPackage.model_validate(
                {
                    "manifest": manifest,
                    "styles": [style] * style_count,
                    "experience_cards": [card] * 64,
                }
            )
    for card_count in (63, 65):
        with pytest.raises(ValidationError):
            AssetPackage.model_validate(
                {
                    "manifest": manifest,
                    "styles": [style] * 10,
                    "experience_cards": [card] * card_count,
                }
            )


def test_literal_contracts_have_one_exact_runtime_source():
    expected_categories = (
        "plot_organization",
        "ensemble",
        "dialogue",
        "emotion",
        "interiority",
        "information_release",
        "pacing",
        "suspense",
        "long_arc_continuity",
        "progression_economy",
        "character_arcs",
        "action_conflict",
    )
    expected_category_counts = {
        "plot_organization": 6,
        "ensemble": 6,
        "dialogue": 6,
        "emotion": 6,
        "interiority": 6,
        "information_release": 6,
        "pacing": 6,
        "suspense": 6,
        "long_arc_continuity": 4,
        "progression_economy": 4,
        "character_arcs": 4,
        "action_conflict": 4,
    }

    assert ASSET_CATEGORIES == expected_categories
    assert get_args(AssetCategory) == ASSET_CATEGORIES
    assert dict(assets.ASSET_CATEGORY_COUNTS) == expected_category_counts
    assert get_args(assets.PackageVersion) == (PACKAGE_VERSION,)
