import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const ROOT = process.cwd()

function read(relPath) {
  return fs.readFileSync(path.join(ROOT, relPath), 'utf8')
}

function assertFile(relPath) {
  assert.ok(fs.existsSync(path.join(ROOT, relPath)), `missing boundary file: ${relPath}`)
}

const gitignore = read('.gitignore')
const writerView = read('frontend/src/views/WriterView.vue')
const contextSession = read('frontend/src/application/writer-flow/context-session.js')

for (const relPath of [
  'frontend/src/application/writer-flow/beat-plan-command.js',
  'frontend/src/application/writer-flow/chapter-title-command.js',
  'frontend/src/application/writer-flow/context-session.js',
  'frontend/src/application/writer-flow/draft-generation-command.js',
  'frontend/src/application/writer-flow/draft-repair-pipeline.js',
  'frontend/src/application/writer-flow/finalization-command.js',
  'frontend/src/application/writer-flow/finalization-marker-action.js',
  'frontend/src/application/writer-flow/preconditions.js',
  'frontend/src/application/writer-flow/save-beat-plan-command.js',
  'frontend/src/application/writer-flow/version-creation-command.js',
  'frontend/src/domain/chapter-draft/ai-content.js',
  'frontend/src/domain/chapter-title/index.js',
  'frontend/src/domain/chapter-title/policy.js',
  'frontend/src/domain/chapter-title/ranker.js',
  'frontend/src/domain/chapter-title/source-extractor.js'
]) {
  assertFile(relPath)
}

for (const ignored of [
  'tmp/realistic-flow-qa/*',
  '!tmp/realistic-flow-qa/README.md',
  'tmp/architecture-governance/',
  'tmp/live-qa-contract-output/',
  'tmp/playwright-run/'
]) {
  assert.match(gitignore, new RegExp(ignored.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), `.gitignore must keep runtime artifact rule: ${ignored}`)
}

assert.match(writerView, /@\/application\/writer-flow\/context-session/)
assert.match(writerView, /@\/application\/writer-flow\/beat-plan-command/)
assert.match(writerView, /@\/application\/writer-flow\/chapter-title-command/)
assert.match(writerView, /@\/application\/writer-flow\/draft-generation-command/)
assert.match(writerView, /@\/application\/writer-flow\/finalization-command/)
assert.match(writerView, /@\/application\/writer-flow\/finalization-marker-action/)
assert.match(writerView, /@\/application\/writer-flow\/preconditions/)
assert.match(writerView, /@\/application\/writer-flow\/save-beat-plan-command/)
assert.match(writerView, /@\/application\/writer-flow\/version-creation-command/)

for (const forbidden of [
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
]) {
  assert.equal(forbidden.test(contextSession), false, `context-session must remain adapter-pure: ${forbidden}`)
}

assert.doesNotMatch(
  writerView,
  /tmp\/architecture-governance|latest-writer-flow-boundary-audit/,
  'WriterView must not depend on architecture audit artifacts'
)

console.log('writer flow boundary source contract passed')
