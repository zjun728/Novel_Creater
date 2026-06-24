import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.settings_library as settings_library  # noqa: E402


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_in(needle, haystack, message):
    if needle not in haystack:
        raise AssertionError(f"{message}: expected {needle!r} in {haystack!r}")


for field_path in [
    "profile.currentHolder",
    "profile.possessionStatus",
    "profile.custodyState",
    "profile.contactStatus",
    "profile.accessState",
    "holder",
    "currentHolder",
    "possessor",
    "currentPossessor",
    "custody",
    "possessionStatus",
    "contactStatus",
    "accessState",
]:
    assert_equal(settings_library._field_tier(field_path), "dynamicState", f"{field_path} tier")
    assert_equal(settings_library._is_hard_setting_field(field_path), False, f"{field_path} not hard")

assert_equal(settings_library._field_tier("profile.owner"), "hardSetting", "owner remains hard")
assert_equal(settings_library._is_hard_setting_field("profile.owner"), True, "owner remains hard field")


async def collect_conflicts(old_value, new_value, evidence):
    entity = {
        "id": "entity-1",
        "entity_type": "item",
        "name": "星债总账",
        "profile": json.dumps({"owner": old_value}, ensure_ascii=False),
        "summary": "星债总账是星债会保管的账册。",
    }
    event = {
        "id": "event-1",
        "entity_type": "item",
        "entity_name": "星债总账",
        "change_type": "update_entity",
        "field_path": "profile.owner",
        "old_value": old_value,
        "new_value": new_value,
        "evidence": evidence,
        "chapter_num": 3,
        "confidence": 0.9,
    }

    original_fetchone = settings_library.fetchone

    async def fake_fetchone(*_args, **_kwargs):
        return entity

    settings_library.fetchone = fake_fetchone
    try:
        return await settings_library._collect_hard_setting_conflicts("project-1", event)
    finally:
        settings_library.fetchone = original_fetchone


mixed_old_conflicts = asyncio.run(collect_conflicts(
    "未知（陆沉舟已接触但未取出）",
    "陆沉舟",
    "陆沉舟已接触星债总账，但章节只证明接触和取出账册，未证明法理归属转移。",
))
assert_equal(mixed_old_conflicts, [], "mixed unknown/contact owner should not hard conflict")

incoming_dynamic_conflicts = asyncio.run(collect_conflicts(
    "星债会",
    "陆沉舟已临时持有/已接触未取出",
    "陆沉舟把星债总账临时藏在身上，只说明当前持有与接触状态。",
))
assert_equal(incoming_dynamic_conflicts, [], "incoming dynamic possession should not hard conflict")

stable_conflicts = asyncio.run(collect_conflicts(
    "星债会",
    "陆沉舟",
    "无转让、夺取、继承或归还等剧情证据。",
))
if not stable_conflicts:
    raise AssertionError("stable owner A to stable owner B without transfer evidence must hard conflict")

transfer_conflicts = asyncio.run(collect_conflicts(
    "星债会",
    "陆沉舟",
    "星债会当众将星债总账正式转让给陆沉舟，确认所有权移交。",
))
assert_equal(transfer_conflicts, [], "explicit stable ownership transfer should be allowed")

profile = {"owner": "未知（陆沉舟已接触但未取出）"}
updates = {}
event = {
    "field_path": "profile.owner",
    "new_value": "陆沉舟",
    "evidence": "陆沉舟已接触星债总账，但未证明所有权转移。",
    "chapter_num": 3,
    "confidence": 0.9,
}
settings_library._rehome_owner_possession_update(
    profile,
    updates,
    event,
    "profile.owner",
    "未知（陆沉舟已接触但未取出）",
    "陆沉舟",
)
assert_equal(profile.get("owner"), "未知", "dynamic old owner should be cleaned to stable unknown")
if not profile.get("possessionStatus"):
    raise AssertionError("owner possession rehome should append profile.possessionStatus")
entry = profile["possessionStatus"][-1]
assert_in("陆沉舟", entry.get("value", ""), "rehome value should keep incoming holder")
assert_in("已接触但未取出", entry.get("preservedOwnerState", ""), "old dynamic owner state should be preserved")
assert_equal(entry.get("chapterNum"), 3, "rehome entry chapter")
assert_equal(profile["_dynamicStateMeta"]["possessionStatus"]["lastUpdatedChapter"], 3, "dynamic meta chapter")

print("owner possession rehoming backend contract tests passed")
