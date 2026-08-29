export function parseIterationCount(value) {
  const normalized = String(value).trim().toLowerCase()
  if (normalized === 'infinite') return Number.POSITIVE_INFINITY
  return Number.parseFloat(normalized) || 0
}
