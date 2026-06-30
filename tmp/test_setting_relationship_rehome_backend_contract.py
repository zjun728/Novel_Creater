import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.settings_library as settings_library  # noqa: E402


EXPECTED_SUMMARY = "陆沉舟通过铜扣继承父亲与星债会的问询权/债务关系，本章已使用一次问询权，后续仍需偿还或承担等价债务。"
EVIDENCE = "老人说：‘铜扣是真的，口令也是真的。’‘但星债会的规矩，你不是不知道——铜扣和口令只能换来试账资格，不是直接取物。’"


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def relationship_event(summary=None, stance="中立"):
    return {
        "id": "event-lcz-star-debt",
        "entity_id": "entity-bad-placeholder",
        "entity_name": "陆沉舟_星债会",
        "entity_type": "character",
        "change_type": "relationship",
        "field_path": "relationship",
        "new_value": settings_library._json({
            "targetEntityName": "星债会",
            "targetEntityType": "faction",
            "relationType": "债务",
            "stance": stance,
            "summary": summary or "陆沉舟通过铜扣继承了父亲陆长庚欠星债会的一次问询权，本章已使用该权利，但地下负责人说‘下次来，要还’，意味着陆沉舟欠星债会一次问询权（或等价债务）。",
        }),
        "evidence": EVIDENCE,
        "chapter_num": 69,
        "confidence": 0.8,
    }


SOURCE_ENTITY = {
    "id": "entity-lcz",
    "project_id": "project-1",
    "entity_type": "character",
    "name": "陆沉舟",
    "summary": "被逐出巡天司的少年。",
    "profile": settings_library._json({}),
    "aliases": settings_library._json([]),
}

TARGET_ENTITY = {
    "id": "entity-star-debt",
    "project_id": "project-1",
    "entity_type": "faction",
    "name": "星债会",
    "summary": "一个与星账、阵眼玉相关的神秘组织。",
    "profile": settings_library._json({}),
    "aliases": settings_library._json([]),
}

FINGERLESS_ENTITY = {
    "id": "entity-fingerless",
    "project_id": "project-1",
    "entity_type": "character",
    "name": "缺指男人",
    "summary": "持续追索陆沉舟的敌对者。",
    "profile": settings_library._json({}),
    "aliases": settings_library._json([]),
}

PLACEHOLDER_ENTITY = {
    "id": "entity-bad-placeholder",
    "project_id": "project-1",
    "entity_type": "character",
    "name": "陆沉舟_星债会",
    "summary": "第 68 章自动识别的设定",
    "tags": settings_library._json(["AI识别"]),
    "profile": settings_library._json({}),
}


async def assert_relationship_accept_rehomes_source_and_target():
    original_fetchone = settings_library.fetchone
    original_find_or_create_entity = settings_library._find_or_create_entity
    original_insert = settings_library._insert
    captured_find_calls = []
    inserted_relation = {}

    async def fake_find_or_create_entity(pid, entity_type, name, event):
        captured_find_calls.append((entity_type, name, event.get("entity_id")))
        if name == "陆沉舟_星债会":
            raise AssertionError("relationship accept must not use A_B as a source entity name")
        if event.get("entity_id") == "entity-bad-placeholder":
            raise AssertionError("relationship source/target lookup must not carry the placeholder entity_id")
        if entity_type == "character" and name == "陆沉舟":
            return SOURCE_ENTITY
        if entity_type == "faction" and name == "星债会":
            return TARGET_ENTITY
        raise AssertionError(f"unexpected entity lookup: {entity_type} {name}")

    async def fake_fetchone(sql, args=None):
        if "FROM setting_relations" in sql and "AND id=%s" in sql:
            return inserted_relation
        if "FROM setting_relations" in sql:
            return None
        if "FROM setting_entities" in sql and args:
            if len(args) >= 3 and args[1] == "character" and args[2] == "陆沉舟_星债会":
                return PLACEHOLDER_ENTITY
        return None

    async def fake_insert(table, values):
        if table != "setting_relations":
            raise AssertionError(f"relationship accept should only insert relation here, got {table}")
        inserted_relation.update(values)

    settings_library.fetchone = fake_fetchone
    settings_library._find_or_create_entity = fake_find_or_create_entity
    settings_library._insert = fake_insert
    try:
        result = await settings_library._apply_relationship_event("project-1", relationship_event())
        assert_equal(result["source_entity_id"], "entity-lcz", "source entity id")
        assert_equal(result["target_entity_id"], "entity-star-debt", "target entity id")
        assert_equal(result["relation_type"], "债务/问询权", "relation type should keep both debt and inquiry right")
        assert_equal(result["stance"], "中立", "stance")
        assert_equal(result["summary"], EXPECTED_SUMMARY, "summary should be product-normalized")
        assert_equal(result["evidence"], EVIDENCE, "evidence preserved")
        assert_equal(result["chapter_num"], 69, "chapter metadata")
        if any(call[1] == "陆沉舟_星债会" for call in captured_find_calls):
            raise AssertionError("A_B placeholder name must not be used for relationship entity lookup")
    finally:
        settings_library.fetchone = original_fetchone
        settings_library._find_or_create_entity = original_find_or_create_entity
        settings_library._insert = original_insert


