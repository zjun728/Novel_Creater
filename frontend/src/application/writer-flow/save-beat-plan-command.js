export async function runSaveBeatPlanCommand({
  showMessage = true,
  getBeatPlanText,
  getBeatPlanStageSnapshot,
  getProjectId,
  getChapterNum,
  ensureCurrentChapterEditable,
  ensureStoryBlockReady,
  captureCurrentBlockStageSnapshot,
  setBeatPlanStageSnapshot,
  saveChapterBeatPlan,
  buildBeatPlanStoryBlockMetadata,
  setBeatPlanText,
  setBeatPlanSavedText,
  warning,
  success,
  error,
}) {
  if (!ensureCurrentChapterEditable('保存小纲')) {
    return false
  }

  const content = String(getBeatPlanText() || '').trim()
  if (!content) {
    warning('请先生成或填写本章小纲')
    return false
  }

  try {
    if (!getBeatPlanStageSnapshot()) {
      const block = await ensureStoryBlockReady('保存小纲')
      if (!block) {
        return false
      }
      setBeatPlanStageSnapshot(captureCurrentBlockStageSnapshot(block))
    }

    await saveChapterBeatPlan(
      getProjectId(),
      getChapterNum(),
      content,
      buildBeatPlanStoryBlockMetadata(),
    )

    setBeatPlanText(content)
    setBeatPlanSavedText(content)
    if (showMessage) {
      success('本章小纲已保存')
    }
    return true
  } catch (err) {
    error(`保存小纲失败：${err.message || err}`)
    return false
  }
}
