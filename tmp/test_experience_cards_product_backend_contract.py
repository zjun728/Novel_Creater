import asyncio
import importlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_product_routes_and_hidden_maintenance_contract():
    router_py = read("backend/routers/experience_cards.py")
    api_client = read("frontend/src/api/db/client.js")
    view_vue = read("frontend/src/views/ExperienceCardsView.vue")

    for route in [
        "/experience-cards/product/cards",
        "/experience-cards/cards/{card_id}/toggle-active",
        "/experience-cards/cards/{card_id}/copy",
        "/experience-cards/cards/{card_id}",
        "/experience-cards/candidates/{candidate_id}/generate-standard",
        "/experience-cards/candidates/{candidate_id}/cards",
        "/experience-cards/standards/{standard_id}/toggle-active",
        "/experience-cards/standards/{standard_id}/copy",
        "/experience-cards/standards/{standard_id}",
    ]:
        assert route in router_py, f"missing product API route: {route}"

    for operation in ["toggleActive", "copy", "delete", "generateStandard", "removeCard"]:
        assert operation in api_client, f"missing frontend API operation: {operation}"

    for forbidden in [
        "导入微示范卡",
        "迁移本地样本报告",
        "审核通过",
        "拒绝",
        "归档",
        "candidate",
        "reviewed",
        "rejected",
        "merged",
        "archived",
        "promoted",
        "draft",
        "reviewing",
        "approved",
        "promote",
    ]:
        assert forbidden not in view_vue, f"formal UI leaked maintenance token: {forbidden}"


class ProductFakeDb:
    def __init__(self):
        self.tables = {
            "experience_card": {},
            "writing_standard_candidate": {},
            "writing_standard": {},
        }

    async def fetchone(self, sql, args=None):
        args = list(args or [])
        table = self._table(sql)
        if table and "where id=%s" in sql.lower():
            row = self.tables[table].get(args[0])
            return dict(row) if row else None
        return None

    async def fetchall(self, sql, args=None):
        args = list(args or [])
        table = self._table(sql)
        if table == "experience_card" and "where id in" in sql.lower():
            return [dict(self.tables[table][item]) for item in args if item in self.tables[table]]
        if table:
            return [dict(row) for row in self.tables[table].values()]
        return []

    async def execute(self, sql, args=None):
        args = list(args or [])
        text = " ".join(sql.strip().split())
        if text.upper().startswith("DELETE FROM"):
            table = re.search(r"DELETE FROM\s+(\w+)", text, re.I).group(1)
            self.tables[table].pop(args[-1], None)
            return 1
        if text.upper().startswith("UPDATE"):
            table = re.search(r"UPDATE\s+(\w+)\s+SET", text, re.I).group(1)
            set_part = re.search(r"SET\s+(.+?)\s+WHERE", text, re.I).group(1)
            columns = [part.split("=")[0].strip() for part in set_part.split(",")]
            values = args[:len(columns)]
            row_id = args[-1]
            if row_id in self.tables[table]:
                self.tables[table][row_id].update(dict(zip(columns, values)))
            return 1
        if text.upper().startswith("INSERT INTO"):
            table = re.search(r"INSERT INTO\s+(\w+)", text, re.I).group(1)
            cols = re.search(r"\(([^)]+)\)\s+VALUES", text, re.I).group(1)
            columns = [part.strip() for part in cols.split(",")]
            row = dict(zip(columns, args))
            self.tables[table][row["id"]] = row
            return 1
        raise AssertionError(f"fake DB does not support SQL: {sql}")

    def _table(self, sql):
        match = re.search(r"FROM\s+(\w+)", sql, re.I)
        return match.group(1) if match else None

    def install(self, module):
        module.fetchone = self.fetchone
        module.fetchall = self.fetchall
        module.execute = self.execute


def _json(value):
    return json.dumps(value, ensure_ascii=False)


async def test_delete_reference_protection_and_snapshot_generation():
    module = importlib.import_module("routers.experience_cards")
    fake = ProductFakeDb()
    fake.install(module)
    module._now = lambda: 7000

    fake.tables["experience_card"]["system-card"] = {
        "id": "system-card",
        "status": "reviewed",
        "source_title": "原创微示范卡 v2.1",
        "source_card_ref": "deep-v2-system",
        "title": "系统卡",
        "card_type": "prompt_injectable_scene",
        "chapter_skeleton": "系统方法",
        "scene_dwell": "系统微示范",
        "anti_ai_notes": "系统反 AI",
        "metrics_json": _json({"sourceKind": "system", "productStatus": "active"}),
    }
    fake.tables["experience_card"]["user-card"] = {
        "id": "user-card",
        "status": "reviewed",
        "source_title": "我的经验",
        "source_card_ref": "mine",
        "title": "用户卡",
        "card_type": "user_experience",
        "chapter_skeleton": "用户方法",
        "scene_dwell": "用户微示范",
        "anti_ai_notes": "用户反 AI",
        "metrics_json": _json({"sourceKind": "user", "productStatus": "active"}),
    }

    try:
        await module.delete_experience_card("system-card")
    except Exception as exc:
        assert "系统内置经验卡禁止删除" in str(exc)
    else:
        raise AssertionError("system card deletion should be blocked")

    deleted = await module.delete_experience_card("user-card")
    assert deleted["ok"] is True
    assert "user-card" not in fake.tables["experience_card"]

    fake.tables["experience_card"]["user-card"] = {
        "id": "user-card",
        "status": "reviewed",
        "source_title": "我的经验",
        "source_card_ref": "mine",
        "title": "用户卡",
        "card_type": "user_experience",
        "chapter_skeleton": "用户方法",
        "scene_dwell": "用户微示范",
        "anti_ai_notes": "用户反 AI",
        "metrics_json": _json({"sourceKind": "user", "productStatus": "active"}),
    }
    fake.tables["writing_standard_candidate"]["draft-1"] = {
        "id": "draft-1",
        "name": "候选",
        "status": "draft",
        "source_card_ids": _json(["user-card"]),
        "merged_guidance": _json({}),
    }

    try:
        await module.delete_experience_card("user-card")
    except Exception as exc:
        assert "该经验卡已被 1 个候选标准、0 个正式写作标准引用" in str(exc)
    else:
        raise AssertionError("candidate-referenced card deletion should be blocked")

    fake.tables["writing_standard_candidate"].clear()
    formal = await module.generate_formal_standard_from_candidate("draft-new", {
        "name": "正式标准",
        "description": "说明",
        "applicableScenes": "关系对白",
        "cardIds": ["user-card"],
    })
    standard = formal["standard"]
    guidance_raw = standard.get("guidance_json") or standard.get("guidanceJson") or standard.get("guidanceJSON")
    guidance = json.loads(guidance_raw) if isinstance(guidance_raw, str) else guidance_raw
    assert standard["status"] == "active"
    assert guidance["experienceCardSnapshots"][0]["id"] == "user-card"

    try:
        await module.delete_experience_card("user-card")
    except Exception as exc:
        assert "0 个候选标准、1 个正式写作标准引用" in str(exc)
    else:
        raise AssertionError("formal-standard-referenced card deletion should be blocked")


if __name__ == "__main__":
    test_product_routes_and_hidden_maintenance_contract()
    asyncio.run(test_delete_reference_protection_and_snapshot_generation())
    print("experience cards product backend contract passed")
