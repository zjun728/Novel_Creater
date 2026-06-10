import assert from 'node:assert/strict'

import { buildDraftPrompt, buildDraftSystemPrompt } from '../frontend/src/prompts/chapterDraftPrompt.js'
import { buildScenePlanPrompt, buildScenePlanSystemPrompt } from '../frontend/src/prompts/chapterPlanPrompt.js'
import { buildLocalWindowRevisionPrompt, buildLocalWindowRevisionSystemPrompt } from '../frontend/src/prompts/chapterRevisionPrompt.js'

const planSystem = buildScenePlanSystemPrompt()
assert.match(planSystem, /场景型小纲/)
assert.match(planSystem, /不是写正文/)

const scenePlan = buildScenePlanPrompt({
  chapterNum: 1,
  previousChapterEnding: '铜钱在雨里发热。',
  chapterGoal: { goal: '主角第一次发现铜钱会回应真实代价。' },
  writingFingerprint: '考据悬疑，信息通过证据被发现。'
})
assert.match(scenePlan, /场景摩擦/)
assert.match(scenePlan, /信息释放/)
assert.match(scenePlan, /有效选择/)
assert.match(scenePlan, /写作指纹/)

const draftSystem = buildDraftSystemPrompt()
assert.match(draftSystem, /正文生成/)
assert.match(draftSystem, /写小说/)
assert.doesNotMatch(draftSystem, /必须报问题/)
assert.doesNotMatch(draftSystem, /审稿报告/)

const draft = buildDraftPrompt({
  chapterNum: 1,
  beatPlan: '### 本章节拍\n1. 雨夜开场。\n2. 铜钱回应。',
  writingFingerprint: '近景、冷静、信息通过物件反应释放。',
  continuityConstraints: '铜钱仍在主角手中。'
})
assert.match(draft, /写作指纹/)
assert.match(draft, /连续性硬约束/)
assert.match(draft, /直接输出正文/)

const revisionSystem = buildLocalWindowRevisionSystemPrompt()
assert.match(revisionSystem, /滑窗局部修订/)
assert.match(revisionSystem, /接缝/)

const revision = buildLocalWindowRevisionPrompt({
  issue: {
    type: 'emotion_label',
    location: '他感到愤怒。',
    replacement: '他把杯沿抵在掌心，瓷边压出一道白痕。'
  },
  before: '屋里静了一下。',
  target: '他感到愤怒。',
  after: '杯底的茶水晃了晃。'
})
assert.match(revision, /前文滑窗/)
assert.match(revision, /目标片段/)
assert.match(revision, /后文滑窗/)
assert.match(revision, /只输出 JSON/)
