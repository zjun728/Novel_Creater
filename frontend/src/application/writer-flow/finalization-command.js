function requiredFunction(input, name) {
  const fn = input?.[name]
  if (typeof fn !== 'function') throw new Error(`${name} function is required`)
  return fn
}

function normalizeError(error) {
  return error instanceof Error ? error : new Error(String(error || 'finalization failed'))
}

function buildRequiredFailureError(requiredFailures = []) {
  return new Error(requiredFailures.map(error => `${error.step}: ${error.message}`).join('；'))
}

function countItems(items) {
  return Array.isArray(items) ? items.length : 0
}

async function invokeOptional(fn, ...args) {
  if (typeof fn === 'function') return await fn(...args)
  return undefined
}

export async function runFinalizeChapterCommand(input = {}) {
  const {
    projectId,
    chapterNum,
    version,
    correctionTaskIds = [],
    onVersionFinalized,
    onMemoryProcessed,
    onStoryBlockReviewFailure,
    onRerouteWarning,
    onPostFinalizeFailure,
    onLinkedCorrectionTaskFailure,
    onClearTempDraftFailure
  } = input

  const beginFinalizationRun = requiredFunction(input, 'beginFinalizationRun')
  const finalizeVersion = requiredFunction(input, 'finalizeVersion')
  const finishLinkedCorrectionTasks = requiredFunction(input, 'finishLinkedCorrectionTasks')
  const clearTempDraft = requiredFunction(input, 'clearTempDraft')
  const processChapterFinalization = requiredFunction(input, 'processChapterFinalization')
  const loadContextData = requiredFunction(input, 'loadContextData')
  const performStoryBlockReviewAfterFinalize = requiredFunction(input, 'performStoryBlockReviewAfterFinalize')
  const rerouteOutlineAfterFinalization = requiredFunction(input, 'rerouteOutlineAfterFinalization')
  const buildRerouteContext = requiredFunction(input, 'buildRerouteContext')
  const markFinalizationFailure = requiredFunction(input, 'markFinalizationFailure')
  const endFinalizationRun = requiredFunction(input, 'endFinalizationRun')

  const finalizationRun = await beginFinalizationRun(projectId, chapterNum, version?.id)
  if (!finalizationRun?.started) {
    return {
      ok: false,
      code: 'finalization_run_blocked',
      reason: finalizationRun?.reason || 'unknown',
      runKey: finalizationRun?.runKey || '',
      chapterFinalized: false,
      finalizationCompleted: false
    }
  }

  let chapterFinalized = false
  let finalizationCompleted = false
  const warnings = []
  let results = null

  try {
    await finalizeVersion(version)
    chapterFinalized = true
    await invokeOptional(onVersionFinalized)

    try {
      await finishLinkedCorrectionTasks(correctionTaskIds)
    } catch (error) {
      warnings.push({ code: 'linked_correction_task_update_failed', error: normalizeError(error) })
      await invokeOptional(onLinkedCorrectionTaskFailure, normalizeError(error))
    }

    try {
      await clearTempDraft(projectId, chapterNum)
    } catch (error) {
      warnings.push({ code: 'temp_draft_clear_failed', error: normalizeError(error) })
      await invokeOptional(onClearTempDraftFailure, normalizeError(error))
    }

    results = await processChapterFinalization(projectId, version?.content || '', chapterNum)
    const requiredFailures = (results?.errors || []).filter(error => error.required)
    if (requiredFailures.length) {
      throw buildRequiredFailureError(requiredFailures)
    }

    await invokeOptional(onMemoryProcessed, results)
    await loadContextData()

    try {
      await performStoryBlockReviewAfterFinalize(results, version, chapterNum, projectId)
    } catch (error) {
      const normalized = normalizeError(error)
      await invokeOptional(onStoryBlockReviewFailure, normalized)
      throw normalized
    }

    try {
      const rerouteContext = await buildRerouteContext(results, version, chapterNum)
      await rerouteOutlineAfterFinalization(projectId, rerouteContext)
    } catch (error) {
      const normalized = normalizeError(error)
      warnings.push({ code: 'outline_reroute_failed', error: normalized })
      await invokeOptional(onRerouteWarning, normalized)
    }

    finalizationCompleted = true
    return {
      ok: true,
      code: 'finalization_completed',
      chapterFinalized,
      finalizationCompleted,
      results,
      factCount: countItems(results?.facts),
      settingChangeCount: countItems(results?.settingChanges),
      warnings
    }
  } catch (error) {
    const normalized = normalizeError(error)
    if (chapterFinalized) {
      await markFinalizationFailure(projectId, chapterNum, normalized)
      await invokeOptional(onPostFinalizeFailure, normalized)
    }
    return {
      ok: false,
      code: chapterFinalized ? 'post_finalize_failed' : 'finalization_failed',
      chapterFinalized,
      finalizationCompleted,
      error: normalized,
      message: normalized.message,
      warnings
    }
  } finally {
    await endFinalizationRun(finalizationRun.runKey, projectId, chapterNum, {
      keepPending: chapterFinalized && !finalizationCompleted
    })
  }
}
