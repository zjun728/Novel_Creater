import assert from 'node:assert/strict'
import {
  expectedChapterWordRange,
  hasUsableChapterContent,
  isChapterWordCountInHardRange,
  isChapterWordCountTooFarForQaStop,
  isChapterWordCountWithinQualityGrace
} from './run_realistic_longform_flow_fixed.mjs'

const project = {
  targetWords: 2000000,
  targetChapters: 400
}

const range = expectedChapterWordRange(project)
assert.equal(range.target, 5000)
assert.equal(range.softMin, 4500)
assert.equal(range.softMax, 6500)
assert.equal(range.hardMax, 7000)

assert.equal(isChapterWordCountInHardRange(project, 7072), false)
assert.equal(isChapterWordCountTooFarForQaStop(project, 7072), false)
assert.equal(isChapterWordCountWithinQualityGrace(project, 7072), true)

assert.equal(isChapterWordCountInHardRange(project, 3778), false)
assert.equal(isChapterWordCountTooFarForQaStop(project, 3778), false)
assert.equal(isChapterWordCountWithinQualityGrace(project, 3778), true)

assert.equal(isChapterWordCountTooFarForQaStop(project, 3400), true)
assert.equal(isChapterWordCountWithinQualityGrace(project, 3400), false)

assert.equal(isChapterWordCountTooFarForQaStop(project, 7600), true)
assert.equal(isChapterWordCountWithinQualityGrace(project, 7600), false)

assert.equal(hasUsableChapterContent(''), false)
assert.equal(hasUsableChapterContent('   \n  '), false)
assert.equal(hasUsableChapterContent('林逐推开门。'), true)

console.log('realistic QA word count policy contract passed')
