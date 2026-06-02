import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const contextBuilder = readFileSync('frontend/src/utils/contextBuilder.js', 'utf8')

assert.match(
  contextBuilder,
  /\.filter\(isCorrectionTaskHighPriorityForWriting\)/,
  'writing context should only inject high-priority correction tasks'
)

assert.match(
  contextBuilder,
  /isCorrectionTaskBlockingForGeneration\(task\).*return true/s,
  'blocking correction tasks should still enter writing context'
)

assert.match(
  contextBuilder,
  /\['critical', 'major'\]\.includes\(task\?\.severity\)/,
  'non-blocking writing correction context should be limited to critical/major issues'
)

console.log('CORRECTION_CONTEXT_PRIORITY_CONTRACT_OK')
