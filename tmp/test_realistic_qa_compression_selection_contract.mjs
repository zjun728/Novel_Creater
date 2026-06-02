import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')
const runChapterStart = source.indexOf('async function runChapter(')
const compressLoopIndex = source.indexOf('for (let compressAttempt = 1; draftCount > range.hardMax && compressAttempt <= 2; compressAttempt += 1)', runChapterStart)
const inRangeIndex = source.indexOf('if (isChapterWordCountInHardRange(project, compressedCount))', compressLoopIndex)
const stillLongIndex = source.indexOf('if (compressedCount > range.hardMax && compressAttempt < 2)', inRangeIndex)
const inRangeBlock = source.slice(inRangeIndex, stillLongIndex)

assert.ok(runChapterStart > -1, 'runChapter should exist')
assert.ok(compressLoopIndex > runChapterStart, 'runChapter should have a compression loop')
assert.ok(inRangeIndex > compressLoopIndex, 'compression loop should detect an acceptable compressed candidate')
assert.match(
  inRangeBlock,
  /\bbreak\b/,
  'an acceptable compressed candidate should stop the compression loop instead of falling through to WORD_COUNT_GATE'
)

assert.match(
  source,
  /function chooseBestChapterCandidate/,
  'realistic QA should choose the best saved candidate when compression attempts overshoot or undershoot'
)
assert.match(
  source,
  /quality_grace/,
  'candidate selection should allow a small quality-preserving grace before failing the run'
)

console.log('realistic QA compression selection contract tests passed')
