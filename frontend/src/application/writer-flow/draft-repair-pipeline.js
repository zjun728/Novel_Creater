const identityStep = async content => content

export async function runDraftRepairPipeline({
  rawContent = '',
  cleaner = content => content,
  repairProseRhythm = identityStep,
  repairNotXButY = identityStep,
  repairParagraphRepetition = identityStep,
  emptyDraftErrorMessage = 'AI 生成正文为空，请重新生成或切换模型后重试。'
} = {}) {
  let content = cleaner(rawContent)
  content = await repairProseRhythm(content)
  content = await repairNotXButY(content)
  content = await repairParagraphRepetition(content)
  if (!String(content || '').trim()) {
    throw new Error(emptyDraftErrorMessage)
  }
  return content
}
