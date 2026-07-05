const DEFAULT_COMMIT_STATUS = 'unknown'

export function normalizeStateProvenance(input = {}, fallback = {}) {
  const nested = input?.provenance || input?.sourceProvenance || input?.snapshotProvenance || {}
  const merged = { ...fallback, ...nested, ...input }
  const sourceChapterNum = numberOrNull(
    merged.sourceChapterNum ??
    merged.source_chapter_num ??
    merged.chapterNum ??
    merged.chapter_num
  )
  return {
    sourceChapterNum,
    sourceVersionId: stringOrEmpty(merged.sourceVersionId ?? merged.source_version_id ?? merged.versionId ?? merged.version_id),
    runId: stringOrEmpty(merged.runId ?? merged.run_id),
    finalizationId: stringOrEmpty(merged.finalizationId ?? merged.finalization_id),
    commitStatus: normalizeCommitStatus(merged.commitStatus ?? merged.commit_status ?? fallback.commitStatus)
  }
}

export function buildFinalizationProvenance(input = {}) {
  return normalizeStateProvenance({
    ...input,
    commitStatus: input.commitStatus || 'final'
  })
}

export function withStateProvenance(payload = {}, provenance = {}, options = {}) {
  const normalized = normalizeStateProvenance(provenance, options.fallback || {})
  return {
    ...payload,
    sourceChapterNum: normalized.sourceChapterNum,
    sourceVersionId: normalized.sourceVersionId,
    runId: normalized.runId,
    finalizationId: normalized.finalizationId,
    commitStatus: normalized.commitStatus,
    provenance: normalized
  }
}

export function auditProvenanceWritePaths() {
  return [
    {
      path: 'chapter_versions',
      currentState: 'sourceModelId/promptBrief exist; Phase 1.2 payloads can carry provenance fields once schema migration is applied',
      status: 'schema_migration_required',
      fix: 'Add provenance JSON plus scalar sourceChapterNum/sourceVersionId/runId/finalizationId/commitStatus in schema/migration; writerStore prepares payloads.'
    },
    {
      path: 'canon_facts',
      currentState: 'chapterNum/status/evidence exist; frontend finalization can attach provenance but current DB schema needs columns',
      status: 'schema_migration_required',
      fix: 'Persist provenance JSON and scalar source fields; health-check warns on missing/unknown legacy rows.'
    },
    {
      path: 'setting_change_events',
      currentState: 'chapterNum/status/evidence exist; finalization extraction can attach final provenance',
      status: 'schema_migration_required',
      fix: 'Persist provenance JSON and scalar source fields; accepted events without final proof remain unknown/degraded.'
    },
    {
      path: 'setting_entities',
      currentState: 'profile JSON can preserve provenance immediately; dedicated columns still recommended',
      status: 'implemented_with_profile_fallback',
      fix: 'Normalize profile.provenance at write time and migrate to first-class provenance columns later.'
    },
    {
      path: 'setting_relations',
      currentState: 'chapterNum/status/evidence exist; no JSON metadata column in current schema',
      status: 'schema_migration_required',
      fix: 'Add provenance JSON/scalars; until then health-check treats missing provenance as unknown/degraded.'
    },
    {
      path: 'project_volumes.stage_summary_report',
      currentState: 'stageSummaryReport JSON can carry snapshotProvenance/sourceExplanation',
      status: 'implemented_with_json_report',
      fix: 'Store snapshotProvenance in stage summary settlement payloads and block failed/untrusted snapshots.'
    },
    {
      path: 'chapter_beat_plans',
      currentState: 'content-only table; beat plans must remain plan evidence and not authority',
      status: 'schema_migration_required_plan_only',
      fix: 'Add provenance JSON/scalars; ContextPack keeps saved beat plans in guardSnapshot only.'
    }
  ]
}

export function normalizeCommitStatus(value) {
  const status = String(value || DEFAULT_COMMIT_STATUS).trim().toLowerCase()
  if (!status) return DEFAULT_COMMIT_STATUS
  if (status === 'finalized') return 'final'
  if (status === 'committed') return 'committed'
  return status
}

function numberOrNull(value) {
  if (value === '' || value == null) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function stringOrEmpty(value) {
  return value == null ? '' : String(value)
}
