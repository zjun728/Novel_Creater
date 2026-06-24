import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.settings_library as settings_library  # noqa: E402


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


OLD_SUMMARY = "掌控九州灵脉贸易与资源流通的商业联盟，与巡天司、星债会争夺星账控制权。"
ACTION_SUMMARY = "掌控九州灵脉贸易与资源流通的商业联盟，与巡天司、星债会争夺星账控制权；已派人追踪陆沉舟，试图用父亲下落交换星账。"


assert_equal(
    settings_library._is_summary_chapter_fact_supplement(
        OLD_SUMMARY,
        ACTION_SUMMARY,
        "第 1 章定稿后抽取：商盟已派人追踪陆沉舟，试图交换星账。",
    ),
    True,
    "organization action supplement should be detected",
)

COMMA_ANCHOR_SUMMARY = "掌控九州灵脉贸易与资源流通的商业联盟，可能通过灵脉账目操纵粮价与修士寿元。"
COMMA_ANCHOR_INCOMING = "掌控九州灵脉贸易与资源流通的商业联盟；已派人追踪陆沉舟，试图用父亲下落交换星账。"
assert_equal(
    settings_library._is_summary_chapter_fact_supplement(
        COMMA_ANCHOR_SUMMARY,
        COMMA_ANCHOR_INCOMING,
        "已派人追踪陆沉舟",
    ),
    True,
    "comma-level stable anchor should be enough when unstable old fragment is omitted",
)

profile = {}
updates = {"summary": ACTION_SUMMARY}
event = {
    "entity_name": "商盟",
    "field_path": "summary",
    "new_value": ACTION_SUMMARY,
    "evidence": "商盟已派人追踪陆沉舟，试图用父亲下落交换星账。",
    "chapter_num": 1,
    "confidence": 0.9,
}
settings_library._rehome_summary_chapter_fact_update(profile, updates, event, OLD_SUMMARY, ACTION_SUMMARY)
if "summary" in updates:
    raise AssertionError("summary action supplement must not update hard summary")
if profile.get("observedFacts"):
    raise AssertionError("current organization actions should not be stored as observedFacts")
if not profile.get("currentActions"):
    raise AssertionError("current organization actions should append profile.currentActions")
entry = profile["currentActions"][-1]
if "已派人追踪陆沉舟" not in entry["value"] or "交换星账" not in entry["value"]:
    raise AssertionError(f"currentActions entry lost action text: {entry!r}")
assert_equal(entry["preservedSummary"], OLD_SUMMARY, "preserved hard summary")
assert_equal(profile["_dynamicStateMeta"]["currentActions"]["chapterNum"], 1, "currentActions meta")

assert_equal(
    settings_library._is_hard_summary_rewrite(
        OLD_SUMMARY,
        "商盟其实不是商业联盟，而是星债会伪装分部。",
    ),
    True,
    "real organization identity rewrite should remain hard conflict",
)

print("organization summary action rehome backend contract tests passed")
