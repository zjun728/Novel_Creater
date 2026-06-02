import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

const runStart = source.indexOf('async function runChapter(')
const overExpandedIndex = source.indexOf('if (expandedCount > range.hardMax)', runStart)
const compressedRetryIndex = source.indexOf('const compressedContent = await compressLongChapterContent', runStart)
const secondAttemptGateIndex = source.indexOf('if (expandAttempt === 2)', runStart)

assert.ok(runStart > -1, 'runChapter should exist')
assert.ok(overExpandedIndex > runStart, 'runChapter should detect over-expanded short-draft retries')
assert.ok(compressedRetryIndex > overExpandedIndex, 'over-expanded retry should fall through to compression')
assert.ok(secondAttemptGateIndex > overExpandedIndex, 'only still-short retries should hit the second-attempt word gate')
assert.doesNotMatch(
  source.slice(overExpandedIndex, secondAttemptGateIndex),
  /throw buildChapterWordGateError/,
  'over-expanded retry should not throw before compression gets a chance'
)

console.log('realistic QA over-expanded retry compression contract tests passed')
