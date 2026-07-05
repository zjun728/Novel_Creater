import assert from 'node:assert/strict'
import fs from 'node:fs'

import {
  PHASE21_SCENE_FIXTURES,
  assertRegressionReportMatchesJson,
  buildOfflineRegressionReport,
  buildOldPromptForFixture,
  buildPhase21RegressionPayload,
  buildSceneCardPromptForFixture,
  detectFutureLeak,
  evaluateOfflineRegressionPair,
  validateOfflineRegressionPayload,
} from './run_offline_narrative_quality_regression_phase2_1.mjs'

const REQUIRED_CATEGORIES = [
  'interrogation_negotiation',
  'conflict_dialogue',
  'chase_action_burst',
  'intimate_relationship裂隙',
  'pre_reveal_night',
  'post_battle_failure_aftermath',
]

function assertNotIncludes(haystack, needle, message) {
  assert.equal(String(haystack).includes(needle), false, message)
}

function assertIncludes(haystack, needle, message) {
  assert.equal(String(haystack).includes(needle), true, message)
}

assert.equal(PHASE21_SCENE_FIXTURES.length, 6, 'Phase 2.1 must cover exactly six synthetic scene fixtures')
assert.deepEqual(PHASE21_SCENE_FIXTURES.map((fixture) => fixture.category), REQUIRED_CATEGORIES)

for (const fixture of PHASE21_SCENE_FIXTURES) {
  assert(fixture.id, 'fixture must have id')
  assert(fixture.title, `${fixture.id} must have title`)
  assert(fixture.chapterGoal?.goal, `${fixture.id} must have scene goal`)
  assert(fixture.chapterGoal?.conflict, `${fixture.id} must have conflict pair`)
  assert(fixture.chapterGoal?.emotionalTurn, `${fixture.id} must have emotional turn`)
  assert(fixture.chapterGoal?.stopPoint, `${fixture.id} must have stop point`)
  assert(fixture.guardSnapshot?.futureRoadmap, `${fixture.id} must have guard-only future roadmap`)
  assert(fixture.futureSecret, `${fixture.id} must have future secret`)
  assert(fixture.currentStageCreativeContext?.writableFacts?.every((fact) => fact.commitStatus === 'committed'))

  const oldPrompt = buildOldPromptForFixture(fixture)
  const newPrompt = buildSceneCardPromptForFixture(fixture)
  assertIncludes(oldPrompt, '写作质量方向', `${fixture.id} old prompt should represent legacy thick rules`)
  assertIncludes(oldPrompt, fixture.futureSecret, `${fixture.id} old prompt should include intentional guard contamination fixture`)
  assertIncludes(newPrompt, 'Scene Execution Card', `${fixture.id} new prompt should use scene card`)
  assertIncludes(newPrompt, 'Narrative Voice Contract', `${fixture.id} new prompt should use voice contract`)
  assertIncludes(newPrompt, '至少两轮直接引号对白', `${fixture.id} new prompt should require direct dialogue exchange`)
  assertIncludes(newPrompt, '本场必须出现一次情绪转折', `${fixture.id} new prompt should require emotional turn`)
  assertIncludes(newPrompt, '一处短内心', `${fixture.id} new prompt should require short interiority`)
  assertIncludes(newPrompt, fixture.sceneSeed.directQuestion, `${fixture.id} new prompt should include the fixture direct-conflict anchor`)
  assertIncludes(newPrompt, fixture.sceneSeed.deflection, `${fixture.id} new prompt should include the fixture deflection anchor`)
  assertIncludes(newPrompt, fixture.sceneSeed.turnRecognition, `${fixture.id} new prompt should include the fixture emotional-turn anchor`)
  assertIncludes(newPrompt, fixture.sceneSeed.environmentalPressure, `${fixture.id} new prompt should include the fixture environment-pressure anchor`)
  assertNotIncludes(newPrompt, '## 硬连续性边界', `${fixture.id} offline new prompt should stay compact, not reintroduce long hard-rule blocks`)
  assertNotIncludes(newPrompt, '## 已确认本章小纲', `${fixture.id} offline new prompt should stay compact, not use beat-plan style blocks`)
  assertNotIncludes(newPrompt, fixture.futureSecret, `${fixture.id} new prompt must not expose guard-only future secret`)
  assertNotIncludes(newPrompt, 'guardSnapshot', `${fixture.id} new prompt must not mention guard implementation`)
  assertNotIncludes(newPrompt, 'roadmap', `${fixture.id} new prompt must not mention roadmap implementation`)
}

