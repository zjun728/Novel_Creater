import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

import {
  approveWritingSampleStandard,
  normalizeWritingSampleReport,
  summarizeWritingSampleReport
} from '../frontend/src/data/writingSampleReview.js'

const report = {
  fileCount: 2,
  cards: [
    {
      id: 'card-a',
      sourceTitle: '样本A',
      sourceMode: 'local_sample',
      noDirectImitation: true,
      genreTags: ['修仙'],
      chapterEntry: '先从具体场景进入。',
      chapterExit: '落在新证据上。',
      dialogueMethod: '对话带遮掩和停顿。',
      characterMethod: '人物有自身目标。',
      ensembleMethod: '配角有自己的小目标。',
      challengeMethod: '任务由代价构成。',
      emotionMethod: '情绪通过动作呈现。',
      informationMethod: '信息从证据释放。',
      proseRhythm: '段落长短有变化。',
      avoidPatterns: ['不得复刻人物名']
    },
    {
      id: 'card-b',
      sourceTitle: '样本B',
      sourceMode: 'local_sample',
      noDirectImitation: true,
      genreTags: ['悬疑'],
      chapterEntry: '从问题和证据进入。',
      dialogueMethod: '对话不替作者解释设定。',
      characterMethod: '人物带误判行动。',
      ensembleMethod: '群像有利益差。',
      challengeMethod: '挑战有资源限制。',
      emotionMethod: '情绪有余波。',
      informationMethod: '信息从失败验证释放。',
      proseRhythm: '中长段承载因果。',
      avoidPatterns: ['不得复制原句']
    }
  ],
  standardCandidate: {
    id: 'old',
    name: '旧候选',
    status: 'draft',
    auditRequired: true
  }
}

test('normalizeWritingSampleReport keeps only auditable cards and no direct-imitation cards', () => {
  const normalized = normalizeWritingSampleReport({
    cards: [
      ...report.cards,
      { id: 'unsafe', sourceTitle: '危险卡', noDirectImitation: false },
      { id: '', sourceTitle: '无ID', noDirectImitation: true }
    ]
  })

  assert.equal(normalized.cards.length, 2)
  assert.deepEqual(normalized.cards.map(card => card.id), ['card-a', 'card-b'])
  assert.equal(normalized.standardCandidate.auditRequired, true)
})

test('approveWritingSampleStandard only merges selected reviewed cards into a draft standard', () => {
  const approved = approveWritingSampleStandard(report, ['card-a'], {
    id: 'approved-standard',
    name: '本地修仙样本标准',
    category: '本地样本 / 修仙'
  })

  assert.equal(approved.id, 'approved-standard')
  assert.equal(approved.name, '本地修仙样本标准')
  assert.equal(approved.status, 'draft')
  assert.equal(approved.auditRequired, true)
  assert.equal(approved.noDirectImitation, true)
  assert.deepEqual(approved.sourceCardIds, ['card-a'])
  assert.match(approved.guidance.chapterEngine, /章节进入|具体场景/)
  assert.doesNotMatch(JSON.stringify(approved), /样本B/)
})

test('summarizeWritingSampleReport exposes counts for frontend review cards', () => {
  const summary = summarizeWritingSampleReport(report)

  assert.equal(summary.cardCount, 2)
  assert.equal(summary.fileCount, 2)
  assert.equal(summary.auditReadyCount, 2)
  assert.deepEqual(summary.genreTags, ['修仙', '悬疑'])
})

test('settings page exposes writing sample review entry and local report is bundled safely', () => {
  const settings = fs.readFileSync('frontend/src/views/SettingsView.vue', 'utf8')
  const component = fs.readFileSync('frontend/src/components/settings/WritingSampleReview.vue', 'utf8')
  const reportJson = JSON.parse(fs.readFileSync('frontend/src/data/localWritingSampleReport.json', 'utf8'))

  assert.match(settings, /WritingSampleReview/)
  assert.match(component, /写作样本审核/)
  assert.match(component, /合并为待审核标准/)
  assert.ok(reportJson.cards.length >= 1)
  assert.equal(['rawExcerpt', 'sourceText'].some(key => Object.hasOwn(reportJson.cards[0], key)), false)
})
