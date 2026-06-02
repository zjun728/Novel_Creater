import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const runtime = readFileSync('tmp/run_rolling_planning_runtime_check.mjs', 'utf8')

assert.match(
  runtime,
  /finalVersionId|final_version_id/,
  'runtime planning check must identify finalized chapters by finalVersionId, matching the chapters API payload'
)

assert.doesNotMatch(
  runtime,
  /filter\(item => item\.status === 'finalized'\)/,
  'chapters API uses status="final" and finalVersionId; status="finalized" would make nextChapterNum fall back to 1'
)

console.log('rolling planning runtime progress contract tests passed')
