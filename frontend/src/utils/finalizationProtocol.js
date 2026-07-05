import { normalizeStateProvenance } from './stateProvenance.js'

const TERMINAL_STATUSES = new Set(['committed', 'failed_pre_commit', 'failed_after_chapter_commit'])

export function createFinalizationProtocol(input = {}) {
  const provenance = normalizeStateProvenance({
    ...input,
    commitStatus: input.commitStatus || 'staged'
  })
  return {
    schemaVersion: 'finalization-protocol-v1',
    chapterNum: provenance.sourceChapterNum,
    sourceVersionId: provenance.sourceVersionId,
    runId: provenance.runId,
    finalizationId: provenance.finalizationId,
    commitStatus: provenance.commitStatus || 'staged',
    startedAt: input.startedAt || input.now || null,
    updatedAt: input.updatedAt || input.now || null,
    reason: input.reason || '',
    history: [
      {
        commitStatus: provenance.commitStatus || 'staged',
        at: input.startedAt || input.now || null,
        reason: input.reason || ''
      }
    ]
  }
}

export function transitionFinalizationProtocol(protocol = {}, event = {}) {
  const current = protocol.commitStatus || 'staged'
  if (TERMINAL_STATUSES.has(current)) {
    return {
      ...protocol,
      rejectedTransition: event.type || 'unknown'
    }
  }

  const nextStatus = normalizeTransition(event.type || event.commitStatus || event.status)
  const next = {
    ...protocol,
    commitStatus: nextStatus,
    updatedAt: event.at || event.now || protocol.updatedAt || null,
    reason: event.reason || protocol.reason || '',
    history: [
      ...(Array.isArray(protocol.history) ? protocol.history : []),
      {
        commitStatus: nextStatus,
        at: event.at || event.now || null,
        reason: event.reason || ''
      }
    ]
  }

  if (event.runId || event.run_id) next.runId = event.runId || event.run_id
  if (event.finalizationId || event.finalization_id) next.finalizationId = event.finalizationId || event.finalization_id
  return next
}

export function finalizationProtocolToMarker(protocol = {}) {
  const status = String(protocol.commitStatus || '').trim().toLowerCase()
  if (!status || status === 'committed') return null
  return {
    projectId: protocol.projectId || '',
    chapterNum: Number(protocol.chapterNum || protocol.sourceChapterNum || 0),
    startedAt: protocol.startedAt || protocol.updatedAt || null,
    sourceVersionId: protocol.sourceVersionId || '',
    runId: protocol.runId || '',
    finalizationId: protocol.finalizationId || '',
    commitStatus: status,
    reason: protocol.reason || ''
  }
}

function normalizeTransition(type) {
  const normalized = String(type || '').trim().toLowerCase()
  if (normalized === 'validate' || normalized === 'validated') return 'validated'
  if (normalized === 'commit' || normalized === 'committed') return 'committed'
  if (normalized === 'fail_pre_commit' || normalized === 'failed_pre_commit') return 'failed_pre_commit'
  if (normalized === 'half_success' || normalized === 'failed_after_chapter_commit') return 'failed_after_chapter_commit'
  return normalized || 'staged'
}
