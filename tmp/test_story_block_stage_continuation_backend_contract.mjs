import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const chaptersRouter = readFileSync('backend/routers/chapters.py', 'utf8')
const storyBlocksRouter = readFileSync('backend/routers/story_blocks.py', 'utf8')

assert.match(chaptersRouter, /def _review_stage_id/)
assert.match(chaptersRouter, /async def _stage_continuation_depth/)
assert.match(chaptersRouter, /_has_stage_continuation_basis[\s\S]*depth[\s\S]*<\s*2/)
assert.match(
  chaptersRouter,
  /story_block_stage_continuation_limit|stageContinuationDepth/,
  'beat-plan validation must expose continuation-depth diagnostics instead of silently allowing the third reuse'
)

assert.match(storyBlocksRouter, /def _review_stage_id/)
assert.match(storyBlocksRouter, /def _stage_continuation_depth/)
assert.match(storyBlocksRouter, /story_block_stage_continuation_limit/)
assert.match(storyBlocksRouter, /settlementDecision/)
assert.match(storyBlocksRouter, /whetherStageClosedBeforeNextBeatPlan/)
assert.match(storyBlocksRouter, /previousOpenStageId/)
assert.match(storyBlocksRouter, /stageContinuationDepth/)
assert.match(
  storyBlocksRouter,
  /stageContinuationDepth[\s\S]*history_item/,
  'story block review history must preserve depth diagnostics for reporting'
)

console.log('story block stage continuation backend contract passed')
