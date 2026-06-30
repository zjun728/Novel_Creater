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
assert.match(finalizationCommand, /let finalizationCompleted\s*=\s*false/)
assert.match(finalizationCommand, /let chapterFinalized\s*=\s*false/)
assert.match(finalizationCommand, /results\?\.errors \|\| \[\]/)
assert.match(finalizationCommand, /finalizationCompleted\s*=\s*true/)
assert.match(finalizationCommand, /keepPending:\s*chapterFinalized && !finalizationCompleted/)

assert.match(finalizationGuard, /keepPending/)
assert.match(finalizationGuard, /if \(!options\.keepPending\)/)

console.log('finalization postprocess contract tests passed')
