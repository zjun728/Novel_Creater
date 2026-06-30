import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const storyBlockStore = readFileSync('frontend/src/stores/storyBlockStore.js', 'utf8')
const finalizationGuard = readFileSync('frontend/src/utils/finalizationGuard.js', 'utf8')
const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

const continueBranch = writerView.match(/review\.decision === 'continue_current_block'[\s\S]*?\} else if \(review\.decision === 'split_unfinalized_content'\)/)?.[0] || ''
assert.ok(continueBranch, 'WriterView must keep an explicit continue_current_block settlement branch')
assert.doesNotMatch(
  continueBranch,
  /stagePlan:\s*reviewedBlock\.stagePlan\s*\|\|\s*\[\]/,
  'continue_current_block must not resend full stagePlan after storyBlockReview locks the current stage'
)

const splitBranch = writerView.match(/review\.decision === 'split_unfinalized_content'[\s\S]*?\} else if \(review\.decision === 'complete_current_block'\)/)?.[0] || ''
assert.ok(splitBranch, 'WriterView must keep an explicit split_unfinalized_content settlement branch')
assert.doesNotMatch(
  splitBranch,
  /stagePlan:\s*reviewedBlock\.stagePlan\s*\|\|\s*\[\]/,
  'split_unfinalized_content must not resend full stagePlan after storyBlockReview locks the current stage'
)

const adjustBranch = writerView.match(/review\.decision === 'adjust_remaining_stages'[\s\S]*?\} else if \(review\.decision === 'continue_current_block'\)/)?.[0] || ''
assert.match(
  adjustBranch,
  /stagePlanPatchMode:\s*'editable_future_only'/,
  'adjust_remaining_stages must use an editable-future-stage patch mode'
)
assert.match(
  writerView,
  /extractEditableFutureStageUpdates/,
  'WriterView must extract future editable stage updates instead of posting the whole stage plan'
)

assert.doesNotMatch(
  storyBlockStore,
  /stagePlan:\s*payload\.stagePlan\s*\|\|\s*\[\]/,
  'storyBlockStore.updateRemainingStages must not coerce omitted stagePlan into []'
)
assert.match(
  storyBlockStore,
  /hasOwnProperty\.call\(payload,\s*'stagePlan'\)/,
  'storyBlockStore.updateRemainingStages must only include stagePlan when caller explicitly supplies it'
)
assert.match(
  storyBlockStore,
  /stagePlanPatchMode/,
  'storyBlockStore.updateRemainingStages must pass through stagePlanPatchMode'
)

assert.match(
  finalizationGuard,
  /storyBlockSettlementFailure/,
  'finalization marker must have an independent storyBlockSettlementFailure field'
)
assert.match(
  finalizationGuard,
  /story_block_stage_update_conflict/,
  'story block settlement 409 must be classified as story_block_stage_update_conflict'
)
assert.match(
  finalizationGuard,
  /retryable:\s*false/,
  'story block settlement 409 must not be marked as an AI retryable postprocess failure'
)

assert.match(
  liveScript,
  /post_finalize_story_block_settlement_failed|story_block_stage_update_conflict/,
  'live script must classify story block settlement conflict separately from AI proxy failure'
)
assert.match(
  liveScript,
  /classifyPostFinalizeMarkerFailure/,
  'live script must classify marker failures before raising blockers'
)
assert.doesNotMatch(
  liveScript,
  /const message = marker\?\.retryablePostprocessFailure\?\.message \|\| '定稿后 AI 代理请求失败，后处理需要重试。'[\s\S]{0,180}error\.code = 'post_finalize_ai_proxy_failed'/,
  'waitForPostFinalizeSettlement must not turn every postFinalizeFailed marker into post_finalize_ai_proxy_failed'
)

console.log('story block settlement conflict contract passed')
