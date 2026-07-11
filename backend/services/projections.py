"""Deterministic projections derived from one immutable Canon event stream."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import re

from backend.domain.canon import (
    CanonValidationError,
    ConfirmationStatus,
    FactKind,
    canonical_json,
    freeze_json,
    thaw_json,
)


GLOBAL_PROJECTION_KEY = "__global__"
_EVENT_FIELDS = frozenset(
    {
        "id",
        "revision_number",
        "event_order",
        "entity_id",
        "fact_kind",
        "field_path",
        "value",
        "confirmation_status",
        "evidence",
    }
)
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


class ProjectionValidationError(ValueError):
    """An event stream or projection value violates the projection contract."""


def _non_negative_integer(value: object, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise ProjectionValidationError(
            f"{field_name} must be a non-negative integer"
        )


def _non_empty_string(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ProjectionValidationError(f"{field_name} must be a non-empty string")


def _enum(enum_type, value: object, field_name: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ProjectionValidationError(
            f"{field_name} is not an allowed value"
        ) from exc


def _freeze(value: object, field_name: str) -> object:
    try:
        return freeze_json(value, field_name=field_name)
    except CanonValidationError as exc:
        raise ProjectionValidationError(str(exc)) from exc


@dataclass(frozen=True, eq=False)
class ProjectionEvent:
    """Validated, copied and immutable input for projection reduction."""

    id: str
    revision_number: int
    event_order: int
    entity_id: str | None
    fact_kind: FactKind
    field_path: str
    value: object
    confirmation_status: ConfirmationStatus
    evidence: object

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ProjectionEvent)
            and _projection_event_key(self) == _projection_event_key(other)
        )

    def __hash__(self) -> int:
        return hash(_projection_event_key(self))

    def __post_init__(self) -> None:
        _non_empty_string(self.id, "id")
        _non_negative_integer(self.revision_number, "revision_number")
        _non_negative_integer(self.event_order, "event_order")
        if self.entity_id is not None:
            _non_empty_string(self.entity_id, "entity_id")
        _non_empty_string(self.field_path, "field_path")
        object.__setattr__(
            self,
            "fact_kind",
            _enum(FactKind, self.fact_kind, "fact_kind"),
        )
        object.__setattr__(
            self,
            "confirmation_status",
            _enum(
                ConfirmationStatus,
                self.confirmation_status,
                "confirmation_status",
            ),
        )
        object.__setattr__(self, "value", _freeze(self.value, "value"))
        object.__setattr__(self, "evidence", _freeze(self.evidence, "evidence"))


def _projection_event_key(item: ProjectionEvent) -> tuple[object, ...]:
    return (
        item.id,
        item.revision_number,
        item.event_order,
        item.entity_id,
        item.fact_kind.value,
        item.field_path,
        canonical_json(thaw_json(item.value), field_name="value"),
        canonical_json(thaw_json(item.evidence), field_name="evidence"),
        item.confirmation_status.value,
    )


@dataclass(frozen=True)
class ProjectionBundle:
    """Deeply immutable, comparable snapshot of every derived projection."""

    revision: int
    current_state: Mapping[str, object]
    memories: Mapping[str, object]
    arcs: Mapping[str, object]
    plot_threads: Mapping[str, object]
    content_hash: str

    def __post_init__(self) -> None:
        _non_negative_integer(self.revision, "revision")
        if not isinstance(self.content_hash, str) or not _SHA256_HEX.fullmatch(
            self.content_hash
        ):
            raise ProjectionValidationError(
                "content_hash must be a lowercase 64-character SHA-256 hex digest"
            )
        for field_name in (
            "current_state",
            "memories",
            "arcs",
            "plot_threads",
        ):
            value = getattr(self, field_name)
            if type(value) is not dict:
                raise ProjectionValidationError(f"{field_name} must be a dict")
            object.__setattr__(self, field_name, _freeze(value, field_name))


def _normalize_event(value: object) -> ProjectionEvent:
    if isinstance(value, ProjectionEvent):
        return value
    if not isinstance(value, Mapping):
        raise ProjectionValidationError(
            "event must be a ProjectionEvent or mapping"
        )
    actual_fields = frozenset(value.keys())
    if actual_fields != _EVENT_FIELDS:
        missing = sorted(_EVENT_FIELDS - actual_fields)
        extra = sorted(
            str(field) for field in actual_fields - _EVENT_FIELDS
        )
        raise ProjectionValidationError(
            f"event fields must match exactly; missing={missing}, extra={extra}"
        )
    return ProjectionEvent(**{field: value[field] for field in _EVENT_FIELDS})


def _memory_item(item: ProjectionEvent) -> dict[str, object]:
    return {
        "eventId": item.id,
        "revisionNumber": item.revision_number,
        "eventOrder": item.event_order,
        "factKind": item.fact_kind.value,
        "fieldPath": item.field_path,
        "value": thaw_json(item.value),
        "evidence": thaw_json(item.evidence),
    }


def build_projection_bundle(
    revision: int,
    events: Iterable[Mapping | ProjectionEvent],
) -> ProjectionBundle:
    """Reduce a project-wide Canon stream into deterministic projections."""

    _non_negative_integer(revision, "revision")
    normalized = tuple(_normalize_event(item) for item in events)

    seen_ids: set[str] = set()
    stream_orders: dict[tuple[int, int], str] = {}
    for item in normalized:
        if item.revision_number > revision:
            raise ProjectionValidationError(
                "event revision_number cannot exceed target revision"
            )
        if item.id in seen_ids:
            raise ProjectionValidationError(f"duplicate event id: {item.id}")
        seen_ids.add(item.id)
        stream_order = (item.revision_number, item.event_order)
        previous_id = stream_orders.get(stream_order)
        if previous_id is not None and previous_id != item.id:
            raise ProjectionValidationError(
                "revision_number and event_order must be unique across the project stream"
            )
        stream_orders[stream_order] = item.id

    ordered = sorted(
        normalized,
        key=lambda item: (item.revision_number, item.event_order, item.id),
    )
    current_state: dict[str, dict[str, object]] = {}
    memories: dict[str, list[dict[str, object]]] = {}
    arcs: dict[str, dict[str, object]] = {}
    plot_threads: dict[str, dict[str, object]] = {}

    for item in ordered:
        if item.confirmation_status is ConfirmationStatus.REJECTED:
            continue

        natural_key = item.entity_id or GLOBAL_PROJECTION_KEY
        memories.setdefault(natural_key, []).append(_memory_item(item))
        if item.fact_kind is FactKind.CLAIM:
            continue

        projection_value = thaw_json(item.value)
        if item.entity_id is not None:
            current_state.setdefault(item.entity_id, {})[
                item.field_path
            ] = projection_value
            if item.field_path.startswith("arc."):
                arcs.setdefault(item.entity_id, {})[
                    item.field_path
                ] = projection_value
        if item.field_path.startswith("plot."):
            plot_threads.setdefault(natural_key, {})[
                item.field_path
            ] = projection_value

    hash_payload = {
        "revision": revision,
        "currentState": current_state,
        "memories": memories,
        "arcs": arcs,
        "plotThreads": plot_threads,
    }
    content_hash = hashlib.sha256(
        canonical_json(hash_payload, field_name="projection bundle").encode("utf-8")
    ).hexdigest()
    return ProjectionBundle(
        revision=revision,
        current_state=current_state,
        memories=memories,
        arcs=arcs,
        plot_threads=plot_threads,
        content_hash=content_hash,
    )
