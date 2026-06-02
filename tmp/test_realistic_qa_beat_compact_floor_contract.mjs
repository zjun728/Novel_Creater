import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

const compactStart = source.indexOf('async function compactBeatPlanIfNeeded(')
const acceptIndex = source.indexOf('if (cleaned.length >= 600', compactStart)
const returnTextIndex = source.indexOf('return text', acceptIndex)

assert.ok(compactStart > -1, 'compactBeatPlanIfNeeded should exist')
assert.ok(acceptIndex > compactStart, 'beat plan compression should enforce a minimum compacted length')
assert.ok(returnTextIndex > acceptIndex, 'too-short compacted outline should be rejected before falling back to original')
assert.match(
  source.slice(compactStart, returnTextIndex),
  /700-1100 字/,
  'compression prompt should ask for a concise but complete outline range'
)

console.log('realistic QA beat compact floor contract tests passed')
