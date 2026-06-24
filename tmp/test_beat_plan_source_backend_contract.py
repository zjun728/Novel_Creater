from pathlib import Path
import re


chapters = Path("backend/routers/chapters.py").read_text(encoding="utf-8")
database = Path("backend/database.py").read_text(encoding="utf-8")
schema = Path("backend/schema.sql").read_text(encoding="utf-8")

assert re.search(r"class BeatPlanSave[\s\S]*beatPlanSource", chapters), "BeatPlanSave must accept beatPlanSource"
assert re.search(r"class BeatPlanSave[\s\S]*derivedFromStoryBlock", chapters), "BeatPlanSave must accept derivedFromStoryBlock"
assert re.search(r"class BeatPlanSave[\s\S]*derivedReason", chapters), "BeatPlanSave must accept derivedReason"

for field in ["beat_plan_source", "derived_from_story_block", "derived_reason"]:
    assert field in schema, f"schema.sql must define {field}"
    assert field in database, f"database.py migrations must ensure {field}"
    assert field in chapters, f"chapters router must persist {field}"

assert re.search(r"UPDATE chapter_beat_plans[\s\S]*beat_plan_source", chapters), "UPDATE must persist beat_plan_source"
assert re.search(r"INSERT INTO chapter_beat_plans[\s\S]*beat_plan_source", chapters), "INSERT must persist beat_plan_source"

print("beat plan source backend contract tests passed")
