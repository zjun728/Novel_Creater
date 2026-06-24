import assert from 'node:assert/strict'

import { buildAuditPrompt } from '../frontend/src/prompts/audit.js'

const prompt = buildAuditPrompt('他把铜钱放在柜台上。掌柜脸色变了。', {
  chapterNum: 2,
  previousChapterEnding: '上一章停在铜钱发热，门外有人敲门。',
  beatPlan: '本章去当铺验证铜钱，并付出暴露风险。',
  blockStageSnapshot: {
    blockGoal: '查清铜钱为什么只回应真实代价。',
    storyFunction: '施压与揭示',
    stagePurpose: '验证铜钱',
    stageAction: '去当铺试探掌柜反应',
    stageChoice: '是否交出铜钱换消息',
    stageCostOrConsequence: '暴露自己持有铜钱'
  }
})

assert.match(prompt, /当前章小纲/)
assert.match(prompt, /block_stage_snapshot/)
assert.match(prompt, /上一章定稿摘要\/结尾/)
assert.match(prompt, /storyTaskConsistency/)
assert.match(prompt, /blockAlignment/)
assert.match(prompt, /readingBurden/)
assert.match(prompt, /overAdvance/)
assert.match(prompt, /underDelivery/)

console.log('story task audit contract tests passed')
