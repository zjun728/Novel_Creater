import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const storyBlocksRouter = readFileSync('backend/routers/story_blocks.py', 'utf8')
const chaptersRouter = readFileSync('backend/routers/chapters.py', 'utf8')
const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.match(storyBlocksRouter, /def _validate_stage_continuation_reason/)
assert.match(storyBlocksRouter, /story_block_review_invalid/)
assert.match(storyBlocksRouter, /stageContinueReason/)
assert.match(
  storyBlocksRouter,
  /_validate_stage_continuation_reason\(review\)[\s\S]*INSERT INTO story_block_reviews/,
  'backend must validate stageContinues before persisting the review'
)

assert.match(chaptersRouter, /def _stage_continue_reason/)
assert.match(
  chaptersRouter,
  /review\.get\("stageContinues"\) is True[\s\S]*_stage_continue_reason\(review\)/,
  'backend beat-plan reuse basis must require a previous same-stage continuation reason'
)

assert.match(liveScript, /story_block_review_invalid/)
assert.match(liveScript, /validateStoryBlockReviewContinuation/)
assert.match(liveScript, /previousStageContinueReason/)
assert.match(liveScript, /currentStageReuseAllowed/)
assert.match(liveScript, /currentStageReuseReason/)
assert.match(liveScript, /reusedStageFromChapter/)

console.log('story block review invalid contract tests passed')
