import pathlib
import sys
import asyncio

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.settings_library as settings_library  # noqa: E402


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


async def assert_miner_creditor_accept_has_no_hard_conflict():
    original_fetchone = settings_library.fetchone

    async def fake_fetchone(sql, args=None):
        if "FROM setting_entities" in sql:
            return {
                "id": "entity-miner-creditor",
                "project_id": "project-1",
                "entity_type": "character",
                "name": "矿山债主",
                "summary": MINER_CREDITOR_OLD_SUMMARY,
                "profile": settings_library._json({}),
                "aliases": settings_library._json([]),
            }
        return None

    settings_library.fetchone = fake_fetchone
    try:
        conflicts = await settings_library._collect_hard_setting_conflicts("project-1", {
            "id": "event-1",
            "entity_id": "entity-miner-creditor",
            "entity_name": "矿山债主",
            "entity_type": "character",
            "change_type": "update_entity",
            "field_path": "summary",
            "old_value": MINER_CREDITOR_OLD_SUMMARY,
            "new_value": MINER_CREDITOR_NEW_SUMMARY,
            "evidence": MINER_CREDITOR_EVIDENCE,
            "chapter_num": 2,
            "confidence": 0.9,
        })
    finally:
        settings_library.fetchone = original_fetchone

    assert_equal(conflicts, [], "backend accept hard conflict collection")


async def assert_affiliation_reveal_accept_has_no_hard_conflict():
    original_fetchone = settings_library.fetchone

    async def fake_fetchone(sql, args=None):
        if "FROM setting_entities" in sql:
            return {
                "id": "entity-toothpick",
                "project_id": "project-1",
                "entity_type": "character",
                "name": "剔牙男人",
                "summary": "跟在陆沉舟后方的剔牙男人。",
                "profile": settings_library._json({"faction": "与缺指男人同一势力"}),
                "aliases": settings_library._json([]),
            }
        return None

    settings_library.fetchone = fake_fetchone
    try:
        conflicts = await settings_library._collect_hard_setting_conflicts("project-1", {
            "id": "event-affiliation-reveal",
            "entity_id": "entity-toothpick",
            "entity_name": "剔牙男人",
            "entity_type": "character",
            "change_type": "update_entity",
            "field_path": "profile.faction",
            "old_value": "与缺指男人同一势力",
            "new_value": "巡天司（暗哨）",
            "evidence": "剔牙男人拿出巡天司暗哨令牌。",
            "chapter_num": 43,
            "confidence": 0.86,
        })
    finally:
        settings_library.fetchone = original_fetchone

    assert_equal(conflicts, [], "faction weak inference plus dark-post reveal should not hard conflict")


