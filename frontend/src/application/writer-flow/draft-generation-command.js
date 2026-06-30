function actionNameForIntent(intent) {
  if (intent === 'multi') return '多候选生成'
  if (intent === 'compare') return '多模型对比'
  return '正文生成'
}

export async function runGenerateFromBeatPlanCommand({
  getBeatPlanIntent,
  getBeatPlanText,
  ensureCurrentChapterEditable,
  warning,
  saveCurrentBeatPlan,
  setShowBeatPlanModal,
  generateMultiVariantsFromPlan,
  openCompareWithPlan,
  generateChapterFromPlan,
}) {
  const intent = getBeatPlanIntent()
  if (!ensureCurrentChapterEditable(actionNameForIntent(intent))) {
    return { ok: false, code: 'currentChapterNotEditable' }
  }

  const confirmedPlan = String(getBeatPlanText() || '').trim()
  if (!confirmedPlan) {
    warning('请先生成或填写本章小纲')
    return { ok: false, code: 'emptyBeatPlan' }
  }

  const saved = await saveCurrentBeatPlan(false)
  if (!saved) {
    return { ok: false, code: 'beatPlanSaveFailed' }
  }

  setShowBeatPlanModal(false)
  if (intent === 'multi') {
    await generateMultiVariantsFromPlan(confirmedPlan)
    return { ok: true, code: 'multiVariantsStarted', plan: confirmedPlan }
  }
  if (intent === 'compare') {
    await openCompareWithPlan(confirmedPlan)
    return { ok: true, code: 'compareStarted', plan: confirmedPlan }
  }

  await generateChapterFromPlan(confirmedPlan)
  return { ok: true, code: 'singleDraftStarted', plan: confirmedPlan }
}
