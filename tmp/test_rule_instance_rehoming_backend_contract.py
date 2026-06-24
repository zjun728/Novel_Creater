import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.settings_library as settings_library  # noqa: E402


OLD_SUMMARY = "星账只记录活人的代价，每次使用必须付出现实代价，代价不可逆且随次数递增，星账不可复制，只能由持有者主动使用或转让。这是推动剧情和主角选择的核心硬规则。"
INSTANCE_SUMMARY = "星账只记录活人的代价，每次使用必须付出现实代价，代价不可逆且随次数递增（第一次左眼视力三成，第二次右眼视力七成），星账不可复制，只能由持有者主动使用或转让。这是推动剧情和主角选择的核心硬规则。"
REWRITE_SUMMARY = "星账不再需要付出现实代价，代价可以逆转，也可以复制星账并记录死人代价。"


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


assert_equal(settings_library._field_tier("profile.observedCosts"), "dynamicState", "observedCosts tier")
assert_equal(settings_library._is_hard_setting_field("profile.observedCosts"), False, "observedCosts not hard")
assert_equal(settings_library._is_hard_setting_field("profile.costHistory"), False, "costHistory not hard")
assert_equal(settings_library._is_hard_setting_field("profile.ruleExamples"), False, "ruleExamples not hard")

assert_equal(
    settings_library._is_rule_instance_summary_supplement(
        OLD_SUMMARY,
        INSTANCE_SUMMARY,
        "陆沉舟欠债一次，代价：左眼视力三成。第二次使用，代价：右眼视力七成",
    ),
    True,
    "summary with observed costs should be detected as rule instance supplement",
)
assert_equal(
    settings_library._is_rule_instance_summary_supplement(OLD_SUMMARY, REWRITE_SUMMARY, ""),
    False,
    "core rule rewrite must not be treated as an observed instance",
)

event = {
    "entity_name": "星账代价规则",
    "field_path": "summary",
    "new_value": INSTANCE_SUMMARY,
    "evidence": "陆沉舟欠债一次，代价：左眼视力三成。第二次使用，代价：右眼视力七成",
    "chapter_num": 3,
    "confidence": 1,
}
profile = {"costRule": "代价不可逆且随次数递增；首次使用代价为左眼视力三成，后续代价更严重"}
updates = {}
settings_library._rehome_rule_instance_summary_update(profile, updates, event, OLD_SUMMARY, INSTANCE_SUMMARY)

if "summary" in updates:
    raise AssertionError("rule instance rehome must not update hard summary")
if not profile.get("observedCosts"):
    raise AssertionError("rule instance rehome should append profile.observedCosts")

entry = profile["observedCosts"][-1]
assert_equal(entry["chapterNum"], 3, "observed cost chapter")
assert "左眼视力三成" in entry["value"]
assert "右眼视力七成" in entry["value"]
assert "陆沉舟欠债一次" in entry["evidence"]

print("rule instance rehoming backend contract tests passed")
