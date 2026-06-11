import assert from 'node:assert/strict'
import { shouldAcceptProseRhythmRepair } from '../frontend/src/utils/proseRhythmGuard.js'

const base = {
  shortParagraphRate: 0.42,
  maxShortStreak: 8,
  aiContrastCount: 7,
  maxSameLeadingSubjectCount: 6
}

assert.equal(
  shouldAcceptProseRhythmRepair(base, {
    shortParagraphRate: 0.28,
    maxShortStreak: 5,
    aiContrastCount: 6,
    maxSameLeadingSubjectCount: 4
  }, 1.02),
  true,
  'should accept a repair that improves at least one rhythm metric without worsening other tracked metrics'
)

assert.equal(
  shouldAcceptProseRhythmRepair(base, {
    shortParagraphRate: 0.25,
    maxShortStreak: 9,
    aiContrastCount: 6,
    maxSameLeadingSubjectCount: 4
  }, 1.01),
  false,
  'should reject a repair that improves one metric but worsens the longest short-paragraph streak'
)

assert.equal(
  shouldAcceptProseRhythmRepair(base, {
    shortParagraphRate: 0.30,
    maxShortStreak: 6,
    aiContrastCount: 8,
    maxSameLeadingSubjectCount: 4
  }, 1.03),
  false,
  'should reject a repair that adds AI-contrast patterns while improving paragraph rhythm'
)

assert.equal(
  shouldAcceptProseRhythmRepair(base, {
    shortParagraphRate: 0.42,
    maxShortStreak: 8,
    aiContrastCount: 7,
    maxSameLeadingSubjectCount: 6
  }, 1.0),
  false,
  'should reject a repair with no measurable improvement'
)

assert.equal(
  shouldAcceptProseRhythmRepair(base, {
    shortParagraphRate: 0.20,
    maxShortStreak: 4,
    aiContrastCount: 5,
    maxSameLeadingSubjectCount: 3
  }, 1.35),
  false,
  'should reject large word-count drift even when rhythm metrics improve'
)

console.log('prose rhythm repair acceptance tests passed')
