import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const store = readFileSync('frontend/src/stores/storyBlockStore.js', 'utf8')
const writer = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const prompt = readFileSync('frontend/src/prompts/storyBlockPrompt.js', 'utf8')
const finalizationCommand = readFileSync('frontend/src/application/writer-flow/finalization-command.js', 'utf8')

const legacyAdjust = ['adjust', 'current', 'block'].join('_')
const obsoleteStatus = ['super', 'seded'].join('')
const obsoleteAuditHint = ['block', 'Review', 'Hint'].join('')
const forbiddenRuntimePattern = new RegExp(`${legacyAdjust}|${obsoleteStatus}`)

assert.doesNotMatch(store, forbiddenRuntimePattern)
assert.doesNotMatch(writer, forbiddenRuntimePattern)
assert.doesNotMatch(prompt, forbiddenRuntimePattern)

assert.match(store, /import \{ chatCompletion \}/)
assert.match(store, /buildStoryBlockPlanningSystemPrompt/)
assert.match(store, /buildStoryBlockPlanningPrompt/)
assert.match(store, /buildStoryBlockReviewSystemPrompt/)
assert.match(store, /buildStoryBlockReviewPrompt/)
assert.match(store, /async function planStoryBlockWithAI/)
assert.match(store, /async function reviewStoryBlockWithAI/)
assert.match(store, /normalizeStoryBlockPlanningResult/)
assert.match(store, /chatCompletion\(provider,\s*messages/)

assert.match(writer, /function buildStoryBlockPlanningContext/)
assert.match(writer, /bible:\s*novelStore\.bible/)
assert.match(writer, /currentVolume:\s*currentVolume\.value/)
assert.match(writer, /settingLibrary/)
assert.match(writer, /recentSummaries/)
assert.match(writer, /previousChapterEnding:\s*previousChapterEnding\.value/)
assert.match(writer, /await storyBlockStore\.planStoryBlockWithAI/)
assert.match(writer, /buildDefaultStoryBlockPayload\(\)[\s\S]*message\.warning\([\s\S]*审阅/)

const reviewFn = writer.slice(
  writer.indexOf('async function performStoryBlockReviewAfterFinalize'),
  writer.indexOf('async function loadFinalizedVersionForPostprocess')
)
const finalizeFn = writer.slice(
  writer.indexOf('async function performFinalize'),
  writer.indexOf('async function performStoryBlockReviewAfterFinalize')
)
assert.match(reviewFn, /await storyBlockStore\.reviewStoryBlockWithAI/)
assert.match(reviewFn, /loadChapterBeatPlan\(finalizedProjectId,\s*finalizedChapterNum\)/)
assert.doesNotMatch(reviewFn, /if \(!blockId\) return null/)
assert.match(reviewFn, /if \(!blockId[\s\S]{0,240}throw new Error/)
assert.match(finalizeFn, /runFinalizeChapterCommand[\s\S]*performStoryBlockReviewAfterFinalize/)
assert.match(
  finalizationCommand,
  /performStoryBlockReviewAfterFinalize\(results,\s*version,\s*chapterNum,\s*projectId\)[\s\S]*onStoryBlockReviewFailure[\s\S]*throw normalized/,
  'finalization command must propagate story-block review failures after recording the callback'
)
assert.doesNotMatch(reviewFn, new RegExp(obsoleteAuditHint))
assert.match(reviewFn, /review\.decision === 'adjust_remaining_stages'[\s\S]*storyBlockStore\.updateRemainingStages/)
assert.match(reviewFn, /review\.decision === 'continue_current_block'[\s\S]*storyBlockStore\.updateRemainingStages/)
assert.match(reviewFn, /carryOverToNextChapter/)
assert.match(reviewFn, /review\.decision === 'open_new_block'[\s\S]*createStoryBlockWithAI/)
assert.match(reviewFn, /function mergeForwardStagePlan/)
assert.match(reviewFn, /snapshot\?\.stageId/)
assert.match(reviewFn, /lockedStageIds/)
assert.match(reviewFn, /canEditStoryBlockStageForReview/)
assert.match(reviewFn, /if \(locked\) \{[\s\S]*merged\.push\(stage\)/)

console.log('story block AI flow contract tests passed')
