from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain.seeds import SEED_FIELD_MAX_LENGTH, SeedPayload


SEED_VALUES = {
    "title": "典镇山河",
    "genre": "东方奇幻",
    "logline": "少年以县志镇压黑潮。",
    "protagonist": "沈码",
    "desire": "让被抹去的乡民重获姓名。",
    "coreConflict": "修史会同时唤醒镇物。",
    "worldPressure": "黑潮上涨，王朝封存旧志。",
    "openingHook": "县志预写了新县令的死期。",
    "differentiation": "以地方志书写为力量体系。",
}


def make_seed(**overrides: object) -> SeedPayload:
    values: dict[str, object] = dict(SEED_VALUES)
    values.update(overrides)
    return SeedPayload(**values)


def test_seed_payload_has_exactly_the_nine_contract_fields():
    payload = make_seed()

    assert tuple(type(payload).model_fields) == (
        "title",
        "genre",
        "logline",
        "protagonist",
        "desire",
        "coreConflict",
        "worldPressure",
        "openingHook",
        "differentiation",
    )

    with pytest.raises(ValidationError):
        SeedPayload(**SEED_VALUES, legacyField="legacy")


@pytest.mark.parametrize("field_name", tuple(SEED_VALUES))
@pytest.mark.parametrize("invalid", ["", "   \t\n"])
def test_seed_payload_rejects_empty_or_whitespace_only_strings(
    field_name: str,
    invalid: str,
):
    with pytest.raises(ValidationError):
        make_seed(**{field_name: invalid})


@pytest.mark.parametrize("field_name", tuple(SEED_VALUES))
def test_seed_payload_applies_one_explicit_maximum_to_every_field(
    field_name: str,
):
    payload = make_seed(**{field_name: "x" * SEED_FIELD_MAX_LENGTH})

    assert len(payload.model_dump()[field_name]) == SEED_FIELD_MAX_LENGTH

    with pytest.raises(ValidationError):
        make_seed(**{field_name: "x" * (SEED_FIELD_MAX_LENGTH + 1)})


@pytest.mark.parametrize("field_name", tuple(SEED_VALUES))
@pytest.mark.parametrize("invalid", [1, True, b"text"])
def test_seed_payload_is_strict_about_string_types(
    field_name: str,
    invalid: object,
):
    with pytest.raises(ValidationError):
        make_seed(**{field_name: invalid})


def test_seed_payload_strips_outer_whitespace_and_is_frozen():
    payload = make_seed(title="  典镇山河\n")

    assert payload.title == "典镇山河"
    with pytest.raises(ValidationError):
        payload.title = "新标题"
