import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

for (const field of [
  'beatPlanSource',
  'aiAttempts',
  'derivedFromStoryBlock',
  'derivedReason',
  'stageSnapshotFields',
  'whetherAllowedToContinue'
]) {
  assert.match(liveScript, new RegExp(field), `live report must include ${field}`)
}

assert.match(liveScript, /beat_plan_requires_review/, 'incomplete derived beat plans must report beat_plan_requires_review')
assert.match(
  liveScript,
  /local_safety_requires_review[\s\S]*beat_plan_requires_review|beat_plan_requires_review[\s\S]*local_safety_requires_review/,
  'live failure classification must map local_safety_requires_review to beat_plan_requires_review'
)
assert.match(
  liveScript,
  /derived_from_story_block[\s\S]*whetherAllowedToContinue|whetherAllowedToContinue[\s\S]*derived_from_story_block/,
  'live diagnostics must mark derived_from_story_block as allowed to continue'
)

console.log('longform beat plan source report contract tests passed')
