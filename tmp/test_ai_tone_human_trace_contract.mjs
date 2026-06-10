import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const auditPrompt = readFileSync('frontend/src/prompts/audit.js', 'utf8')
const rewritePrompt = readFileSync('frontend/src/prompts/rewrite.js', 'utf8')
const chapterPrompt = readFileSync('frontend/src/prompts/chapter.js', 'utf8')
const auditLabels = readFileSync('frontend/src/utils/auditLabels.js', 'utf8')

for (const type of [
  'sensory_checklist',
  'decorative_number',
  'emotion_label',
  'overfunctional_density',
  'skipped_loss'
]) {
  assert.match(
    auditPrompt,
    new RegExp(type),
    `audit prompt should allow issue type ${type}`
  )
  assert.match(
    auditLabels,
    new RegExp(`${type}:\\s*'[^']+'`),
    `audit UI labels should render ${type} in Chinese`
  )
}

for (const phrase of [
  '感官打勾',
  '无效数字',
  '情绪贴标签',
  '功能过满',
  '失去过程跳过'
]) {
  assert.match(
    auditPrompt,
    new RegExp(phrase),
    `audit prompt should explicitly check ${phrase}`
  )
}

assert.doesNotMatch(
  auditPrompt,
  /超过\s*2\s*次必须提出问题/,
  'audit prompt should not treat a single contrast sentence count as a hard AI-tone diagnosis'
)

assert.match(
  auditPrompt,
  /综合判断/,
  'audit prompt should judge AI tone by combined narrative symptoms'
)

for (const phrase of [
  '不要五感打勾式罗列',
  '数字和术语',
  '不直接命名情绪',
  '允许少量不直接推进剧情',
  '失去必须有过程'
]) {
  assert.match(
    rewritePrompt,
    new RegExp(phrase),
    `rewrite prompt should guide human-trace repair for ${phrase}`
  )
}

for (const phrase of [
  '非功能但真实的细节',
  '数字或专业术语必须影响',
  '不要平均打勾五感',
  '重大失去不能一句带过',
  '不要把每段都写成钩子'
]) {
  assert.match(
    chapterPrompt,
    new RegExp(phrase),
    `chapter prompt should prevent AI trace during generation for ${phrase}`
  )
}

console.log('AI tone human trace prompt contract tests passed')
