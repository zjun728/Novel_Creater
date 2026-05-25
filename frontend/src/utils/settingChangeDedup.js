function normalizeValue(value) {
  if (value === undefined || value === null) return ''
  return String(value).replace(/\s+/g, ' ').trim()
}

function normalizeChapterNum(value) {
  if (value === undefined || value === null || value === '') return ''
  const parsed = Number(value)
  return Number.isFinite(parsed) ? String(parsed) : String(value)
}

export function settingChangeDedupKey(event = {}) {
  return [
    normalizeValue(event.entityType),
    normalizeValue(event.entityName),
    normalizeValue(event.changeType || 'update'),
    normalizeValue(event.fieldPath),
    normalizeChapterNum(event.chapterNum),
    normalizeValue(event.evidence),
    normalizeValue(event.newValue)
  ].join('|')
}

export function findDuplicateSettingChangeEvent(events, candidate) {
  const targetKey = settingChangeDedupKey(candidate)
  return (events || []).find(event =>
    (event.status || 'pending_review') === 'pending_review' &&
    settingChangeDedupKey(event) === targetKey
  ) || null
}
