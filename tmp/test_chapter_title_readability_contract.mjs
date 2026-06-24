import assert from 'node:assert/strict'

import {
  cleanGeneratedChapterTitle,
  evaluateChapterTitlePolicy,
  getChapterTitleQuality
} from '../frontend/src/prompts/chapter.js'

for (const title of ['巡', '追']) {
  const policy = evaluateChapterTitlePolicy(title)
  assert.notEqual(policy.status, 'pass', `${title} should not pass as a generic single-character title`)
  assert.equal(policy.status, 'warning', `${title} should be a warning, not a hard fail`)
  const quality = getChapterTitleQuality(title)
  assert.equal(quality.titleValid, true, `${title} should remain usable but warned`)
  assert.equal(quality.status, 'warning', `${title} quality should report warning`)
  assert.ok(quality.reason, `${title} warning reason should be reported`)
}

for (const title of ['这边', '那边', '来一张', '干什么', '怎么说', '你爹挖的']) {
  const policy = evaluateChapterTitlePolicy(title)
  assert.notEqual(policy.status, 'pass', `${title} should not pass as a dialogue fragment`)
  assert.ok(['warning', 'fail'].includes(policy.status), `${title} should warn or fail`)
}

for (const title of ['河坊巷', '后门', '丁字库', '黑铁令', '巡天司']) {
  const policy = evaluateChapterTitlePolicy(title)
  assert.equal(policy.status, 'pass', `${title} should pass as a plain catalog noun`)
  assert.equal(cleanGeneratedChapterTitle(title), title, `${title} should be accepted`)
}

assert.equal(evaluateChapterTitlePolicy('第 2 章', { chapterNum: 2 }).status, 'fail')

const selected = cleanGeneratedChapterTitle(JSON.stringify({
  candidates: [
    { title: '来一张', type: 'event', reason: 'dialogue line' },
    { title: '丁字库', type: 'place', reason: 'main place' },
    { title: '你爹挖的', type: 'result', reason: 'dialogue line' }
  ]
}), {
  content: '陆沉舟绕进丁字库，黑铁令贴着掌心发烫。有人在门外低声说，来一张。'
})

assert.equal(selected, '丁字库', `candidate ranking should prefer concrete noun over dialogue fragment, got ${selected}`)

console.log('CHAPTER_TITLE_READABILITY_CONTRACT_OK')
