"""Pure exact-selection helpers for local WorkingDraft operations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re


LOCAL_DRAFT_OPERATION_INTENTS = {
    "rewrite_selection": "rewrite",
    "polish_selection": "polish",
    "expand_selection": "expand",
    "compress_selection": "compress",
}
LOCAL_DRAFT_OPERATION_TYPES = frozenset(LOCAL_DRAFT_OPERATION_INTENTS)

_HASH = re.compile(r"^[0-9a-f]{64}$")
_CONTEXT_SCALARS = 300


@dataclass(frozen=True)
class DraftSelection:
    content: str
    prefix: str
    selected_text: str
    suffix: str
    start_offset: int
    end_offset: int
    selected_text_hash: str


def _valid_utf8(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def validate_selection(
    content: object,
    start_offset: object,
    end_offset: object,
    selected_text_hash: object,
) -> DraftSelection:
    if (
        not _valid_utf8(content)
        or isinstance(start_offset, bool)
        or not isinstance(start_offset, int)
        or isinstance(end_offset, bool)
        or not isinstance(end_offset, int)
        or start_offset < 0
        or end_offset <= start_offset
        or end_offset > len(content)
        or not isinstance(selected_text_hash, str)
        or _HASH.fullmatch(selected_text_hash) is None
    ):
        raise ValueError("invalid draft selection")

    selected_text = content[start_offset:end_offset]
    digest = hashlib.sha256(selected_text.encode("utf-8")).hexdigest()
    if digest != selected_text_hash:
        raise ValueError("invalid draft selection")
    return DraftSelection(
        content=content,
        prefix=content[:start_offset],
        selected_text=selected_text,
        suffix=content[end_offset:],
        start_offset=start_offset,
        end_offset=end_offset,
        selected_text_hash=selected_text_hash,
    )


def selection_context(target: DraftSelection) -> dict[str, str]:
    if not isinstance(target, DraftSelection):
        raise ValueError("invalid draft selection")
    return {
        "left": target.prefix[-_CONTEXT_SCALARS:],
        "selected": target.selected_text,
        "right": target.suffix[:_CONTEXT_SCALARS],
    }


def replace_selection(
    target: DraftSelection,
    replacement: object,
) -> tuple[str, int, int]:
    if not isinstance(target, DraftSelection) or not _valid_utf8(replacement):
        raise ValueError("invalid draft replacement")
    return (
        target.prefix + replacement + target.suffix,
        target.start_offset,
        target.start_offset + len(replacement),
    )
