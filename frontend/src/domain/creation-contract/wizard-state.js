export function nextAllowedStep(state = {}) {
  if (!state.selectedSeed) return 1
  if (!state.selectedEngine) return 2
  if (!state.primaryStyle) return 3
  if (!state.assetsLoaded) return 4
  return 5
}

export function contractStepAccess({ selectionDrift = false, lastSavedStage = null } = {}) {
  if (selectionDrift) return { restoredStep: 1, maxOpenStep: 1 }
  if (lastSavedStage === 'assets') return { restoredStep: 4, maxOpenStep: 5 }
  if (lastSavedStage === 'style') return { restoredStep: 3, maxOpenStep: 3 }
  if (lastSavedStage === 'engine') return { restoredStep: 2, maxOpenStep: 2 }
  return { restoredStep: 1, maxOpenStep: 1 }
}

export function contractReady({ readiness } = {}) {
  return Boolean(
    readiness?.ready === true
    && Array.isArray(readiness?.reasons)
    && readiness.reasons.length === 0,
  )
}

export function contractDraftVersion(value) {
  return Number.isInteger(value) && value > 0 ? value : null
}

export function providerRetryAction(batch) {
  return batch?.status === 'outcome_unknown'
    ? 'create-new-batch-with-explicit-confirmation'
    : 'none'
}
