from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.domain.assets import (
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
    package = AssetPackage(
        manifest=manifest,
        styles=(StyleTemplateRevision.model_validate(style_values()),),
        experience_cards=(ExperienceCardRevision.model_validate(card_values()),),
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
