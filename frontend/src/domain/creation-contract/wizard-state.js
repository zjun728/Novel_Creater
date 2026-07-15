export function nextAllowedStep(state = {}) {
  if (!state.selectedSeed) return 1
  if (!state.selectedEngine) return 2
  if (!state.primaryStyle) return 3
  if (!state.assetsLoaded) return 4
  return 5
}

export function contractReady({ readiness } = {}) {
  return Boolean(
    readiness?.ready === true
    && Array.isArray(readiness?.reasons)
    && readiness.reasons.length === 0,
  )
}

export function providerRetryAction(batch) {
  return batch?.status === 'outcome_unknown'
    ? 'create-new-batch-with-explicit-confirmation'
    : 'none'
}
