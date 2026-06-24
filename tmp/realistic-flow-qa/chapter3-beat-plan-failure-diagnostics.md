# 第 3 章小纲失败原项目诊断

- mode: read_only_original_failure_project_diagnostic
- projectId: 5eb10995-7aa7-4027-9ac9-b350c9e673d7
- projectName: LongformBrowser240w_20260620_001203
- activeStoryBlock: 夜行灵脉城 (ccfb597d-c526-4713-a074-f19174ef3b77)
- activeStoryBlockCount: 1
- activeStageCount: 4
- activeNextStage: stage-1
- chapter3BeatPlanExists: false
- confirmsFailureShape: true

```json
{
  "checkedAt": "2026-06-20T00:47:34.886Z",
  "mode": "read_only_original_failure_project_diagnostic",
  "projectId": "5eb10995-7aa7-4027-9ac9-b350c9e673d7",
  "projectName": "LongformBrowser240w_20260620_001203",
  "projectError": "",
  "chapters": [
    {
      "chapterNum": 1,
      "title": "典当还是赎当",
      "status": "final",
      "wordCount": 923,
      "finalVersionId": "b57126b2-0daf-4d0f-bebd-064825a8a201"
    },
    {
      "chapterNum": 2,
      "title": "嗯",
      "status": "final",
      "wordCount": 4466,
      "finalVersionId": "b3d92435-4786-464e-a08e-c6ab66641972"
    },
    {
      "chapterNum": 3,
      "title": "第 3 章",
      "status": "drafting",
      "wordCount": 0,
      "finalVersionId": null
    }
  ],
  "activeStoryBlock": {
    "id": "ccfb597d-c526-4713-a074-f19174ef3b77",
    "title": "夜行灵脉城",
    "status": "active",
    "stageCount": 4,
    "nextStage": {
      "id": "stage-1",
      "status": "planned",
      "purpose": "逃离雨夜当铺区域",
      "sceneOrAction": "陆沉舟发现城门已封，利用小巷和星账感知避开巡天司巡逻，咳嗽加重，在废弃货棚暂歇"
    },
    "nextStageSuggestion": "stage-4 后续：陆沉舟带着残页逃出旧账房，被巡天司通缉，逃往商盟控制的灵脉城深处",
    "completedStages": [],
    "chapterRefs": []
  },
  "activeStoryBlockCount": 1,
  "chapterBeatPlans": {
    "1": {
      "exists": true,
      "storyBlockId": "b34c845f-eae7-4192-b4cb-17ce78fc7063",
      "blockStageId": "stage-1",
      "hasSnapshot": true,
      "contentLength": 641
    },
    "2": {
      "exists": true,
      "storyBlockId": "b34c845f-eae7-4192-b4cb-17ce78fc7063",
      "blockStageId": "stage-2",
      "hasSnapshot": true,
      "contentLength": 530
    },
    "3": {
      "exists": false,
      "storyBlockId": "",
      "blockStageId": "",
      "hasSnapshot": false,
      "contentLength": 0
    }
  },
  "confirmsFailureShape": true,
  "latestReportBlocker": {
    "blocked": true,
    "stage": "beat_plan_generation_failed",
    "message": "beat_plan_generation_failed: chapter 3 beat plan failed before draft: 小纲准备失败：第 3 章小纲生成返回空内容，请重试或切换模型。",
    "stack": "Error: beat_plan_generation_failed: chapter 3 beat plan failed before draft: 小纲准备失败：第 3 章小纲生成返回空内容，请重试或切换模型。\n    at waitForGeneratedChapterVersion (file:///D:/Projects/Novel_Creater/tmp/run_longform_browser_240w_phase1.mjs:691:21)\n    at process.processTicksAndRejections (node:internal/process/task_queues:103:5)\n    at async runChapter (file:///D:/Projects/Novel_Creater/tmp/run_longform_browser_240w_phase1.mjs:1338:5)\n    at async main (file:///D:/Projects/Novel_Creater/tmp/run_longform_browser_240w_phase1.mjs:1639:7)",
    "liveDiagnostics": {
      "stage": "beat_plan_generation_failed",
      "chapterId": "075f48c5-14ee-4cfa-a59c-a1fb405a36a5",
      "chapterBeatPlan": null,
      "beatPlanQuality": {
        "missingFields": [
          "chapterEvent",
          "characterGoal",
          "coreConflict",
          "externalPressure",
          "costOrLoss",
          "irreversibleChange",
          "endingHandoff"
        ],
        "placeholderFields": [],
        "repaired": false,
        "repairSucceeded": false,
        "finalBeatPlanLength": 0
      },
      "hasSavedBeatPlan": false,
      "versionsCount": 0,
      "messages": [
        "距离上次备份已过去 从未备份，建议立即备份项目数据\n立即备份",
        "已根据当前上下文规划故事块。后续只能更新未执行、未引用的剩余阶段。",
        "小纲准备失败：第 3 章小纲生成返回空内容，请重试或切换模型。"
      ],
      "page": {
        "messages": [
          "距离上次备份已过去 从未备份，建议立即备份项目数据\n立即备份"
        ],
        "activeAction": [],
        "url": "http://127.0.0.1:5173/writer/5eb10995-7aa7-4027-9ac9-b350c9e673d7/3"
      }
    },
    "dirtyDataWritten": {
      "project": true,
      "settingsChangeEvents": true,
      "chapters": true,
      "storyBlocks": true
    }
  }
}
```