async def assert_org_relationship_rehomes_without_character_placeholder():
    original_fetchone = settings_library.fetchone
    original_insert = settings_library._insert
    inserted_relation = {}

    xuntiansi = {
        "id": "entity-xuntiansi",
        "project_id": "project-1",
        "entity_type": "faction",
        "name": "巡天司",
        "summary": "监管修行者的组织。",
        "profile": settings_library._json({}),
        "aliases": settings_library._json([]),
    }
    shangmeng = {
        "id": "entity-shangmeng",
        "project_id": "project-1",
        "entity_type": "faction",
        "name": "商盟",
        "summary": "控制市面交易的商会势力。",
        "profile": settings_library._json({}),
        "aliases": settings_library._json([]),
    }
    event = {
        "id": "event-org-relation",
        "entity_id": "bad-placeholder-org-relation",
        "entity_name": "巡天司_商盟",
        "entity_type": "character",
        "change_type": "relationship",
        "field_path": "relationship",
        "new_value": settings_library._json({
            "targetEntityName": "商盟",
            "targetEntityType": "character",
            "relationType": "交易限制",
            "stance": "中立",
            "summary": "巡天司与商盟之间存在交易限制，不能直接通过外人转手账本。",
        }),
        "evidence": "巡天司的人不能直接跟商盟过账，这是规矩。",
        "chapter_num": 70,
        "confidence": 0.76,
    }

    async def fake_fetchone(sql, args=None):
        if "FROM setting_relations" in sql and "AND id=%s" in sql:
            return inserted_relation
        if "FROM setting_relations" in sql:
            return None
        if "FROM setting_entities" in sql and args:
            if "entity_type=%s AND name=%s" in sql:
                name = args[2]
                entity_type = args[1]
                if entity_type == "faction" and name == "巡天司":
                    return xuntiansi
                if entity_type == "faction" and name == "商盟":
                    return shangmeng
                return None
            if "name=%s" in sql:
                name = args[1]
                if name == "巡天司":
                    return xuntiansi
                if name == "商盟":
                    return shangmeng
        return None

    async def fake_insert(table, values):
        if table == "setting_entities":
            raise AssertionError(f"relationship accept must not create character placeholder for organization relation: {values}")
        if table != "setting_relations":
            raise AssertionError(f"unexpected insert table: {table}")
        inserted_relation.update(values)

    settings_library.fetchone = fake_fetchone
    settings_library._insert = fake_insert
    try:
        result = await settings_library._apply_relationship_event("project-1", event)
        assert_equal(result["source_entity_id"], "entity-xuntiansi", "organization source entity id")
        assert_equal(result["target_entity_id"], "entity-shangmeng", "organization target entity id")
        assert_equal(result["relation_type"], "交易限制", "organization relation type")
    finally:
        settings_library.fetchone = original_fetchone
        settings_library._insert = original_insert


