import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const chapterVersionList = readFileSync('frontend/src/components/writer/ChapterVersionList.vue', 'utf8')

assert.match(writerView, /beginChapterFinalizationRun/)
assert.match(writerView, /endChapterFinalizationRun/)

const performFinalizeBlock = writerView.match(/async function performFinalize\(version\) \{[\s\S]*?\n\}/)?.[0] || ''
assert.match(performFinalizeBlock, /beginChapterFinalizationRun/)
assert.match(performFinalizeBlock, /endChapterFinalizationRun/)
assert.match(performFinalizeBlock, /memoryProcessing\.value\s*=\s*true[\s\S]*writerStore\.finalizeVersion/)

assert.match(writerView, /:disabled="auditRunning \|\| auditRevisionGenerating \|\| finalizationActionBusy"/)
assert.match(writerView, /auditButtonText/, 'writer desk should distinguish finalized chapter audit as readonly review')
assert.match(writerView, /finalizedVersionId/, 'writer view should derive finalized chapter readonly state')
assert.match(writerView, /readonlyAuditResult/, 'finalized chapter audits should be stored as readonly review data')

const finalizePopconfirmBlock = chapterVersionList.match(/<n-popconfirm\s+v-else-if="!hasFinalVersion"[\s\S]*?<\/n-popconfirm>/)?.[0] || ''
assert.match(finalizePopconfirmBlock, /@positive-click="emit\('finalize', version\)"/)
assert.doesNotMatch(
  finalizePopconfirmBlock,
  /@click\.stop/,
  'finalize popconfirm trigger must not stop its own click event, otherwise the confirmation never opens'
)
assert.match(
  chapterVersionList,
  /<div class="flex justify-end gap-1 mt-1"\s+@click\.stop>/,
  'version action container should stop card load propagation instead of popconfirm trigger buttons'
)

console.log('writer finalization lock contract tests passed')
