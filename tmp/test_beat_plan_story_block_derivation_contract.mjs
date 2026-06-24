import assert from 'node:assert/strict'

import {
  BEAT_PLAN_SOURCES,
  collectStructuredBeatPlanIssues,
  deriveChapterBeatPlanFromStoryBlock,
  parseStructuredBeatPlan
} from '../frontend/src/prompts/chapter.js'

const completeSnapshot = {
  storyBlockId: 'block-escape-1',
  stageId: 'stage-1',
  blockTitle: '逃出灵脉城',
  blockGoal: '陆沉舟带着星账残页逃出灵脉城，同时确认巡天司内部有人想让他活着离开。',
  storyFunction: '把追查从当铺推进到城内追捕与互相试探。',
  entryState: '上一章结尾，陆沉舟在账房夹道被孙茂才和巡天司暗哨堵住。',
  exitTarget: '带着损坏残页进入旧水渠，暂时摆脱明面追捕。',
  mainPressure: '孙茂才封锁账房出口，巡天司暗哨逼近，星账使用代价随时反噬。',
  stagePurpose: '逃跑与周旋',
  stageAction: '陆沉舟借账房暗门和旧水渠周旋，逼方鹤暴露一次暗中放水的痕迹。',
  stageChoice: '选择相信方鹤留下的缝隙冒险突围，还是留在账房硬扛孙茂才盘问。',
  stageCostOrConsequence: '残页被水汽浸坏一角，陆沉舟右臂旧伤加重，并让孙茂才确认他接触过星账。',
  nextStageSuggestion: '在旧水渠尽头发现父亲当年留下的铜牌暗号。',
  unresolvedQuestions: [
    '方鹤为何暗中帮助陆沉舟',
    '孙茂才从哪里知道星账残页',
    '铜牌暗号指向星债会还是巡天司旧档'
  ]
}

const before = JSON.parse(JSON.stringify(completeSnapshot))
const result = deriveChapterBeatPlanFromStoryBlock({
  chapterNum: 3,
  previousChapterEnding: '上一章结尾，孙茂才把账房外门反锁，方鹤在门缝里留下一道可疑空隙。',
  blockStageSnapshot: completeSnapshot
}, 3)

assert.equal(result.source, BEAT_PLAN_SOURCES.derivedFromStoryBlock)
assert.equal(result.allowedToContinue, true)
assert.equal(result.derivedFromStoryBlock, true)
assert.match(result.reason, /story block|故事块|阶段/)
assert.deepEqual(completeSnapshot, before, 'deriving a beat plan must not mutate the story block snapshot')

const parsed = parseStructuredBeatPlan(result.content)
for (const field of [
  'chapterEvent',
  'characterGoal',
  'coreConflict',
  'externalPressure',
  'costOrLoss',
  'irreversibleChange',
  'endingHandoff'
]) {
  assert.ok(String(parsed[field] || '').trim(), `derived beat plan must include ${field}`)
}
assert.match(parsed.chapterEvent, /陆沉舟|账房|旧水渠|方鹤/)
assert.match(parsed.characterGoal, /逃出|突围|相信方鹤|硬扛/)
assert.match(parsed.coreConflict, /孙茂才|巡天司|逼近|封锁/)
assert.match(parsed.costOrLoss, /残页|右臂|星账/)
assert.match(parsed.endingHandoff, /旧水渠|铜牌暗号/)

const quality = collectStructuredBeatPlanIssues(parsed, { nearTurnDecisionCard: { requiredChange: '逃离账房并进入旧水渠' } })
assert.deepEqual(quality.missingRequiredFields, [])
assert.deepEqual(quality.placeholderFields, [])
assert.equal(quality.volumeGoalHandoffStatus, 'pass')
assert.equal(quality.turnDecisionStatus, 'pass')

const incompleteResult = deriveChapterBeatPlanFromStoryBlock({
  chapterNum: 3,
  blockStageSnapshot: {
    ...completeSnapshot,
    stageChoice: '',
    stageCostOrConsequence: ''
  }
}, 3)
assert.equal(incompleteResult.source, BEAT_PLAN_SOURCES.localSafetyRequiresReview)
assert.equal(incompleteResult.allowedToContinue, false)
assert.equal(incompleteResult.derivedFromStoryBlock, false)
assert.match(incompleteResult.issues.join('\n'), /stageChoice|stageCostOrConsequence/)

const placeholderResult = deriveChapterBeatPlanFromStoryBlock({
  chapterNum: 3,
  blockStageSnapshot: {
    ...completeSnapshot,
    stageAction: '待补充',
    nextStageSuggestion: '推进剧情'
  }
}, 3)
assert.equal(placeholderResult.source, BEAT_PLAN_SOURCES.localSafetyRequiresReview)
assert.equal(placeholderResult.allowedToContinue, false)
assert.match(placeholderResult.issues.join('\n'), /placeholder|占位|stageAction|nextStageSuggestion/)

console.log('beat plan story block derivation contract tests passed')
