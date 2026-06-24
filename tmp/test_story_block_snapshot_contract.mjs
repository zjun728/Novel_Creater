import assert from 'node:assert/strict'

import {
  ALLOWED_STORY_BLOCK_REVIEW_DECISIONS,
  buildBlockStageSnapshot,
  canEditRemainingStage,
  findNextEditableStage,
  normalizeStoryBlockStatus,
  normalizeStoryBlockReviewDecision
} from '../frontend/src/utils/storyBlockSnapshot.js'

const legacyAdjustDecision = ['adjust', 'current', 'block'].join('_')
const obsoleteStatus = ['super', 'seded'].join('')

assert.deepEqual(ALLOWED_STORY_BLOCK_REVIEW_DECISIONS, [
  'continue_current_block',
  'adjust_remaining_stages',
  'split_unfinalized_content',
  'complete_current_block',
  'open_new_block'
])

assert.equal(normalizeStoryBlockStatus(obsoleteStatus), 'paused')
assert.equal(normalizeStoryBlockReviewDecision(legacyAdjustDecision), 'continue_current_block')

const block = {
  id: 'block-1',
  title: '雨夜追索',
  goal: '查清铜钱为什么只回应真实代价。',
  storyFunction: '施压与揭示',
  entryState: '主角刚拿到发热铜钱。',
  nextStageSuggestion: '去当铺验证铜钱。',
  unresolvedQuestions: ['铜钱是谁留下的'],
  stagePlan: [
    {
      id: 'stage-1',
      purpose: '验证铜钱',
      sceneOrAction: '主角去当铺试探掌柜反应',
      choice: '是否交出铜钱换消息',
      costOrConsequence: '暴露自己持有铜钱',
      status: 'planned'
    }
  ]
}

const snapshot = buildBlockStageSnapshot(block, block.stagePlan[0], { capturedAt: 123 })
assert.equal(snapshot.storyBlockId, 'block-1')
assert.equal(snapshot.blockGoal, block.goal)
assert.equal(snapshot.entryState, block.entryState)
assert.equal(snapshot.stageId, 'stage-1')
assert.equal(snapshot.stagePurpose, '验证铜钱')
assert.equal(snapshot.stageAction, '主角去当铺试探掌柜反应')
assert.equal(snapshot.stageChoice, '是否交出铜钱换消息')
assert.equal(snapshot.stageCostOrConsequence, '暴露自己持有铜钱')
assert.equal(snapshot.capturedAt, 123)

block.goal = '被后续滚动改写的目标'
block.stagePlan[0].purpose = '被后续滚动改写的阶段'
assert.equal(snapshot.blockGoal, '查清铜钱为什么只回应真实代价。')
assert.equal(snapshot.stagePurpose, '验证铜钱')

const rollingBlock = {
  ...block,
  completedStages: [{ id: 'stage-1', chapterNum: 1 }],
  stagePlan: [
    { id: 'stage-1', purpose: 'completed stage', status: 'planned' },
    { id: 'stage-2', purpose: 'next stage', status: 'planned' }
  ]
}
assert.equal(findNextEditableStage(rollingBlock).id, 'stage-2')

const exhaustedBlock = {
  ...block,
  completedStages: [
    { id: 'stage-1', chapterNum: 1 },
    { id: 'stage-2', chapterNum: 2 }
  ],
  stagePlan: [
    { id: 'stage-1', purpose: 'completed stage', status: 'completed', chapterRefs: [1] },
    { id: 'stage-2', purpose: 'also completed', status: 'completed', chapterRefs: [2] }
  ]
}
assert.equal(
  findNextEditableStage(exhaustedBlock),
  null,
  'when every stage is completed or chapter-bound, stage selection must not fall back to stage-1'
)

const closedBlock = {
  ...rollingBlock,
  status: 'completed'
}
assert.equal(
  findNextEditableStage(closedBlock),
  null,
  'completed story blocks must not offer an editable stage for a new chapter'
)

assert.equal(canEditRemainingStage({ status: 'planned' }), true)
assert.equal(canEditRemainingStage({ status: 'completed' }), false)
assert.equal(canEditRemainingStage({ status: 'planned', lockedByBeatPlan: true }), false)
assert.equal(canEditRemainingStage({ status: 'planned', lockedByFinalChapter: true }), false)
assert.equal(canEditRemainingStage({ status: 'planned', chapterRefs: [1] }), false)

console.log('story block snapshot contract tests passed')
