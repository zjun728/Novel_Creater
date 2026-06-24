import assert from 'node:assert/strict'

import { cleanGeneratedChapterTitle } from '../frontend/src/prompts/chapter.js'

const eventPreferred = cleanGeneratedChapterTitle(JSON.stringify({
  candidates: [
    { title: '母亲核心冷光', type: 'item', reason: '物象状态' },
    { title: '审问', type: 'event', reason: '本章核心事件' },
    { title: '第七封信', type: 'item', reason: '关键道具' }
  ]
}), {
  content: '母亲核心冷光还在墙上。审问发生在火灶房。第七封信被留在桌上。'
})

assert.equal(eventPreferred, '审问')

const naturalNounPreferred = cleanGeneratedChapterTitle(JSON.stringify({
  candidates: [
    { title: '档案室凭证', type: 'item', reason: '标签式拼接' },
    { title: '火灶房', type: 'place', reason: '本章主要场景' },
    { title: '金龙宝行', type: 'organization', reason: '本章登场势力' }
  ]
}), {
  content: '火灶房里有人守着，金龙宝行的人后来才进门。档案室凭证被随手搁在灶台边。'
})

assert.ok(['火灶房', '金龙宝行'].includes(naturalNounPreferred), `${naturalNounPreferred} should prefer a natural catalog noun`)

const stillUsableWhenOnlyAverage = cleanGeneratedChapterTitle(JSON.stringify({
  candidates: [
    { title: '母亲核心冷光', type: 'item', reason: '物象状态' }
  ]
}))

assert.equal(stillUsableWhenOnlyAverage, '母亲核心冷光')

console.log('CHAPTER_TITLE_CANDIDATE_RANKING_CONTRACT_OK')
