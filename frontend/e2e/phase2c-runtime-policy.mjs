const MISSING_DRAFT_FAILURE_COUNTS = Object.freeze({
  manual: 1,
  gateway: 2,
})


export function expectedMissingDraftFailureCount(scenarioMode) {
  if (!Object.hasOwn(MISSING_DRAFT_FAILURE_COUNTS, scenarioMode)) {
    throw new Error('Phase 2C browser scenario mode is invalid')
  }
  return MISSING_DRAFT_FAILURE_COUNTS[scenarioMode]
}
