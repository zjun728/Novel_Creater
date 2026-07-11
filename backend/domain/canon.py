"""Immutable Canon identity values and pure hard-conflict rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Iterable, Literal, Mapping
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


def _canonical_json(value: object, *, field_name: str = "value") -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonValidationError(
            f"{field_name} must be valid finite JSON"
        ) from exc


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


@dataclass(frozen=True)
class CanonEventInput:
    entity_id: str | None
    fact_kind: FactKind
    field_path: str
    value: object
    evidence: dict
    effective_start_chapter: int | None
    effective_end_chapter: int | None
    confirmation_status: ConfirmationStatus
    assertion_operator: AssertionOperator
    value_cardinality: ValueCardinality

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
        if not isinstance(self.evidence, dict):
            raise CanonValidationError("evidence must be a dict")
        _canonical_json(self.evidence, field_name="evidence")

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

        _canonical_json(self.value)


@dataclass(frozen=True)
class AliasResolution:
    status: AliasStatus
    entity_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in _ALIAS_STATUSES:
            raise CanonValidationError("alias resolution status is invalid")
        normalized_ids = tuple(sorted({str(value) for value in self.entity_ids}))
        if any(not entity_id for entity_id in normalized_ids):
            raise CanonValidationError("alias entity_ids must be non-empty")
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
            row_alias = normalize_name(str(row["normalized_alias"]))
            if row_alias != normalized_name:
                raise CanonValidationError(
                    "row normalized_alias does not match the lookup name"
                )
        try:
            entity_id = str(row["entity_id"])
        except KeyError as exc:
            raise CanonValidationError("alias row requires entity_id") from exc
        if not entity_id:
            raise CanonValidationError("alias row entity_id must be non-empty")
        entity_ids.add(entity_id)

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


def _stable_scope(left: CanonEventInput, right: CanonEventInput) -> bool:
    return (
        left.entity_id is not None
        and left.entity_id == right.entity_id
        and left.field_path == right.field_path
        and left.fact_kind is FactKind.STABLE_DEFINITION
        and right.fact_kind is FactKind.STABLE_DEFINITION
    )


def _event_key(item: CanonEventInput) -> tuple:
    return (
        item.entity_id or "",
        item.field_path,
        item.fact_kind.value,
        item.confirmation_status.value,
        item.assertion_operator.value,
        item.value_cardinality.value,
        1
        if item.effective_start_chapter is None
        else item.effective_start_chapter,
        float("inf")
        if item.effective_end_chapter is None
        else item.effective_end_chapter,
        _canonical_json(item.value),
    )


def find_hard_conflicts(
    existing: Iterable[CanonEventInput],
    incoming: Iterable[CanonEventInput],
) -> tuple[CanonConflict, ...]:
    pairs: dict[tuple[tuple, tuple], CanonConflict] = {}
    existing_events = tuple(existing)
    incoming_events = tuple(incoming)
    for old in existing_events:
        for new in incoming_events:
            if not _stable_scope(old, new):
                continue
            if old.value_cardinality is not new.value_cardinality:
                raise CanonValidationError(
                    "stable events for one entity and field must use one value_cardinality"
                )
            if (
                old.confirmation_status is ConfirmationStatus.CONFIRMED
                and new.confirmation_status is ConfirmationStatus.CONFIRMED
                and _overlaps(old, new)
                and _mutually_exclusive(old, new)
            ):
                key = (_event_key(old), _event_key(new))
                pairs.setdefault(
                    key,
                    CanonConflict(
                        old=old,
                        new=new,
                        reason="mutually_exclusive_stable_definition",
                    ),
                )
    return tuple(pairs[key] for key in sorted(pairs))
