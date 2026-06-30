import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { getFinalizationMarkerAction } from '../frontend/src/application/writer-flow/finalization-marker-action.js'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const finalizationGuard = readFileSync('frontend/src/utils/finalizationGuard.js', 'utf8')
const finalizationCommand = readFileSync('frontend/src/application/writer-flow/finalization-command.js', 'utf8')
const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

function blockBetween(source, startNeedle, endNeedle) {
  const start = source.indexOf(startNeedle)
  assert.notEqual(start, -1, `missing block start: ${startNeedle}`)
  const end = source.indexOf(endNeedle, start + startNeedle.length)
  assert.notEqual(end, -1, `missing block end: ${endNeedle}`)
  return source.slice(start, end)
}

function extractFunctionBlock(source, signature) {
  const start = source.indexOf(signature)
  assert.notEqual(start, -1, `missing function signature: ${signature}`)
  const bodyStart = source.indexOf('{', start)
  assert.notEqual(bodyStart, -1, `missing function body: ${signature}`)
  let depth = 0
  for (let index = bodyStart; index < source.length; index += 1) {
    const char = source[index]
    if (char === '{') depth += 1
    if (char === '}') {
      depth -= 1
      if (depth === 0) return source.slice(start, index + 1)
    }
  }
  assert.fail(`unterminated function body: ${signature}`)
}

function assertOrdered(source, needles, message) {
  let cursor = -1
  for (const needle of needles) {
    const next = source.indexOf(needle, cursor + 1)
    assert.notEqual(next, -1, `${message}: missing ${needle}`)
    assert.ok(next > cursor, `${message}: ${needle} is out of order`)
    cursor = next
  }
}

const handleFinalizeBlock = blockBetween(
  writerView,
  'async function handleFinalize(version)',
  'async function performFinalize(version)'
)
assert.doesNotMatch(
  handleFinalizeBlock,
  /beginChapterFinalizationRun|markChapterFinalizationPending/,
  'preflight audit and hard gates must not create a pending finalization marker'
)
assertOrdered(
  handleFinalizeBlock,
  [
    'ensureChapterAboveHardWordMinBeforeFinalize(version)',
    'memoryStore.auditChapter',
    'hardIssues.length',
    'return',
    'await performFinalize(version)'
  ],
  'preflight hard audit failures must return before performFinalize can create a marker'
)

