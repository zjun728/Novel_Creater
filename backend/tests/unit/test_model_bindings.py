from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain.model_bindings import (
    TASK_KEYS,
    BindingItem,
    BindingRevision,
)


EXPECTED_TASK_KEYS = (
    "seed",
    "planning",
    "writing",
    "audit",
    "summary",
    "extraction",
    "polish",
    "market",
)


def unbound_item(task_key: str = "seed") -> BindingItem:
    return BindingItem(
        task_key=task_key,
        resolution_status="unbound",
        provider_id=None,
        provider_name_snapshot=None,
        model_name_snapshot=None,
    )


def bound_item(task_key: str = "seed") -> BindingItem:
    return BindingItem(
        task_key=task_key,
        resolution_status="bound",
        provider_id=f"provider-{task_key}",
        provider_name_snapshot=f"Provider {task_key}",
        model_name_snapshot=f"model-{task_key}",
    )


def revision_with(factory=unbound_item, **overrides: object) -> BindingRevision:
    values: dict[str, object] = {
        "project_id": "project-1",
        "revision": 1,
        "items": tuple(factory(task_key) for task_key in TASK_KEYS),
    }
    values.update(overrides)
    return BindingRevision(**values)


def test_task_keys_are_the_exact_ordered_closed_set():
    assert TASK_KEYS == EXPECTED_TASK_KEYS


def test_eight_unbound_items_are_complete_but_not_ready():
    revision = revision_with()

    assert revision.binding_complete is True
    assert revision.binding_ready is False


def test_eight_bound_items_are_complete_and_ready():
    revision = revision_with(bound_item)

    assert revision.binding_complete is True
    assert revision.binding_ready is True


@pytest.mark.parametrize(
    "items",
    [
        tuple(unbound_item(key) for key in TASK_KEYS[:-1]),
        tuple(unbound_item(key) for key in TASK_KEYS) + (unbound_item("seed"),),
        tuple(unbound_item(key) for key in TASK_KEYS[:-1]) + (unbound_item("seed"),),
    ],
)
def test_revision_requires_exactly_one_item_for_every_task_key(items):
    with pytest.raises(ValidationError):
        revision_with(items=items)


def test_revision_rejects_complete_items_outside_canonical_task_order():
    reversed_items = tuple(
        unbound_item(task_key) for task_key in reversed(TASK_KEYS)
    )

    with pytest.raises(ValidationError, match="canonical order"):
        revision_with(items=reversed_items)


@pytest.mark.parametrize("project_id", ["", 123])
def test_revision_requires_a_strict_non_empty_project_id(project_id: object):
    with pytest.raises(ValidationError):
        revision_with(project_id=project_id)


@pytest.mark.parametrize("revision", [0, -1, 1.0, "1", True])
def test_revision_requires_a_strict_positive_integer(revision: object):
    with pytest.raises(ValidationError):
        revision_with(revision=revision)


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider_id": "provider"},
        {"provider_name_snapshot": "Provider"},
        {"model_name_snapshot": "model"},
    ],
)
def test_unbound_item_requires_all_provider_snapshots_to_be_none(overrides):
    values = unbound_item().model_dump()
    values.update(overrides)

    with pytest.raises(ValidationError):
        BindingItem(**values)


@pytest.mark.parametrize(
    "missing_field",
    ["provider_id", "provider_name_snapshot", "model_name_snapshot"],
)
def test_bound_item_requires_all_provider_snapshot_fields(missing_field: str):
    values = bound_item().model_dump()
    values[missing_field] = None

    with pytest.raises(ValidationError):
        BindingItem(**values)


@pytest.mark.parametrize(
    "values",
    [
        {
            "task_key": "legacy",
            "resolution_status": "unbound",
            "provider_id": None,
            "provider_name_snapshot": None,
            "model_name_snapshot": None,
        },
        {
            "task_key": "seed",
            "resolution_status": "fallback",
            "provider_id": None,
            "provider_name_snapshot": None,
            "model_name_snapshot": None,
        },
    ],
)
def test_binding_item_uses_closed_literal_values(values):
    with pytest.raises(ValidationError):
        BindingItem(**values)


def test_binding_models_are_strict_frozen_and_forbid_extra_fields():
    with pytest.raises(ValidationError):
        BindingItem(**unbound_item().model_dump(), legacyField="legacy")
    with pytest.raises(ValidationError):
        BindingRevision(**revision_with().model_dump(), legacyField="legacy")
    with pytest.raises(ValidationError):
        revision_with(items=list(revision_with().items))

    item = unbound_item()
    revision = revision_with()
    with pytest.raises(ValidationError):
        item.resolution_status = "bound"
    with pytest.raises(ValidationError):
        revision.revision = 2
