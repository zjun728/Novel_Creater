import assert from 'node:assert/strict'
import fs from 'node:fs'

const router = fs.readFileSync('backend/routers/story_blocks.py', 'utf8')

for (const field of [
  'equivalentCompletionScope',
  'futureStageTouched',
  'futureStageEvidence',
  'futureStageOverClosed',
  'replanRemainingStages'
]) {
  assert.match(router, new RegExp(field), `backend review history should persist ${field}`)
}

assert.match(
  router,
  /completed_by_equivalent_story_function[\s\S]{0,900}current_stage_id|current_stage_id[\s\S]{0,900}completed_by_equivalent_story_function/,
  'backend must clamp equivalent completion to the current bound stage'
)

assert.match(
  router,
  /futureStageOverClosed[\s\S]{0,900}False|False[\s\S]{0,900}futureStageOverClosed/,
  'backend should prevent future stage over-close rather than silently completing future stages'
)

console.log('story block equivalent scope backend contract passed')
