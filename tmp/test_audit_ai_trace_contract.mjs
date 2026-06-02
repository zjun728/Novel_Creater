import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const auditPrompt = readFileSync('frontend/src/prompts/audit.js', 'utf8')
const memoryStore = readFileSync('frontend/src/stores/memoryStore.js', 'utf8')
const auditLabels = readFileSync('frontend/src/utils/auditLabels.js', 'utf8')

for (const type of [
  'template_ending',
  'surface_emotion',
  'tool_character',
  'info_dump',
  'cliche_imagery'
]) {
  assert.match(
    auditPrompt,
    new RegExp(type),
    `audit prompt should allow issue type ${type}`
  )
  assert.match(
    memoryStore,
    new RegExp(type),
    `audit normalizer should preserve issue type ${type}`
  )
  assert.match(
    auditLabels,
    new RegExp(`${type}:\\s*'[^']+'`),
    `audit UI labels should render ${type} in Chinese`
  )
}

for (const phrase of [
  '章节结尾模板化',
  '表层情绪',
  '工具人',
  '信息倾倒',
  '套话意象'
]) {
  assert.match(
    auditPrompt,
    new RegExp(phrase),
    `audit prompt should explicitly check ${phrase}`
  )
}

assert.match(
  auditPrompt,
  /location 必须从正文中逐字复制原文/,
  'audit prompt should keep exact quote requirements for local replacements'
)

console.log('audit AI trace contract tests passed')
