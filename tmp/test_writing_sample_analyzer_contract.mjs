import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { execFileSync } from 'node:child_process'

import {
  analyzeWritingSampleText,
  createWritingStandardCandidate,
  sampleTextWindows
} from '../frontend/src/data/writingSampleAnalyzer.js'
import { formatWritingFingerprintCardForPrompt } from '../frontend/src/data/writingFingerprints.js'

const sampleText = `
第一章 雨夜旧楼

雨下了半夜，楼道里有股旧木头泡开的味道。

林秋把伞收起来，没有立刻进门。门缝里漏出一点灯，像有人刚刚走过，又像只是电线接触不良。

“你回来得比我想的早。”屋里的人说。

林秋听出那声音里的沙哑，手指在门把上停了一下。他本来想问母亲在哪里，话到嘴边，变成了：“饭还热吗？”

屋里安静了一会儿。

第二章 木箱

木箱底部贴着半张旧车票，日期被水泡开，只剩下一个模糊的“七”。

老周蹲在门槛边抽烟，烟灰落在鞋面上。他说：“别问我是谁放的，我只管看门。”

林秋把车票夹进书里。那一页原本空着，现在多了一道浅浅的水痕。
`

test('sampleTextWindows extracts capped beginning middle and ending windows', () => {
  const windows = sampleTextWindows(sampleText.repeat(20), { windowSize: 180, maxWindows: 3 })

  assert.equal(windows.length, 3)
  assert.deepEqual(windows.map(item => item.position), ['opening', 'middle', 'ending'])
  assert.ok(windows.every(item => item.text.length <= 180))
})

test('analyzeWritingSampleText creates reusable fingerprint without source prose', () => {
  const card = analyzeWritingSampleText(sampleText, {
    sourceTitle: '雨夜样本',
    genreTags: ['现实悬疑']
  })
  const prompt = formatWritingFingerprintCardForPrompt(card)

  assert.equal(card.sourceTitle, '雨夜样本')
  assert.equal(card.noDirectImitation, true)
  assert.ok(card.metrics.chapterCount >= 2)
  assert.ok(card.metrics.dialogueParagraphRatio > 0)
  assert.match(card.chapterEntry, /具体场景|场景|人物/)
  assert.match(card.dialogueMethod, /停顿|遮掩|言外之意|身份/)
  assert.match(card.emotionMethod, /动作|迟疑|身体|细节/)
  assert.match(card.informationMethod, /物件|证据|动作|细节/)
  assert.match(card.proseRhythm, /段落|长短|节奏/)
  assert.doesNotMatch(prompt, /雨下了半夜/)
  assert.doesNotMatch(prompt, /林秋把伞收起来/)
  assert.equal((prompt.match(/不得复刻人物名/g) || []).length, 1)
  assert.equal(Object.prototype.hasOwnProperty.call(card, 'rawExcerpt'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(card, 'sourceText'), false)
})

test('createWritingStandardCandidate merges cards into an auditable standard candidate', () => {
  const cards = [
    analyzeWritingSampleText(sampleText, { sourceTitle: '样本一', genreTags: ['现实悬疑'] }),
    analyzeWritingSampleText(sampleText.replaceAll('林秋', '陈青'), { sourceTitle: '样本二', genreTags: ['现实悬疑'] })
  ]
  const standard = createWritingStandardCandidate(cards, {
    id: 'local-realistic-suspense',
    name: '本地现实悬疑样本标准',
    category: '本地样本 / 现实悬疑'
  })

  assert.equal(standard.id, 'local-realistic-suspense')
  assert.equal(standard.sourceCardIds.length, 2)
  assert.match(standard.guidance.chapterEngine, /章节/)
  assert.match(standard.guidance.dialogueMethod, /对话/)
  assert.doesNotMatch(standard.guidance.dialogueMethod, /对话方式：对话方式/)
  assert.match(standard.guidance.avoid, /复刻|原句|专有名词/)
  assert.doesNotMatch(JSON.stringify(standard), /雨下了半夜/)
})

test('sample analyzer CLI writes JSON and Markdown reports from a local directory', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'novel-sample-'))
  const outputDir = path.join(root, 'out')
  fs.writeFileSync(path.join(root, '样本A.txt'), sampleText.repeat(3), 'utf8')
  fs.writeFileSync(path.join(root, '样本B.txt'), sampleText.replaceAll('林秋', '陈青').repeat(3), 'utf8')

  execFileSync('node', [
    'tmp/analyze_writing_samples.mjs',
    '--input', root,
    '--output', outputDir,
    '--limit', '2',
    '--standard-id', 'local-test',
    '--standard-name', '本地测试标准'
  ], { cwd: process.cwd(), stdio: 'pipe' })

  const jsonPath = path.join(outputDir, 'writing-sample-analysis.json')
  const mdPath = path.join(outputDir, 'writing-sample-analysis.md')
  assert.ok(fs.existsSync(jsonPath))
  assert.ok(fs.existsSync(mdPath))

  const data = JSON.parse(fs.readFileSync(jsonPath, 'utf8'))
  const md = fs.readFileSync(mdPath, 'utf8')
  assert.equal(data.cards.length, 2)
  assert.equal(data.standardCandidate.id, 'local-test')
  assert.match(md, /写作样本分析报告/)
  assert.match(md, /禁止复刻/)
  assert.doesNotMatch(md, /林秋把伞收起来/)
})
