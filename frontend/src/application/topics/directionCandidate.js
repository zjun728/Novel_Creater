import { reactive } from 'vue'
import { topicSuggestionKey } from './topicSuggestionKey.js'
import { enterTopicSubject } from './topicContext.js'

const key = () => Array.from(crypto.getRandomValues(new Uint8Array(32)), n => n.toString(16).padStart(2, '0')).join('')
export function createDirectionCandidateController(topics) {
  const state = topics.directionCandidateState || reactive({ busy: false, error: '', pending: null, uncertain: false })
  topics.directionCandidateState = state
  async function generate(subject) {
    if (state.busy || topics.sending || state.uncertain) return null
    if (state.pending && state.pending.subjectKey !== `${subject.id}:${subject.version}`) {
      state.error = '上一份候选尚待保存，请返回原方向版本完成保存。'; return null
    }
    state.busy = true; state.error = ''
    let phase = 'read'
    try {
      if (!state.pending) {
        await enterTopicSubject(topics, subject)
        phase = 'send'
        const response = await topics.sendMessage(subject.discussionId, {
          content: `请以已附加的选题方向“${subject.title}”为依据，展开恰好一个完整候选种子，填齐候选字段，不创建项目。`,
          idempotencyKey: key(), evidence: topics.selectedEvidence,
          subject: { kind: 'direction', id: subject.id, version: subject.version, contentHash: subject.contentHash },
        })
        phase = 'result'
        const suggestions = response.result?.candidateSuggestions || []
        if (suggestions.length !== 1) throw new Error('回复未包含唯一候选，请通过继续讨论查看结果并选择保存，勿重复生成。')
        state.pending = { savedKey: `${response.requestId}:candidate:0`, subjectKey: `${subject.id}:${subject.version}`, discussionId: subject.discussionId, data: { messageId: response.assistantMessageId, payload: suggestions[0], evidence: topics.selectedEvidence.map(item => ({ ...item })), idempotencyKey: await topicSuggestionKey(subject.discussionId, response.requestId, 'candidate', 0) } }
      }
      phase = 'save'
      const receipt = await topics.saveCandidate(state.pending.discussionId, state.pending.data)
      topics.savedSuggestionKeys = [...new Set([...(topics.savedSuggestionKeys || []), state.pending.savedKey])]
      state.pending = null
      return receipt
    } catch (error) {
      if (phase === 'send' && !['TOPIC_PROVIDER_FAILED', 'TOPIC_INVALID_RESPONSE', 'TOPIC_PROVIDER_NOT_READY'].includes(error?.code)) state.uncertain = true
      if (phase === 'result') state.uncertain = true
      state.error = phase === 'save' ? '候选已生成，保存未确认。再次点击仅重试保存，不重复生成。' : state.uncertain ? '生成结果需要核对。请通过继续讨论查看已有记录，避免重复生成。' : (error.message || '候选生成失败')
      return null
    } finally { state.busy = false }
  }
  return { state, generate }
}