const calibratedPair = evaluateOfflineRegressionPair({
  fixture: PHASE21_SCENE_FIXTURES[0],
  oldOutput: [
    '本章主要说明林遥完成审讯任务。',
    '首先她进行观察，其次她推进问题，最后周岑交代线索。',
    '这意味着关系发生变化，后续剧情进入下一阶段。',
  ].join('\n'),
  newOutput: [
    '雨敲着审讯室的铁窗。',
    '林遥把半张提货单推过去：“周岑，你不是忘了账本，你是在拖时间。”',
    '周岑偏开脸，声音压低：“别问了，再问下去你也会被拖进去。”',
    '她没有退，纸边压住他的手背；灯光却在这时灭了一瞬。她忽然明白，他不是挑衅，是怕。',
  ].join('\n'),
})
assert.equal(calibratedPair.oldPrompt.passedEvaluator, false)
assert(calibratedPair.oldPrompt.blockingIssueCodes.includes('documentary_tone'))
assert.equal(calibratedPair.newPrompt.passedEvaluator, true)
assert.equal(calibratedPair.newPrompt.blockingIssueCodes.length, 0)
assert.equal(calibratedPair.newPrompt.leakedFutureSecret, false)
assert.equal(calibratedPair.newPrompt.futureLeakRisk, false)
assert.equal(calibratedPair.comparison.newPromptRegressed, false)

const paraphrasedLeak = detectFutureLeak(
  PHASE21_SCENE_FIXTURES[0],
  '真正买走账本的人不是周岑，而是顾闻舟。'
)
assert.equal(paraphrasedLeak.exactSecretLeak, false)
assert.equal(paraphrasedLeak.futureLeakRisk, true)
assert(paraphrasedLeak.riskTerms.includes('顾闻舟'))

const stageSafeBuyerQuestion = detectFutureLeak(
  PHASE21_SCENE_FIXTURES[0],
  '林遥追问账本背后的买家，但周岑始终没有说出名字。'
)
assert.equal(stageSafeBuyerQuestion.futureLeakRisk, false)

const stageSafeAllianceOriginal = detectFutureLeak(
  PHASE21_SCENE_FIXTURES[1],
  '夏弦把盟约原件按在桌上，却拒绝说明它后来去了哪里。'
)
assert.equal(stageSafeAllianceOriginal.futureLeakRisk, false)

const fixtureResults = PHASE21_SCENE_FIXTURES.map((fixture, index) => {
  const pair = evaluateOfflineRegressionPair({
    fixture,
    oldOutput: `本章主要说明旧链路样本 ${index} 完成任务。首先推进，其次总结，最后进入下一阶段。`,
    newOutput: [
      `${fixture.sceneSeed.environmentalPressure}压在场上。`,
      `“${fixture.sceneSeed.directQuestion}”${fixture.sceneSeed.protagonist}说。`,
      `“${fixture.sceneSeed.deflection}”${fixture.sceneSeed.opponent}偏开脸，声音发紧。`,
      `${fixture.sceneSeed.protagonist}停了一瞬，忽然明白${fixture.sceneSeed.turnRecognition}`,
    ].join('\n'),
  })
  return pair
})

const payload = buildPhase21RegressionPayload({
  provider: { name: 'deterministic-test', model: 'no-model', parameters: { temperature: 0, top_p: 1 } },
  fixtureResults,
  status: 'completed',
  mode: 'deterministic-fixture',
})
assert.doesNotThrow(() => validateOfflineRegressionPayload(payload))
assert.equal(payload.summary.fixtureCount, 6)
assert.equal(payload.summary.newPromptFutureLeaks, 0)
assert.equal(payload.summary.oldPromptFutureLeaks, 0)
assert.equal(payload.summary.newPromptRegressions, 0)

