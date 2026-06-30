export function extractAiContent(result, options = {}) {
  const preferOwnContent = options.preferOwnContent !== false
  const stringifyUnknown = options.stringifyUnknown !== false
  const hasUnknownFallback = Object.prototype.hasOwnProperty.call(options, 'unknownFallback')

  if (typeof result === 'string') return result
  if (result && typeof result === 'object') {
    if (Object.prototype.hasOwnProperty.call(result, 'content') && (preferOwnContent || result.content)) {
      return result.content || ''
    }
    if (Array.isArray(result.choices)) {
      return result.choices?.[0]?.message?.content || result.choices?.[0]?.text || ''
    }
    if (Object.prototype.hasOwnProperty.call(result, 'content')) return ''
  }
  if (!result) return ''
  if (hasUnknownFallback) return options.unknownFallback
  return stringifyUnknown ? JSON.stringify(result) : result
}