async def assert_three_segment_relationship_rehomes_qualifier():
    original_fetchone = settings_library.fetchone
    original_insert = settings_library._insert
    inserted_relation = {}
    event = {
        "id": "event-new-threat",
        "entity_id": "entity-bad-three-segment",
        "entity_name": "缺指男人_陆沉舟_新威胁",
        "entity_type": "character",
        "change_type": "relationship",
        "field_path": "relationship",
        "new_value": settings_library._json({
            "targetEntityName": "陆沉舟",
            "targetEntityType": "character",
            "relationType": "威胁",
            "stance": "敌对",
            "summary": "缺指男人对陆沉舟发出新的威胁，要求他交出星账。",
        }),
        "evidence": "缺指男人说，三日后不交星账，就从小九开始收账。",
        "chapter_num": 76,
        "confidence": 0.77,
    }
    payload = settings_library._relationship_payload(event)
    assert_equal(settings_library._relationship_source_name_from_event(event, payload), "缺指男人", "three segment source")
    assert_equal(settings_library._relationship_target_name_from_event(event, payload), "陆沉舟", "three segment target")

    async def fake_fetchone(sql, args=None):
        if "FROM setting_relations" in sql and "AND id=%s" in sql:
            return inserted_relation
        if "FROM setting_relations" in sql:
            return None
        if "FROM setting_entities" in sql and args:
            if "entity_type=%s AND name=%s" in sql:
                if args[1] == "character" and args[2] == "缺指男人":
                    return FINGERLESS_ENTITY
                if args[1] == "character" and args[2] == "陆沉舟":
                    return SOURCE_ENTITY
            if "name=%s" in sql:
                if args[1] == "缺指男人":
                    return FINGERLESS_ENTITY
                if args[1] == "陆沉舟":
                    return SOURCE_ENTITY
        return None

    async def fake_insert(table, values):
        if table == "setting_entities":
            raise AssertionError(f"three-segment relationship must not create a character placeholder: {values}")
        if table != "setting_relations":
            raise AssertionError(f"unexpected insert table: {table}")
        inserted_relation.update(values)

    settings_library.fetchone = fake_fetchone
    settings_library._insert = fake_insert
    try:
        result = await settings_library._apply_relationship_event("project-1", event)
        assert_equal(result["source_entity_id"], "entity-fingerless", "three segment source id")
        assert_equal(result["target_entity_id"], "entity-lcz", "three segment target id")
        assert_equal(result["relation_type"], "威胁", "three segment relation type")
    finally:
        settings_library.fetchone = original_fetchone
        settings_library._insert = original_insert


async def assert_self_relationship_rehomes_without_active_relation():
    original_fetchone = settings_library.fetchone
    original_insert = settings_library._insert
    original_update_by_columns = settings_library._update_by_columns
    updated_entity = {}

    self_event = {
        "id": "event-self-relation",
        "entity_id": "entity-lcz",
        "entity_name": "陆沉舟",
        "entity_type": "character",
        "change_type": "relationship",
        "field_path": "relationship",
        "new_value": settings_library._json({
            "targetEntityName": "陆沉舟",
            "targetEntityType": "character",
            "relationType": "债务状态",
            "stance": "中立",
            "summary": "陆沉舟在本章确认自己仍背着星债会的偿还压力。",
        }),
        "evidence": "他把铜扣攥回袖口，知道这笔账还没完。",
        "chapter_num": 70,
        "confidence": 0.74,
    }

    async def fake_fetchone(sql, args=None):
        if "FROM setting_entities" in sql and args:
            if args[-1] == "entity-lcz" or (len(args) >= 3 and args[2] == "陆沉舟"):
                return {**SOURCE_ENTITY, **updated_entity}
        if "FROM setting_relations" in sql:
            return None
        return None

    async def fake_insert(table, values):
        if table == "setting_relations":
            raise AssertionError("self relationship must not be kept as active relation")
        raise AssertionError(f"unexpected insert table: {table}")

    async def fake_update_by_columns(table, values, where_sql, where_args):
        if table != "setting_entities":
            raise AssertionError(f"self relationship should rehome to entity profile, got {table}")
        profile = settings_library._decode_json(values.get("profile")) or {}
        rehomed_entries = []
        for key in ("observedFacts", "currentActions", "internalMechanisms"):
            value = profile.get(key) or []
            if isinstance(value, list):
                rehomed_entries.extend(value)
        if not any("星债会" in str(item) for item in rehomed_entries):
            raise AssertionError(f"self relationship profile should keep rehomed fact/action/mechanism, got {profile!r}")
        updated_entity.update(values)

    settings_library.fetchone = fake_fetchone
    settings_library._insert = fake_insert
    settings_library._update_by_columns = fake_update_by_columns
    try:
        result = await settings_library._apply_relationship_event("project-1", self_event)
        assert_equal(result["status"], "rehomed_to_entity_profile", "self relationship rehome status")
        assert_equal(result["source_entity_id"], "entity-lcz", "self relationship source id")
        assert_equal(result["target_entity_id"], "entity-lcz", "self relationship target id")
    finally:
        settings_library.fetchone = original_fetchone
        settings_library._insert = original_insert
        settings_library._update_by_columns = original_update_by_columns


