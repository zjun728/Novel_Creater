import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

import {
  getAllWritingStyleStandards,
  getWritingStyleStandard,
  loadCustomWritingStyleStandards,
  normalizeReviewedStandardAsWritingStyleStandard,
  saveCustomWritingStyleStandard,
  formatWritingStyleStandardsForPrompt
} from '../frontend/src/data/writingStyleStandards.js'

function createMemoryStorage() {
  const data = new Map()
  return {
    getItem: key => data.has(key) ? data.get(key) : null,
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: key => data.delete(key)
  }
}

const reviewedStandard = {
  id: 'reviewed-local-sample-1',
  name: '本地真人样本写作标准',
  category: '本地样本 / 人工审核',
  status: 'draft',
  auditRequired: true,
  noDirectImitation: true,
  sourceCardIds: ['card-a', 'card-b'],
  guidance: {
    chapterEngine: '章节先进入具体处境，再让问题从行动里露出。',
    dialogueMethod: '对话带遮掩、停顿和言外之意。',
    characterMethod: '人物带自身目标和误判行动。',
    ensembleMethod: '配角有自己的小目标。',
    challengeMethod: '挑战由选择代价和资源限制构成。',
    emotionMethod: '情绪通过动作、迟疑和余波呈现。',
    informationMethod: '信息从证据、失败验证和关系变化释放。',
    proseRhythm: '段落长短有变化，中长段承载因果。',
    endingPreference: '结尾落在新证据或旧判断被推翻上。',
    avoid: '不得复刻原文、人物名、地名、专有名词。'
  }
}

test('reviewed sample standard can be normalized as an official custom writing standard', () => {
  const standard = normalizeReviewedStandardAsWritingStyleStandard(reviewedStandard)

  assert.equal(standard.id, reviewedStandard.id)
  assert.equal(standard.name, reviewedStandard.name)
  assert.equal(standard.custom, true)
  assert.equal(standard.noDirectImitation, true)
  assert.equal(standard.auditRequired, false)
  assert.match(standard.shortRule, /具体处境/)
  assert.deepEqual(standard.sourceCardIds, ['card-a', 'card-b'])
})

test('custom writing standards are persisted and can be selected by prompt formatter', () => {
  const storage = createMemoryStorage()
  const saved = saveCustomWritingStyleStandard(reviewedStandard, { storage })

  assert.equal(saved.status, 'active')
  assert.equal(saved.auditRequired, false)
  assert.equal(loadCustomWritingStyleStandards({ storage }).length, 1)
  assert.equal(getWritingStyleStandard('reviewed-local-sample-1', { storage }).name, reviewedStandard.name)
  assert.ok(getAllWritingStyleStandards({ storage }).some(item => item.id === reviewedStandard.id))

  const prompt = formatWritingStyleStandardsForPrompt({
    primaryStandard: reviewedStandard.id
  }, { storage })
  assert.match(prompt, /本地真人样本写作标准/)
  assert.match(prompt, /对话带遮掩/)
  assert.match(prompt, /不得复刻原文/)
})

test('creative bible options include custom writing standards instead of only built-ins', () => {
  const source = fs.readFileSync('frontend/src/components/bible/CreativeBible.vue', 'utf8')

  assert.match(source, /getAllWritingStyleStandards/)
  assert.doesNotMatch(source, /WRITING_STYLE_STANDARDS\.map/)
})

test('sample review UI exposes a manual confirm action before joining official standards', () => {
  const source = fs.readFileSync('frontend/src/components/settings/WritingSampleReview.vue', 'utf8')

  assert.match(source, /确认加入正式标准库/)
  assert.match(source, /saveCustomWritingStyleStandard/)
  assert.match(source, /正式标准库/)
})

