from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
import hashlib
import inspect
import json
import math

import pytest

from backend.services.projections import (
    ProjectionBundle,
    ProjectionEvent,
    ProjectionValidationError,
    build_projection_bundle,
)


def event(
    event_id: str = "e1",
    *,
    revision_number: int = 1,
    event_order: int = 1,
    entity_id: str | None = "p1",
    fact_kind: str = "dynamic_event",
    field_path: str = "status.rank",
    value: object = "百户",
    confirmation_status: str = "confirmed",
    evidence: object = None,
) -> dict[str, object]:
    return {
        "id": event_id,
        "revision_number": revision_number,
        "event_order": event_order,
        "entity_id": entity_id,
        "fact_kind": fact_kind,
        "field_path": field_path,
        "value": value,
        "confirmation_status": confirmation_status,
        "evidence": {"quote": "正文证据"} if evidence is None else evidence,
    }


def thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


def expected_content_hash(bundle: ProjectionBundle) -> str:
    payload = {
        "revision": bundle.revision,
        "currentState": thaw(bundle.current_state),
        "memories": thaw(bundle.memories),
        "arcs": thaw(bundle.arcs),
        "plotThreads": thaw(bundle.plot_threads),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_projection_is_deterministic_for_event_and_mapping_key_order():
    events = [
        event(
            "e1",
            revision_number=1,
            event_order=1,
            fact_kind="stable_definition",
            field_path="identity.name",
            value={"display": "沈砚", "aliases": ["掌柜"]},
        ),
        event("e2", revision_number=2, event_order=1),
        event(
            "e3",
            revision_number=2,
            event_order=2,
            fact_kind="claim",
            field_path="identity.origin",
            value="天外来客",
        ),
    ]
    reordered_mappings = [dict(reversed(tuple(item.items()))) for item in events]

    first = build_projection_bundle(2, events)
    second = build_projection_bundle(2, list(reversed(reordered_mappings)))

    assert first == second
    assert first.content_hash == second.content_hash
    assert len(first.content_hash) == 64
    assert set(first.content_hash) <= set("0123456789abcdef")
    assert first.content_hash == expected_content_hash(first)


def test_latest_confirmed_non_claim_event_wins_current_state():
    bundle = build_projection_bundle(
        2,
        [
            event("older", revision_number=1, event_order=8, value="总旗"),
            event("newer", revision_number=2, event_order=1, value="百户"),
            event(
                "claim",
                revision_number=2,
                event_order=2,
                fact_kind="claim",
                value="都督",
            ),
        ],
    )

    assert bundle.current_state["p1"]["status.rank"] == "百户"
    assert [item["eventId"] for item in bundle.memories["p1"]] == [
        "older",
        "newer",
        "claim",
    ]
    assert bundle.memories["p1"][-1]["factKind"] == "claim"


def test_rejected_events_appear_nowhere():
    bundle = build_projection_bundle(
        1,
        [
            event(
                "rejected",
                confirmation_status="rejected",
                field_path="arc.trust",
                value="伪状态",
                evidence={},
            ),
            event(
                "rejected-plot",
                event_order=2,
                entity_id=None,
                confirmation_status="rejected",
                field_path="plot.gunpowder",
                value="伪线索",
                evidence={},
            ),
        ],
    )

    assert bundle.current_state == {}
    assert bundle.memories == {}
    assert bundle.arcs == {}
    assert bundle.plot_threads == {}


def test_entityless_confirmed_events_use_global_memory_and_plot_key():
    bundle = build_projection_bundle(
        1,
        [
            event(
                "global",
                entity_id=None,
                field_path="plot.gunpowder",
                value={"status": "推进"},
                evidence={"chapter": 3},
            )
        ],
    )

    memory = bundle.memories["__global__"][0]
    assert memory == {
        "eventId": "global",
        "revisionNumber": 1,
        "eventOrder": 1,
        "factKind": "dynamic_event",
        "fieldPath": "plot.gunpowder",
        "value": {"status": "推进"},
        "evidence": {"chapter": 3},
    }
    assert bundle.current_state == {}
    assert bundle.plot_threads["__global__"]["plot.gunpowder"] == {
        "status": "推进"
    }


def test_arc_and_plot_views_are_deterministic_filters_of_current_stream():
    bundle = build_projection_bundle(
        2,
        [
            event("arc-old", field_path="arc.trust", value="动摇"),
            event(
                "arc-new",
                revision_number=2,
                field_path="arc.trust",
                value="稳固",
            ),
            event(
                "plot-person",
                revision_number=2,
                event_order=2,
                field_path="plot.gunpowder",
                value="追查",
            ),
            event(
                "ordinary",
                revision_number=2,
                event_order=3,
                field_path="status.location",
                value="北平",
            ),
            event(
                "arc-claim",
                revision_number=2,
                event_order=4,
                fact_kind="claim",
                field_path="arc.trust",
                value="传闻破裂",
            ),
        ],
    )

    assert bundle.current_state["p1"] == {
        "arc.trust": "稳固",
        "plot.gunpowder": "追查",
        "status.location": "北平",
    }
    assert bundle.arcs == {"p1": {"arc.trust": "稳固"}}
    assert bundle.plot_threads == {"p1": {"plot.gunpowder": "追查"}}


def test_plot_threads_with_same_field_are_scoped_by_entity_natural_key():
    events = [
        event("p2", entity_id="p2", field_path="plot.heir", value="隐瞒"),
        event(
            "global",
            event_order=2,
            entity_id=None,
            field_path="plot.heir",
            value="公开悬念",
        ),
        event(
            "p1",
            event_order=3,
            entity_id="p1",
            field_path="plot.heir",
            value="追查",
        ),
    ]

    forward = build_projection_bundle(1, events)
    reverse = build_projection_bundle(1, reversed(events))

    assert forward == reverse
    assert forward.plot_threads == {
        "__global__": {"plot.heir": "公开悬念"},
        "p1": {"plot.heir": "追查"},
        "p2": {"plot.heir": "隐瞒"},
    }


def test_empty_bundle_and_hash_are_stable():
    first = build_projection_bundle(0, [])
    second = build_projection_bundle(0, iter(()))

    assert first == second
    assert first == ProjectionBundle(
        revision=0,
        current_state={},
        memories={},
        arcs={},
        plot_threads={},
        content_hash=expected_content_hash(first),
    )


def test_mapping_input_is_copied_and_bundle_is_deeply_immutable():
    raw_value = {"rank": "百户", "badges": ["虎符"]}
    raw_evidence = {"quote": {"text": "授百户"}}
    raw_event = event(value=raw_value, evidence=raw_evidence)
    bundle = build_projection_bundle(1, [raw_event])

    raw_value["rank"] = "外部篡改"
    raw_value["badges"].append("污染")
    raw_evidence["quote"]["text"] = "外部篡改"
    raw_event["field_path"] = "external.mutation"

    assert bundle.current_state["p1"]["status.rank"] == {
        "badges": ("虎符",),
        "rank": "百户",
    }
    assert bundle.memories["p1"][0]["evidence"] == {
        "quote": {"text": "授百户"}
    }
    with pytest.raises(FrozenInstanceError):
        bundle.revision = 2
    with pytest.raises(TypeError):
        bundle.current_state["p1"]["status.rank"]["rank"] = "不可写"
    with pytest.raises(TypeError):
        bundle.memories["p1"][0]["evidence"]["quote"]["text"] = "不可写"
    with pytest.raises(AttributeError):
        bundle.current_state["p1"]["status.rank"]["badges"].append("不可写")


def test_projection_event_input_is_normalized_once_and_remains_immutable():
    raw = event(value={"rank": ["百户"]})
    normalized = ProjectionEvent(**raw)
    bundle = build_projection_bundle(1, [normalized])

    raw["value"]["rank"].append("污染")

    assert bundle.current_state["p1"]["status.rank"] == {"rank": ("百户",)}
    with pytest.raises(FrozenInstanceError):
        normalized.id = "changed"


@pytest.mark.parametrize("revision", [-1, True, 1.0, "1"])
def test_target_revision_must_be_a_non_negative_integer(revision):
    with pytest.raises(ProjectionValidationError, match="revision"):
        build_projection_bundle(revision, [])


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"event_id": ""}, "id"),
        ({"event_id": "　"}, "id"),
        ({"event_id": 1}, "id"),
        ({"revision_number": -1}, "revision_number"),
        ({"revision_number": True}, "revision_number"),
        ({"event_order": -1}, "event_order"),
        ({"event_order": 1.0}, "event_order"),
        ({"entity_id": ""}, "entity_id"),
        ({"entity_id": "　"}, "entity_id"),
        ({"entity_id": 1}, "entity_id"),
        ({"fact_kind": "fact"}, "fact_kind"),
        ({"confirmation_status": "pending"}, "confirmation_status"),
        ({"field_path": ""}, "field_path"),
        ({"field_path": "　"}, "field_path"),
        ({"field_path": 1}, "field_path"),
    ],
)
def test_event_identity_order_enum_and_path_fields_are_strict(changes, message):
    with pytest.raises(ProjectionValidationError, match=message):
        build_projection_bundle(1, [event(**changes)])


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("value", ("tuple",)),
        ("value", {"set"}),
        ("value", {1: "non-string key"}),
        ("value", math.nan),
        ("value", math.inf),
        ("evidence", {"nested": ("tuple",)}),
        ("evidence", {1: "non-string key"}),
        ("evidence", {"score": -math.inf}),
    ],
)
def test_event_value_and_evidence_must_be_strict_json(field, invalid):
    with pytest.raises(ProjectionValidationError, match=field):
        build_projection_bundle(1, [event(**{field: invalid})])


