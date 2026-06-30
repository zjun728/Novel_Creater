import assert from 'node:assert/strict'
import {
  buildStoryBlockReviewPrompt,
  normalizeStoryBlockReviewResult
} from '../frontend/src/prompts/storyBlockPrompt.js'

const prompt = buildStoryBlockReviewPrompt({
  chapterNum: 38,
  finalizedSummary: '老张内鬼坐实，小九被绑，星账代价加剧。',
  blockStageSnapshot: {
    storyBlockId: 'block-open',
    stageId: 'stage-4',
    stagePurpose: '取物人反制或逆转',
    stageAction: '判断失误触发小困境'
  },
  stageContinuationDepth: 2,
  previousOpenStageId: 'stage-4',
  storyBlock: { id: 'block-open' }
})

assert.match(prompt, /故事功能等价完成/)
assert.match(prompt, /错误信任|误信/)
assert.match(prompt, /低估敌人|被反制/)
assert.match(prompt, /小九被绑/)
assert.match(prompt, /代价加剧|行动选择受限/)
assert.match(prompt, /stageContinuationDepth/)
assert.match(prompt, /settlementDecision/)
assert.match(prompt, /completed_by_equivalent_story_function/)
assert.match(prompt, /split_remaining_stage/)
assert.match(prompt, /opened_new_block_for_residue/)
assert.match(prompt, /blocked_for_manual_review/)

const normalized = normalizeStoryBlockReviewResult({
  decision: 'continue_current_block',
  stageContinues: false,
  completedStageIds: ['stage-4'],
  settlementDecision: 'completed_by_equivalent_story_function',
  settlementEvidence: ['小九被绑', '星账代价加剧'],
  whetherStageClosedBeforeNextBeatPlan: true,
  previousOpenStageId: 'stage-4',
  stageContinuationDepth: 2
})

assert.equal(normalized.settlementDecision, 'completed_by_equivalent_story_function')
assert.deepEqual(normalized.settlementEvidence, ['小九被绑', '星账代价加剧'])
assert.equal(normalized.whetherStageClosedBeforeNextBeatPlan, true)
assert.equal(normalized.previousOpenStageId, 'stage-4')
assert.equal(normalized.stageContinuationDepth, 2)

console.log('story block review equivalent prompt contract passed')
