import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildDraftPrompt } from '../frontend/src/prompts/chapterDraftPrompt.js'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function fileUrl(relPath) {
  return new URL(`file://${path.join(ROOT, relPath).replace(/\\/g, '/')}`).href
}

const standards = await import(`${fileUrl('frontend/src/data/writingStyleStandards.js')}?contract=${Date.now()}`)

assert.equal(typeof standards.resolveActiveWritingStandardLowDose, 'function')
assert.equal(typeof standards.formatActiveWritingStandardLowDoseForPrompt, 'function')

const activeSystem = {
  id: 'system-dialogue-realism',
  name: '对话真实感增强',
  category: '对话',
  status: 'active',
  sourceKind: 'system',
  noDirectImitation: true,
  principles: ['先让角色带着自己的算盘说话，不要句句替剧情服务。', '第二条不应进正文。'],
  originalMicroDemo: '他把药放到桌边，说你爱用不用。人却没走，手指还压着油纸包。',
  antiAiReminder: '不要把关心写成说明书，也不要让角色直接报情绪。',
  guidance: {
    dialogueMethod: '这条完整 guidance 不应整块进正文。',
    characterMethod: '这条也不应整块进正文。'
  },
  experienceCardSnapshots: [{ id: 'sys-card-1', title: '嘴硬关心' }]
}
const inactiveUser = {
  id: 'user-inactive',
  name: '未激活标准',
  status: 'inactive',
  sourceKind: 'user',
  noDirectImitation: true,
  principles: ['未激活原则不得进入。'],
  originalMicroDemo: '未激活微示范不得进入。',
  antiAiReminder: '未激活提醒不得进入。'
}

const resolved = standards.resolveActiveWritingStandardLowDose([inactiveUser, activeSystem])
assert.deepEqual(Object.keys(resolved).sort(), ['antiAiReminder', 'callStrength', 'originalMicroDemo', 'principle', 'standardId', 'standardName'].sort())
assert.equal(resolved.standardId, 'system-dialogue-realism')
assert.equal(resolved.principle, activeSystem.principles[0])
assert.equal(resolved.originalMicroDemo, activeSystem.originalMicroDemo)
assert.equal(resolved.antiAiReminder, activeSystem.antiAiReminder)

const promptSection = standards.formatActiveWritingStandardLowDoseForPrompt([inactiveUser, activeSystem])
assert.match(promptSection, /正式写作标准低量调用/)
assert.match(promptSection, /写法原则/)
assert.match(promptSection, /原创微示范/)
assert.match(promptSection, /反 AI 提醒/)
assert.ok(!promptSection.includes('未激活'), 'inactive formal standards must not enter prompt')
assert.ok(!promptSection.includes('第二条不应进正文'), 'prompt should include at most one principle')
assert.ok(!promptSection.includes('完整 guidance'), 'prompt must not dump full standard guidance')

assert.equal(standards.formatActiveWritingStandardLowDoseForPrompt([inactiveUser]), '', 'no active formal standard means no sample-library prompt injection')

const directCardPrompt = buildDraftPrompt({
  chapterNum: 8,
  sampleMicroDemoCard: {
    promptReadiness: 'prompt-ready-low-dose',
    cardTitle: '经验卡直连',
    promptInjectionSafeVersion: '这条不能进正文 prompt。',
    originalMicroDemo: '这段经验卡微示范不能进正文 prompt。',
    antiSkeletonEffect: '这条提醒也不能进正文 prompt。'
  }
})
assert.ok(!directCardPrompt.includes('原创微示范低量参考'), 'experience cards must not directly create draft prompt sections')
assert.ok(!directCardPrompt.includes('这段经验卡微示范不能进正文 prompt'), 'direct sampleMicroDemoCard content must be ignored')

const formalPrompt = buildDraftPrompt({
  chapterNum: 8,
  activeWritingStandards: [activeSystem],
  beatPlan: { chapterEvent: '两人在门口争执，但都没有把真正担心说出口。' }
})
assert.match(formalPrompt, /正式写作标准低量调用/)
assert.match(formalPrompt, /先让角色带着自己的算盘说话/)
assert.match(formalPrompt, /他把药放到桌边/)
assert.match(formalPrompt, /不要把关心写成说明书/)

const source = fs.readFileSync(path.join(ROOT, 'frontend/src/prompts/chapterDraftPrompt.js'), 'utf8')
assert.ok(!source.includes('sampleMicroDemoCards'), 'draft prompt source must not import sample micro demo card module')

console.log('writing standard prompt boundary contract passed')
