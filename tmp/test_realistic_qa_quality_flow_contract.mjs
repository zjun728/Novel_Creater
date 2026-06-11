import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_realistic_longform_flow_fixed.mjs', 'utf8')

const compactStart = source.indexOf('async function compactBeatPlanIfNeeded(')
const qualityGateStart = source.indexOf('async function ensureBeatPlanQuality(', compactStart)
assert.ok(compactStart > -1, 'compactBeatPlanIfNeeded should exist')
assert.ok(qualityGateStart > compactStart, 'ensureBeatPlanQuality should follow beat compaction')

const compactBlock = source.slice(compactStart, qualityGateStart)
assert.match(
  compactBlock,
  /assertCheck\(best\.length <= 1300/,
  'beat plan compaction should record a failed hard-limit check when compressed outline remains over the limit'
)
assert.doesNotMatch(
  compactBlock,
  /return best\.length < text\.length \? best : text/,
  'beat plan compaction should not silently return an overlong outline after a failed compression'
)

const generateBeatStart = source.indexOf('async function generateBeatPlan(', qualityGateStart)
const qualityGateBlock = source.slice(qualityGateStart, generateBeatStart)
assert.match(
  qualityGateBlock,
  /result\.length >= 500/,
  'beat plan quality gate should enforce a minimum usable length'
)
assert.match(
  qualityGateBlock,
  /result\.length <= 1300/,
  'beat plan quality gate should enforce the hard maximum before drafting'
)

const expandStart = source.indexOf('async function expandShortChapterContent(')
const compressStart = source.indexOf('async function compressLongChapterContent(', expandStart)
assert.ok(expandStart > -1, 'expandShortChapterContent should exist')
assert.ok(compressStart > expandStart, 'compressLongChapterContent should follow short expansion')

const expandBlock = source.slice(expandStart, compressStart)
assert.match(
  expandBlock,
  /局部补足/,
  'short chapter expansion should be a local gap-filling pass, not a full rewrite'
)
assert.doesNotMatch(
  expandBlock,
  /至少新增一到两个完整场景/,
  'short chapter expansion should not force one or two complete new scenes, which causes over-expansion'
)
assert.match(
  expandBlock,
  /补足上限/,
  'short chapter expansion prompt should include an explicit upper bound for the added content'
)

console.log('realistic QA quality flow contract tests passed')

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const writerCompactStart = writerStore.indexOf('async function compactChapterBeatPlanIfNeeded(')
const writerRepairStart = writerStore.indexOf('async function repairProseRhythmIfNeeded(', writerCompactStart)
assert.ok(writerCompactStart > -1, 'writer store should compact chapter beat plans')
assert.ok(writerRepairStart > writerCompactStart, 'writer repair function should follow beat compaction')
const writerCompactBlock = writerStore.slice(writerCompactStart, writerRepairStart)

assert.match(
  writerCompactBlock,
  /throw new Error\(`第 \$\{chapterNum\} 章小纲压缩后仍超过上限/,
  'frontend beat plan generation should surface overlong outline compression failures instead of silently continuing'
)
assert.doesNotMatch(
  writerCompactBlock,
  /return best\s*\n\s*}\s*catch/,
  'frontend beat plan compaction should not return an overlong shorter outline'
)

console.log('frontend beat compaction gate contract tests passed')
