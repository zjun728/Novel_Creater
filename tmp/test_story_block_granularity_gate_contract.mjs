import assert from 'node:assert/strict'

import {
  assessStoryBlockCloseDecision,
  filterExecutedCompletedStageIds,
  splitStoryBlockStagesByExecution
} from '../frontend/src/utils/storyBlockGranularity.js'

const fourStageBlock = {
  goal: '从城外河滩安全抵达北境矿场外围',
  exitTarget: '抵达北境矿场并获得进入矿洞的身份',
  stagePlan: [
    { id: 'stage-1', status: 'planned', chapterRefs: [1] },
    { id: 'stage-2', status: 'planned' },
    { id: 'stage-3', status: 'planned' },
    { id: 'stage-4', status: 'planned' }
  ],
  completedStages: []
}

const weakCloseReview = {
  decision: 'complete_current_block',
  completedStageIds: ['stage-1', 'stage-2', 'stage-3', 'stage-4'],
  completionEvidence: '本章高效完成，一气呵成，无需多章展开，属于短冲突块。',
  singleChapterBlockReason: '短冲突块。'
}

const filtered = filterExecutedCompletedStageIds(weakCloseReview, fourStageBlock, { stageId: 'stage-1' })
assert.deepEqual(filtered, ['stage-1'], 'unexecuted stages must not be counted as completed')

const weakAssessment = assessStoryBlockCloseDecision(weakCloseReview, fourStageBlock, {
  stageId: 'stage-1'
})
assert.equal(weakAssessment.earlyCloseAllowed, false)
assert.equal(weakAssessment.blockCloseReasonType, 'weak_or_generic')

const split = splitStoryBlockStagesByExecution(fourStageBlock, weakCloseReview, { stageId: 'stage-1' })
assert.equal(split.completedStages.length, 1)
assert.equal(split.closedUnexecutedStages.length, 3)
assert.equal(split.invalidatedStages.length, 0)

const strongCloseReview = {
  decision: 'complete_current_block',
  completedStageIds: ['stage-1', 'stage-2'],
  completionEvidence: 'exitTarget 已真实达成：陆沉舟抵达北境矿场并获得矿工身份，旧逃亡块主任务自然结束，下一章转入矿洞寻账的新地点新任务。',
  singleChapterBlockReason: ''
}

const strongAssessment = assessStoryBlockCloseDecision(strongCloseReview, fourStageBlock, {
  stageId: 'stage-1'
})
assert.equal(strongAssessment.earlyCloseAllowed, true)
assert.match(strongAssessment.blockCloseReasonType, /exit_target_achieved|major_turn/)
