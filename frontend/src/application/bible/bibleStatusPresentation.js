const REASON_LABELS = Object.freeze({
  selection_missing: '请选择种子后继续。', seed_missing: '请选择种子后继续。',
  contract_missing: '请完成或重新签署创作契约。', contract_not_ready: '请完成或重新签署创作契约。', contract_revision_replaced: '请完成或重新签署创作契约。',
  contract_basis_invalid: '请完成或重新签署创作契约。', contract_unavailable: '请完成或重新签署创作契约。',
  selection_revision_changed: '内容已固定为项目永久基线，请查看历史记录。', seed_identity_changed: '内容已固定为项目永久基线，请查看历史记录。', seed_revision_changed: '内容已固定为项目永久基线，请查看历史记录。', seed_generation_changed: '内容已固定为项目永久基线，请查看历史记录。', contract_revision_changed: '内容已固定为项目永久基线，请查看历史记录。', creation_contract_changed: '内容已固定为项目永久基线，请查看历史记录。', style_contract_changed: '内容已固定为项目永久基线，请查看历史记录。', bible_policy_changed: '内容已固定为项目永久基线，请查看历史记录。', bible_head_changed: '内容已固定为项目永久基线，请查看历史记录。', bible_revision_replaced: '内容已固定为项目永久基线，请查看历史记录。',
  project_archived: '项目已归档，只能查阅。', bible_read_only: '项目已归档，只能查阅。',
})

const MODE_LABELS = Object.freeze({ first: '待建立', draft: '工作草稿', head: '已确认', superseded: '历史修订', archived: '只读归档' })
const HISTORY_STATUS_LABELS = Object.freeze({ current: '当前修订', superseded: '历史修订' })
const UNKNOWN_REASON_LABEL = '创作圣经状态需要重新读取。'
const UNKNOWN_STATUS_LABEL = '状态待核对'
const EMPTY_REASONS = Object.freeze([])

export function bibleReasonLabel(reason) {
  try {
    if (reason === 'bible_confirmed') return null
    return Object.hasOwn(REASON_LABELS, reason) ? REASON_LABELS[reason] : UNKNOWN_REASON_LABEL
  } catch {
    return UNKNOWN_REASON_LABEL
  }
}

export function presentBibleReasons(reasons) {
  try {
    if (!Array.isArray(reasons)) return EMPTY_REASONS
    const labels = []
    for (const reason of reasons) {
      const label = bibleReasonLabel(reason)
      if (label !== null && !labels.includes(label)) labels.push(label)
    }
    return Object.freeze(labels)
  } catch {
    return EMPTY_REASONS
  }
}

export function bibleModeLabel(mode) {
  try {
    return Object.hasOwn(MODE_LABELS, mode) ? MODE_LABELS[mode] : UNKNOWN_STATUS_LABEL
  } catch {
    return UNKNOWN_STATUS_LABEL
  }
}

export function bibleHistoryStatusLabel(status) {
  try {
    return Object.hasOwn(HISTORY_STATUS_LABELS, status) ? HISTORY_STATUS_LABELS[status] : UNKNOWN_STATUS_LABEL
  } catch {
    return UNKNOWN_STATUS_LABEL
  }
}
