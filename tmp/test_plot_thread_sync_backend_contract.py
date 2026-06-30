import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.novel as novel  # noqa: E402


def _json(value):
    return json.dumps(value, ensure_ascii=False)


async def run_with_rows(*, facts=None, threads=None, volumes=None):
    facts = list(facts or [])
    threads = list(threads or [])
    volumes = list(volumes or [])
    executed = []
    inserted = []
    updated = []

    original_fetchall = novel.fetchall
    original_fetchone = novel.fetchone
    original_execute = novel.execute

    async def fake_fetchall(sql, args=None):
        normalized = " ".join(sql.split()).lower()
        if "from canon_facts" in normalized:
            return facts
        if "from plot_threads" in normalized:
            return threads
        if "from project_volumes" in normalized:
            return volumes
        return []

    async def fake_fetchone(sql, args=None):
        if "from plot_threads" in " ".join(sql.split()).lower():
            tid = args[0] if args else None
            return next((thread for thread in threads if thread.get("id") == tid), None)
        return None

    async def fake_execute(sql, args=None):
        executed.append((sql, args))
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("insert into plot_threads"):
            row = {
                "id": args[0],
                "project_id": args[1],
                "title": args[2],
                "content": args[3],
                "status": args[4],
                "planted_chapter": args[5],
                "related_characters": args[6],
                "possible_resolve_window": args[7],
                "resolve_options": args[8],
                "resolved_chapter": args[9],
                "notes": args[10],
                "created_at": args[11],
                "updated_at": args[12],
            }
            threads.append(row)
            inserted.append(row)
        elif normalized.startswith("update plot_threads"):
            tid = args[-1]
            row = next(thread for thread in threads if thread["id"] == tid)
            if "status=%s" in sql:
                # The sync update uses an explicit column order; assert against
                # the resulting row instead of parsing arbitrary SQL.
                columns = [
                    "title",
                    "content",
                    "status",
                    "planted_chapter",
                    "related_characters",
                    "resolved_chapter",
                    "notes",
                    "updated_at",
                ]
                for column, value in zip(columns, args[:-1]):
                    row[column] = value
            updated.append(row.copy())

    novel.fetchall = fake_fetchall
    novel.fetchone = fake_fetchone
    novel.execute = fake_execute
    try:
        result = await novel.syncPlotThreadsFromCanonFacts("project-1")
    finally:
        novel.fetchall = original_fetchall
        novel.fetchone = original_fetchone
        novel.execute = original_execute

    return result, threads, inserted, updated, executed


async def test_canon_fact_related_threads_create_plot_thread():
    result, threads, inserted, _, _ = await run_with_rows(facts=[
        {
            "id": "fact-1",
            "project_id": "project-1",
            "chapter_num": 1,
            "fact_type": "plot",
            "content": "陆沉舟拿到父亲旧钥匙，父亲旧案出现第一条可追踪线索。",
            "related_characters": _json(["陆沉舟", "陆远之"]),
            "related_plot_threads": _json(["#主角身世线", "#关键道具线"]),
            "status": "accepted",
            "created_at": 1000,
            "updated_at": 1000,
        }
    ])

    titles = {thread["title"] for thread in threads}
    assert "主角身世线" in titles
    assert "关键道具线" in titles
    assert all(thread["status"] == "planted" for thread in inserted)
    assert all(thread["planted_chapter"] == 1 for thread in inserted)
    assert result["created"] == 2


async def test_multi_chapter_same_thread_merges_without_duplicate():
    existing = {
        "id": "thread-1",
        "project_id": "project-1",
        "title": "主角身世线",
        "content": "由 Canon facts 自动同步。",
        "status": "planted",
        "planted_chapter": 1,
        "related_characters": _json(["陆沉舟"]),
        "possible_resolve_window": _json([None, None]),
        "resolve_options": _json([]),
        "resolved_chapter": None,
        "notes": "第 1 章：旧线索",
        "created_at": 1000,
        "updated_at": 1000,
    }
    result, threads, inserted, updated, _ = await run_with_rows(threads=[existing], facts=[
        {
            "id": "fact-1",
            "project_id": "project-1",
            "chapter_num": 1,
            "content": "父亲旧案出现线索。",
            "related_characters": _json(["陆沉舟"]),
            "related_plot_threads": _json(["#主角身世线"]),
            "status": "accepted",
            "created_at": 1000,
            "updated_at": 1000,
        },
        {
            "id": "fact-2",
            "project_id": "project-1",
            "chapter_num": 3,
            "content": "宋怀安补充父亲账房身份，主角身世线继续推进。",
            "related_characters": _json(["宋怀安"]),
            "related_plot_threads": _json(["主角身世线"]),
            "status": "accepted",
            "created_at": 3000,
            "updated_at": 3000,
        },
    ])

    assert not inserted
    assert result["updated"] == 1
    assert len([thread for thread in threads if thread["title"] == "主角身世线"]) == 1
    assert updated[-1]["status"] == "developing"
    assert json.loads(updated[-1]["related_characters"]) == ["陆沉舟", "宋怀安"]
    assert "第 3 章" in updated[-1]["notes"]


async def test_resolved_only_when_explicit_reveal_words_present():
    _, threads, _, _, _ = await run_with_rows(facts=[
        {
            "id": "fact-1",
            "project_id": "project-1",
            "chapter_num": 2,
            "content": "陆沉舟继续追查第三密栈行动，线索推进但还没有答案。",
            "related_characters": _json(["陆沉舟"]),
            "related_plot_threads": _json(["#第三密栈行动"]),
            "status": "accepted",
            "created_at": 2000,
            "updated_at": 2000,
        },
        {
            "id": "fact-2",
            "project_id": "project-1",
            "chapter_num": 5,
            "content": "第三密栈行动真相揭开：陆沉舟查清暗号来源并完成回收。",
            "related_characters": _json(["陆沉舟"]),
            "related_plot_threads": _json(["#第三密栈行动"]),
            "status": "accepted",
            "created_at": 5000,
            "updated_at": 5000,
        },
    ])

    thread = next(thread for thread in threads if thread["title"] == "第三密栈行动")
    assert thread["status"] == "resolved"
    assert thread["resolved_chapter"] == 5


async def test_volume_foreshadowing_plan_creates_candidate_only():
    _, threads, inserted, _, _ = await run_with_rows(volumes=[
        {
            "id": "volume-1",
            "project_id": "project-1",
            "volume_num": 1,
            "foreshadowing_plan": _json(["父亲密信提及星债会", "星账每次使用后出现新痕"]),
            "created_at": 1000,
            "updated_at": 1000,
        }
    ])

    assert {thread["title"] for thread in threads} == {"父亲密信提及星债会", "星账每次使用后出现新痕"}
    assert all(thread["status"] == "candidate" for thread in inserted)
    assert all(thread["planted_chapter"] is None for thread in inserted)


async def main():
    await test_canon_fact_related_threads_create_plot_thread()
    await test_multi_chapter_same_thread_merges_without_duplicate()
    await test_resolved_only_when_explicit_reveal_words_present()
    await test_volume_foreshadowing_plan_creates_candidate_only()
    print("plot thread sync backend contract passed")


if __name__ == "__main__":
    asyncio.run(main())
