import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const script = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

assert.match(
  script,
  /AUDIT_GATE: chapter/,
  'realistic QA should stop before finalize when chapter audit cannot be parsed'
)

const runChapterStart = script.indexOf('async function runChapter(')
const auditFailedIndex = script.indexOf('if (audit.auditFailed)', runChapterStart)
const auditGateIndex = script.indexOf("throw auditGateError", auditFailedIndex)
const reviseIndex = script.indexOf('const revisedContent = await reviseChapter', runChapterStart)
const finalizeIndex = script.indexOf('await finalizeChapter(project, chapter, finalVersion, summary)', runChapterStart)

assert.ok(runChapterStart > -1, 'runChapter should exist')
assert.ok(auditFailedIndex > runChapterStart, 'runChapter should explicitly handle audit failures')
assert.ok(auditGateIndex > auditFailedIndex, 'audit failure should throw a gate error')
assert.ok(reviseIndex > auditGateIndex, 'audit gate should run before revision')
assert.ok(finalizeIndex > auditGateIndex, 'audit gate should run before finalize')

console.log('realistic QA audit gate contract tests passed')
