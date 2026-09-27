export async function enterTopicSubject(topics, subject) {
  if (topics.sending) throw new Error('请等待当前讨论发送完成。')
  if (!subject?.discussionId) throw new Error('缺少来源讨论，无法继续。')
  const detail = await topics.openDiscussion(subject.discussionId)
  if (topics.activeDiscussion?.discussion?.id !== subject.discussionId) throw new Error('讨论已切换，请重试。')
  topics.selectedEvidence = (subject.evidence || []).map(({ snapshotId, contentHash }) => ({ snapshotId, contentHash }))
  topics.discussionSubject = { kind: subject.kind, id: subject.id, version: subject.version, contentHash: subject.contentHash, title: subject.title }
  topics.discussionRecommendation = null
  return detail
}

export function clearTopicContext(topics) {
  topics.selectedEvidence = []
  topics.discussionSubject = null
  topics.discussionRecommendation = null
}
