import assert from 'node:assert/strict'
import {
  normalizeStoryHumanityReview,
  storyHumanityReviewAliases
} from './story_humanity_review_utils.mjs'

const canonical = normalizeStoryHumanityReview({
  overallVerdict: { shortAnswer: '能看，但人物弱。' },
  prioritizedIssues: [{ severity: 'P0', title: '循环' }],
  storyHumanityV1Plan: { mechanisms: [{ name: '关系任务' }] },
  nextRoundVerification: { afterSmallChange: ['只跑第 21-25 章五章。'] }
})

assert.equal(canonical.overall.shortAnswer, '能看，但人物弱。')
assert.equal(canonical.issueSummary.length, 1)
assert.equal(canonical.nextPlan.afterSmallChange[0], '只跑第 21-25 章五章。')
assert.equal(canonical.overallVerdict.shortAnswer, canonical.overall.shortAnswer)
assert.equal(canonical.prioritizedIssues, canonical.issueSummary)
assert.equal(canonical.storyHumanityV1Plan, canonical.nextPlan)

const legacy = normalizeStoryHumanityReview({
  overall: { shortAnswer: '旧字段也能读。' },
  issueSummary: [{ severity: 'P1', title: '人物工具化' }],
  nextPlan: { mechanisms: [{ name: '声音卡' }], afterSmallChange: ['只跑第 21-25 章五章。'] }
})

assert.equal(legacy.overallVerdict.shortAnswer, '旧字段也能读。')
assert.equal(legacy.prioritizedIssues[0].title, '人物工具化')
assert.equal(legacy.storyHumanityV1Plan.mechanisms[0].name, '声音卡')
assert.ok(storyHumanityReviewAliases.requiredCanonical.every(key => key in canonical))
assert.ok(storyHumanityReviewAliases.compatibility.every(key => key in canonical))

console.log('story humanity report schema contract passed')
