import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.settings_library as settings_library  # noqa: E402


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


OFFICIAL_ORG_SUMMARY = "巡天司是大靖朝廷设立的官方机构，负责巡查九州异象、缉拿违规修士，并掌握部分旧档案。"
OFFICIAL_ORG_WITH_FACTS = "巡天司是大靖朝廷设立的官方机构，负责巡查九州异象、缉拿违规修士，并掌握部分旧档案。第 2 章揭示其存在内部处决机制，司主正在追捕陆沉舟，方鹤暗中帮助陆沉舟。"
SECRET_ORG_SUMMARY = "星债会是围绕星账债务运转的秘密组织，暗中收集债务线索并操纵欠债者。"
SECRET_ORG_REWRITE = "星债会不再是秘密组织，而是公开官署，负责正式登记所有星账债务。"
DESCRIPTIVE_PLACEHOLDER_SUMMARY = "在矿城西区木门后出现的老人，知道陆沉舟父亲和庚子账，主动引陆沉舟进入，可能是父亲旧识或关键情报源。"
FORMAL_IDENTITY_SUMMARY = "宋怀安，前矿北账务所账房，与陆怀安共事大半年，陆怀安留信物与他，掌握庚子账线索。"


assert_equal(settings_library._is_placeholder_summary("第 1 章自动识别的设定"), True, "numbered placeholder")
assert_equal(settings_library._is_placeholder_summary("第 ? 章自动识别的设定"), True, "unknown chapter placeholder")
assert_equal(settings_library._is_placeholder_summary(""), True, "empty summary placeholder")

for field_path in [
    "profile.observedFacts",
    "profile.revealedClues",
    "profile.currentActions",
    "profile.internalMechanisms",
    "profile.chapterEvidence",
    "profile.hiddenStance",
    "profile.currentAction",
]:
    assert_equal(settings_library._field_tier(field_path), "dynamicState", f"{field_path} tier")
    assert_equal(settings_library._is_hard_setting_field(field_path), False, f"{field_path} not hard")

assert_equal(
    settings_library._is_summary_chapter_fact_supplement(
        OFFICIAL_ORG_SUMMARY,
        OFFICIAL_ORG_WITH_FACTS,
        "第 2 章定稿后设定抽取：章节揭示、行动、线索、内部机制",
    ),
    True,
    "stable org summary plus chapter facts should be detected",
)
assert_equal(
    settings_library._is_descriptive_placeholder_identity_reveal(
        "木门后老人",
        DESCRIPTIVE_PLACEHOLDER_SUMMARY,
        FORMAL_IDENTITY_SUMMARY,
        "老人承认自己叫宋怀安，曾任矿北账务所账房，并拿出陆怀安留下的信物。",
    ),
    True,
    "descriptive placeholder identity reveal should be detected",
)
assert_equal(
    settings_library._is_descriptive_placeholder_identity_reveal(
        "陆远之",
        "陆远之，陆沉舟的父亲，曾任巡天司星吏，三年前在北境矿案后失踪。",
        FORMAL_IDENTITY_SUMMARY,
        "无伪装、化名或误认证据。",
    ),
    False,
    "stable formal name rewrite should not be treated as identity reveal",
)
assert_equal(
    settings_library._is_hard_summary_rewrite(
        OFFICIAL_ORG_SUMMARY,
        "巡天司其实不是官方机构，而是商盟在朝廷外伪造的分部。",
    ),
    True,
    "official organization identity rewrite should block",
)
assert_equal(
    settings_library._is_hard_summary_rewrite(SECRET_ORG_SUMMARY, SECRET_ORG_REWRITE),
    True,
    "secret organization identity rewrite should block",
)
assert_equal(
    settings_library._is_hard_field_behavior_supplement(
        "profile.faction",
        "巡天司",
        "巡天司（见习吏，但暗中帮助陆沉舟）",
        "方鹤表面隶属巡天司，暗中帮助陆沉舟。",
    ),
    True,
    "hard faction plus hidden behavior should be rehomed",
)
assert_equal(
    settings_library._is_hard_field_behavior_supplement("profile.faction", "巡天司", "商盟", ""),
    False,
    "direct faction replacement must not be treated as behavior supplement",
)

