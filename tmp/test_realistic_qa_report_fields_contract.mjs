import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_realistic_longform_flow_fixed.mjs', 'utf8')

assert.match(
  source,
  /function createEmptyQaFindings\(\)/,
  'realistic QA should define a stable qaFindings object for repeatable quality reports'
)

for (const field of [
  'missingChapterTitles',
  'beatPlanIssues',
  'wordCountIssues',
  'settingExtractionFailures',
  'memoryMissingChapters',
  'volumeTargetDrift',
  'aiToneSignals'
]) {
  assert.match(
    source,
    new RegExp(`${field}: \\[\\]`),
    `qaFindings should include ${field}`
  )
}

assert.match(
  source,
  /qaFindings: createEmptyQaFindings\(\)/,
  'report.generated should initialize qaFindings'
)

assert.match(
  source,
  /function formatQaFindingsReport\(\)/,
  'Markdown report should have a dedicated formatter for qaFindings'
)

const writeReportStart = source.indexOf('function writeReport()')
assert.ok(writeReportStart > -1, 'writeReport should exist')
const writeReportBlock = source.slice(writeReportStart)

assert.match(
  writeReportBlock,
  /## 专项质量指标/,
  'realistic QA markdown should include a dedicated quality metrics section'
)

for (const label of [
  '章名缺失',
  '小纲异常',
  '字数异常',
  '设定变更失败',
  '记忆缺失',
  '分卷目标偏离',
  'AI 腔指标'
]) {
  assert.match(
    source,
    new RegExp(label),
    `quality metrics report should include label: ${label}`
  )
}

assert.match(
  source,
  /type:\s*'volume_target_drift'/,
  'multi-chapter acceptance should classify volume target drift explicitly'
)

assert.match(
  source,
  /recordQaFinding\('aiToneSignals'/,
  'chapter audit or prose checks should record AI-tone signals into qaFindings'
)

assert.match(
  source,
  /\/chapters\/\$\{chapter\.id\}\/title/,
  'realistic QA title generation should use the metadata-only chapter title endpoint'
)

console.log('realistic QA report fields contract tests passed')
