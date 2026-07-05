import assert from 'node:assert/strict'
import fs from 'node:fs'

import { evaluateLiteraryQuality } from '../frontend/src/utils/literaryQualityEvaluator.js'
import {
  assertReportMatchesModelValidation,
  summarizeModelOutputForQa,
  validateModelValidationPayload,
} from './run_narrative_voice_phase2_model_validation.mjs'

function assertIncludes(haystack, needle, message) {
  assert.equal(String(haystack).includes(needle), true, message)
}

const warnOnlyScene = [
  '雨水敲着审讯室外的铁窗。',
  '林遥把半张提货单推过去：“周岑，你不是忘了账本，你是在拖时间。”',
  '周岑偏开脸，声音压低：“别问了，再问下去你也会被拖进去。”',
  '她没有退，纸边压住他的手背；灯光却在这时灭了一瞬，桌边的沉默变成逼问。',
].join('\n')

const warnOnlyQuality = evaluateLiteraryQuality(warnOnlyScene)
assert.equal(warnOnlyQuality.passed, true, 'warning-only scene can pass evaluator')
assert(warnOnlyQuality.issues.some((issue) => issue.severity === 'warn'))
assert.equal(warnOnlyQuality.issues.some((issue) => issue.severity === 'blocking'), false)

const warnOnlySummary = summarizeModelOutputForQa(warnOnlyScene, { futureSecret: '顾闻舟是幕后人' })
assert.equal(warnOnlySummary.passedEvaluator, true)
assert.deepEqual(warnOnlySummary.blockingIssueCodes, [])
assert(warnOnlySummary.warningIssueCodes.includes('missing_short_interiority'))
assert(warnOnlySummary.issueCodes.includes('missing_short_interiority'))

const blockingScene = [
  '本章主要说明林遥完成审讯任务。',
  '首先她进行观察，其次她推进问题，最后周岑交代线索。',
  '这意味着关系发生变化，后续剧情进入下一阶段。',
].join('\n')
const blockingSummary = summarizeModelOutputForQa(blockingScene, { futureSecret: '顾闻舟是幕后人' })
assert.equal(blockingSummary.passedEvaluator, false)
assert(blockingSummary.blockingIssueCodes.includes('documentary_tone'))
assert(blockingSummary.blockingIssueCodes.includes('low_dialogue_conflict'))

assert.throws(
  () => validateModelValidationPayload({
    status: 'completed',
    results: {
      oldPrompt: {
        qualityScore: 80,
        passedEvaluator: true,
        blockingIssueCodes: ['low_dialogue_conflict'],
        warningIssueCodes: [],
        issueCodes: ['low_dialogue_conflict'],
        leakedFutureSecret: false,
      },
      newPrompt: {
        qualityScore: 90,
        passedEvaluator: true,
        blockingIssueCodes: [],
        warningIssueCodes: [],
        issueCodes: [],
        leakedFutureSecret: false,
      },
      conclusion: {
        newPromptQualityAtLeastOld: true,
        newPromptAvoidedFutureSecret: true,
      },
    },
  }),
  /passedEvaluator cannot be true with blocking issues/
)

const json = JSON.parse(fs.readFileSync('tmp/realistic-flow-qa/narrative-voice-phase2-model-validation.json', 'utf8'))
assert.doesNotThrow(() => validateModelValidationPayload(json))

for (const label of ['oldPrompt', 'newPrompt']) {
  const summary = json.results[label]
  assert(Array.isArray(summary.blockingIssueCodes), `${label} must expose blockingIssueCodes`)
  assert(Array.isArray(summary.warningIssueCodes), `${label} must expose warningIssueCodes`)
  assert.equal(
    summary.passedEvaluator,
    summary.qualityScore >= 70 && summary.blockingIssueCodes.length === 0,
    `${label} passedEvaluator must match score/blocking semantics`
  )
}

assert.equal(
  json.results.conclusion.newPromptQualityAtLeastOld,
  json.results.newPrompt.qualityScore >= json.results.oldPrompt.qualityScore
)

const report = fs.readFileSync('tmp/realistic-flow-qa/narrative-voice-scene-contract-phase2-report.md', 'utf8')
assert.doesNotThrow(() => assertReportMatchesModelValidation(report, json))

const staleScoreReport = report.replace(
  `newPrompt.qualityScore=${json.results.newPrompt.qualityScore}`,
  'newPrompt.qualityScore=95'
)
assert.throws(
  () => assertReportMatchesModelValidation(staleScoreReport, json),
  /newPrompt\.qualityScore/
)

const stalePassReport = report.replace(
  `newPrompt.passedEvaluator=${json.results.newPrompt.passedEvaluator}`,
  'newPrompt.passedEvaluator=false'
)
assert.throws(
  () => assertReportMatchesModelValidation(stalePassReport, json),
  /newPrompt\.passedEvaluator/
)

console.log('narrative voice phase2 evidence contract passed')
