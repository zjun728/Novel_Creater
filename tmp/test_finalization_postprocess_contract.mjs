import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const memoryStore = readFileSync('frontend/src/stores/memoryStore.js', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const finalizationCommand = readFileSync('frontend/src/application/writer-flow/finalization-command.js', 'utf8')
const finalizationGuard = readFileSync('frontend/src/utils/finalizationGuard.js', 'utf8')

function extractFunctionBlock(source, signature) {
  const start = source.indexOf(signature)
  assert.notEqual(start, -1, `missing function signature: ${signature}`)
  const bodyStart = source.indexOf('{', start)
  assert.notEqual(bodyStart, -1, `missing function body: ${signature}`)
  let depth = 0
  for (let index = bodyStart; index < source.length; index += 1) {
    const char = source[index]
    if (char === '{') depth += 1
    if (char === '}') {
      depth -= 1
      if (depth === 0) return source.slice(start, index + 1)
    }
  }
  assert.fail(`unterminated function body: ${signature}`)
}

const processBlock = memoryStore.match(/async function processChapterFinalization\([\s\S]*?\n  \}/)?.[0] || ''
assert.match(processBlock, /errors:\s*\[\]/)
assert.match(processBlock, /recordFinalizationStepError/)
assert.match(processBlock, /requiredFailures/)

const performBlock = extractFunctionBlock(writerView, 'async function performFinalize(version)')
assert.match(performBlock, /runFinalizeChapterCommand/)
assert.match(performBlock, /saveDurableFinalizationMarker/)
assert.match(performBlock, /upsertDurableFinalizationMarker/)
assert.match(finalizationCommand, /let finalizationCompleted\s*=\s*false/)
assert.match(finalizationCommand, /let chapterFinalized\s*=\s*false/)
assert.match(finalizationCommand, /results\?\.errors \|\| \[\]/)
assert.match(finalizationCommand, /finalizationCompleted\s*=\s*true/)
assert.match(finalizationCommand, /keepPending:\s*chapterFinalized && !finalizationCompleted/)
assert.match(finalizationCommand, /const saveDurableFinalizationMarker = input\.saveDurableFinalizationMarker/)
assert.match(finalizationCommand, /const upsertDurableFinalizationMarker = input\.upsertDurableFinalizationMarker/)
assert.match(finalizationCommand, /await finalizeVersion\(version,\s*finalizationProvenance\)/)
assert.match(finalizationCommand, /processChapterFinalization\(projectId,\s*version\?\.content \|\| '',\s*chapterNum,\s*finalizationProvenance\)/)
assert.match(finalizationCommand, /await markFinalizationFailure\(projectId,\s*chapterNum,\s*normalized,\s*failedProvenance\)/)
assert.match(finalizationCommand, /await invokeOptional\(saveDurableFinalizationMarker,\s*chapterNum,\s*\{[\s\S]*commitStatus:\s*'failed_after_chapter_commit'[\s\S]*runId:\s*finalizationRun\.runId[\s\S]*finalizationId:\s*finalizationRun\.finalizationId[\s\S]*\}\)/)
assert.match(finalizationCommand, /if \(savedDurableMarker\) await invokeOptional\(upsertDurableFinalizationMarker,\s*savedDurableMarker\)/)

const retryBlock = writerView.match(/async function retryFinalizationPostprocess\(targetChapterNum\) \{[\s\S]*?\n\}/)?.[0] || ''
assert.match(retryBlock, /memoryStore\.processChapterFinalization\(projectId\.value,\s*version\.content,\s*num,\s*\{[\s\S]*sourceVersionId:\s*version\.id[\s\S]*runId:\s*finalizationRun\.runId[\s\S]*finalizationId:\s*finalizationRun\.finalizationId[\s\S]*\}\)/)
assert.match(retryBlock, /sourceVersionId:\s*retryVersionId,[\s\S]*runId:\s*finalizationRun\.runId,[\s\S]*finalizationId:\s*finalizationRun\.finalizationId/)

assert.match(finalizationGuard, /keepPending/)
assert.match(finalizationGuard, /DURABLE_PENDING_STATUSES/)
assert.match(finalizationGuard, /failed_after_chapter_commit/)
assert.match(finalizationGuard, /if \(options\.keepPending\)/)
assert.match(finalizationGuard, /markChapterFinalizationPending\(projectId, chapterNum/)

console.log('finalization postprocess contract tests passed')
