from __future__ import annotations

import hashlib
import json

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.seeds import SeedPayload


def seed_values() -> dict[str, str]:
    return {
        "title": "典镇山河",
        "genre": "东方奇幻",
        "logline": "少年守着一部残缺县志，与吞噬地脉的黑潮对抗。",
        "protagonist": "被贬史官之子沈码",
        "desire": "重修县志，让被抹去的乡民重获姓名。",
        "coreConflict": "每写回一段历史，就会唤醒一头镇物。",
        "worldPressure": "黑潮逐年上涨，王朝却下令封存所有旧志。",
        "openingHook": "新县令到任当夜，县志上凭空多出了他的卒年。",
        "differentiation": "以地方志书写作为力量体系的群像叙事。",
    }


def test_seed_payload_round_trip_preserves_canonical_hash():
    payload = SeedPayload(**seed_values())

    restored = SeedPayload.model_validate(payload.model_dump(mode="json"))

    assert restored == payload
    assert canonical_hash(restored) == canonical_hash(payload)


def test_canonical_json_matches_compact_sorted_utf8_json_for_dict():
    value = {"z": "山河", "a": {"b": 2, "a": 1}}
    expected = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    rendered = canonical_json(value)

    assert rendered == expected
    assert "山河" in rendered
    assert "\\u5c71" not in rendered


def test_canonical_json_uses_model_json_dump_and_hashes_utf8_bytes():
    payload = SeedPayload(**seed_values())
    expected = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    rendered = canonical_json(payload)

    assert rendered == expected
    assert canonical_hash(payload) == hashlib.sha256(
        expected.encode("utf-8")
    ).hexdigest()
    assert canonical_hash(payload.model_dump(mode="json")) == canonical_hash(
        payload
    )
