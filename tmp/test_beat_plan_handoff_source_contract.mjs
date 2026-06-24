import assert from 'node:assert/strict'

import {
  BEAT_PLAN_SOURCES,
  deriveChapterBeatPlanFromStoryBlock,
  parseStructuredBeatPlan,
  resolveMeaningfulHandoffSource
} from '../frontend/src/prompts/chapter.js'

const snapshot = {
  storyBlockId: 'block-1',
  stageId: 'stage-1',
  blockTitle: '星账初现',
  blockGoal: '陆沉舟在当铺清账时发现父亲名字出现在新账上，首次使用星账追踪线索并付出记忆代价，被巡天司追捕后利用账目漏洞逃脱。',
  stagePurpose: '发现异常账目',
  stageAction: '陆沉舟在当铺清账，翻到父亲名字的新账条目，确认日期为当天。',
  stageChoice: '是否相信账目真实性并追查',
  stageCostOrConsequence: '若追查则必须使用星账，可能暴露行踪',
  mainPressure: '巡天司追捕与星账首次使用代价（失去短期记忆）的冲突。',
  unresolvedQuestions: [
    '父亲名字为何出现在新账上？',
    '星账代价是否可逆？',
    '林渡是否可信？'
  ],
  nextStageSuggestion: 'stage-1',
  exitTarget: '陆沉舟获得巡天司驻地地图，准备潜入找回名籍。'
}

const handoff = resolveMeaningfulHandoffSource(snapshot)
assert.equal(handoff.sourceField, 'exitTarget')
assert.match(handoff.value, /巡天司驻地地图|潜入|名籍/)

const result = deriveChapterBeatPlanFromStoryBlock({
  chapterNum: 1,
  previousChapterEnding: '雨夜当铺的账页被翻开，父亲名字出现在当天新账上。',
  blockStageSnapshot: snapshot
}, 1)

assert.equal(result.source, BEAT_PLAN_SOURCES.derivedFromStoryBlock)
assert.equal(result.allowedToContinue, true)
assert.equal(result.derivedFromStoryBlock, true)
assert.deepEqual(result.issues, [])

const parsed = parseStructuredBeatPlan(result.content)
assert.match(parsed.endingHandoff, /巡天司驻地地图|潜入|名籍/)

const sameStageSuggestion = resolveMeaningfulHandoffSource({
  ...snapshot,
  nextStageSuggestion: 'stage-2',
  stageId: 'stage-2'
})
assert.equal(sameStageSuggestion.sourceField, 'exitTarget')

const missingHandoff = deriveChapterBeatPlanFromStoryBlock({
  chapterNum: 1,
  blockStageSnapshot: {
    ...snapshot,
    nextStageSuggestion: 'stage-1',
    exitTarget: ''
  }
}, 1)
assert.equal(missingHandoff.source, BEAT_PLAN_SOURCES.localSafetyRequiresReview)
assert.equal(missingHandoff.allowedToContinue, false)
assert.match(missingHandoff.issues.join('\n'), /ending handoff|handoff support|exitTarget/)

console.log('beat plan meaningful handoff source contract tests passed')