assert.throws(
  () => validateOfflineRegressionPayload({
    ...payload,
    summary: { ...payload.summary, oldPromptPasses: 999 },
  }),
  /oldPromptPasses/
)
assert.throws(
  () => validateOfflineRegressionPayload({
    ...payload,
    summary: { ...payload.summary, averageOldScore: 1 },
  }),
  /averageOldScore/
)
assert.throws(
  () => validateOfflineRegressionPayload({
    ...payload,
    summary: { ...payload.summary, newPromptOverallNonRegression: false },
  }),
  /newPromptOverallNonRegression/
)

const report = buildOfflineRegressionReport(payload)
assert.doesNotThrow(() => assertRegressionReportMatchesJson(report, payload))
assertIncludes(report, '| id | category | trusted facts | conflict | emotional turn | stop point | guard-only secret |')
for (const fixture of PHASE21_SCENE_FIXTURES) {
  assertIncludes(report, fixture.chapterGoal.emotionalTurn, `${fixture.id} report should include emotional turn coverage`)
}

const verificationReport = buildOfflineRegressionReport({
  ...payload,
  verification: {
    commands: [
      { command: 'node tmp\\test_offline_narrative_quality_regression_phase2_1.mjs', result: 'passed' },
      { command: 'npm --prefix frontend run build', result: 'passed with existing dynamic import warning' },
    ],
  },
})
assertIncludes(verificationReport, '## Verification', 'report should include optional verification metadata from JSON')
assertIncludes(verificationReport, 'npm --prefix frontend run build', 'report should include build command when provided')

const staleReport = report.replace(
  `newPromptRegressions=${payload.summary.newPromptRegressions}`,
  'newPromptRegressions=99'
)
assert.throws(
  () => assertRegressionReportMatchesJson(staleReport, payload),
  /newPromptRegressions/
)

const duplicateStaleReport = staleReport + `\nnewPromptRegressions=${payload.summary.newPromptRegressions}\n`
assert.throws(
  () => assertRegressionReportMatchesJson(duplicateStaleReport, payload),
  /newPromptRegressions/
)

const staleResultRowReport = report.replace(
  `oldPrompt.qualityScore=${payload.results[0].oldPrompt.qualityScore};`,
  `oldPrompt.qualityScore=1; oldPrompt.qualityScore=${payload.results[0].oldPrompt.qualityScore};`
)
assert.throws(
  () => assertRegressionReportMatchesJson(staleResultRowReport, payload),
  /oldPrompt\.qualityScore/
)

const staleCoverageRowReport = report.replace(
  `| ${payload.fixtureCoverage[0].id} | ${payload.fixtureCoverage[0].category} | true | ${payload.fixtureCoverage[0].conflict} |`,
  `| ${payload.fixtureCoverage[0].id} | ${payload.fixtureCoverage[0].category} | true | stale-conflict | ${payload.fixtureCoverage[0].conflict} |`
)
assert.throws(
  () => assertRegressionReportMatchesJson(staleCoverageRowReport, payload),
  /fixture coverage/
)

if (fs.existsSync('tmp/realistic-flow-qa/offline-narrative-quality-regression-phase2-1.json')) {
  const currentJson = JSON.parse(fs.readFileSync('tmp/realistic-flow-qa/offline-narrative-quality-regression-phase2-1.json', 'utf8'))
  const currentReport = fs.readFileSync('tmp/realistic-flow-qa/offline-narrative-quality-regression-phase2-1-report.md', 'utf8')
  assert.doesNotThrow(() => validateOfflineRegressionPayload(currentJson))
  assert.doesNotThrow(() => assertRegressionReportMatchesJson(currentReport, currentJson))
}

console.log('offline narrative quality regression phase2.1 no-model contract passed')
