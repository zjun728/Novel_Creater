import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const script = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

const runChapterBlock = script.match(/async function runChapter\([\s\S]*?\n\}/)?.[0] || ''
assert.match(runChapterBlock, /extractCanonFacts/)
assert.match(runChapterBlock, /throw new Error\([^)]*记忆事实/)

const backfillBlock = script.match(/async function backfillMissingFinalizedPostprocess\([\s\S]*?\n\}/)?.[0] || ''
assert.match(backfillBlock, /extractCanonFacts/)
assert.match(backfillBlock, /throw new Error\([^)]*记忆事实/)

console.log('realistic QA postprocess gate contract tests passed')
