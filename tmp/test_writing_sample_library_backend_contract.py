import json
import asyncio
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def assert_contains(text: str, needle: str, label: str) -> None:
    assert needle in text, f"missing {label}: {needle}"


def test_schema_and_runtime_migrations_cover_sample_library_v1():
    schema_sql = read("backend/schema.sql")
    database_py = read("backend/database.py")
    required_tables = [
        "sample_source",
        "sample_chunk",
        "experience_card",
        "writing_standard_candidate",
        "writing_standard",
    ]
    for table in required_tables:
        assert_contains(schema_sql, f"CREATE TABLE IF NOT EXISTS {table}", f"schema table {table}")
        assert_contains(database_py, f"CREATE TABLE IF NOT EXISTS {table}", f"runtime migration table {table}")

    for status in ["candidate", "reviewed", "rejected", "merged", "archived"]:
        assert_contains(schema_sql, status, f"experience card status {status}")
    for status in ["draft", "reviewing", "approved", "rejected", "promoted"]:
        assert_contains(schema_sql, status, f"standard candidate status {status}")


def test_experience_cards_router_exposes_minimum_api_and_seed_import():
    router_path = ROOT / "backend" / "routers" / "experience_cards.py"
    assert router_path.exists(), "backend/routers/experience_cards.py must exist"
    router_py = router_path.read_text(encoding="utf-8")
    main_py = read("backend/main.py")

    assert_contains(main_py, "experience_cards", "main router import")
    assert_contains(main_py, "experience_cards.router", "main router registration")

    for route in [
        "/experience-cards/sources",
        "/experience-cards/cards",
        "/experience-cards/cards/{card_id}/review",
        "/experience-cards/cards/{card_id}/reject",
        "/experience-cards/cards/{card_id}/archive",
        "/experience-cards/candidates",
        "/experience-cards/candidates/{candidate_id}/approve",
        "/experience-cards/candidates/{candidate_id}/reject",
        "/experience-cards/candidates/{candidate_id}/promote",
        "/experience-cards/standards",
        "/experience-cards/seed-local-report",
    ]:
        assert_contains(router_py, route, f"API route {route}")

    assert_contains(router_py, "localWritingSampleReport.json", "local report seed import")
    assert_contains(router_py, "reviewed", "card review transition")
    assert_contains(router_py, "merged", "card merge transition")
    assert_contains(router_py, "promoted", "candidate promote transition")


def test_sanitizer_prevents_source_text_and_sample_names_from_prompt_standards():
    router_py = read("backend/routers/experience_cards.py")
    helpers_py = read("backend/routers/helpers.py")

    for field in ["rawExcerpt", "sourceText", "sourceCardIds"]:
        assert_contains(router_py, field, f"sanitizer forbidden field {field}")

    for forbidden_name in ["凡人修仙传", "四世同堂", "韩立", "黄枫谷"]:
        assert_contains(router_py, forbidden_name, f"sanitizer sample token {forbidden_name}")

    for json_field in [
        "chunk_ids",
        "genre_tags",
        "avoid_patterns",
        "metrics_json",
        "safety_flags",
        "source_card_ids",
        "merged_guidance",
        "audit_focus",
        "guidance_json",
    ]:
        assert_contains(helpers_py, json_field, f"JSON field conversion {json_field}")
    assert_contains(helpers_py, "no_direct_imitation", "bool conversion no_direct_imitation")


def test_local_report_still_has_46_abstract_cards_for_migration():
    report = json.loads(read("frontend/src/data/localWritingSampleReport.json"))
    cards = report.get("cards", [])
    assert len(cards) == 46
    titles = {card.get("sourceTitle") for card in cards}
    assert "凡人修仙传" in titles
    assert "老舍：四世同堂" in titles
    for card in cards:
        assert "rawExcerpt" not in card
        assert "sourceText" not in card
        assert card.get("forbiddenImitation")


class FakeExperienceCardDb:
    def __init__(self):
        self.tables = {
            "sample_source": {},
            "sample_chunk": {},
            "experience_card": {},
            "writing_standard_candidate": {},
            "writing_standard": {},
        }

    async def fetchone(self, sql, args=None):
        args = list(args or [])
        table = self._table_from_sql(sql)
        if table and "where id=%s" in sql.lower():
            row = self.tables[table].get(args[0])
            if not row:
                return None
            if re.search(r"select\s+id\s+from", sql, re.I):
                return {"id": row["id"]}
            return dict(row)
        return None

    async def fetchall(self, sql, args=None):
        args = list(args or [])
        table = self._table_from_sql(sql)
        if table == "experience_card" and "where id in" in sql.lower():
            return [dict(self.tables[table][item]) for item in args if item in self.tables[table]]
        if table:
            return [dict(row) for row in self.tables[table].values()]
        return []

    async def execute(self, sql, args=None):
        args = list(args or [])
        text = " ".join(sql.strip().split())
        if text.upper().startswith("INSERT INTO"):
            table = re.search(r"INSERT INTO\s+(\w+)", text, re.I).group(1)
            cols = re.search(r"\(([^)]+)\)\s+VALUES", text, re.I).group(1)
            columns = [part.strip() for part in cols.split(",")]
            row = dict(zip(columns, args))
            self.tables[table][row["id"]] = row
            return 1
        if text.upper().startswith("UPDATE"):
            table = re.search(r"UPDATE\s+(\w+)\s+SET", text, re.I).group(1)
            set_part = re.search(r"SET\s+(.+?)\s+WHERE", text, re.I).group(1)
            columns = [part.split("=")[0].strip() for part in set_part.split(",")]
            values = args[:len(columns)]
            where_args = args[len(columns):]
            ids = where_args if " IN " in text.upper() else where_args[-1:]
            for row_id in ids:
                row = self.tables[table].get(row_id)
                if row:
                    row.update(dict(zip(columns, values)))
            return 1
        raise AssertionError(f"fake DB does not support SQL: {sql}")

    def _table_from_sql(self, sql):
        match = re.search(r"FROM\s+(\w+)", sql, re.I)
        return match.group(1) if match else None

    def install(self, module):
        module.fetchone = self.fetchone
        module.fetchall = self.fetchall
        module.execute = self.execute


