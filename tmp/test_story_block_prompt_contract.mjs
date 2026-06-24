import assert from 'node:assert/strict'

import {
  buildStoryBlockPlanningPrompt,
  buildStoryBlockReviewPrompt,
  buildStoryBlockReviewSystemPrompt,
  normalizeStoryBlockReviewResult
} from '../frontend/src/prompts/storyBlockPrompt.js'

const legacyAdjust = ['adjust', 'current', 'block'].join('_')
const obsoleteStatus = ['super', 'seded'].join('')
const forbiddenRuntimePattern = new RegExp(`${legacyAdjust}|${obsoleteStatus}`)

const system = buildStoryBlockReviewSystemPrompt()
assert.match(system, /只允许向前滚动/)
assert.match(system, /adjust_remaining_stages/)
assert.match(system, /split_unfinalized_content/)
assert.doesNotMatch(system, forbiddenRuntimePattern)

const planningPrompt = buildStoryBlockPlanningPrompt({
  bible: { title: '铜钱志' },
  currentVolume: { title: '第一卷' },
  volumePlanning: [{ title: '第一卷', coreGoal: '确认铜钱规则' }],
  settingLibrary: { entities: ['当铺'] },
  stateLedger: { facts: ['主角拿到铜钱'] },
  recentFacts: ['铜钱只回应真实代价'],
  recentSummaries: ['主角在当铺交出铜钱'],
  previousChapterEnding: '柜台后的抽屉自己开了一条缝'
})
assert.match(planningPrompt, /创作圣经/)
assert.match(planningPrompt, /分卷规划/)
assert.match(planningPrompt, /设定和记忆边界/)
assert.match(planningPrompt, /近期章节/)
assert.match(planningPrompt, /上一章结尾/)
assert.doesNotMatch(planningPrompt, forbiddenRuntimePattern)

const prompt = buildStoryBlockReviewPrompt({
  chapterNum: 2,
  finalizedSummary: '主角在当铺交出铜钱，换到半张旧账页。',
  blockStageSnapshot: {
    blockGoal: '查清铜钱为什么只回应真实代价。',
    stagePurpose: '验证铜钱',
    stageAction: '去当铺试探掌柜反应'
  },
  storyBlock: {
    goal: '查清铜钱为什么只回应真实代价。',
    entryState: '主角刚拿到铜钱。',
    completedStages: []
  }
})

assert.match(prompt, /block_stage_snapshot/)
assert.match(prompt, /不得回改/)
assert.match(prompt, /已定稿章节/)
assert.match(prompt, /stageContinues/)
assert.match(prompt, /跨章继续|继续同一阶段|stageContinues=true/)
assert.doesNotMatch(prompt, forbiddenRuntimePattern)

const normalized = normalizeStoryBlockReviewResult({
  decision: legacyAdjust,
  remainingStages: [{ id: 'stage-2', purpose: '后续阶段' }]
})
assert.equal(normalized.decision, 'continue_current_block')
assert.equal(normalized.stageContinues, false)

const normalizedContinuation = normalizeStoryBlockReviewResult({
  decision: 'continue_current_block',
  stageContinues: true,
  reason: '当前阶段需要跨章继续，因为本章只完成了审判场，未进入星账激活后果。'
})
assert.equal(normalizedContinuation.stageContinues, true)

console.log('story block prompt contract tests passed')
