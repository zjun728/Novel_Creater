import assert from 'node:assert/strict'
import {
  buildStageContinuationDiagnostics,
  enforceStageContinuationSettlement,
  hasEquivalentStoryFunction
} from '../frontend/src/utils/storyBlockStageSettlement.js'

const snapshot = Object.freeze({
  storyBlockId: 'block-open',
  stageId: 'stage-4',
  stagePurpose: '取物人反制或逆转',
  stageAction: '判断失误触发小困境',
  stageChoice: '全力突围还是将计就计',
  stageCostOrConsequence: '小九处境恶化或星账代价加剧'
})

const equivalentContext = {
  chapterNum: 37,
  stageContinuationDepth: 2,
  previousOpenStageId: 'stage-4',
  blockStageSnapshot: snapshot,
  finalizedSummary: [
    '陆沉舟误信老张能兜底，独自去渡口仓库。',
    '缺指男人反制设伏，老张内鬼坐实。',
    '小九被绑走，星账使用次数到极限，取物人真实目标确认。'
  ].join(''),
  chapterEnding: '缺指男人留下纸条：用星账换小九。',
  settingChanges: [
    { entityName: '老张', evidence: '老张与缺指男人交易，内鬼身份坐实' },
    { entityName: '小九', evidence: '小九被绑走，成为交换筹码' }
  ]
}

assert.equal(hasEquivalentStoryFunction(equivalentContext).equivalent, true)

const settled = enforceStageContinuationSettlement({
  decision: 'continue_current_block',
  completedStageIds: [],
  stageContinues: true,
  stageContinueReason: '本章尚未逐字写出判断失误，下一章继续让陆沉舟选择。',
  reason: '本章尚未逐字写出判断失误，下一章继续让陆沉舟选择。'
}, equivalentContext)

assert.equal(settled.stageContinues, false)
assert.equal(settled.settlementDecision, 'completed_by_equivalent_story_function')
assert.equal(settled.whetherStageClosedBeforeNextBeatPlan, true)
assert.equal(settled.previousOpenStageId, 'stage-4')
assert.equal(settled.stageContinuationDepth, 2)
assert.ok(settled.completedStageIds.includes('stage-4'))
assert.ok(settled.settlementEvidence.length >= 3)
assert.deepEqual(snapshot, {
  storyBlockId: 'block-open',
  stageId: 'stage-4',
  stagePurpose: '取物人反制或逆转',
  stageAction: '判断失误触发小困境',
  stageChoice: '全力突围还是将计就计',
  stageCostOrConsequence: '小九处境恶化或星账代价加剧'
})

const split = enforceStageContinuationSettlement({
  decision: 'continue_current_block',
  completedStageIds: [],
  stageContinues: true,
  stageContinueReason: '第三密栈和反向设局还没展开。',
  reason: '第三密栈和反向设局还没展开。'
}, {
  chapterNum: 38,
  stageContinuationDepth: 2,
  previousOpenStageId: 'stage-4',
  blockStageSnapshot: snapshot,
  finalizedSummary: '本章只确认第三密栈线索，尚无代价后果。',
  storyBlock: {
    stagePlan: [snapshot]
  }
})

assert.equal(split.stageContinues, false)
assert.equal(split.settlementDecision, 'split_remaining_stage')
assert.equal(split.whetherStageClosedBeforeNextBeatPlan, true)
assert.ok(split.completedStageIds.includes('stage-4'))
assert.ok(split.remainingStages.length >= 1)
assert.match(split.reason, /不得继续复用同一阶段/)

const diagnostics = buildStageContinuationDiagnostics({
  currentStageId: 'stage-4',
  previousOpenStageId: 'stage-4',
  reviewHistory: [
    { chapterNum: 35, stageContinues: true, blockStageId: 'stage-4', stageContinueReason: '继续到渡口' },
    { chapterNum: 36, stageContinues: true, blockStageId: 'stage-4', stageContinueReason: '继续完成选择' }
  ]
})

assert.equal(diagnostics.stageContinuationDepth, 2)
assert.equal(diagnostics.previousOpenStageId, 'stage-4')
assert.equal(diagnostics.requiresSettlementBeforeNextBeatPlan, true)

const closedTailDiagnostics = buildStageContinuationDiagnostics({
  currentStageId: 'stage-settle-38-1',
  previousOpenStageId: 'stage-settle-38-1',
  reviewHistory: [
    { chapterNum: 35, stageContinues: true, stageContinueReason: '旧阶段继续' },
    { chapterNum: 36, stageContinues: true, stageContinueReason: '旧阶段继续' },
    { chapterNum: 37, stageContinues: false, blockStageId: 'stage-4', settlementDecision: 'completed_by_equivalent_story_function' }
  ]
})

assert.equal(closedTailDiagnostics.stageContinuationDepth, 0)
assert.equal(closedTailDiagnostics.requiresSettlementBeforeNextBeatPlan, false)

console.log('story block stage settlement contract passed')
