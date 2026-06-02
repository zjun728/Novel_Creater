import assert from 'node:assert/strict'
import {
  assessChapterWordCount,
  buildChapterWordTarget,
  normalizeWordCount
} from '../frontend/src/utils/chapterWordTarget.js'

const target = buildChapterWordTarget({
  targetWords: 3000000,
  targetChapters: 600
})

assert.equal(normalizeWordCount('5000'), 5000)
assert.deepEqual(target, {
  target: 5000,
  min: 4500,
  max: 6500,
  hardMin: 4000,
  hardMax: 7000
})

assert.equal(assessChapterWordCount('x'.repeat(5200), target).level, 'ok')
assert.equal(assessChapterWordCount('x'.repeat(6200), target).level, 'ok')
assert.equal(assessChapterWordCount('x'.repeat(6800), target).level, 'over')
assert.equal(assessChapterWordCount('x'.repeat(7100), target).level, 'hard_over')
assert.equal(assessChapterWordCount('x'.repeat(4300), target).level, 'under')
assert.equal(assessChapterWordCount('x'.repeat(4100), target).level, 'under')
assert.equal(assessChapterWordCount('x'.repeat(3900), target).level, 'hard_under')

const volumeTarget = buildChapterWordTarget({}, {
  targetWords: 300000,
  chapterRange: '第 1-60 章'
})

assert.equal(volumeTarget.target, 5000)

console.log('CHAPTER_WORD_TARGET_TEST_OK')
