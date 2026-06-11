import assert from 'node:assert/strict'
import { buildFallbackCanonFacts } from '../frontend/src/utils/canonFactFallback.js'

const chapterText = `
林墨把宿命之书合上时，钟楼已经敲过凌晨四点。
母亲的注视还剩三十个小时才会彻底转移到他身上。
他把第三枚铜钱塞回衣袋，右手虎口的裂伤还在渗血。
`

const facts = buildFallbackCanonFacts({
  chapterNum: 6,
  chapterContent: chapterText,
  summary: '林墨发现母亲的注视即将转移到自己身上，并带着第三枚铜钱离开钟楼。'
})

assert.ok(Array.isArray(facts), 'fallback should return fact list')
assert.ok(facts.length >= 1, 'fallback should produce at least one memory anchor')
assert.ok(facts.some(fact => fact.content.includes('第 6 章') || fact.content.includes('第6章')), 'fallback should include chapter anchor')
assert.ok(
  facts.some(fact => /三十|30|第三枚|裂伤|凌晨四点/.test(`${fact.content} ${fact.evidence}`)),
  'fallback should retain obvious hard-state signals'
)
assert.ok(facts.every(fact => fact.status === 'accepted'), 'fallback facts should be directly usable')

console.log('canon fact fallback contract passed')
