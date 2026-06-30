import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  assertChapterRangeFreeze,
  assertNoUnexpectedChapterStarted,
  assertSettingsAndRelationHealth,
  collectFreezeGuardSummary
} from './live-qa/guards/live-run-freeze-guards.mjs'

function assertGuardFails(fn, code) {
  assert.throws(fn, error => {
    assert.equal(error.code, code)
    return true
  })
}

const healthyReport = {
  target: {
    startChapter: 83,
    endChapter: 88,
    runChapterCount: 6
  },
  acceptance: {
    completedChapters: 6
  },
  chapterReports: [
    { chapterNum: 83, finalized: true },
    { chapterNum: 84, finalized: true },
    { chapterNum: 85, finalized: true },
    { chapterNum: 86, finalized: true },
    { chapterNum: 87, finalized: true },
    { chapterNum: 88, finalized: true }
  ],
  pendingSettingsCount: 0,
  relationshipAudit: {
    activeRelationCount: 42,
    activeSyntheticRelationCount: 0,
    activeSelfRelationCount: 0,
    activeWrongLayerRelationCount: 0,
    activeMissingEndpointRelationCount: 0
  }
}

assert.doesNotThrow(() => assertChapterRangeFreeze({
  report: healthyReport,
  startChapter: 83,
  endChapter: 88,
  forbiddenChapters: [89, 50, 78]
}))
assert.doesNotThrow(() => assertNoUnexpectedChapterStarted({ report: healthyReport, chapterNum: 89 }))
assert.doesNotThrow(() => assertSettingsAndRelationHealth({
  report: healthyReport,
  expectedPendingCount: 0,
  expectedRelationRisk: {
    activeRelationCount: 42,
    activeSyntheticRelationCount: 0,
    activeSelfRelationCount: 0,
    activeWrongLayerRelationCount: 0,
    activeMissingEndpointRelationCount: 0
  }
}))

assertGuardFails(() => assertNoUnexpectedChapterStarted({
  report: {
    ...healthyReport,
    chapterReports: [...healthyReport.chapterReports, { chapterNum: 89, flowEvents: { chapter_run_started: {} } }]
  },
  chapterNum: 89
}), 'unexpected_next_chapter_started')

assertGuardFails(() => assertNoUnexpectedChapterStarted({
  report: {
    ...healthyReport,
    chapter89Started: true
  },
  chapterNum: 89
}), 'unexpected_next_chapter_started')

assertGuardFails(() => assertChapterRangeFreeze({
  report: {
    ...healthyReport,
    chapterReports: [...healthyReport.chapterReports, { chapterNum: 90 }]
  },
  startChapter: 83,
  endChapter: 88,
  forbiddenChapters: [89, 90]
}), 'out_of_range_chapter')

assertGuardFails(() => assertSettingsAndRelationHealth({
  report: {
    ...healthyReport,
    pendingSettingsCount: 1
  },
  expectedPendingCount: 0,
  expectedRelationRisk: healthyReport.relationshipAudit
}), 'pending_settings_non_zero')

assertGuardFails(() => assertSettingsAndRelationHealth({
  report: {
    ...healthyReport,
    relationshipAudit: {
      ...healthyReport.relationshipAudit,
      activeWrongLayerRelationCount: 1
    }
  },
  expectedPendingCount: 0,
  expectedRelationRisk: healthyReport.relationshipAudit
}), 'relation_risk_non_zero')

assertGuardFails(() => assertSettingsAndRelationHealth({
  report: {
    ...healthyReport,
    relationshipAudit: {
      ...healthyReport.relationshipAudit,
      activeRelationCount: 41
    }
  },
  expectedPendingCount: 0,
  expectedRelationRisk: healthyReport.relationshipAudit
}), 'relation_health_mismatch')

assertGuardFails(() => assertChapterRangeFreeze({
  report: {
    ...healthyReport,
    chapterReports: undefined
  },
  startChapter: 83,
  endChapter: 88
}), 'missing_required_report_field')

assertGuardFails(() => assertSettingsAndRelationHealth({
  report: {
    ...healthyReport,
    relationshipAudit: undefined
  },
  expectedPendingCount: 0,
  expectedRelationRisk: healthyReport.relationshipAudit
}), 'missing_required_report_field')

const summary = collectFreezeGuardSummary({
  report: healthyReport,
  startChapter: 83,
  endChapter: 88,
  forbiddenChapters: [89],
  unexpectedChapterNum: 89,
  expectedPendingCount: 0,
  expectedRelationRisk: healthyReport.relationshipAudit
})
assert.equal(summary.ok, true)
assert.equal(summary.startChapter, 83)
assert.equal(summary.endChapter, 88)
assert.equal(summary.chapter89Exists, false)
assert.equal(summary.pendingSettingsCount, 0)
assert.equal(summary.activeRelationCount, 42)
assert.equal(summary.relationshipRiskChecked, true)
assert.equal(summary.relationshipRiskSkippedReason, null)
assert.ok(summary.checkedFailureModes.includes('relationRiskNonZero'))
assert.ok(summary.declaredFailureModes.includes('relationRiskNonZero'))

const noRelationshipAuditSummary = collectFreezeGuardSummary({
  report: {
    ...healthyReport,
    relationshipAudit: undefined
  },
  startChapter: 83,
  endChapter: 88,
  forbiddenChapters: [89],
  unexpectedChapterNum: 89,
  expectedPendingCount: 0,
  expectedRelationRisk: healthyReport.relationshipAudit
})
assert.equal(noRelationshipAuditSummary.ok, true)
assert.equal(noRelationshipAuditSummary.relationshipRiskChecked, false)
assert.equal(noRelationshipAuditSummary.relationshipRiskSkippedReason, 'relationshipAuditMissing')
assert.ok(!noRelationshipAuditSummary.checkedFailureModes.includes('relationRiskNonZero'))
assert.ok(noRelationshipAuditSummary.declaredFailureModes.includes('relationRiskNonZero'))
assert.equal(noRelationshipAuditSummary.activeRelationCount, null)

const runnerSource = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
assert.match(runnerSource, /live-run-freeze-guards\.mjs/, 'runner should import the freeze guard module')
assert.match(runnerSource, /assertChapterRangeFreeze\s*\(/, 'runner should delegate chapter range checks to freeze guard')
assert.match(runnerSource, /assertNoUnexpectedChapterStarted\s*\(/, 'runner should delegate no-next-chapter checks to freeze guard')
assert.match(runnerSource, /assertSettingsAndRelationHealth\s*\(/, 'runner should delegate pending/relation health checks to freeze guard')

const guardSource = readFileSync('tmp/live-qa/guards/live-run-freeze-guards.mjs', 'utf8')
assert.doesNotMatch(
  guardSource,
  /chromium|page\.|fetch\s*\(|api\s*\(|aiomysql|mysql|SELECT\s+|writeFileSync|readFileSync/i,
  'freeze guard module must stay pure: no browser/API/DB/file I/O'
)

console.log('live runner freeze guards contract passed')
