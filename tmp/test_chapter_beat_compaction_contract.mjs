import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const qaScript = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

assert.match(writerStore, /async function compactChapterBeatPlanIfNeeded/)
assert.match(writerStore, /content\.length <= 1300/)
assert.match(writerStore, /700-1100/)
assert.match(writerStore, /4-6/)

assert.match(qaScript, /async function compactBeatPlanIfNeeded/)
assert.match(qaScript, /text\.length <= 1300/)
assert.match(qaScript, /700-1100/)
assert.match(qaScript, /4-6/)

console.log('chapter beat compaction contract tests passed')
