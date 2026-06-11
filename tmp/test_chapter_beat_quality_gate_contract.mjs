import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const checklist = readFileSync('FUNCTION_TEST_CHECKLIST.md', 'utf8')

assert.match(
  writerStore,
  /async function ensureChapterBeatPlanQuality\(provider, chapterNum, content, context = \{\}\)/,
  'writer store should have a unified beat-plan quality gate'
)
assert.match(
  writerStore,
  /async function expandChapterBeatPlanIfNeeded\(provider, chapterNum, content, context = \{\}\)/,
  'too-short beat plans should have an expansion retry path'
)
assert.match(
  writerStore,
  /content\.length >= 500/,
  'beat plan quality gate should enforce a minimum usable length'
)
assert.match(
  writerStore,
  /content\.length <= 1300/,
  'beat plan quality gate should enforce the existing maximum length'
)
assert.match(
  writerStore,
  /context = \{ \.\.\.context, beatPlan: await ensureChapterBeatPlanQuality/,
  'chapter generation should validate confirmed/manual beat plan before drafting'
)
assert.match(
  checklist,
  /小纲过短时会尝试扩展/,
  'test checklist should include short beat-plan expansion behavior'
)

console.log('chapter beat quality gate contract passed')
