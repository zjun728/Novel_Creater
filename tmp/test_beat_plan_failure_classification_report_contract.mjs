import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

for (const code of [
  'beat_plan_parse_failed',
  'beat_plan_missing_fields',
  'beat_plan_quality_failed'
]) {
  assert.match(writerStore, new RegExp(code), `writerStore must classify ${code}`)
  assert.match(liveScript, new RegExp(code), `live report must preserve ${code}`)
}

for (const field of [
  'candidateRaw',
  'parsedCandidate',
  'qualityGateInput',
  'qualityGateResult'
]) {
  assert.match(writerStore, new RegExp(field), `writerStore diagnostics must record ${field}`)
  assert.match(liveScript, new RegExp(field), `live report diagnostics must surface ${field}`)
}

assert.doesNotMatch(
  writerStore,
  /小纲推进\/新鲜度闸未通过：\$\{issueTypes\}/,
  'progression failures must not collapse parse, missing-fields, and quality-gate errors into one generic message'
)

console.log('beat plan failure classification report contract tests passed')
