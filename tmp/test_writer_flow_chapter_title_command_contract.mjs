import fs from 'node:fs'
import assert from 'node:assert/strict'

import {
  normalizeManualChapterTitle,
  validateManualChapterTitle,
  runGenerateChapterTitleCommand,
  runSaveManualChapterTitleCommand
} from '../frontend/src/application/writer-flow/chapter-title-command.js'

function assertBlock(result, code) {
  assert.equal(result.ok, false)
  assert.equal(result.code, code)
  assert.equal(typeof result.messageKey, 'string')
  assert.equal(typeof result.details, 'object')
}

assert.equal(normalizeManualChapterTitle('  东城   染坊  '), '东城 染坊')

let generateCalls = []
let result = await runGenerateChapterTitleCommand({
  projectId: 'p1',
  chapter: null,
  chapterNum: 8,
  content: '正文',
  generateDefaultChapterTitle: (...args) => generateCalls.push(args)
})
assertBlock(result, 'chapterNotReady')
assert.equal(generateCalls.length, 0)

result = await runGenerateChapterTitleCommand({
  projectId: 'p1',
  chapter: { id: 'c8' },
  chapterNum: 8,
  content: '   ',
  generateDefaultChapterTitle: (...args) => generateCalls.push(args)
})
assertBlock(result, 'emptyContent')
assert.equal(generateCalls.length, 0)

result = await runGenerateChapterTitleCommand({
  projectId: 'p1',
  chapter: { id: 'c8' },
  chapterNum: 8,
  content: '章节正文',
  chapterGoal: '去染坊找证据',
  beatPlan: '进入地下仓库',
  generateDefaultChapterTitle: async (...args) => {
    generateCalls.push(args)
    return '铁箱账本'
  }
})
assert.equal(result.ok, true)
assert.equal(result.title, '铁箱账本')
assert.deepEqual(generateCalls.at(-1), [
  'p1',
  { id: 'c8' },
  8,
  '章节正文',
  { chapterGoal: '去染坊找证据', beatPlan: '进入地下仓库' },
  null,
  { force: true }
])

result = await runGenerateChapterTitleCommand({
  projectId: 'p1',
  chapter: { id: 'c8' },
  chapterNum: 8,
  content: '章节正文',
  generateDefaultChapterTitle: async () => ''
})
assertBlock(result, 'noQualifiedTitle')
assert.equal(result.openEditor, true)

let updateCalls = []
result = await runSaveManualChapterTitleCommand({
  projectId: 'p1',
  chapter: null,
  chapterNum: 8,
  draftTitle: '章名',
  assessTitle: () => ({ titleValid: true }),
  updateChapterTitle: (...args) => updateCalls.push(args)
})
assertBlock(result, 'chapterNotReady')
assert.equal(updateCalls.length, 0)

assertBlock(validateManualChapterTitle({
  chapter: { id: 'c8' },
  chapterNum: 8,
  title: '   ',
  assessTitle: () => ({ titleValid: true })
}), 'emptyTitle')

assertBlock(validateManualChapterTitle({
  chapter: { id: 'c8' },
  chapterNum: 8,
  title: '第一行\n第二行',
  assessTitle: () => ({ titleValid: true })
}), 'invalidManualTitleShape')

assertBlock(validateManualChapterTitle({
  chapter: { id: 'c8' },
  chapterNum: 8,
  title: '一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一',
  assessTitle: () => ({ titleValid: true })
}), 'invalidManualTitleShape')

result = await runSaveManualChapterTitleCommand({
  projectId: 'p1',
  chapter: { id: 'c8' },
  chapterNum: 8,
  draftTitle: '就是这里',
  assessTitle: () => ({ titleValid: false, titleInvalidReason: 'location_pointer_fragment' }),
  updateChapterTitle: (...args) => updateCalls.push(args)
})
assertBlock(result, 'invalidTitlePolicy')
assert.equal(result.details.reason, 'location_pointer_fragment')

result = await runSaveManualChapterTitleCommand({
  projectId: 'p1',
  chapter: { id: 'c8' },
  chapterNum: 8,
  draftTitle: '  东城   染坊  ',
  assessTitle: (title, context) => {
    assert.equal(title, '东城 染坊')
    assert.deepEqual(context, { chapterNum: 8 })
    return { titleValid: true }
  },
  updateChapterTitle: async (...args) => {
    updateCalls.push(args)
    return { title: args[2] }
  }
})
assert.equal(result.ok, true)
assert.equal(result.title, '东城 染坊')
assert.deepEqual(updateCalls.at(-1), ['p1', 'c8', '东城 染坊'])

const moduleSource = fs.readFileSync('frontend/src/application/writer-flow/chapter-title-command.js', 'utf8')
const forbiddenPurePatterns = [
  /from ['"]vue['"]/,
  /pinia/,
  /stores\//,
  /api\//,
  /router/,
  /naive/i,
  /prompts\//,
  /chatCompletion/,
  /localStorage|sessionStorage/,
  /\bwindow\b|\bdocument\b/
]
for (const pattern of forbiddenPurePatterns) {
  assert.equal(pattern.test(moduleSource), false, `chapter title command module must stay adapter-pure: ${pattern}`)
}

const writerViewSource = fs.readFileSync('frontend/src/views/WriterView.vue', 'utf8')
assert.match(writerViewSource, /@\/application\/writer-flow\/chapter-title-command/)
assert.match(writerViewSource, /async function handleGenerateChapterTitle/)
assert.match(writerViewSource, /async function handleSaveManualChapterTitle/)
assert.match(writerViewSource, /生成章名/)
assert.match(writerViewSource, /保存章名/)
assert.match(writerViewSource, /runGenerateChapterTitleCommand/)
assert.match(writerViewSource, /runSaveManualChapterTitleCommand/)
assert.doesNotMatch(writerViewSource, /createdCleanProject: !EXISTING_PROJECT_ID/)

console.log('writer flow chapter title command contract passed')
