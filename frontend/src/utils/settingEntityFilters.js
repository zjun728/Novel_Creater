const PLACEHOLDER_SUMMARY_PATTERN = /^(?:第\s*(?:\?|[一二三四五六七八九十百千万\d]+)\s*章自动识别的设定|自动识别的设定|待补全|待完善|未知|暂无|无|占位|占位设定|暂无明确设定|无有效摘要)$/

export function isPlaceholderSettingSummary(value = '') {
  return PLACEHOLDER_SUMMARY_PATTERN.test(String(value || '').trim())
}

function hasMeaningfulProfile(profile = {}) {
  if (!profile || typeof profile !== 'object') return false
  return Object.entries(profile).some(([key, value]) => {
    if (value == null || value === '') return false
    if (Array.isArray(value)) return value.length > 0
    if (typeof value === 'object') return Object.keys(value).length > 0
    return String(value).trim() && !isPlaceholderSettingSummary(value)
  })
}

export function isSettingEntitySafeForGeneration(entity = {}) {
  const summary = String(entity.summary || '').trim()
  if (!isPlaceholderSettingSummary(summary)) return true
  return false
}

export function filterSettingEntitiesForGeneration(entities = []) {
  return (entities || []).filter(isSettingEntitySafeForGeneration)
}
