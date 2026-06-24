import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const store = readFileSync('frontend/src/stores/storyBlockStore.js', 'utf8')
const writer = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const prompt = readFileSync('frontend/src/prompts/storyBlockPrompt.js', 'utf8')
const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.match(prompt, /buildStoryBlockReviewRepairPrompt/)
assert.match(prompt, /"decision"/)
assert.match(prompt, /"stageContinues"/)

assert.match(store, /lastReviewDiagnostics/)
assert.match(store, /STORY_BLOCK_REVIEW_TIMEOUT_MS/)
assert.match(store, /reviewStoryBlockJsonWithRepair/)
assert.match(store, /createStoryBlockReviewDiagnostics/)
assert.match(store, /repairStoryBlockReviewJson/)
assert.match(store, /withStoryBlockReviewTimeout/)
assert.match(store, /repairTriggered/)
assert.match(store, /repairSucceeded/)

const reviewFn = writer.slice(
  writer.indexOf('async function performStoryBlockReviewAfterFinalize'),
  writer.indexOf('async function loadStoryBlockAfterReview')
)
assert.match(reviewFn, /buildFallbackStoryBlockReviewAfterFailure/)
assert.match(reviewFn, /continue_current_block/)
assert.match(writer, /completedStageIds/)
assert.match(writer, /function buildFallbackStoryBlockReviewAfterFailure/)
assert.match(writer, /aiReviewFallback/)
assert.match(writer, /story_block_review_ai_failure_fallback/)
assert.match(writer, /storyBlockStore\.lastReviewDiagnostics/)

assert.match(liveScript, /collectStoryBlockReviewDiagnostics/)
assert.match(liveScript, /chapter_\$\{chapterNum\}_story_block_review/)
assert.match(liveScript, /waitForStoryBlockReviewSaved\(chapterNum\)/)
assert.match(liveScript, /error\.liveDiagnostics = \{/)
assert.match(liveScript, /collectStoryBlockReviewDiagnostics\(page, chapterNum\)/)
assert.match(liveScript, /reviewHistory/)
assert.match(liveScript, /completedStages/)

console.log('story block review timeout contract tests passed')
