"""Immutable Canon identity values and pure hard-conflict rules."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations
import json
import math
from typing import Literal
import unicodedata


class CanonValidationError(ValueError):
    """A Canon value or ChangeSet violates the domain contract."""


class EntityType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    PLACE = "place"
    ITEM = "item"


class FactKind(StrEnum):
    STABLE_DEFINITION = "stable_definition"
    DYNAMIC_EVENT = "dynamic_event"
    CLAIM = "claim"


class ConfirmationStatus(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class AssertionOperator(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"


class ValueCardinality(StrEnum):
    SINGLE = "single"
    MULTI = "multi"


AliasStatus = Literal["missing", "resolved", "ambiguous"]
_ALIAS_STATUSES = frozenset({"missing", "resolved", "ambiguous"})


class FrozenJsonObject(Mapping[str, object]):
    """A tuple-backed immutable JSON object with stable hashing."""

    __slots__ = ("_hash", "_items")

    def __init__(self, values: Iterable[tuple[str, object]]) -> None:
        items = tuple(sorted(values))
        object.__setattr__(self, "_items", items)
        object.__setattr__(self, "_hash", hash(items))

    def __getitem__(self, key: str) -> object:
        for candidate, value in self._items:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __hash__(self) -> int:
        return self._hash

    def __repr__(self) -> str:
        return repr(dict(self._items))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("FrozenJsonObject is immutable")


def freeze_json(value: object, *, field_name: str) -> object:
    """Copy and deeply freeze one strict JSON value."""

    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if math.isfinite(value):
            return value
        raise CanonValidationError(f"{field_name} must contain finite JSON numbers")
    if type(value) is list:
        return tuple(
            freeze_json(item, field_name=field_name)
            for item in value
        )
    if type(value) is dict:
        frozen_items: list[tuple[str, object]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonValidationError(
                    f"{field_name} JSON object keys must be strings"
                )
            frozen_items.append(
                (key, freeze_json(item, field_name=field_name))
            )
        return FrozenJsonObject(frozen_items)
    raise CanonValidationError(
        f"{field_name} must contain only strict JSON values"
    )


def thaw_json(value: object) -> object:
    """Return a mutable strict-JSON representation of a frozen JSON value."""

    if isinstance(value, FrozenJsonObject):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def canonical_json(value: object, *, field_name: str = "value") -> str:
    """Serialize a frozen or raw strict JSON value deterministically."""

    try:
        return json.dumps(
            thaw_json(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonValidationError(
            f"{field_name} must be valid finite JSON"
        ) from exc


# Private aliases preserve the established internal API while callers migrate to
# the deliberately small public strict-JSON boundary above.
_freeze_json = freeze_json
_thaw_json = thaw_json
_canonical_json = canonical_json


def _closed_enum(enum_type, value: object, field_name: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CanonValidationError(f"{field_name} is not an allowed value") from exc


def _chapter(value: int | None, field_name: str) -> None:
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
    ):
        raise CanonValidationError(f"{field_name} must be a positive integer")


@dataclass(frozen=True, eq=False)
class CanonEventInput:
    entity_id: str | None
    fact_kind: FactKind
    field_path: str
    value: object
    evidence: Mapping[str, object]
    effective_start_chapter: int | None
    effective_end_chapter: int | None
    confirmation_status: ConfirmationStatus
    assertion_operator: AssertionOperator
    value_cardinality: ValueCardinality

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, CanonEventInput)
            and _event_key(self) == _event_key(other)
        )

    def __hash__(self) -> int:
        return hash(_event_key(self))

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fact_kind",
            _closed_enum(FactKind, self.fact_kind, "fact_kind"),
        )
        object.__setattr__(
            self,
            "confirmation_status",
            _closed_enum(
                ConfirmationStatus,
                self.confirmation_status,
                "confirmation_status",
            ),
        )
        object.__setattr__(
            self,
            "assertion_operator",
            _closed_enum(
                AssertionOperator,
                self.assertion_operator,
                "assertion_operator",
            ),
        )
        object.__setattr__(
            self,
            "value_cardinality",
            _closed_enum(
                ValueCardinality,
                self.value_cardinality,
                "value_cardinality",
            ),
        )

        if not isinstance(self.field_path, str) or not self.field_path.strip():
            raise CanonValidationError("field_path must be non-empty")
        if self.entity_id is not None and (
            not isinstance(self.entity_id, str) or not self.entity_id.strip()
        ):
            raise CanonValidationError("entity_id must be non-empty when provided")
        if type(self.evidence) is not dict:
            raise CanonValidationError("evidence must be a dict")
        frozen_value = _freeze_json(self.value, field_name="value")
        frozen_evidence = _freeze_json(self.evidence, field_name="evidence")
        object.__setattr__(self, "value", frozen_value)
        object.__setattr__(self, "evidence", frozen_evidence)

        _chapter(self.effective_start_chapter, "effective_start_chapter")
        _chapter(self.effective_end_chapter, "effective_end_chapter")
        if (
            self.effective_start_chapter is not None
            and self.effective_end_chapter is not None
            and self.effective_end_chapter < self.effective_start_chapter
        ):
            raise CanonValidationError(
                "effective_end_chapter cannot precede effective_start_chapter"
            )
        if (
            self.confirmation_status is ConfirmationStatus.CONFIRMED
            and not self.evidence
        ):
            raise CanonValidationError("confirmed events require non-empty evidence")
        if (
            self.fact_kind is FactKind.STABLE_DEFINITION
            and self.entity_id is None
        ):
            raise CanonValidationError("stable_definition requires an entity_id")

@dataclass(frozen=True)
class AliasResolution:
    status: AliasStatus
    entity_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or self.status not in _ALIAS_STATUSES:
            raise CanonValidationError("alias resolution status is invalid")
        normalized: set[str] = set()
        try:
            values = tuple(self.entity_ids)
        except TypeError as exc:
            raise CanonValidationError("alias entity_ids must be strings") from exc
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise CanonValidationError(
                    "alias entity_ids must be non-empty strings"
                )
            normalized.add(value.strip())
        normalized_ids = tuple(sorted(normalized))
        object.__setattr__(self, "entity_ids", normalized_ids)
        expected_count = {
            "missing": len(normalized_ids) == 0,
            "resolved": len(normalized_ids) == 1,
            "ambiguous": len(normalized_ids) > 1,
        }
        if not expected_count[self.status]:
            raise CanonValidationError(
                "alias resolution status does not match entity_ids"
            )


@dataclass(frozen=True)
class CanonConflict:
    old: CanonEventInput
    new: CanonEventInput
    reason: str


def normalize_name(value: str) -> str:
    if not isinstance(value, str):
        raise CanonValidationError("name must be a string")
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if not normalized:
        raise CanonValidationError("name must be non-empty after normalization")
    return normalized


def resolve_alias(
    name: str,
    rows: Iterable[Mapping[str, object]],
) -> AliasResolution:
    normalized_name = normalize_name(name)
    entity_ids: set[str] = set()
    for row in rows:
        if "normalized_alias" in row:
            row_alias = row["normalized_alias"]
            if not isinstance(row_alias, str):
                raise CanonValidationError(
                    "row normalized_alias must be a string"
                )
            if row_alias != normalized_name:
                raise CanonValidationError(
                    "row normalized_alias does not match the lookup name"
                )
        try:
            entity_id = row["entity_id"]
        except KeyError as exc:
            raise CanonValidationError("alias row requires entity_id") from exc
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise CanonValidationError(
                "alias row entity_id must be a non-empty string"
            )
        entity_ids.add(entity_id.strip())

    ordered_ids = tuple(sorted(entity_ids))
    if not ordered_ids:
        status: AliasStatus = "missing"
    elif len(ordered_ids) == 1:
        status = "resolved"
    else:
        status = "ambiguous"
    return AliasResolution(status=status, entity_ids=ordered_ids)


def _overlaps(left: CanonEventInput, right: CanonEventInput) -> bool:
    left_start = (
        1
        if left.effective_start_chapter is None
        else left.effective_start_chapter
    )
    right_start = (
        1
        if right.effective_start_chapter is None
        else right.effective_start_chapter
    )
    left_end = (
        float("inf")
        if left.effective_end_chapter is None
        else left.effective_end_chapter
    )
    right_end = (
        float("inf")
        if right.effective_end_chapter is None
        else right.effective_end_chapter
    )
    return max(left_start, right_start) <= min(left_end, right_end)


def _mutually_exclusive(left: CanonEventInput, right: CanonEventInput) -> bool:
    left_value = _canonical_json(left.value)
    right_value = _canonical_json(right.value)
    if (
        left.assertion_operator is AssertionOperator.EQUALS
        and right.assertion_operator is AssertionOperator.EQUALS
    ):
        return (
            left.value_cardinality is ValueCardinality.SINGLE
            and right.value_cardinality is ValueCardinality.SINGLE
            and left_value != right_value
        )
    return (
        {left.assertion_operator, right.assertion_operator}
        == {AssertionOperator.EQUALS, AssertionOperator.NOT_EQUALS}
        and left_value == right_value
    )


def _is_hard_conflict_pair(
    left: CanonEventInput,
    right: CanonEventInput,
) -> bool:
    return _overlaps(left, right) and _mutually_exclusive(left, right)


def _event_key(item: CanonEventInput) -> tuple:
    return (
        item.entity_id or "",
        item.field_path,
        item.fact_kind.value,
        item.confirmation_status.value,
        item.assertion_operator.value,
        item.value_cardinality.value,
        (0, 1)
        if item.effective_start_chapter is None
        else (1, item.effective_start_chapter),
        (1, 0)
        if item.effective_end_chapter is None
        else (0, item.effective_end_chapter),
        _canonical_json(item.value),
        _canonical_json(item.evidence, field_name="evidence"),
    )


def _unique_sorted_events(
    events: Iterable[CanonEventInput],
    event_key,
) -> tuple[CanonEventInput, ...]:
    ordered = sorted(events, key=event_key)
    unique: list[CanonEventInput] = []
    previous_key: tuple | None = None
    for item in ordered:
        key = event_key(item)
        if key != previous_key:
            unique.append(item)
            previous_key = key
    return tuple(unique)


def _stable_groups(
    events: Iterable[CanonEventInput],
) -> dict[tuple[str, str], list[CanonEventInput]]:
    groups: dict[tuple[str, str], list[CanonEventInput]] = {}
    for item in events:
        if item.entity_id is None or item.fact_kind is not FactKind.STABLE_DEFINITION:
            continue
        scope = (item.entity_id, item.field_path)
        groups.setdefault(scope, []).append(item)
    return groups


def find_hard_conflicts(
    existing: Iterable[CanonEventInput],
    incoming: Iterable[CanonEventInput],
) -> tuple[CanonConflict, ...]:
    key_cache: dict[int, tuple] = {}

    def event_key(item: CanonEventInput) -> tuple:
        identity = id(item)
        key = key_cache.get(identity)
        if key is None:
            key = _event_key(item)
            key_cache[identity] = key
        return key

    existing_events = _unique_sorted_events(existing, event_key)
    incoming_events = _unique_sorted_events(incoming, event_key)
    existing_groups = _stable_groups(existing_events)
    incoming_groups = _stable_groups(incoming_events)

    conflicts: list[CanonConflict] = []
    seen: set[tuple[tuple, tuple]] = set()
    for scope in sorted(existing_groups.keys() | incoming_groups.keys()):
        old_scope = existing_groups.get(scope, [])
        new_scope = incoming_groups.get(scope, [])
        cardinalities = {
            item.value_cardinality for item in (*old_scope, *new_scope)
        }
        if len(cardinalities) > 1:
            raise CanonValidationError(
                "stable events for one entity and field must use one value_cardinality"
            )

        confirmed_old = [
            item
            for item in old_scope
            if item.confirmation_status is ConfirmationStatus.CONFIRMED
        ]
        confirmed_new = [
            item
            for item in new_scope
            if item.confirmation_status is ConfirmationStatus.CONFIRMED
        ]
        candidate_pairs = [
            *((old, new) for old in confirmed_old for new in confirmed_new),
            *combinations(confirmed_new, 2),
        ]
        candidate_pairs.sort(
            key=lambda pair: (event_key(pair[0]), event_key(pair[1]))
        )
        for old, new in candidate_pairs:
            if _is_hard_conflict_pair(old, new):
                key = tuple(sorted((event_key(old), event_key(new))))
                if key in seen:
                    continue
                seen.add(key)
                conflicts.append(
                    CanonConflict(
                        old=old,
                        new=new,
                        reason="mutually_exclusive_stable_definition",
                    )
                )
    return tuple(
        sorted(
            conflicts,
            key=lambda item: (event_key(item.old), event_key(item.new)),
        )
    )
