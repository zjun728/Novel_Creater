import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.experience_cards as experience_cards  # noqa: E402


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


LONG_SOURCE_CARD_ID = "v2.2-dialogue-fear-nonsense-with-debt-book-and-copper-token"


expected_id = experience_cards._stable_uuid(f"system-card:{LONG_SOURCE_CARD_ID}")
actual_id = experience_cards._builtin_experience_card_id(LONG_SOURCE_CARD_ID)
assert_equal(len(actual_id), 36, "builtin experience card id must fit CHAR(36)")
assert_equal(actual_id, expected_id, "builtin experience card id should be stable")


async def assert_builtin_upsert_uses_stable_id_and_keeps_source_ref():
    original_loader = experience_cards._load_prompt_micro_demo_cards
    original_fetchone = experience_cards.fetchone
    original_upsert = experience_cards._upsert_by_id
    captured = []

    def fake_loader():
        return [{
            "card_id": LONG_SOURCE_CARD_ID,
            "version": "v2.2",
            "card_type": "prompt_injectable_dialogue",
            "card_title": "恐惧里的胡扯",
            "prompt_injection_safe_version": "恐惧场景里允许角色说半截废话来遮掩真实害怕。",
            "original_micro_demo": "他摸了半天钥匙，先骂门槛，又问今晚有没有热汤。",
            "anti_skeleton_effect": "不要让恐惧只变成说明和尖叫。",
            "dialogue_type": "恐惧里的胡扯",
            "prompt_readiness": "prompt-ready-low-dose",
            "micro_demo_chars": 23,
        }]

    async def fake_fetchone(sql, args=None):
        return None

    async def fake_upsert(table, values):
        captured.append((table, values))
        return True

    experience_cards._load_prompt_micro_demo_cards = fake_loader
    experience_cards.fetchone = fake_fetchone
    experience_cards._upsert_by_id = fake_upsert
    try:
        await experience_cards._ensure_builtin_experience_cards()
    finally:
        experience_cards._load_prompt_micro_demo_cards = original_loader
        experience_cards.fetchone = original_fetchone
        experience_cards._upsert_by_id = original_upsert

    if not captured:
        raise AssertionError("builtin experience cards should be upserted")
    table, values = captured[0]
    assert_equal(table, "experience_card", "upsert table")
    assert_equal(values["id"], expected_id, "upsert id")
    assert_equal(values["source_card_ref"], LONG_SOURCE_CARD_ID, "source card ref preserves original card id")
    if len(values["id"]) > 36:
        raise AssertionError(f"upsert id is too long: {values['id']}")


asyncio.run(assert_builtin_upsert_uses_stable_id_and_keeps_source_ref())

print("experience card builtin id contract passed")
