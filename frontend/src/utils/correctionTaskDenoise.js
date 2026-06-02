const SEVERITY_RANK = {
  critical: 0,
  major: 1,
  minor: 2,
  suggestion: 3
}

const TASK_WORTHY_MINOR_TYPES = new Set([
  'contradiction',
  'character_inconsistency',
  'world_rule_violation',
  'logic',
  'continuity'
])

const DEFAULT_MAX_TASKS = 3

export function filterIssuesForCorrectionTasks(issues, options = {}) {
  const maxTasks = Number(options.maxTasks || DEFAULT_MAX_TASKS)
  const seen = new Set()

  return (Array.isArray(issues) ? issues : [])
    .filter(Boolean)
    .map((issue, index) => ({ issue, index }))
    .filter(({ issue }) => isTaskWorthyIssue(issue))
    .filter(({ issue }) => {
      const key = correctionIssueKey(issue)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .sort((a, b) => {
      const severityDelta = severityRank(a.issue.severity) - severityRank(b.issue.severity)
      return severityDelta || a.index - b.index
    })
    .slice(0, maxTasks > 0 ? maxTasks : DEFAULT_MAX_TASKS)
    .map(({ issue }) => issue)
}

export function isTaskWorthyIssue(issue = {}) {
  const severity = normalizeText(issue.severity || 'minor')
  const type = normalizeText(issue.type || issue.issueType || '')
  if (severity === 'critical' || severity === 'major') return true
  if (severity === 'suggestion') return false
  return TASK_WORTHY_MINOR_TYPES.has(type)
}

function correctionIssueKey(issue = {}) {
  return [
    normalizeText(issue.type || issue.issueType || 'general'),
    normalizeText(issue.description || issue.title || ''),
    normalizeText(issue.location || '')
  ].join('::')
}

function severityRank(severity) {
  return SEVERITY_RANK[normalizeText(severity)] ?? SEVERITY_RANK.minor
}

function normalizeText(value) {
  return String(value || '').trim().toLowerCase()
}