def _sample_report(card_count=4):
    cards = []
    for index in range(1, card_count + 1):
        cards.append({
            "id": f"card-{index}",
            "sourceTitle": f"抽象样本{index}",
            "sourceMode": "local_sample",
            "genreTags": ["测试"],
            "chapterEntry": "从具体场景进入。",
            "chapterExit": "落在新问题上。",
            "dialogueMethod": "对话带停顿。",
            "characterMethod": "人物带自身目标行动。",
            "ensembleMethod": "配角有小目标。",
            "challengeMethod": "挑战来自代价。",
            "emotionMethod": "情绪落到动作。",
            "informationMethod": "信息从证据释放。",
            "proseRhythm": "长短句自然变化。",
            "avoidPatterns": ["不得复刻人物名"],
            "forbiddenImitation": ["不得复制原句"],
            "metrics": {"charCount": 1000 + index},
            "analysisNotes": ["抽象方法卡"],
        })
    return {"generatedAt": "2026-06-27T00:00:00.000Z", "cards": cards}


async def test_seed_preserves_manual_card_states_in_memory():
    import routers.experience_cards as module

    fake_db = FakeExperienceCardDb()
    fake_db.install(module)
    module._load_local_report = lambda: _sample_report(4)
    ticks = iter([1000, 2000, 3000, 4000, 5000])
    module._now = lambda: next(ticks)

    await module.seed_local_writing_sample_report()
    card_ids = [module._stable_uuid(f"experience-card:card-{index}") for index in range(1, 5)]

    await module.review_experience_card(card_ids[0], {"reviewNote": "人工审核通过"})
    await module.reject_experience_card(card_ids[1], {"reviewNote": "人工拒绝"})
    await module.archive_experience_card(card_ids[2], {"reviewNote": "人工归档"})
    fake_db.tables["experience_card"][card_ids[3]].update({
        "status": "merged",
        "review_note": "已由正式标准合并",
        "reviewed_at": 3999,
    })
    before = {
        card_id: {
            "status": fake_db.tables["experience_card"][card_id]["status"],
            "review_note": fake_db.tables["experience_card"][card_id]["review_note"],
            "reviewed_at": fake_db.tables["experience_card"][card_id]["reviewed_at"],
        }
        for card_id in card_ids
    }

    await module.seed_local_writing_sample_report()

    after = {
        card_id: {
            "status": fake_db.tables["experience_card"][card_id]["status"],
            "review_note": fake_db.tables["experience_card"][card_id]["review_note"],
            "reviewed_at": fake_db.tables["experience_card"][card_id]["reviewed_at"],
        }
        for card_id in card_ids
    }
    assert after == before
    assert fake_db.tables["experience_card"][card_ids[0]]["safety_flags"]


async def test_candidate_reject_keeps_cards_reusable_and_promote_merges_in_memory():
    import routers.experience_cards as module

    fake_db = FakeExperienceCardDb()
    fake_db.install(module)
    module._now = lambda: 6000
    card_ids = ["reviewed-card-a", "reviewed-card-b"]
    for card_id in card_ids:
        fake_db.tables["experience_card"][card_id] = {
            "id": card_id,
            "status": "reviewed",
            "title": card_id,
            "source_title": "抽象样本",
            "chapter_skeleton": "章节骨架",
            "dialogue_naturalness": "对话方法",
            "protagonist_progression": "主角推进",
            "supporting_character_method": "配角塑造",
            "answers_and_suspense": "悬念安排",
            "emotional_dwell": "情绪停留",
            "setting_exposure": "设定露出",
            "scene_dwell": "场景停留",
            "anti_ai_notes": "不得复刻",
            "review_note": "人工通过",
            "reviewed_at": 5000,
            "updated_at": 5000,
        }

    first = await module.create_writing_standard_candidate({"name": "候选一", "cardIds": card_ids})
    assert [fake_db.tables["experience_card"][card_id]["status"] for card_id in card_ids] == ["reviewed", "reviewed"]

    await module.reject_writing_standard_candidate(first["id"], {"reviewNote": "不采用"})
    assert [fake_db.tables["experience_card"][card_id]["status"] for card_id in card_ids] == ["reviewed", "reviewed"]

    second = await module.create_writing_standard_candidate({"name": "候选二", "cardIds": card_ids})
    await module.approve_writing_standard_candidate(second["id"], {"reviewNote": "通过"})
    promoted = await module.promote_writing_standard_candidate(second["id"])

    assert promoted["candidate"]["status"] == "promoted"
    assert promoted["standard"]["status"] == "active"
    assert [fake_db.tables["experience_card"][card_id]["status"] for card_id in card_ids] == ["merged", "merged"]


if __name__ == "__main__":
    test_schema_and_runtime_migrations_cover_sample_library_v1()
    test_experience_cards_router_exposes_minimum_api_and_seed_import()
    test_sanitizer_prevents_source_text_and_sample_names_from_prompt_standards()
    test_local_report_still_has_46_abstract_cards_for_migration()
    asyncio.run(test_seed_preserves_manual_card_states_in_memory())
    asyncio.run(test_candidate_reject_keeps_cards_reusable_and_promote_merges_in_memory())
