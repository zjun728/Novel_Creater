import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const correctionTaskStore = readFileSync('frontend/src/stores/correctionTaskStore.js', 'utf8')

assert.match(
  writerView,
  /const readonlyAuditResult = ref\(null\)/,
  'finalized chapter audits should use an isolated readonly result instead of the global editable audit result'
)
assert.match(
  writerView,
  /const auditModalReport = computed/,
  'audit modal should read through a dedicated report computed value'
)
assert.match(
  writerView,
  /hasAuditRevisionIssues[\s\S]*!currentChapterFinalized\.value/,
  'finalized chapter audit issues must not open the right-side revision panel'
)
assert.match(
  writerView,
  /currentChapterFinalized\.value \? '本章审稿（只读）' : '本章审稿'/,
  'finalized chapter audit entry should remain visible as a readonly chapter audit button'
)
assert.match(
  writerView,
  /if \(currentChapterFinalized\.value\)[\s\S]*readonlyAuditResult\.value = report[\s\S]*memoryStore\.lastAuditResult = null/,
  'finalized chapter audits should clear global lastAuditResult after storing the readonly report'
)
assert.doesNotMatch(
  writerView,
  /已定稿，仅可分卷\/全局软纠偏/,
  'finalized chapter audit should not present a correction-entry message'
)

const buildTasksBlock = correctionTaskStore.match(/function buildTasksFromChapterAudit\(chapterNum, report, options = \{\}\) \{[\s\S]*?\n  \}/)?.[0] || ''
assert.match(
  buildTasksBlock,
  /if \(options\.finalized\) return \[\]/,
  'finalized chapter audit reports must not create correction tasks'
)
assert.doesNotMatch(
  buildTasksBlock,
  /sourceFinalized:\s*finalized/,
  'chapter audit task builder should only create hard tasks for editable chapters'
)

console.log('finalized audit readonly contract passed')