OFFICIAL_ORG_SUMMARY = "巡天司是大靖朝廷设立的官方机构，负责巡查九州异象、缉拿违规修士，并掌握部分旧档案。"
OFFICIAL_ORG_WITH_FACTS = "巡天司是大靖朝廷设立的官方机构，负责巡查九州异象、缉拿违规修士，并掌握部分旧档案。第 2 章揭示其存在内部处决机制，司主正在追捕陆沉舟，方鹤暗中帮助陆沉舟。"
SECRET_ORG_SUMMARY = "星债会是围绕星账债务运转的秘密组织，暗中收集债务线索并操纵欠债者。"
SECRET_ORG_REWRITE = "星债会不再是秘密组织，而是公开官署，负责正式登记所有星账债务。"
DESCRIPTIVE_PLACEHOLDER_SUMMARY = "在矿城西区木门后出现的老人，知道陆沉舟父亲和庚子账，主动引陆沉舟进入，可能是父亲旧识或关键情报源。"
FORMAL_IDENTITY_SUMMARY = "宋怀安，前矿北账务所账房，与陆怀安共事大半年，陆怀安留信物与他，掌握庚子账线索。"
MINER_CREDITOR_OLD_SUMMARY = "自称替陆沉舟父亲收债的神秘矿工，可能掌握父亲债务的细节或与玉虚峰矿山的交易内幕，后续可能引导调查或成为敌对。"
MINER_CREDITOR_NEW_SUMMARY = "自称替私人债主收债的玉虚峰丙七矿区矿工，曾是陆沉舟父亲的跟班矿工，认识巡天司北城执事赵鹤，知道星账在陆沉舟手中，并提供了逃跑路线和欠条。"
MINER_CREDITOR_EVIDENCE = "“我给他当了两年跟班矿工。”“我不是债主——我是来替他收债的。”“你认识赵鹤？”“你爹生前跟我说过那本账。”"


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
    "profile.affiliationClaims",
    "profile.hiddenAffiliation",
    "profile.currentRole",
    "profile.identityReveal",
    "profile.identityReveals",
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
    settings_library._is_summary_identity_background_reveal(
        MINER_CREDITOR_OLD_SUMMARY,
        MINER_CREDITOR_NEW_SUMMARY,
        MINER_CREDITOR_EVIDENCE,
    ),
    True,
    "uncertain summary plus concrete identity/background evidence should be reveal",
)
assert_equal(
    settings_library._allows_layered_hard_field_reveal(
        MINER_CREDITOR_OLD_SUMMARY,
        MINER_CREDITOR_NEW_SUMMARY,
        MINER_CREDITOR_EVIDENCE,
    ),
    True,
    "background reveal should suppress hard summary rewrite warning",
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
    settings_library._is_summary_identity_background_reveal(
        "张三，巡天司执事，长期负责北城旧档。",
        "李四，商盟长老，长期负责资源交易。",
        "无伪装、化名或误认证据。",
    ),
    False,
    "stable identity replacement without reveal evidence should still block",
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
assert_equal(
    settings_library._is_faction_affiliation_reveal_rehome_change(
        "profile.faction",
        "与缺指男人同一势力",
        "巡天司（暗哨）",
        "剔牙男人拿出巡天司暗哨令牌。",
    ),
    True,
    "weak inferred faction plus explicit dark-post evidence should be rehomed",
)
assert_equal(
    settings_library._is_faction_affiliation_reveal_rehome_change(
        "profile.faction",
        "未知势力，可能与巡天司或商盟有关",
        "巡天司",
        "缺指男人指挥巡天司暗哨设伏，瘦高个巡天司领队听从其命令。",
    ),
    True,
    "unknown possible faction plus command evidence should be rehomed as affiliation reveal",
)
assert_equal(
    settings_library._is_faction_affiliation_reveal_rehome_change(
        "profile.faction",
        "巡天司",
        "星债会核心成员",
        "无卧底、伪装、暗线或身份揭示证据。",
    ),
    False,
    "stable faction rewrite should remain a hard conflict",
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

profile = {"faction": "与缺指男人同一势力"}
updates = {}
event = {
    "entity_name": "剔牙男人",
    "field_path": "profile.faction",
    "new_value": "巡天司（暗哨）",
    "evidence": "剔牙男人拿出巡天司暗哨令牌。",
    "chapter_num": 43,
    "confidence": 0.86,
}
settings_library._rehome_faction_affiliation_reveal_update(
    profile,
    updates,
    event,
    "profile.faction",
    "与缺指男人同一势力",
    "巡天司（暗哨）",
)
assert_equal(profile["faction"], "与缺指男人同一势力", "hard faction should not be overwritten by dark-post reveal")
if not profile.get("hiddenAffiliation"):
    raise AssertionError("dark-post reveal should append profile.hiddenAffiliation")
if not profile.get("affiliationClaims"):
    raise AssertionError("dark-post reveal should append profile.affiliationClaims")
if not profile.get("observedFacts"):
    raise AssertionError("dark-post reveal should append profile.observedFacts")
assert "巡天司" in profile["hiddenAffiliation"][-1]["value"]
assert_equal(profile["_dynamicStateMeta"]["hiddenAffiliation"]["chapterNum"], 43, "hiddenAffiliation meta")

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

background_entity = {
    "name": "矿山债主",
    "summary": MINER_CREDITOR_OLD_SUMMARY,
    "aliases": settings_library._json([]),
}
background_profile = {}
background_updates = {}
background_event = {
    "entity_name": "矿山债主",
    "field_path": "summary",
    "new_value": MINER_CREDITOR_NEW_SUMMARY,
    "evidence": MINER_CREDITOR_EVIDENCE,
    "chapter_num": 2,
    "confidence": 0.9,
}
settings_library._apply_identity_background_reveal_update(
    background_entity,
    background_profile,
    background_updates,
    background_event,
    MINER_CREDITOR_OLD_SUMMARY,
    MINER_CREDITOR_NEW_SUMMARY,
)
if "name" in background_updates:
    raise AssertionError("background reveal without formal name must not change canonicalName")
assert_equal(background_updates["summary"], MINER_CREDITOR_NEW_SUMMARY, "specific background reveal may update summary")
if not background_profile.get("identityReveal"):
    raise AssertionError("background reveal should be preserved in profile.identityReveal")
if "神秘矿工" not in background_profile.get("identityReveal", ""):
    raise AssertionError("old uncertain clue should be preserved in identityReveal")

assert_equal(settings_library._is_invalid_entity_name("陆沉舟-方鹤"), True, "relation-like name should be invalid")
assert_equal(settings_library._is_invalid_entity_name("死去三年"), True, "time/phrase name should be invalid")
assert_equal(settings_library._is_invalid_entity_name("陆远之"), False, "normal name should be valid")

asyncio.run(assert_miner_creditor_accept_has_no_hard_conflict())
asyncio.run(assert_affiliation_reveal_accept_has_no_hard_conflict())

print("setting summary write policy backend contract tests passed")
