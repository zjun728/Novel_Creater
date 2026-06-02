import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const extractionPrompt = readFileSync('frontend/src/prompts/extraction.js', 'utf8')
const settingExtractionPrompt = readFileSync('frontend/src/prompts/settingExtraction.js', 'utf8')
const realisticFlow = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

for (const term of ['交易次数', '剩余寿命', '冷却时间', '物品价值', '时间流速']) {
  assert.match(extractionPrompt, new RegExp(term), `memory extraction prompt should mention ${term}`)
  assert.match(settingExtractionPrompt, new RegExp(term), `setting extraction prompt should mention ${term}`)
  assert.match(realisticFlow, new RegExp(term), `realistic QA extraction should mention ${term}`)
}

for (const field of ['profile.transactionCount', 'profile.remainingLifespan', 'profile.cooldownUntil', 'profile.valueLevel', 'profile.timeFlowRule']) {
  assert.match(settingExtractionPrompt, new RegExp(field.replace('.', '\\.')), `setting extraction schema should allow ${field}`)
}

console.log('HARD_STATE_EXTRACTION_PROMPTS_TEST_OK')
