import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

const auditStart = source.indexOf('async function auditChapter(')
const compactRetryIndex = source.indexOf('审稿紧凑重试', auditStart)
const ultraRetryIndex = source.indexOf('审稿最终极简重试', auditStart)
const auditFailIndex = source.indexOf('report.generated.auditFailures += 1', auditStart)

assert.ok(auditStart > -1, 'auditChapter should exist')
assert.ok(compactRetryIndex > auditStart, 'audit should have a compact retry before failing')
assert.ok(ultraRetryIndex > compactRetryIndex, 'audit should have an ultra-compact retry after compact retry')
assert.ok(auditFailIndex > ultraRetryIndex, 'audit should only fail after ultra-compact retry')
assert.match(
  source.slice(ultraRetryIndex, auditFailIndex),
  /只保留 0-1 个/,
  'ultra-compact retry should force at most one issue'
)
assert.match(
  source.slice(ultraRetryIndex, auditFailIndex),
  /每个字段少于 50 字/,
  'ultra-compact retry should keep fields short enough to avoid truncation'
)

console.log('realistic QA audit ultra retry contract tests passed')
