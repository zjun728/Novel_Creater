function collectLeafFailures(error, failures = [], visited = new Set()) {
  if (error && (typeof error === 'object' || typeof error === 'function')) {
    if (visited.has(error)) return failures
    visited.add(error)
    if (error instanceof AggregateError && Array.isArray(error.errors)) {
      for (const nested of error.errors) {
        collectLeafFailures(nested, failures, visited)
      }
      if (error.errors.length > 0) return failures
    }
  }
  failures.push(error)
  return failures
}


const SAFE_CATEGORIES = new Set([
  'initialization',
  'browser',
  'audit',
  'cleanup',
])


export { collectLeafFailures }


export function compactDiagnostic(value) {
  return String(value ?? '').replace(/\s+/gu, ' ').trim()
}


export function redactDiagnostic(value, sensitiveValues) {
  let redacted = String(value)
  for (const sensitive of sensitiveValues) {
    redacted = redacted.replaceAll(sensitive, '[redacted]')
    const encoded = encodeURIComponent(sensitive)
    if (encoded !== sensitive) redacted = redacted.replaceAll(encoded, '[redacted]')
  }
  return redacted
}


export function formatSafeLifecycleDiagnostics(entries) {
  if (!Array.isArray(entries)) {
    throw new TypeError('safe lifecycle diagnostics entries are invalid')
  }
  const categories = []
  for (const entry of entries) {
    if (
      !entry
      || typeof entry !== 'object'
      || Array.isArray(entry)
      || !Object.hasOwn(entry, 'error')
    ) {
      throw new TypeError('safe lifecycle diagnostics entries are invalid')
    }
    const category = SAFE_CATEGORIES.has(entry?.category)
      ? entry.category
      : 'lifecycle'
    for (const _failure of collectLeafFailures(entry?.error)) {
      categories.push(category)
    }
  }
  return {
    errorCount: categories.length,
    categories,
  }
}
