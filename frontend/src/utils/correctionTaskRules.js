export const CORRECTION_CONTEXT_STATUSES = ['pending', 'accepted', 'in_progress']
export const CORRECTION_CLOSED_STATUSES = ['done', 'rejected', 'ignored', 'cancelled', 'archived']
export const CORRECTION_MODES = {
  HARD: 'hard',
  SOFT: 'soft',
  SETTING: 'setting_candidate',
  CANON: 'canon_candidate',
  ADVICE: 'advice'
}

export function isCorrectionTaskOpen(task) {
  return !CORRECTION_CLOSED_STATUSES.includes(task?.status)
}

export function isCorrectionTaskActiveForContext(task) {
  const status = task?.status || 'pending'
  return CORRECTION_CONTEXT_STATUSES.includes(status)
}

export function correctionTaskMode(task) {
  const metadata = task?.metadata || {}
  if (metadata.correctionMode) return metadata.correctionMode
  if (task?.sourceType === 'chapter_audit') return CORRECTION_MODES.HARD
  if (task?.targetModule === 'setting') return CORRECTION_MODES.SETTING
  if (task?.targetModule === 'canon') return CORRECTION_MODES.CANON
  if (task?.severity === 'suggestion' || task?.issueType === 'next_action') return CORRECTION_MODES.ADVICE
  return CORRECTION_MODES.SOFT
}

export function isCorrectionTaskBlockingForGeneration(task) {
  if (!isCorrectionTaskActiveForContext(task)) return false
  const metadata = task?.metadata || {}
  return metadata.blocking === true || correctionTaskMode(task) === CORRECTION_MODES.HARD
}

export function isCorrectionTaskSoftForContext(task) {
  if (!isCorrectionTaskActiveForContext(task)) return false
  return !isCorrectionTaskBlockingForGeneration(task)
}
