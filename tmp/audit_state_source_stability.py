"""Lightweight identity/source-state audit helpers used by contracts.

The audit keeps canon-fact ``related_characters`` references from inflating the
character model. Organization names, aliases of already merged character
entities, and possessive relationship mentions are explained separately; only
the remainder stays unresolved.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any


PARENS_RE = re.compile(r"（([^）]+)）|\(([^)]+)\)")


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _decode_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_as_text(item) for item in value if _as_text(item)]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except ValueError:
            return [text]
        return _decode_list(parsed)
    return []


def _decode_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _name_parts(value: str) -> set[str]:
    text = _as_text(value)
    if not text:
        return set()
    parts = {text}
    base = PARENS_RE.sub("", text).strip()
    if base:
        parts.add(base)
    for match in PARENS_RE.finditer(text):
        alias = (match.group(1) or match.group(2) or "").strip()
        if alias:
            parts.add(alias)
    return parts


def _entity_names(entity: dict[str, Any]) -> set[str]:
    names = set(_name_parts(entity.get("name")))
    names.update(_decode_list(entity.get("aliases")))
    profile = _decode_object(entity.get("profile"))
    names.update(_name_parts(profile.get("canonicalName")))
    names.update(_name_parts(profile.get("identity")))
    for persona in profile.get("personas") or []:
        if isinstance(persona, dict):
            names.update(_name_parts(persona.get("name")))
    return {name for name in names if name}


def _character_rows(characters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for character in characters or []:
        names = set(_name_parts(character.get("name")))
        names.update(_decode_list(character.get("aliases")))
        if names:
            rows.append({"raw": character, "names": names})
    return rows


def _count_items(counter: Counter[str], names: set[str]) -> list[dict[str, Any]]:
    return [
        {"name": name, "count": counter[name]}
        for name in counter
        if name in names
    ]


def _is_same_title_family(ref: str, known_names: set[str]) -> bool:
    if not ref or len(ref) < 2:
        return False
    surname = ref[0]
    title_markers = ("主簿", "掌柜", "长老", "先生", "真人", "道士", "和尚")
    return any(name.startswith(surname) and any(marker in name for marker in title_markers) for name in known_names)


def summarize_identity_model(
    entities: list[dict[str, Any]] | None,
    facts: list[dict[str, Any]] | None,
    characters: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    character_entities = [
        entity for entity in entities or []
        if _as_text(entity.get("entity_type") or entity.get("entityType")) == "character"
    ]
    organization_entities = [
        entity for entity in entities or []
        if _as_text(entity.get("entity_type") or entity.get("entityType")) in {"faction", "organization", "org"}
    ]

    setting_character_names = set()
    for entity in character_entities:
        setting_character_names.update(_entity_names(entity))

    organization_names = set()
    for entity in organization_entities:
        organization_names.update(_entity_names(entity))

    character_rows = _character_rows(characters or [])
    matched_character_row_names = set()
    relationship_row_names = set()
    for row in character_rows:
        if row["names"] & setting_character_names:
            matched_character_row_names.update(row["names"])
        else:
            relationship_row_names.update(row["names"])

    refs: list[str] = []
    for fact in facts or []:
        refs.extend(_decode_list(fact.get("related_characters") or fact.get("relatedCharacters")))
    counter = Counter(refs)

    organization_refs = set()
    merged_character_refs = set()
    pending_relationship_refs = set()
    unresolved_refs = set()

    for ref in counter:
        if ref in organization_names:
            organization_refs.add(ref)
        elif ref in setting_character_names or ref in matched_character_row_names or _is_same_title_family(ref, setting_character_names | matched_character_row_names):
            merged_character_refs.add(ref)
        elif "的" in ref or ref in relationship_row_names:
            pending_relationship_refs.add(ref)
        else:
            unresolved_refs.add(ref)

    return {
        "characterArcMergeBeforeAfter": {
            "charactersTableRawCount": len(characters or []),
            "settingCharacterEntityCount": len(character_entities),
            "canonicalPersonCountAfterMerge": len(character_entities),
            "noFactIsolatedPersonCount": max(0, len(character_rows) - len(character_entities)),
        },
        "unresolvedCharacterRefGovernance": {
            "beforeCount": len(counter),
            "afterCount": len(unresolved_refs),
            "organizationRefs": _count_items(counter, organization_refs),
            "mergedCharacterRefs": _count_items(counter, merged_character_refs),
            "pendingRelationshipRefs": _count_items(counter, pending_relationship_refs),
            "unresolvedCharacterRefs": _count_items(counter, unresolved_refs),
        },
    }
