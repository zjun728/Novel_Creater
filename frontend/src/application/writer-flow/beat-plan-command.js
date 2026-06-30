const ACTION_NAME = '小纲生成'

export function normalizeBeatPlanCommandOptions(options = {}) {
  return {
    persist: options.persist !== false
  }
}

export function shouldReuseExistingBeatPlan({ existingPlan = '', force = false } = {}) {
  return Boolean(String(existingPlan || '').trim()) && !force
}

export async function runEnsureBeatPlanCommand({
  projectId,
  chapterNum,
  existingPlan = '',
  force = false,
  beatPlanStageSnapshot = null,
  options = {},
  callbacks = {}
} = {}) {
  const { persist } = normalizeBeatPlanCommandOptions(options)
  const planText = String(existingPlan || '').trim()

  if (!await callbacks.ensureAiContextReady(ACTION_NAME)) {
    return { ok: false, code: 'aiContextNotReady', plan: '' }
  }

  if (shouldReuseExistingBeatPlan({ existingPlan: planText, force })) {
    if (!beatPlanStageSnapshot) {
      const storyBlock = await callbacks.ensureStoryBlockReady(ACTION_NAME)
      if (!storyBlock) return { ok: false, code: 'storyBlockNotReady', plan: '' }
      const snapshot = callbacks.captureCurrentBlockStageSnapshot(storyBlock)
      callbacks.setBeatPlanStageSnapshot(snapshot)
      if (persist) {
        await callbacks.saveChapterBeatPlan(
          projectId,
          chapterNum,
          planText,
          callbacks.buildBeatPlanStoryBlockMetadata()
        )
        callbacks.setBeatPlanSavedText(planText)
      }
    }
    return { ok: true, code: 'reuseExistingPlan', plan: planText }
  }

  if (!callbacks.ensureCurrentChapterEditable(ACTION_NAME)) {
    return { ok: false, code: 'currentChapterNotEditable', plan: '' }
  }
  if (!await callbacks.ensurePreviousChapterFinalized(ACTION_NAME)) {
    return { ok: false, code: 'previousChapterNotFinalized', plan: '' }
  }
  if (!await callbacks.ensureNoPendingSettingChanges(ACTION_NAME)) {
    return { ok: false, code: 'pendingSettingChanges', plan: '' }
  }
  if (!await callbacks.ensureNoPendingStoryMemory(ACTION_NAME)) {
    return { ok: false, code: 'pendingStoryMemory', plan: '' }
  }
  if (!await callbacks.ensureCorrectionTasksAllowGeneration(ACTION_NAME)) {
    return { ok: false, code: 'correctionTaskBlocker', plan: '' }
  }

  const storyBlock = await callbacks.ensureStoryBlockReady(ACTION_NAME)
  if (!storyBlock) return { ok: false, code: 'storyBlockNotReady', plan: '' }

  const snapshot = callbacks.captureCurrentBlockStageSnapshot(storyBlock)
  callbacks.setBeatPlanStageSnapshot(snapshot)

  const generatedPlan = await callbacks.generateChapterBeatPlan(projectId, chapterNum, {
    ...callbacks.buildBaseContext(),
    storyBlock,
    blockStageSnapshot: snapshot,
    chaseLoopDiagnostics: callbacks.buildChaseLoopDiagnosticsForBeatPlan()
  })
  callbacks.setBeatPlanText(generatedPlan)

  const generatedText = String(generatedPlan || '')
  if (persist && generatedText.trim()) {
    await callbacks.saveChapterBeatPlan(
      projectId,
      chapterNum,
      generatedPlan,
      callbacks.buildBeatPlanStoryBlockMetadata()
    )
    callbacks.setBeatPlanSavedText(generatedText.trim())
  }

  return { ok: true, code: 'generatedPlan', plan: generatedPlan }
}
