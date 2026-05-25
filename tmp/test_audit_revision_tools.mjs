import assert from 'node:assert/strict'
import {
  applyAuditReplacement,
  cleanAuditQuote,
  getAuditReplacement,
  locateAuditQuote
} from '../frontend/src/utils/auditRevisionTools.js'

assert.equal(cleanAuditQuote('原文：“林逐抬头，眼泪滚落。”'), '林逐抬头，眼泪滚落。')
assert.equal(cleanAuditQuote('位置： “不是害怕，是愤怒。” '), '不是害怕，是愤怒。')

const content = '雨水打在屋檐上。\n\n林逐抬头，眼泪滚落。\n\n他没有说话。'
const issue = {
  location: '“林逐抬头，眼泪滚落。”',
  replacement: '林逐抬起头，喉结动了动，把眼泪咽回去。'
}

assert.equal(getAuditReplacement(issue), '林逐抬起头，喉结动了动，把眼泪咽回去。')

const found = locateAuditQuote(content, issue)
assert.equal(found.found, true)
assert.equal(found.index, content.indexOf('林逐抬头，眼泪滚落。'))

const applied = applyAuditReplacement(content, issue)
assert.equal(applied.ok, true)
assert.equal(
  applied.content,
  '雨水打在屋檐上。\n\n林逐抬起头，喉结动了动，把眼泪咽回去。\n\n他没有说话。'
)

const missing = applyAuditReplacement(content, {
  location: '不存在的原文',
  replacement: '替换文本'
})
assert.equal(missing.ok, false)
assert.equal(missing.reason, 'not_found')
assert.equal(missing.content, content)

const quotedContent = '投影室里，那个闭着眼睛的投影睁开了眼。\n\n“让他进。陈塘关的遗愿，我们林家等了三千年。”'
const looseIssue = {
  location: '投影室里，那个闭着眼睛的投影睁开了眼。 让他进。陈塘关的遗愿，我们林家等了三千年。',
  replacement: '投影室里，那个闭着眼睛的投影睁开了眼。指尖在扶手上轻叩三下，低语道：“让他进。暗河入口三千年才开一次，我们需要一个活体钥匙。”'
}
const looseLocated = locateAuditQuote(quotedContent, looseIssue)
assert.equal(looseLocated.found, true)
assert.equal(looseLocated.matchMode, 'loose')

const looseApplied = applyAuditReplacement(quotedContent, looseIssue)
assert.equal(looseApplied.ok, true)
assert.equal(looseApplied.content, looseIssue.replacement)

const punctuationContent = '不是刻上去的。是信息态纹理的显形。字迹是火尖枪尖烧出来的一道沟槽。'
const punctuationIssue = {
  location: '不是刻上去的——是信息态纹理的显形。',
  replacement: '砧石表面浮现出一行字，字迹是信息态纹理自行显形。'
}
const punctuationLocated = locateAuditQuote(punctuationContent, punctuationIssue)
assert.equal(punctuationLocated.found, true)
assert.equal(punctuationLocated.matchMode, 'punctuation')
assert.equal(punctuationLocated.quote, '不是刻上去的。是信息态纹理的显形。')
const punctuationApplied = applyAuditReplacement(punctuationContent, punctuationIssue)
assert.equal(punctuationApplied.ok, true)
assert.equal(
  punctuationApplied.content,
  '砧石表面浮现出一行字，字迹是信息态纹理自行显形。字迹是火尖枪尖烧出来的一道沟槽。'
)

const fragmentContent = '不是刻上去的。是信息态纹理的显形。字迹是火尖枪尖烧出来的一道沟槽。'
const fragmentIssue = {
  location: '不是刻上去的',
  replacement: '砧石表面浮现出一行字，字迹是信息态纹理自行显形。'
}
const fragmentApplied = applyAuditReplacement(fragmentContent, fragmentIssue)
assert.equal(fragmentApplied.ok, true)
assert.equal(fragmentApplied.expanded, true)
assert.equal(fragmentApplied.quote, '不是刻上去的。')
assert.equal(
  fragmentApplied.content,
  '砧石表面浮现出一行字，字迹是信息态纹理自行显形。是信息态纹理的显形。字迹是火尖枪尖烧出来的一道沟槽。'
)

const sentenceContent = '铭文发烫——烫的不是温度，是共鸣。赘字铭文在回应暗河里某个东西的召唤。'
const sentenceIssue = {
  location: '烫的不是温度',
  replacement: '铭文浮出一层冷光，那不是温度变化，而是与暗河深处形成了短暂共鸣。'
}
const sentenceApplied = applyAuditReplacement(sentenceContent, sentenceIssue)
assert.equal(sentenceApplied.ok, true)
assert.equal(sentenceApplied.expanded, true)
assert.equal(sentenceApplied.quote, '铭文发烫——烫的不是温度，是共鸣。')
assert.equal(
  sentenceApplied.content,
  '铭文浮出一层冷光，那不是温度变化，而是与暗河深处形成了短暂共鸣。赘字铭文在回应暗河里某个东西的召唤。'
)

console.log('AUDIT_REVISION_TOOLS_OK')
