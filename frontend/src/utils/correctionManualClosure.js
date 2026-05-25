export function correctionTaskEvidenceKey(task = {}) {
  const title = String(task.title || '').trim()
  return title ? `纠偏任务：${title}` : ''
}

export function settingCandidateStateForTask(events = [], task = {}, localGenerated = false) {
  const key = correctionTaskEvidenceKey(task)
  const matches = key
    ? (events || []).filter(event => String(event.evidence || '').includes(key))
    : []

  const accepted = matches.find(event => event.status === 'accepted')
  if (accepted) {
    return {
      status: 'accepted',
      exists: true,
      locked: true,
      buttonText: '设定候选已确认',
      hint: '设定候选已确认入库：请点击「完成」关闭这条纠偏任务。'
    }
  }

  const pending = matches.find(event => (event.status || 'pending_review') === 'pending_review')
  if (pending || localGenerated) {
    return {
      status: 'pending_review',
      exists: true,
      locked: true,
      buttonText: '已生成设定候选',
      hint: '已生成待确认设定变更：请到「4 设定库」确认或拒绝候选；确认入库后回到这里点击「完成」。'
    }
  }

  const rejected = matches.find(event => event.status === 'rejected')
  if (rejected) {
    return {
      status: 'rejected',
      exists: true,
      locked: false,
      buttonText: '重新生成设定候选',
      hint: '设定候选已被拒绝：如果本次问题不再处理，请点击「忽略本次」；如果仍需处理，可以重新生成候选或人工处理。'
    }
  }

  return {
    status: 'none',
    exists: false,
    locked: false,
    buttonText: '生成设定候选',
    hint: ''
  }
}
