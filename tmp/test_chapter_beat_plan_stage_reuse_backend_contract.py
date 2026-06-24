import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import HTTPException  # noqa: E402
import routers.chapters as chapters  # noqa: E402


async def main():
    original_fetchone = chapters.fetchone

    async def fake_fetchone(sql, args):
        if "FROM story_blocks" in sql:
            return {
                "id": "block-1",
                "project_id": "project-1",
                "status": "active",
                "goal": "逃出当铺追捕",
                "entry_state": "上一章已经完成试探",
                "story_function": "追逃",
                "main_pressure": "巡天司和星债会同时逼近",
                "completed_stages": json.dumps([{"id": "stage-1", "chapterNum": 1}], ensure_ascii=False),
                "stage_plan": json.dumps([
                    {
                        "id": "stage-1",
                        "purpose": "当铺试探",
                        "sceneOrAction": "陆沉舟与掌柜周旋",
                        "choice": "是否暴露星账",
                        "costOrConsequence": "被追踪",
                        "status": "completed",
                        "chapterRefs": [1],
                    },
                    {
                        "id": "stage-2",
                        "purpose": "逃离封锁",
                        "sceneOrAction": "陆沉舟寻找出城缺口",
                        "choice": "救人还是藏身",
                        "costOrConsequence": "失去线索",
                        "status": "closed_unexecuted",
                    },
                ], ensure_ascii=False),
            }
        return None

    chapters.fetchone = fake_fetchone
    try:
        try:
            await chapters._validate_story_block_reference(
                "project-1",
                chapters.BeatPlanSave(
                    content="第 2 章小纲",
                    storyBlockId="block-1",
                    blockStageId="stage-1",
                    blockStageSnapshot={
                        "storyBlockId": "block-1",
                        "stageId": "stage-1",
                        "blockGoal": "逃出当铺追捕",
                        "entryState": "上一章已经完成试探",
                        "storyFunction": "追逃",
                        "mainPressure": "巡天司和星债会同时逼近",
                        "stagePurpose": "当铺试探",
                        "stageAction": "陆沉舟与掌柜周旋",
                        "stageChoice": "是否暴露星账",
                        "stageCostOrConsequence": "被追踪",
                    },
                ),
            )
        except HTTPException as exc:
            if exc.status_code != 409:
                raise AssertionError(f"expected 409 for completed stage reuse, got {exc.status_code}") from exc
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            if detail.get("code") != "story_block_stage_reuse_detected":
                raise AssertionError(f"expected story_block_stage_reuse_detected, got {detail!r}")
        else:
            raise AssertionError("completed story block stage reuse must be rejected")
        try:
            await chapters._validate_story_block_reference(
                "project-1",
                chapters.BeatPlanSave(
                    content="第 3 章小纲",
                    storyBlockId="block-1",
                    blockStageId="stage-2",
                    blockStageSnapshot={
                        "storyBlockId": "block-1",
                        "stageId": "stage-2",
                        "blockGoal": "逃出当铺追捕",
                        "entryState": "上一章已经完成试探",
                        "storyFunction": "追逃",
                        "mainPressure": "巡天司和星债会同时逼近",
                        "stagePurpose": "逃离封锁",
                        "stageAction": "陆沉舟寻找出城缺口",
                        "stageChoice": "救人还是藏身",
                        "stageCostOrConsequence": "失去线索",
                    },
                ),
            )
        except HTTPException as exc:
            if exc.status_code != 409:
                raise AssertionError(f"expected 409 for closed_unexecuted stage reuse, got {exc.status_code}") from exc
        else:
            raise AssertionError("closed_unexecuted story block stage reuse must be rejected")
    finally:
        chapters.fetchone = original_fetchone


asyncio.run(main())
print("chapter beat plan stage reuse backend contract tests passed")