async def assert_existing_relationship_conflict_still_blocks():
    original_fetchone = settings_library.fetchone

    async def fake_fetchone(sql, args=None):
        if "FROM setting_entities" in sql and args:
            if len(args) >= 3 and args[1] == "character" and args[2] == "陆沉舟":
                return SOURCE_ENTITY
            if len(args) >= 3 and args[1] == "faction" and args[2] == "星债会":
                return TARGET_ENTITY
            if len(args) >= 3 and args[2] == "陆沉舟_星债会":
                return PLACEHOLDER_ENTITY
        if "FROM setting_relations" in sql:
            assert_equal(args[1], "entity-lcz", "conflict check source")
            assert_equal(args[2], "entity-star-debt", "conflict check target")
            assert_equal(args[3], "债务/问询权", "conflict check relation type")
            return {
                "id": "relation-existing",
                "project_id": "project-1",
                "source_entity_id": "entity-lcz",
                "target_entity_id": "entity-star-debt",
                "relation_type": "债务/问询权",
                "stance": "敌对",
                "summary": "旧关系说明。",
            }
        return None

    settings_library.fetchone = fake_fetchone
    try:
        conflicts = await settings_library._collect_hard_setting_conflicts(
            "project-1",
            relationship_event(summary="陆沉舟通过铜扣使用一次问询权，但与星债会立场转为敌对。", stance="中立"),
        )
        if not conflicts:
            raise AssertionError("existing contradictory relationship should still require manual review")
        if not any("陆沉舟" in item and "星债会" in item for item in conflicts):
            raise AssertionError(f"relationship conflict should name real source/target, got {conflicts!r}")
    finally:
        settings_library.fetchone = original_fetchone


async def assert_accept_endpoint_repoints_relationship_event_to_source():
    original_fetchone = settings_library.fetchone
    original_execute = settings_library.execute
    original_collect = settings_library._collect_hard_setting_conflicts
    original_apply_relationship = settings_library._apply_relationship_event
    update_args = []
    fetched_after_update = False

    async def fake_fetchone(sql, args=None):
        nonlocal fetched_after_update
        if "FROM setting_change_events" in sql:
            if fetched_after_update:
                accepted = {**relationship_event(), "status": "accepted", "entity_id": "entity-lcz"}
                return accepted
            return relationship_event()
        return None

    async def fake_execute(sql, args=None):
        nonlocal fetched_after_update
        if "UPDATE setting_change_events SET status=%s, entity_id=%s" in sql:
            update_args.append(args)
            fetched_after_update = True

    async def fake_collect(pid, event):
        return []

    async def fake_apply_relationship(pid, event):
        return {
            "id": "relation-lcz-star-debt",
            "source_entity_id": "entity-lcz",
            "target_entity_id": "entity-star-debt",
            "relation_type": "债务/问询权",
        }

    settings_library.fetchone = fake_fetchone
    settings_library.execute = fake_execute
    settings_library._collect_hard_setting_conflicts = fake_collect
    settings_library._apply_relationship_event = fake_apply_relationship
    try:
        await settings_library.accept_setting_change_event("project-1", "event-lcz-star-debt", None)
        if not update_args:
            raise AssertionError("accept endpoint should update the change event")
        assert_equal(update_args[0][1], "entity-lcz", "accepted relationship event should point at source entity")
    finally:
        settings_library.fetchone = original_fetchone
        settings_library.execute = original_execute
        settings_library._collect_hard_setting_conflicts = original_collect
        settings_library._apply_relationship_event = original_apply_relationship


asyncio.run(assert_relationship_accept_rehomes_source_and_target())
asyncio.run(assert_org_relationship_rehomes_without_character_placeholder())
asyncio.run(assert_three_segment_relationship_rehomes_qualifier())
asyncio.run(assert_self_relationship_rehomes_without_active_relation())
asyncio.run(assert_existing_relationship_conflict_still_blocks())
asyncio.run(assert_accept_endpoint_repoints_relationship_event_to_source())

print("setting relationship rehome backend contract passed")
