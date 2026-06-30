const DEFAULT_RELATION_RISK = Object.freeze({
  activeSyntheticRelationCount: 0,
  activeSelfRelationCount: 0,
  activeWrongLayerRelationCount: 0,
  activeMissingEndpointRelationCount: 0
})

export const DECLARED_FREEZE_GUARD_FAILURE_MODES = Object.freeze([
  'unexpectedNextChapter',
  'pendingSettingsNonZero',
  'relationRiskNonZero',
  'missingRequiredReportField',
  'outOfRangeChapter'
])

function freezeGuardError(code, message, details = {}) {
  const error = new Error(`${code}: ${message}`)
  error.code = code
  error.liveDiagnostics = {
    guard: 'live-run-freeze',
    code,
    ...details
  }
  return error
}

function requireReportObject(report) {
  if (!report || typeof report !== 'object') {
    throw freezeGuardError('missing_required_report_field', 'report object is required', { field: 'report' })
  }
}

function requireArray(value, field) {
  if (!Array.isArray(value)) {
    throw freezeGuardError('missing_required_report_field', `${field} must be an array`, { field })
  }
}

function requireNumber(value, field) {
  if (!Number.isFinite(Number(value))) {
    throw freezeGuardError('missing_required_report_field', `${field} must be a number`, { field })
  }
  return Number(value)
}

function chapterNumOf(entry) {
  return Number(entry?.chapterNum ?? entry?.chapter_num ?? 0)
}

function chapterStarted(entry = {}) {
  if (!entry || typeof entry !== 'object') return false
  if (entry.finalized || entry.status || entry.title || entry.wordCount) return true
  const events = entry.flowEvents || {}
  return Boolean(
    events.chapter_run_started ||
    events.writer_page_visible ||
    events.draft_generation_wait_started ||
    events.finalize_done
  )
}

function relationRiskKeys(expectedRelationRisk = {}) {
  return Object.keys({
    ...DEFAULT_RELATION_RISK,
    ...(expectedRelationRisk || {})
  }).filter(key => key !== 'activeRelationCount')
}

function hasRelationshipAudit(report) {
  return Boolean(report?.relationshipAudit && typeof report.relationshipAudit === 'object')
}

function hasExpectedRelationRisk(expectedRelationRisk) {
  return Boolean(expectedRelationRisk && typeof expectedRelationRisk === 'object')
}

export function assertChapterRangeFreeze({
  report,
  startChapter,
  endChapter,
  forbiddenChapters = []
} = {}) {
  requireReportObject(report)
  requireArray(report.chapterReports, 'report.chapterReports')
  const start = requireNumber(startChapter, 'startChapter')
  const end = requireNumber(endChapter, 'endChapter')
  if (end < start) {
    throw freezeGuardError('out_of_range_chapter', 'endChapter is before startChapter', { startChapter: start, endChapter: end })
  }

  const forbidden = new Set((Array.isArray(forbiddenChapters) ? forbiddenChapters : [])
    .map(Number)
    .filter(Number.isFinite))

  for (const entry of report.chapterReports) {
    const chapterNum = chapterNumOf(entry)
    if (!chapterNum) {
      throw freezeGuardError('missing_required_report_field', 'chapter report is missing chapterNum', { field: 'chapterReports[].chapterNum', entry })
    }
    if (chapterNum < start || chapterNum > end || forbidden.has(chapterNum)) {
      throw freezeGuardError('out_of_range_chapter', `chapter ${chapterNum} is outside frozen range ${start}-${end}`, {
        chapterNum,
        startChapter: start,
        endChapter: end,
        forbiddenChapters: [...forbidden]
      })
    }
  }

  return {
    ok: true,
    startChapter: start,
    endChapter: end,
    checkedChapterCount: report.chapterReports.length
  }
}

export function assertNoUnexpectedChapterStarted({ report, chapterNum } = {}) {
  requireReportObject(report)
  requireArray(report.chapterReports, 'report.chapterReports')
  const targetChapter = requireNumber(chapterNum, 'chapterNum')
  const flagName = `chapter${targetChapter}Started`
  const entry = report.chapterReports.find(item => chapterNumOf(item) === targetChapter)
  if (report[flagName] === true || chapterStarted(entry)) {
    throw freezeGuardError('unexpected_next_chapter_started', `chapter ${targetChapter} appears to have started`, {
      chapterNum: targetChapter,
      flagName,
      flagValue: report[flagName],
      entry: entry || null
    })
  }
  return {
    ok: true,
    chapterNum: targetChapter,
    started: false
  }
}

