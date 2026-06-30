export const storyHumanityReviewAliases = {
  requiredCanonical: [
    'overallVerdict',
    'prioritizedIssues',
    'storyHumanityV1Plan',
    'nextRoundVerification'
  ],
  compatibility: [
    'overall',
    'issueSummary',
    'nextPlan'
  ]
}

export function normalizeStoryHumanityReview(input = {}) {
  const overallVerdict = normalizeObject(input.overallVerdict || input.overall)
  const prioritizedIssues = normalizeArray(input.prioritizedIssues || input.issueSummary)
  const nextRoundVerification = normalizeObject(input.nextRoundVerification)
  const basePlan = normalizeObject(input.storyHumanityV1Plan || input.nextPlan)
  const storyHumanityV1Plan = {
    ...basePlan,
    ...pickMissingVerificationAliases(basePlan, nextRoundVerification)
  }

  return {
    ...input,
    overallVerdict,
    prioritizedIssues,
    storyHumanityV1Plan,
    nextRoundVerification,
    overall: overallVerdict,
    issueSummary: prioritizedIssues,
    nextPlan: storyHumanityV1Plan
  }
}

function normalizeObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function normalizeArray(value) {
  return Array.isArray(value) ? value : []
}

function pickMissingVerificationAliases(plan = {}, verification = {}) {
  const out = {}
  for (const key of ['beforeChange', 'afterSmallChange', 'commandsThisRound', 'frontendBuildRequired']) {
    if (plan[key] === undefined && verification[key] !== undefined) out[key] = verification[key]
  }
  return out
}
