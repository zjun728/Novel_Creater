import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createWritingFingerprintCard,
  formatWritingFingerprintCardForPrompt,
  formatWritingFingerprintCardsForPrompt
} from '../frontend/src/data/writingFingerprints.js'
import {
  getWritingStrategyDisplayCards
} from '../frontend/src/data/writingStyleStandards.js'

test('writing fingerprint cards keep reusable method and exclude source prose', () => {
  const card = createWritingFingerprintCard({
    sourceTitle: '本地样本A',
    genreTags: ['修仙', '知识体系'],
    sourceNote: '由本地小说样本离线分析生成',
    proseRhythm: '长句承载观察和推理，短句只用于动作转折；避免整章一短到底。',
    chapterEntry: '先让人物进入具体场景，再让异常从物件、动作或误判里露出。',
    chapterExit: '结尾落在新证据或旧判断被推翻上，不用模板化状态总结。',
    dialogueMethod: '对话带身份、遮掩和停顿，不让角色主动交底。',
    characterMethod: '人物先按自身利益和恐惧行动，再被主线牵动。',
    ensembleMethod: '配角要有自己的小目标和代价，不只递线索。',
    challengeMethod: '关卡靠选择代价、资源限制和信息误判成立。',
    emotionMethod: '情绪通过动作延迟、身体反应和无用细节呈现，不直接贴标签。',
    informationMethod: '信息从证据、物件反应和失败验证中释放。',
    avoidPatterns: ['反派长篇解释计划', '章节末尾固定抬头总结'],
    forbiddenImitation: ['不得复刻人物名、专有名词、原句'],
    rawExcerpt: '青石板路面上积着没过脚踝的浑水，沿街摊棚的塑料布被雨打得噼啪作响。'
  })

  const prompt = formatWritingFingerprintCardForPrompt(card)

  assert.match(prompt, /写作指纹卡/)
  assert.match(prompt, /章节进入/)
  assert.match(prompt, /对话方式/)
  assert.match(prompt, /人物方法/)
  assert.match(prompt, /群像方法/)
  assert.match(prompt, /任务\/挑战/)
  assert.match(prompt, /情绪呈现/)
  assert.match(prompt, /禁止复刻/)
  assert.doesNotMatch(prompt, /青石板路面上积着没过脚踝的浑水/)
  assert.doesNotMatch(prompt, /rawExcerpt/)
})

test('multiple fingerprint cards are compacted and capped before entering prompts', () => {
  const cards = Array.from({ length: 4 }, (_, index) => createWritingFingerprintCard({
    sourceTitle: `样本${index + 1}`,
    genreTags: ['都市奇幻'],
    proseRhythm: `节奏方法${index + 1}`,
    chapterEntry: `进入方式${index + 1}`,
    chapterExit: `结尾方式${index + 1}`,
    dialogueMethod: `对话方法${index + 1}`,
    characterMethod: `人物方法${index + 1}`,
    ensembleMethod: `群像方法${index + 1}`,
    challengeMethod: `挑战方法${index + 1}`,
    emotionMethod: `情绪方法${index + 1}`,
    informationMethod: `信息方法${index + 1}`,
    avoidPatterns: [`避免项${index + 1}`]
  }))

  const prompt = formatWritingFingerprintCardsForPrompt(cards, { maxCards: 2 })

  assert.match(prompt, /样本1/)
  assert.match(prompt, /样本2/)
  assert.doesNotMatch(prompt, /样本3/)
  assert.doesNotMatch(prompt, /样本4/)
  assert.ok(prompt.length < 1800)
})

test('writing strategy display exposes full fingerprint methods for the frontend', () => {
  const cards = getWritingStrategyDisplayCards({
    selectedStandards: ['system-character-humanity', 'system-dialogue-realism'],
    customStyleNotes: '本书更重考据细节和父子情感。'
  })

  assert.equal(cards.length, 2)
  assert.equal(cards[0].role, '主写作标准')
  assert.equal(cards[1].role, '辅助风味')
  for (const card of cards) {
    const labels = card.sections.map(section => section.label)
    assert.ok(labels.includes('章节组织'))
    assert.ok(labels.includes('对话方式'))
    assert.ok(labels.includes('人物方法'))
    assert.ok(labels.includes('群像方法'))
    assert.ok(labels.includes('任务/挑战'))
    assert.ok(labels.includes('情绪呈现'))
    assert.ok(labels.includes('避免项'))
  }
  assert.match(cards[0].note, /本书更重考据细节/)
})
