import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  detectSamplePromptLeakage,
  normalizeSampleMicroDemoLibrary
} from '../frontend/src/data/sampleMicroDemoCards.js'
import {
  buildSystemWritingStandardsFromExperienceCards,
  formatActiveWritingStandardLowDoseForPrompt
} from '../frontend/src/data/writingStyleStandards.js'
import { buildDraftPrompt } from '../frontend/src/prompts/chapterDraftPrompt.js'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function readJson(relPath) {
  return JSON.parse(fs.readFileSync(path.join(ROOT, relPath), 'utf8'))
}

const library = normalizeSampleMicroDemoLibrary({
  v21: readJson('frontend/src/data/sampleMicroDemoCards.v2_1.json'),
  v22: readJson('frontend/src/data/sampleMicroDemoCards.v2_2.json')
})

assert.equal(library.cards.filter(card => card.version === 'v2.1').length, 16)
assert.equal(library.cards.filter(card => card.version === 'v2.2').length, 12)
assert.equal(library.promptCandidates.filter(card => card.version === 'v2.2').length, 8)
assert.ok(library.backendReferenceOnly.some(card => card.cardId === 'dialogue-v2_2-03-interrogate-back'))

const standards = buildSystemWritingStandardsFromExperienceCards(library.cards)
for (const required of [
  '对话真实感增强',
  '人物血肉与情绪反应',
  '场景停留与生活质感',
  '反 AI 腔基础标准',
  '通俗故事推进',
  '设定自然呈现'
]) {
  assert.ok(standards.some(item => item.name === required), `missing system formal standard: ${required}`)
}
assert.ok(standards.every(item => item.sourceKind === 'system' && item.active === true), 'system formal standards should be active by default')
assert.ok(standards.every(item => item.experienceCardSnapshots?.length), 'system formal standards should keep experience card snapshots')

const lowDosePrompt = formatActiveWritingStandardLowDoseForPrompt(standards)
for (const allowed of ['写法原则', '原创微示范', '反 AI 提醒']) {
  assert.match(lowDosePrompt, new RegExp(allowed), `formal standard prompt should include ${allowed}`)
}
for (const forbidden of [
  'sourceWork',
  'sourceInfluence',
  'sourceCardId',
  'characterEmotionVariants',
  'emotionDialogueOptions',
  '凡人修仙传',
  '四世同堂',
  '一句顶一万句',
  '修真聊天群',
  '韩立',
  '黄枫谷',
  '祁家'
]) {
  assert.ok(!lowDosePrompt.includes(forbidden), `formal standard prompt leaked forbidden token: ${forbidden}`)
}
assert.equal(detectSamplePromptLeakage(lowDosePrompt).detected, false)

const draftPrompt = buildDraftPrompt({
  chapterNum: 63,
  sampleMicroDemoCard: library.promptCandidates[0],
  activeWritingStandards: standards.slice(0, 1),
  beatPlan: {
    chapterEvent: '小九和陆沉舟在雨棚下争执，表面互相嫌弃，实际都在确认对方有没有撑住。'
  }
})
assert.equal((draftPrompt.match(/正式写作标准低量调用/g) || []).length, 1, 'draft prompt should inject at most one formal-standard section')
assert.equal((draftPrompt.match(/原创微示范低量参考/g) || []).length, 0, 'experience cards must not directly inject into draft prompt')
assert.ok(!draftPrompt.includes(library.promptCandidates[0].cardId), 'sampleCardId must stay out of prompt text')
assert.equal(detectSamplePromptLeakage(draftPrompt).detected, false)

console.log('sample micro demo formal-standard contract passed')