export function assertSettingsAndRelationHealth({
  report,
  expectedPendingCount = 0,
  expectedRelationRisk = null
} = {}) {
  requireReportObject(report)
  const pendingCount = requireNumber(report.pendingSettingsCount, 'report.pendingSettingsCount')
  const expectedPending = requireNumber(expectedPendingCount, 'expectedPendingCount')
  if (pendingCount !== expectedPending) {
    throw freezeGuardError(
      pendingCount > expectedPending ? 'pending_settings_non_zero' : 'pending_settings_count_mismatch',
      `pending settings count ${pendingCount} does not match expected ${expectedPending}`,
      { pendingSettingsCount: pendingCount, expectedPendingCount: expectedPending }
    )
  }

  if (expectedRelationRisk) {
    const audit = report.relationshipAudit
    if (!audit || typeof audit !== 'object') {
      throw freezeGuardError('missing_required_report_field', 'report.relationshipAudit is required', { field: 'report.relationshipAudit' })
    }

    if (Object.hasOwn(expectedRelationRisk, 'activeRelationCount')) {
      const actualActive = requireNumber(audit.activeRelationCount, 'report.relationshipAudit.activeRelationCount')
      const expectedActive = requireNumber(expectedRelationRisk.activeRelationCount, 'expectedRelationRisk.activeRelationCount')
      if (actualActive !== expectedActive) {
        throw freezeGuardError('relation_health_mismatch', `active relation count ${actualActive} does not match expected ${expectedActive}`, {
          activeRelationCount: actualActive,
          expectedActiveRelationCount: expectedActive
        })
      }
    }

    for (const key of relationRiskKeys(expectedRelationRisk)) {
      const actual = requireNumber(audit[key], `report.relationshipAudit.${key}`)
      const expected = requireNumber(expectedRelationRisk[key] ?? 0, `expectedRelationRisk.${key}`)
      if (actual !== expected) {
        throw freezeGuardError('relation_risk_non_zero', `${key}=${actual} does not match expected ${expected}`, {
          relationRiskField: key,
          actual,
          expected
        })
      }
    }
  }

  return {
    ok: true,
    pendingSettingsCount: pendingCount,
    relationshipAudit: expectedRelationRisk ? report.relationshipAudit : null
  }
}

export function collectFreezeGuardSummary({
  report,
  startChapter,
  endChapter,
  forbiddenChapters = [],
  unexpectedChapterNum,
  expectedPendingCount = 0,
  expectedRelationRisk = null
} = {}) {
  const range = assertChapterRangeFreeze({ report, startChapter, endChapter, forbiddenChapters })
  const unexpected = unexpectedChapterNum
    ? assertNoUnexpectedChapterStarted({ report, chapterNum: unexpectedChapterNum })
    : { ok: true }
  const relationshipRiskExpected = hasExpectedRelationRisk(expectedRelationRisk)
  const relationshipRiskChecked = relationshipRiskExpected && hasRelationshipAudit(report)
  const relationshipRiskSkippedReason = relationshipRiskChecked
    ? null
    : relationshipRiskExpected
      ? 'relationshipAuditMissing'
      : 'expectedRelationRiskMissing'
  const health = assertSettingsAndRelationHealth({
    report,
    expectedPendingCount,
    expectedRelationRisk: relationshipRiskChecked ? expectedRelationRisk : null
  })
  const checkedFailureModes = [
    'outOfRangeChapter',
    'pendingSettingsNonZero',
    'missingRequiredReportField'
  ]
  if (unexpectedChapterNum) checkedFailureModes.push('unexpectedNextChapter')
  if (relationshipRiskChecked) checkedFailureModes.push('relationRiskNonZero')

  return {
    ok: true,
    startChapter: range.startChapter,
    endChapter: range.endChapter,
    checkedChapterCount: range.checkedChapterCount,
    chapter89Exists: unexpectedChapterNum === 89 ? unexpected.started : false,
    unexpectedChapterNum: unexpectedChapterNum || null,
    pendingSettingsCount: health.pendingSettingsCount,
    activeRelationCount: health.relationshipAudit?.activeRelationCount ?? null,
    activeSyntheticRelationCount: health.relationshipAudit?.activeSyntheticRelationCount ?? null,
    activeSelfRelationCount: health.relationshipAudit?.activeSelfRelationCount ?? null,
    activeWrongLayerRelationCount: health.relationshipAudit?.activeWrongLayerRelationCount ?? null,
    activeMissingEndpointRelationCount: health.relationshipAudit?.activeMissingEndpointRelationCount ?? null,
    relationshipRiskChecked,
    relationshipRiskSkippedReason,
    checkedFailureModes,
    declaredFailureModes: [...DECLARED_FREEZE_GUARD_FAILURE_MODES]
  }
}