profile = {}
updates = {"summary": OFFICIAL_ORG_WITH_FACTS}
event = {
    "entity_name": "巡天司",
    "field_path": "summary",
    "new_value": OFFICIAL_ORG_WITH_FACTS,
    "evidence": "第 2 章定稿后设定抽取：章节揭示、行动、线索、内部机制",
    "chapter_num": 2,
    "confidence": 0.9,
}
settings_library._rehome_summary_chapter_fact_update(profile, updates, event, OFFICIAL_ORG_SUMMARY, OFFICIAL_ORG_WITH_FACTS)
if "summary" in updates:
    raise AssertionError("chapter fact supplement must not update hard summary")
if not profile.get("observedFacts"):
    raise AssertionError("chapter fact supplement should append profile.observedFacts")
entry = profile["observedFacts"][-1]
assert "内部处决机制" in entry["value"]
assert_equal(entry["preservedSummary"], OFFICIAL_ORG_SUMMARY, "preserved hard summary")
assert_equal(profile["_dynamicStateMeta"]["observedFacts"]["chapterNum"], 2, "observedFacts meta")

profile = {"faction": "巡天司"}
updates = {}
event = {
    "entity_name": "方鹤",
    "field_path": "profile.faction",
    "new_value": "巡天司（见习吏，但暗中帮助陆沉舟）",
    "evidence": "方鹤表面隶属巡天司，暗中帮助陆沉舟。",
    "chapter_num": 2,
    "confidence": 0.9,
}
settings_library._rehome_hard_field_behavior_update(profile, updates, event, "profile.faction", "巡天司", "巡天司（见习吏，但暗中帮助陆沉舟）")
assert_equal(profile["faction"], "巡天司", "hard faction should remain stable")
if not profile.get("hiddenStance"):
    raise AssertionError("hidden behavior should append profile.hiddenStance")
assert "暗中帮助陆沉舟" in profile["hiddenStance"][-1]["value"]
assert_equal(profile["_dynamicStateMeta"]["hiddenStance"]["chapterNum"], 2, "hiddenStance meta")

entity = {
    "summary": "第 1 章自动识别的设定",
    "tags": settings_library._json(["AI识别", "父亲"]),
}
updates = {}
settings_library._apply_placeholder_summary_completion(entity, updates, "完整父亲设定")
assert_equal(updates["summary"], "完整父亲设定", "placeholder summary should be completed")
tags = settings_library._decode_json(updates["tags"])
if "AI识别" in tags:
    raise AssertionError("placeholder completion should remove AI识别 tag")

identity_entity = {
    "name": "木门后老人",
    "summary": DESCRIPTIVE_PLACEHOLDER_SUMMARY,
    "aliases": settings_library._json([]),
}
identity_profile = {}
identity_updates = {}
identity_event = {
    "entity_name": "木门后老人",
    "field_path": "summary",
    "new_value": FORMAL_IDENTITY_SUMMARY,
    "evidence": "老人承认自己叫宋怀安，曾任矿北账务所账房，并拿出陆怀安留下的信物。",
    "chapter_num": 8,
    "confidence": 0.9,
}
settings_library._apply_descriptive_identity_reveal_update(
    identity_entity,
    identity_profile,
    identity_updates,
    identity_event,
    DESCRIPTIVE_PLACEHOLDER_SUMMARY,
    FORMAL_IDENTITY_SUMMARY,
)
assert_equal(identity_updates["name"], "宋怀安", "formal name should become canonical name")
aliases = settings_library._decode_json(identity_updates["aliases"])
if "木门后老人" not in aliases:
    raise AssertionError("descriptive placeholder name should be preserved in aliases")
if "旧描述" not in identity_profile.get("identityReveal", "") and "木门后老人" not in identity_profile.get("identityReveal", ""):
    raise AssertionError("identity reveal details should be preserved in profile.identityReveal")

assert_equal(settings_library._is_invalid_entity_name("陆沉舟-方鹤"), True, "relation-like name should be invalid")
assert_equal(settings_library._is_invalid_entity_name("死去三年"), True, "time/phrase name should be invalid")
assert_equal(settings_library._is_invalid_entity_name("陆远之"), False, "normal name should be valid")

print("setting summary write policy backend contract tests passed")
