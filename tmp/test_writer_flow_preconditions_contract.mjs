import fs from 'node:fs'
import assert from 'node:assert/strict'

import {
  checkCurrentChapterWritable,
  checkPreviousChapterFinalized,
  checkPendingSettingChanges,
  checkPendingStoryMemory,
  checkCorrectionTaskBlocker,
  checkChapterHardWordMinimum,
  firstBlockingPrecondition
} from '../frontend/src/application/writer-flow/preconditions.js'

function assertOk(result) {
  assert.equal(result.ok, true)
  assert.equal(result.code, undefined)
}

function assertBlock(result, code) {
  assert.equal(result.ok, false)
  assert.equal(result.code, code)
  assert.equal(typeof result.messageKey, 'string')
  assert.ok(result.messageKey.length > 0)
  assert.equal(typeof result.severity, 'string')
  assert.equal(typeof result.details, 'object')
}

assertOk(checkCurrentChapterWritable({ currentChapterFinalized: false }))
assertBlock(checkCurrentChapterWritable({ currentChapterFinalized: true }), 'currentChapterFinalized')

assertOk(checkPreviousChapterFinalized({ chapterNum: 1, previousChapter: null }))
assertOk(checkPreviousChapterFinalized({
  chapterNum: 8,
  previousChapter: { chapterNum: 7, status: 'final', finalVersionId: 'v7' }
}))
assertBlock(checkPreviousChapterFinalized({
  chapterNum: 8,
  previousChapter: { chapterNum: 7, status: 'drafting', finalVersionId: '' }
}), 'previousChapterNotFinalized')
assertBlock(checkPreviousChapterFinalized({
  chapterNum: 8,
  previousChapter: null
}), 'previousChapterMissing')
assertBlock(checkPreviousChapterFinalized({
  chapterNum: 8,
  previousChapter: { chapter_num: 7, status: 'final', final_version_id: 'v7' },
  previousFinalizationPending: { chapterNum: 7 }
}), 'previousFinalizationPending')

assertOk(checkPendingSettingChanges({ pendingSettingChanges: [] }))
assertBlock(checkPendingSettingChanges({ pendingSettingChanges: [{ id: 's1' }] }), 'pendingSettingChanges')
assertBlock(checkPendingSettingChanges({ pendingSettingCount: 2 }), 'pendingSettingChanges')

assertOk(checkPendingStoryMemory({ pendingCanonFacts: [] }))
assertBlock(checkPendingStoryMemory({ pendingCanonFacts: [{ id: 'f1' }] }), 'pendingStoryMemory')
assertBlock(checkPendingStoryMemory({ pendingMemoryCount: 3 }), 'pendingStoryMemory')

assertOk(checkCorrectionTaskBlocker({ blockers: [], softTasks: [] }))
const correctionBlocker = checkCorrectionTaskBlocker({
  blockers: [{ id: 'task-1', severity: 'major' }],
  softTasks: [{ id: 'task-2' }]
})
assertBlock(correctionBlocker, 'correctionTaskBlocker')
assert.equal(correctionBlocker.details.blockerCount, 1)
assert.equal(correctionBlocker.details.softTaskCount, 1)

assertOk(checkChapterHardWordMinimum({ assessment: { level: 'ok', count: 2500 }, wordTarget: { hardMin: 1800 } }))
const hardWordBlocker = checkChapterHardWordMinimum({
  assessment: { level: 'hard_under', count: 1200 },
  wordTarget: { hardMin: 1800 }
})
assertBlock(hardWordBlocker, 'chapterBelowHardMin')
assert.equal(hardWordBlocker.details.count, 1200)
assert.equal(hardWordBlocker.details.hardMin, 1800)

const first = firstBlockingPrecondition([
  { ok: true },
  { ok: false, code: 'x', messageKey: 'x', severity: 'warning', details: {} },
  { ok: false, code: 'y', messageKey: 'y', severity: 'warning', details: {} }
])
assert.equal(first.code, 'x')
assert.equal(firstBlockingPrecondition([{ ok: true }, { ok: true }]), null)

const moduleSource = fs.readFileSync('frontend/src/application/writer-flow/preconditions.js', 'utf8')
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
  assert.equal(pattern.test(moduleSource), false, `preconditions module must stay pure: ${pattern}`)
}

const writerViewSource = fs.readFileSync('frontend/src/views/WriterView.vue', 'utf8')
assert.match(writerViewSource, /@\/application\/writer-flow\/preconditions/)
for (const name of [
  'ensureNoPendingSettingChanges',
  'ensurePreviousChapterFinalized',
  'performFinalize',
  'generateChapterFromPlan'
]) {
  assert.match(writerViewSource, new RegExp(`function ${name}|async function ${name}`), `${name} must remain present`)
}
assert.match(writerViewSource, /checkCurrentChapterWritable/)
assert.match(writerViewSource, /checkPreviousChapterFinalized/)
assert.match(writerViewSource, /checkPendingSettingChanges/)
assert.match(writerViewSource, /checkPendingStoryMemory/)
assert.match(writerViewSource, /checkCorrectionTaskBlocker/)

const diffNameOnly = (path) => {
  try {
    return fs.statSync(path).mtimeMs
  } catch {
    return 0
  }
}
assert.ok(diffNameOnly('frontend/src/stores/writerStore.js') > 0)

console.log('writer flow preconditions contract passed')
