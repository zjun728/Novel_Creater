import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

assert.match(
  source,
  /function isChapterWordCountWithinQualityGrace\(project, count\)/,
  'word QA should have a quality-preserving grace band for near-limit long chapters'
)
assert.match(
  source,
  /const qaStopMax = Math\.round\(range\.target \* 1\.4\)/,
  'QA should stop only when a chapter is far beyond the target, not when it is slightly above the recommended hard max'
)
assert.match(
  source,
  /字数进入质量保留容忍区/,
  'word count assessment should warn but allow quality-grace chapters'
)

const chooseStart = source.indexOf('function chooseBestChapterCandidate')
const chooseEnd = source.indexOf('function buildChapterWordGateError', chooseStart)
const chooseBlock = source.slice(chooseStart, chooseEnd)
assert.match(
  chooseBlock,
  /isChapterWordCountWithinQualityGrace\(project, candidate\.count\)/,
  'candidate selection should preserve a complete near-limit draft if compression collapses too short'
)

const outlierStart = source.indexOf('function findFinalizedWordOutliers')
const outlierEnd = source.indexOf('function assertNoFinalizedWordOutliers', outlierStart)
const outlierBlock = source.slice(outlierStart, outlierEnd)
assert.match(
  outlierBlock,
  /isChapterWordCountTooFarForQaStop\(project, item\?\.wordCount\)/,
  'multi-chapter acceptance should flag only severe word-count outliers after quality-grace chapters are finalized'
)

console.log('realistic QA word quality grace contract tests passed')