const performFinalizeBlock = finalizationCommand
assert.match(
  extractFunctionBlock(writerView, 'async function performFinalize(version)'),
  /runFinalizeChapterCommand/,
  'WriterView.performFinalize must delegate post-preflight state transition to finalization command'
)
assertOrdered(
  performFinalizeBlock,
  [
    'beginFinalizationRun',
    'finalizeVersion',
    'chapterFinalized = true',
    'processChapterFinalization',
    'requiredFailures.length',
    'throw buildRequiredFailureError',
    'performStoryBlockReviewAfterFinalize',
    'finalizationCompleted = true'
  ],
  'finalize transition must preserve marker for post-version required failures'
)
assert.match(
  performFinalizeBlock,
  /if \(chapterFinalized\) \{[\s\S]*markFinalizationFailure/,
  'post-version failures must write a failure marker'
)
assert.match(
  performFinalizeBlock,
  /endFinalizationRun\([\s\S]*keepPending:\s*chapterFinalized && !finalizationCompleted/,
  'post-version failures must keep the marker pending until full settlement completes'
)
assert.match(
  performFinalizeBlock,
  /performStoryBlockReviewAfterFinalize[\s\S]*catch \(error\) \{[\s\S]*throw normalized/,
  'story-block settlement failures must propagate into marker preservation'
)

assert.match(
  finalizationGuard,
  /markerStatus:\s*'storyBlockSettlementFailure'[\s\S]*failureType:\s*'story_block_settlement'[\s\S]*retryable:\s*false/,
  'story block settlement conflicts must be classified separately and non-retryable'
)
assert.match(
  finalizationGuard,
  /markerStatus:\s*'retryablePostprocessFailure'[\s\S]*failureType:\s*'post_finalize_ai_proxy'/,
  'memory/settings postprocess failures must remain retryable through the generic path'
)

const retryableAction = getFinalizationMarkerAction({
  chapterNum: 88,
  retryablePostprocessFailure: { message: 'settings timeout', retryable: true }
})
assert.equal(retryableAction.kind, 'retry_postprocess')
assert.equal(retryableAction.canRetryPostprocess, true)

const storyBlockAction = getFinalizationMarkerAction({
  chapterNum: 88,
  storyBlockSettlementFailure: { message: 'story_block_stage_update_conflict', retryable: false }
})
assert.equal(storyBlockAction.kind, 'manual_story_block_settlement')
assert.equal(storyBlockAction.canRetryPostprocess, false)

const processingAction = getFinalizationMarkerAction({
  chapterNum: 88,
  status: 'processing',
  postFinalizePending: true,
  postFinalizeFailed: false
})
assert.equal(processingAction.kind, 'pending_postprocess')
assert.equal(processingAction.canRetryPostprocess, false)

const retryBlock = blockBetween(
  writerView,
  'async function retryFinalizationPostprocess',
  'async function handleForceFinalizePending'
)
assertOrdered(
  retryBlock,
  [
    'const markerAction = getFinalizationMarkerAction(marker)',
    'if (!markerAction.canRetryPostprocess)',
    'return',
    'beginChapterFinalizationRun',
    'memoryStore.processChapterFinalization'
  ],
  'generic retry must reject non-retryable markers before rerunning memory/settings extraction'
)
assert.doesNotMatch(
  retryBlock,
  /performStoryBlockReviewAfterFinalize/,
  'generic memory/settings retry must not pretend to rerun story-block settlement'
)

const reconcileBlock = blockBetween(
  writerView,
  'async function reconcileCompletedFinalizationMarker',
  'async function ensureAiContextReady'
)
assertOrdered(
  reconcileBlock,
  [
    'isChapterFinalized(chapter)',
    'hasPendingSettings',
    'hasPendingFacts',
    'api.beatPlans.get',
    'beat?.storyBlockId',
    'storyBlockStore.loadBlocks',
    'hasStoryBlockReview',
    'clearChapterFinalizationPending'
  ],
  'reconcile must clear markers only after final chapter, no pending settings/facts, beat storyBlockId, and saved story-block review'
)
assert.match(
  reconcileBlock,
  /review\?\.decision && Number\(review\.chapterNum \|\| review\.chapter_num \|\| num\) === num/,
  'reconcile story-block review check must be scoped to the same chapter'
)

const storyReviewBlock = blockBetween(
  writerView,
  'async function performStoryBlockReviewAfterFinalize',
  'function buildFallbackStoryBlockReviewAfterFailure'
)
const continueBranch = storyReviewBlock.match(/review\.decision === 'continue_current_block'[\s\S]*?\} else if \(review\.decision === 'split_unfinalized_content'\)/)?.[0] || ''
assert.ok(continueBranch, 'continue_current_block settlement branch must remain explicit')
assert.doesNotMatch(continueBranch, /stagePlan\s*:/, 'continue_current_block must not send a stagePlan payload')
const splitBranch = storyReviewBlock.match(/review\.decision === 'split_unfinalized_content'[\s\S]*?\} else if \(review\.decision === 'complete_current_block'\)/)?.[0] || ''
assert.ok(splitBranch, 'split_unfinalized_content settlement branch must remain explicit')
assert.doesNotMatch(splitBranch, /stagePlan\s*:/, 'split_unfinalized_content must not send a stagePlan payload')
const adjustBranch = storyReviewBlock.match(/review\.decision === 'adjust_remaining_stages'[\s\S]*?\} else if \(review\.decision === 'continue_current_block'\)/)?.[0] || ''
assert.match(adjustBranch, /stagePlan:\s*extractEditableFutureStageUpdates/, 'adjust_remaining_stages must send only editable future stage patches')
assert.match(adjustBranch, /stagePlanPatchMode:\s*'editable_future_only'/, 'adjust_remaining_stages must use editable_future_only patch mode')

const waitBlock = blockBetween(
  liveScript,
  'async function waitForPostFinalizeSettlement',
  'async function clickFinalizeForLatestHardPassCandidate'
)
assert.match(waitBlock, /classifyPostFinalizeMarkerFailure\(marker\)/, 'runner wait must classify marker failures')
assert.match(waitBlock, /story_block_review_not_saved/, 'runner wait must block on missing story-block review')
assert.match(waitBlock, /pending_settings_unreadable/, 'runner wait must check pending settings readability')
assert.match(waitBlock, /pending_canon_facts_unreadable/, 'runner wait must check pending facts readability')
assert.match(waitBlock, /pendingSettingsCount/, 'runner wait must report pending settings count')
assert.match(waitBlock, /pendingCanonFactsCount/, 'runner wait must report pending facts count')

console.log('finalization state transition contract passed')
