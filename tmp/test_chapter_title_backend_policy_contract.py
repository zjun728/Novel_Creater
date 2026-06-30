from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "backend" / "routers" / "chapters.py").read_text(encoding="utf-8")

policy_source = SOURCE[
    SOURCE.index("CHAPTER_TITLE_PRONOUN_FRAGMENT_RE"):
    SOURCE.index("\nclass VersionCreate")
]
namespace = {"re": re}
exec(policy_source, namespace)

invalid_reason = namespace["_chapter_title_invalid_reason"]


BAD_TITLES = {
    "还有多远": "route_question_fragment",
    "多远了": "route_question_fragment",
    "走多久": "route_question_fragment",
    "到哪了": "route_question_fragment",
    "这通向哪": "direction_question_fragment",
    "往哪走": "direction_question_fragment",
    "去哪儿": "direction_question_fragment",
    "哪走": "direction_question_fragment",
    "就是这里": "location_pointer_fragment",
    "就在这儿": "location_pointer_fragment",
    "就是这边": "location_pointer_fragment",
    "不一定": "oral_judgment_fragment",
    "可支撑": "oral_judgment_fragment",
    "也许吧": "oral_judgment_fragment",
    "可能吧": "oral_judgment_fragment",
    "假的": "oral_judgment_fragment",
    "真的": "oral_judgment_fragment",
    "坐": "single_character_action_fragment",
    "走": "single_character_action_fragment",
    "追": "single_character_action_fragment",
    "看": "single_character_action_fragment",
    "等": "single_character_action_fragment",
    "跑": "single_character_action_fragment",
    "停": "single_character_action_fragment",
    "开": "single_character_action_fragment",
    "关": "single_character_action_fragment",
    "这边": "direction_fragment",
    "那边": "direction_fragment",
    "里面": "direction_fragment",
    "前头也有": "location_fragment",
}

GOOD_TITLES = [
    "庚七密室",
    "东城染坊",
    "星债会地窖",
    "火灶房",
    "十一号门",
    "铁盒纸条",
    "铁箱账本",
    "三号仓钥",
    "染坊钥匙",
    "密约残页",
    "旧铜钥匙",
    "星账换令",
    "两封相反的信",
    "审问",
    "交易",
    "破局",
    "星账最后一页",
]


for title, expected_reason in BAD_TITLES.items():
    actual = invalid_reason(title)
    assert actual == expected_reason, f"{title} should reject as {expected_reason}, got {actual!r}"

for title in GOOD_TITLES:
    actual = invalid_reason(title)
    assert actual == "", f"{title} should be accepted by backend title policy, got {actual!r}"

print("chapter title backend policy contract passed")