def test_future_revision_is_rejected_instead_of_silently_ignored():
    with pytest.raises(ProjectionValidationError, match="revision_number"):
        build_projection_bundle(1, [event(revision_number=2)])


def test_duplicate_event_id_is_rejected_even_at_a_different_order():
    with pytest.raises(ProjectionValidationError, match="duplicate.*id"):
        build_projection_bundle(
            1,
            [event("same", event_order=1), event("same", event_order=2)],
        )


def test_different_events_cannot_share_one_project_stream_order():
    with pytest.raises(ProjectionValidationError, match="revision.*event_order"):
        build_projection_bundle(
            1,
            [event("first", event_order=1), event("second", event_order=1)],
        )


def test_mapping_events_require_exactly_the_projection_fields():
    missing = event()
    missing.pop("evidence")
    extra = event()
    extra["chapterText"] = "不得进入投影"

    with pytest.raises(ProjectionValidationError, match="fields"):
        build_projection_bundle(1, [missing])
    with pytest.raises(ProjectionValidationError, match="fields"):
        build_projection_bundle(1, [extra])
    with pytest.raises(ProjectionValidationError, match="event"):
        build_projection_bundle(1, ["not-a-mapping"])


def test_builder_signature_accepts_only_revision_and_events():
    assert tuple(inspect.signature(build_projection_bundle).parameters) == (
        "revision",
        "events",
    )
    with pytest.raises(TypeError):
        build_projection_bundle(1, [], chapterText="正文")
    with pytest.raises(TypeError):
        build_projection_bundle(1, [], modelClient=object())
