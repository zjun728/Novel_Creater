import hashlib

import pytest

from backend.services.draft_selection import (
    LOCAL_DRAFT_OPERATION_INTENTS,
    LOCAL_DRAFT_OPERATION_TYPES,
    replace_selection,
    selection_context,
    validate_selection,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_local_operation_vocabulary_and_intents_are_closed():
    assert LOCAL_DRAFT_OPERATION_TYPES == frozenset({
        "rewrite_selection",
        "polish_selection",
        "expand_selection",
        "compress_selection",
    })
    assert LOCAL_DRAFT_OPERATION_INTENTS == {
        "rewrite_selection": "rewrite",
        "polish_selection": "polish",
        "expand_selection": "expand",
        "compress_selection": "compress",
    }


def test_validate_selection_uses_unicode_scalar_offsets_and_exact_utf8_hash():
    content = "甲😀乙\n丙"

    target = validate_selection(content, 1, 4, _digest("😀乙\n"))

    assert target.content == content
    assert target.prefix == "甲"
    assert target.selected_text == "😀乙\n"
    assert target.suffix == "丙"
    assert target.start_offset == 1
    assert target.end_offset == 4
    assert target.selected_text_hash == _digest("😀乙\n")


@pytest.mark.parametrize(
    ("start", "end", "digest"),
    [
        (-1, 1, _digest("甲")),
        (1, 1, _digest("")),
        (2, 1, _digest("")),
        (0, 6, _digest("甲😀乙\n丙")),
        (True, 1, _digest("甲")),
        (0, False, _digest("")),
        (0, 1, "A" * 64),
        (0, 1, "0" * 64),
    ],
)
def test_validate_selection_rejects_invalid_range_or_selected_text_drift(
    start, end, digest,
):
    with pytest.raises(ValueError, match="invalid draft selection"):
        validate_selection("甲😀乙\n丙", start, end, digest)


@pytest.mark.parametrize("content", ["bad\ud800text", "bad\udcfftext"])
def test_validate_selection_rejects_non_utf8_unicode(content):
    with pytest.raises(ValueError, match="invalid draft selection"):
        validate_selection(content, 0, 1, "0" * 64)


def test_selection_context_is_bounded_to_three_hundred_scalars_each_side():
    content = "左" * 340 + "😀目标" + "右" * 360
    start = 340
    end = start + len("😀目标")
    target = validate_selection(content, start, end, _digest("😀目标"))

    context = selection_context(target)

    assert context == {
        "left": "左" * 300,
        "selected": "😀目标",
        "right": "右" * 300,
    }


def test_replace_selection_reconstructs_exact_text_and_inserted_scalar_range():
    target = validate_selection("前😀旧后", 1, 3, _digest("😀旧"))

    content, start, end = replace_selection(target, "新🌙段")

    assert content == "前新🌙段后"
    assert (start, end) == (1, 4)


@pytest.mark.parametrize("replacement", [None, "bad\ud800text"])
def test_replace_selection_rejects_invalid_unicode_replacement(replacement):
    target = validate_selection("旧文", 0, 2, _digest("旧文"))

    with pytest.raises(ValueError, match="invalid draft replacement"):
        replace_selection(target, replacement)
