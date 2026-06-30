import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.novel as novel  # noqa: E402


def test_backend_classifies_system_and_real_threads():
    assert novel._plot_thread_class({"title": "主线推进"}) == "system_tag"
    assert novel._plot_thread_class({"title": "关键道具清单"}) == "system_tag"
    assert novel._plot_thread_class({"title": "关键地点线"}) == "system_tag"
    assert novel._plot_thread_class({"title": "追捕线"}) == "system_tag"
    assert novel._plot_thread_class({"title": "星账代价线"}) == "real_thread"
    assert novel._plot_thread_class({"title": "第三密栈行动"}) == "real_thread"


def test_backend_classifies_future_candidates():
    assert novel._plot_thread_class({
        "title": "父亲密信提及星债会",
        "status": "candidate",
        "notes": "候选来源：第 1 卷分卷规划；尚未由 Canon facts 证明已埋设。",
    }) == "future_candidate"


def test_backend_resolved_gate_is_strict():
    broad_fact = {
        "content": "宋怀安确认陆长庚曾在第三密栈留下账册。",
        "evidence": "确认线索存在。",
    }
    assert novel._should_resolve_thread("主角身世线", [broad_fact]) is False
    assert novel._should_resolve_thread("关键道具线", [broad_fact]) is False

    progress_fact = {
        "content": "陆沉舟进入庚字号门后，获得账簿和玉佩。",
        "evidence": "获得物品，进入下一地点。",
    }
    assert novel._should_resolve_thread("庚字号门后的真相", [progress_fact]) is False

    reveal_fact = {
        "content": "庚字号门后的真相揭开：铁箱中账簿证明徐正清长期超额抽取灵脉。",
        "evidence": "完成回收。",
    }
    assert novel._should_resolve_thread("庚字号门后的真相", [reveal_fact]) is True


if __name__ == "__main__":
    test_backend_classifies_system_and_real_threads()
    test_backend_classifies_future_candidates()
    test_backend_resolved_gate_is_strict()
    print("plot thread noise backend contract passed")
