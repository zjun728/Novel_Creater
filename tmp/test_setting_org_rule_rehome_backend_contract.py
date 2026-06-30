import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.settings_library as settings_library  # noqa: E402


OLD_SUMMARY = "一个与星账、阵眼玉相关的神秘组织，陆沉舟母亲曾与之有关，陆沉舟需替母亲还一笔旧债给北街七号的沈姓债主。"
RULE_SUMMARY = "神秘组织，记录活人债务，以铜扣和欠条为凭证，不与外人做交易，有严格规矩。"
RULE_EVIDENCE = "星债会不对外人开放。铜扣是你的通行证，但星账是活人的债本。带着债本进去，等于把外面的债带进门里。会里不认这个。"
HARD_NEGATION = "星债会已与星账、阵眼玉、陆沉舟母亲旧债无关，只是茶楼里临时起名的无关势力。"


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def org_event():
    return {
        "id": "event-star-debt-rule",
        "entity_id": "entity-star-debt",
        "entity_name": "星债会",
        "entity_type": "faction",
        "change_type": "update_entity",
        "field_path": "summary",
        "old_value": "",
        "new_value": RULE_SUMMARY,
        "evidence": RULE_EVIDENCE,
        "chapter_num": 68,
        "confidence": 0.9,
    }


def org_entity():
    return {
        "id": "entity-star-debt",
        "project_id": "project-1",
        "entity_type": "faction",
        "name": "星债会",
        "summary": OLD_SUMMARY,
        "profile": settings_library._json({}),
        "aliases": settings_library._json([]),
    }


assert_equal(
    settings_library._is_org_rule_summary_refinement(
        "faction",
        "星债会",
        OLD_SUMMARY,
        RULE_SUMMARY,
        RULE_EVIDENCE,
    ),
    True,
    "org access/debt rule should be a refinement",
)

assert_equal(
    settings_library._is_org_rule_summary_refinement(
        "faction",
        "星债会",
        OLD_SUMMARY,
        HARD_NEGATION,
        "无规则揭示，只是否定旧记录。",
    ),
    False,
    "stable org relationship deletion must not be rehomed",
)

profile = {}
updates = {"summary": RULE_SUMMARY}
settings_library._rehome_org_rule_summary_update(profile, updates, org_event(), OLD_SUMMARY, RULE_SUMMARY)
if "summary" in updates:
    raise AssertionError("org rule refinement must not overwrite summary")
if not profile.get("internalMechanisms"):
    raise AssertionError("org rule refinement should append profile.internalMechanisms")
entry = profile["internalMechanisms"][-1]
assert "铜扣" in entry["value"]
assert "债本" in entry["evidence"]
assert_equal(entry["preservedSummary"], OLD_SUMMARY, "preserved summary")
assert_equal(profile["_dynamicStateMeta"]["internalMechanisms"]["chapterNum"], 68, "internalMechanisms meta")


async def assert_collect_conflicts_and_accept_path():
    original_fetchone = settings_library.fetchone
    original_find_or_create_entity = settings_library._find_or_create_entity
    original_update_by_columns = settings_library._update_by_columns
    captured_updates = {}

    async def fake_fetchone(sql, args=None):
        if "FROM setting_entities" in sql:
            merged = {**org_entity(), **captured_updates}
            return merged
        return None

    async def fake_find_or_create_entity(pid, entity_type, entity_name, event):
        return org_entity()

    async def fake_update_by_columns(table, updates, where_sql, where_args):
        captured_updates.update(updates)

    settings_library.fetchone = fake_fetchone
    settings_library._find_or_create_entity = fake_find_or_create_entity
    settings_library._update_by_columns = fake_update_by_columns
    try:
        conflicts = await settings_library._collect_hard_setting_conflicts("project-1", org_event())
        assert_equal(conflicts, [], "org rule refinement should not hard-block backend accept")

        await settings_library._apply_entity_event("project-1", org_event())
        if "summary" in captured_updates:
            raise AssertionError("accept path must preserve original summary for org rule refinement")
        profile_after = settings_library._decode_json(captured_updates.get("profile")) or {}
        if not profile_after.get("internalMechanisms"):
            raise AssertionError("accept path should write org rules into profile.internalMechanisms")
        assert "不对外人开放" in profile_after["internalMechanisms"][-1]["evidence"]
    finally:
        settings_library.fetchone = original_fetchone
        settings_library._find_or_create_entity = original_find_or_create_entity
        settings_library._update_by_columns = original_update_by_columns


asyncio.run(assert_collect_conflicts_and_accept_path())

print("setting org rule rehome backend contract passed")
