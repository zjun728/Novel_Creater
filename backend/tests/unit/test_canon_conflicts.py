from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import math

import pytest

from backend.domain.canon import (
    AssertionOperator,
    CanonConflict,
    CanonEventInput,
    CanonValidationError,
    ConfirmationStatus,
    FactKind,
    ValueCardinality,
    find_hard_conflicts,
)


def event(
    value="北平",
    *,
    entity_id="person-1",
    kind="stable_definition",
    field_path="identity.birthplace",
    evidence=None,
    start=1,
    end=None,
    status="confirmed",
    operator="equals",
    cardinality="single",
):
    return CanonEventInput(
        entity_id=entity_id,
        fact_kind=kind,
        field_path=field_path,
        value=value,
        evidence={"quote": "正文证据"} if evidence is None else evidence,
        effective_start_chapter=start,
        effective_end_chapter=end,
        confirmation_status=status,
        assertion_operator=operator,
        value_cardinality=cardinality,
    )


def test_event_input_coerces_closed_enum_values_and_is_immutable():
    item = event()
    assert item.fact_kind is FactKind.STABLE_DEFINITION
    assert item.confirmation_status is ConfirmationStatus.CONFIRMED
    assert item.assertion_operator is AssertionOperator.EQUALS
    assert item.value_cardinality is ValueCardinality.SINGLE
    with pytest.raises(FrozenInstanceError):
        item.field_path = "other"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"field_path": "　"}, "field_path"),
        ({"start": 0}, "start"),
        ({"start": -1}, "start"),
        ({"end": 0}, "end"),
        ({"start": 4, "end": 3}, "end"),
        ({"evidence": {}}, "evidence"),
        ({"entity_id": None}, "entity_id"),
    ],
)
def test_event_input_rejects_invalid_stable_definitions(changes, message):
    with pytest.raises(CanonValidationError, match=message):
        event(**changes)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_event_input_rejects_non_finite_json_numbers(value):
    with pytest.raises(CanonValidationError, match="JSON"):
        event(value)


def test_event_input_rejects_values_that_are_not_json_serializable():
    with pytest.raises(CanonValidationError, match="JSON"):
        event({"chapters": {1, 2}})


@pytest.mark.parametrize("evidence", [{"score": math.nan}, {"chapters": {1, 2}}])
def test_event_input_rejects_evidence_that_is_not_strict_json(evidence):
    with pytest.raises(CanonValidationError, match="evidence.*JSON"):
        event(evidence=evidence)


@pytest.mark.parametrize("kind", ["claim", "dynamic_event"])
def test_non_stable_events_may_be_plot_global(kind):
    assert event(entity_id=None, kind=kind).entity_id is None


def test_rejected_events_may_have_empty_evidence():
    assert event(status="rejected", evidence={}).evidence == {}


@pytest.mark.parametrize(
    ("changes", "enum_name"),
    [
        ({"kind": "fact"}, "fact_kind"),
        ({"status": "pending"}, "confirmation_status"),
        ({"operator": "contains"}, "assertion_operator"),
        ({"cardinality": "unknown"}, "value_cardinality"),
    ],
)
def test_event_input_rejects_values_outside_closed_enums(changes, enum_name):
    with pytest.raises(CanonValidationError, match=enum_name):
        event(**changes)


def test_overlapping_confirmed_single_stable_equals_with_different_values_conflict():
    conflicts = find_hard_conflicts((event("北平"),), (event("应天"),))
    assert conflicts == (
        CanonConflict(
            old=event("北平"),
            new=event("应天"),
            reason="mutually_exclusive_stable_definition",
        ),
    )


@pytest.mark.parametrize(
    ("old_cardinality", "new_cardinality"),
    [("single", "single"), ("multi", "multi")],
)
def test_equals_and_not_equals_same_json_value_conflict_for_any_matching_cardinality(
    old_cardinality, new_cardinality
):
    old = event(
        {"name": "北平", "script": "汉字"},
        cardinality=old_cardinality,
    )
    new = event(
        {"script": "汉字", "name": "北平"},
        operator="not_equals",
        cardinality=new_cardinality,
    )
    assert len(find_hard_conflicts((old,), (new,))) == 1


def test_closed_interval_boundaries_overlap():
    old = event("北平", start=None, end=5)
    new = event("应天", start=5, end=5)
    assert len(find_hard_conflicts((old,), (new,))) == 1


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (event("北平"), event("北平")),
        (
            event("木工", field_path="skills", cardinality="multi"),
            event("算学", field_path="skills", cardinality="multi"),
        ),
        (event("北平", operator="not_equals"), event("应天", operator="not_equals")),
        (event("北平"), event("应天", operator="not_equals")),
        (event("北平"), event("应天", kind="claim")),
        (event("北平"), event("应天", kind="dynamic_event")),
        (event("北平"), event("应天", status="rejected", evidence={})),
        (event("北平"), event("应天", entity_id="person-2")),
        (event("北平"), event("应天", field_path="identity.residence")),
        (
            event("北平", entity_id=None, kind="claim"),
            event("应天", entity_id=None, kind="claim"),
        ),
        (event("北平", start=1, end=5), event("应天", start=6)),
    ],
)
def test_non_mutually_exclusive_or_out_of_scope_pairs_do_not_conflict(old, new):
    assert find_hard_conflicts((old,), (new,)) == ()


