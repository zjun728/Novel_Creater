import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.settings_library as settings_library  # noqa: E402


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


for field_path in [
    "profile.location",
    "profile.currentGoal",
    "profile.physicalStatus",
    "profile.itemStatus",
    "profile.behaviorState",
    "profile.mentalState",
]:
    assert_equal(settings_library._field_tier(field_path), "dynamicState", f"{field_path} tier")
    assert_equal(settings_library._is_hard_setting_field(field_path), False, f"{field_path} hard field")

assert_equal(settings_library._field_tier("profile.ability"), "observedCapability", "ability tier")
assert_equal(settings_library._is_hard_setting_field("profile.ability"), False, "ability not hard field")
assert_equal(settings_library._field_tier("profile.faction"), "hardSetting", "faction tier")
assert_equal(settings_library._field_tier("profile.realm"), "hardSetting", "realm tier")
assert_equal(settings_library._field_tier("profile.fixedRelationship"), "hardSetting", "fixed relationship tier")

assert_equal(
    settings_library._is_ability_core_conflict(
        "会记债的账本，只记录活人的代价，每次使用必须付出现实代价，代价随机且不可逆；已展现能力星移，使用后显示下一线索及有效期",
        "会记债的账本，只记录活人的代价，每次使用必须付出现实代价，代价随机且不可逆；已展现能力星移，使用后显示下一线索及有效期；能主动显示指引文字",
        "星账浮现指引文字",
    ),
    False,
    "observed ability manifestation should not be hard conflict",
)

assert_equal(
    settings_library._is_ability_core_conflict(
        "只能转移债务，不能伪造或销毁，每次使用必须付出现实代价，代价随机且不可逆，只记录活人的代价",
        "星账不再需要付出代价，可以伪造和销毁，也可以记录死者债务",
        "无剧情代价铺垫",
    ),
    True,
    "ability core rule rewrite should be hard conflict",
)

meta = settings_library._change_event_meta({
    "chapter_num": 2,
    "evidence": "第 2 章定稿",
    "confidence": 0.9,
})
assert_equal(meta["chapterNum"], 2, "meta chapterNum")
assert_equal(meta["lastUpdatedChapter"], 2, "meta lastUpdatedChapter")
assert_equal(meta["evidence"], "第 2 章定稿", "meta evidence")
assert_equal(meta["confidence"], 0.9, "meta confidence")

print("setting field tiers backend contract tests passed")
