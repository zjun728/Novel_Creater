from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from backend.domain.canon import (
    AliasResolution,
    AssertionOperator,
    CanonValidationError,
    ConfirmationStatus,
    EntityType,
    FactKind,
    ValueCardinality,
    normalize_name,
    resolve_alias,
)


def test_domain_enums_are_closed_over_the_canon_schema_values():
    assert tuple(EntityType) == (
        EntityType.PERSON,
        EntityType.ORGANIZATION,
        EntityType.PLACE,
        EntityType.ITEM,
    )
    assert [member.value for member in EntityType] == [
        "person",
        "organization",
        "place",
        "item",
    ]
    assert [member.value for member in FactKind] == [
        "stable_definition",
        "dynamic_event",
        "claim",
    ]
    assert [member.value for member in ConfirmationStatus] == [
        "confirmed",
        "rejected",
    ]
    assert [member.value for member in AssertionOperator] == [
        "equals",
        "not_equals",
    ]
    assert [member.value for member in ValueCardinality] == ["single", "multi"]


def test_name_normalization_uses_nfkc_strip_and_casefold_only():
    assert normalize_name("  沈砚　") == "沈砚"
    assert normalize_name("ＳＨＥＮ") == "shen"
    assert normalize_name("Straße") == "strasse"
    assert normalize_name("沈砚") != normalize_name("沈彦")


@pytest.mark.parametrize("name", ["", "  ", "　"])
def test_name_normalization_rejects_empty_results(name):
    with pytest.raises(CanonValidationError, match="name"):
        normalize_name(name)


def test_alias_resolution_reports_missing_and_resolved_results():
    assert resolve_alias("掌柜", []) == AliasResolution("missing", ())
    assert resolve_alias(
        "掌柜",
        [
            {"entity_id": "person-1", "normalized_alias": "掌柜"},
            {"entity_id": "person-1", "normalized_alias": "掌柜"},
        ],
    ) == AliasResolution("resolved", ("person-1",))


def test_alias_resolution_deduplicates_sorts_and_never_picks_an_ambiguous_match():
    rows = [
        {"entity_id": "b", "normalized_alias": "掌柜"},
        {"entity_id": "a", "normalized_alias": "掌柜"},
        {"entity_id": "b", "normalized_alias": "掌柜"},
    ]
    assert resolve_alias("掌柜", rows) == AliasResolution("ambiguous", ("a", "b"))


def test_alias_resolution_rejects_rows_from_a_different_normalized_lookup():
    with pytest.raises(CanonValidationError, match="normalized_alias"):
        resolve_alias(
            "ＳＨＥＮ",
            [{"entity_id": "person-1", "normalized_alias": "other"}],
        )


def test_alias_resolution_requires_a_non_empty_exact_lookup_name():
    with pytest.raises(CanonValidationError, match="name"):
        resolve_alias("　", [])


def test_alias_resolution_is_immutable_and_rejects_unknown_statuses():
    resolution = AliasResolution("resolved", ("person-1",))
    with pytest.raises(FrozenInstanceError):
        resolution.status = "missing"
    with pytest.raises(CanonValidationError, match="status"):
        AliasResolution("guessed", ("person-1",))


@pytest.mark.parametrize("entity_id", [None, 0, False, "　"])
def test_alias_rows_reject_non_string_or_empty_entity_ids(entity_id):
    with pytest.raises(CanonValidationError, match="entity_id"):
        resolve_alias(
            "掌柜",
            [{"entity_id": entity_id, "normalized_alias": "掌柜"}],
        )


@pytest.mark.parametrize("entity_id", [None, 0, False, "　"])
def test_alias_resolution_rejects_non_string_or_empty_entity_ids(entity_id):
    with pytest.raises(CanonValidationError, match="entity_ids"):
        AliasResolution("resolved", (entity_id,))


def test_alias_entity_ids_are_trimmed_deduplicated_and_sorted():
    assert resolve_alias(
        "掌柜",
        [
            {"entity_id": " b ", "normalized_alias": "掌柜"},
            {"entity_id": "a", "normalized_alias": "掌柜"},
            {"entity_id": "b", "normalized_alias": "掌柜"},
        ],
    ) == AliasResolution("ambiguous", ("a", "b"))


@pytest.mark.parametrize("normalized_alias", [None, 0, False, "ＳＨＥＮ"])
def test_alias_rows_require_an_exact_normalized_string(normalized_alias):
    with pytest.raises(CanonValidationError, match="normalized_alias"):
        resolve_alias(
            "ＳＨＥＮ",
            [{"entity_id": "person-1", "normalized_alias": normalized_alias}],
        )