def test_cardinality_mismatch_invalidates_same_entity_field_stable_comparison():
    old = event("北平")
    new = event(["应天"], cardinality="multi")
    with pytest.raises(CanonValidationError, match="value_cardinality"):
        find_hard_conflicts((old,), (new,))


def test_incoming_only_cardinality_mismatch_invalidates_the_change_set():
    incoming = (
        event("北平", cardinality="single"),
        event(["应天"], cardinality="multi"),
    )
    with pytest.raises(CanonValidationError, match="value_cardinality"):
        find_hard_conflicts((), incoming)


def test_existing_only_cardinality_mismatch_fails_fast_on_dirty_history():
    existing = (
        event("北平", cardinality="single"),
        event(["应天"], cardinality="multi"),
    )
    with pytest.raises(CanonValidationError, match="value_cardinality"):
        find_hard_conflicts(existing, ())


def test_cardinality_mismatch_is_not_applied_outside_same_entity_field_stable_scope():
    single = event("北平")
    assert find_hard_conflicts(
        (single,),
        (event(["应天"], cardinality="multi", entity_id="person-2"),),
    ) == ()
    assert find_hard_conflicts(
        (single,),
        (event(["应天"], cardinality="multi", field_path="skills"),),
    ) == ()
    assert find_hard_conflicts(
        (single,),
        (event(["应天"], cardinality="multi", kind="dynamic_event"),),
    ) == ()


def test_incoming_change_set_detects_its_own_hard_conflict_once():
    north = event("北平")
    south = event("应天")

    forward = find_hard_conflicts((), (south, north))
    reverse = find_hard_conflicts((), (north, south))

    assert forward == reverse
    assert len(forward) == 1
    assert {forward[0].old.value, forward[0].new.value} == {"北平", "应天"}


def test_existing_history_is_not_compared_against_itself_for_hard_conflicts():
    assert find_hard_conflicts((event("北平"), event("应天")), ()) == ()


@pytest.mark.parametrize(
    "incoming",
    [
        (event("北平", start=1, end=5), event("应天", start=6)),
        (
            event("木工", field_path="skills", cardinality="multi"),
            event("算学", field_path="skills", cardinality="multi"),
        ),
    ],
)
def test_non_conflicting_incoming_change_set_remains_empty(incoming):
    assert find_hard_conflicts((), incoming) == ()


def test_conflict_output_is_stable_and_deduplicated_for_reordered_inputs():
    old_a = event("北平", field_path="identity.birthplace")
    new_a = event("应天", field_path="identity.birthplace")
    old_b = event("吴语", field_path="identity.language")
    new_b = event("官话", field_path="identity.language")

    forward = find_hard_conflicts((old_b, old_a, old_a), (new_b, new_a, new_a))
    reverse = find_hard_conflicts((old_a, old_b), (new_a, new_b))

    assert forward == reverse
    assert len(forward) == 2
    assert tuple(conflict.old.field_path for conflict in forward) == (
        "identity.birthplace",
        "identity.language",
    )


def test_conflict_output_uses_evidence_in_its_full_stable_event_key():
    old_a = event("北平", evidence={"quote": "A"})
    old_b = event("北平", evidence={"quote": "B"})
    new_a = event("应天", evidence={"quote": "A"})
    new_b = event("应天", evidence={"quote": "B"})

    forward = find_hard_conflicts((old_b, old_a), (new_b, new_a))
    reverse = find_hard_conflicts((old_a, old_b), (new_a, new_b))

    assert forward == reverse
    assert len(forward) == 4
    assert tuple(
        (conflict.old.evidence["quote"], conflict.new.evidence["quote"])
        for conflict in forward
    ) == (("A", "A"), ("A", "B"), ("B", "A"), ("B", "B"))


def test_only_exact_duplicate_events_collapse_in_conflict_output():
    implicit_start = event("北平", start=None)
    explicit_start = event("北平", start=1)

    conflicts = find_hard_conflicts(
        (explicit_start, implicit_start),
        (event("应天"),),
    )

    assert len(conflicts) == 2
    assert tuple(conflict.old.effective_start_chapter for conflict in conflicts) == (
        None,
        1,
    )


def test_same_unordered_conflict_pair_is_reported_once_across_candidate_sources():
    event_a = event("北平", evidence={"quote": "A"})
    event_b = event("应天", evidence={"quote": "B"})

    forward = find_hard_conflicts((event_b,), (event_a, event_b))
    reverse = find_hard_conflicts((event_b,), (event_b, event_a))

    assert forward == reverse
    assert forward == (
        CanonConflict(
            old=event_a,
            new=event_b,
            reason="mutually_exclusive_stable_definition",
        ),
    )
