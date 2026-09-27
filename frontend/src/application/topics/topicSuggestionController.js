import { reactive } from 'vue'

export const TOPIC_GENRES = Object.freeze(['玄幻', '奇幻', '武侠', '仙侠修真', '都市', '现实', '历史', '军事', '悬疑', '科幻', '游戏', '体育', '轻小说', '诸天无限', '现代言情', '古代言情'])
export const TOPIC_QUICK_GENRES = Object.freeze(['东方玄幻', '修真', '穿越'])

function newCommandKey() {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), byte => byte.toString(16).padStart(2, '0')).join('')
}

export function createTopicSuggestionController({ market, topics, commandKey = newCommandKey }) {
  const state = topics.marketSuggestionState || reactive({ genre: '东方玄幻', busy: false, stage: '', error: '', sources: [], discussionId: '', outcomeUnknown: false, resultGenre: '', lastResult: null })
  topics.marketSuggestionState = state
  function selectGenre(genre) {
    if (!state.busy && [...TOPIC_GENRES, ...TOPIC_QUICK_GENRES].includes(genre)) state.genre = genre
  }
  async function generate() {
    if (state.busy || topics.sending || state.outcomeUnknown) return false
    state.busy = true
    state.error = ''
    state.sources = []
    state.discussionId = ''
    const genre = state.genre
    state.resultGenre = genre
    let phase = 'sources'
    try {
      state.stage = '正在获取可用市场来源…'
      await market.loadSources()
      const sources = market.sources.filter(source => source.canRefresh && !market.isSourceBusy(source.id)).slice(0, 4)
      if (!sources.length) throw new Error('目前没有可刷新的市场来源。可查看历史资料，或直接进入 AI 讨论。')
      state.stage = '正在采集公开作品参考…'
      const evidence = []
      for (const source of sources) {
        state.stage = `正在获取${source.displayName}…`
        try {
          const snapshot = await market.refreshSource(source.id, commandKey())
          evidence.push({ snapshotId: snapshot.id, contentHash: snapshot.contentHash, label: source.displayName })
          state.sources.push({ name: source.displayName, succeeded: true, capturedAt: snapshot.capturedAt })
        } catch { state.sources.push({ name: source.displayName, succeeded: false }) }
      }
      if (!evidence.length) throw new Error('本次市场采集全部失败，未调用 AI。可重试采集，或直接进入 AI 讨论。')
      phase = 'create'
      state.stage = '正在建立本次选题讨论…'
      const discussion = await topics.createDiscussion(`${genre} · 选题建议`)
      state.discussionId = discussion.discussion.id
      topics.selectedEvidence = evidence
      topics.discussionSubject = null
      topics.discussionRecommendation = null
      phase = 'send'
      state.stage = '正在归纳市场参考并生成多个创作建议…'
      await topics.sendMessage(state.discussionId, {
        content: `请围绕“${genre}”生成 3 个适合长篇发展的原创选题建议。先归纳所附公开榜单能够支持的市场观察，再分别说明读者期待、创作切入点、差异化、长期冲突与风险，并提供可保存的方向和候选种子。附件是综合或男女频榜单，不是该题材专榜；请识别题材相关作品，明确区分证据与创作推测，样本不足时直说，不编造热度、销量或趋势。`,
        idempotencyKey: commandKey(),
        evidence: evidence.map(({ snapshotId, contentHash }) => ({ snapshotId, contentHash })),
        subject: null,
      })
      phase = 'read'
      const detail = await topics.openDiscussion(state.discussionId)
      const completed = [...(detail?.requests || [])].reverse().find(request => request.status === 'succeeded' && request.assistantMessageId && request.result)
      if (completed) state.lastResult = { discussionId: state.discussionId, genre, result: completed.result, sources: state.sources.filter(source => source.succeeded).map(source => ({ ...source })), evidence: evidence.map(item => ({ ...item })), completedAt: completed.completedAt }
      state.stage = '选题建议已生成，可在下方阅读、保存或继续讨论。'
      return true
    } catch (error) {
      state.stage = ''
      // A transport failure while creating/sending may have written successfully.
      // Keep the author on a recovery path rather than silently issuing a duplicate.
      state.outcomeUnknown = phase === 'create' || (phase === 'send' && !['TOPIC_PROVIDER_FAILED', 'TOPIC_INVALID_RESPONSE', 'TOPIC_PROVIDER_NOT_READY'].includes(error?.code))
      state.error = phase === 'sources' ? error.message
        : phase === 'read' ? '建议已生成，但读取失败。请打开 AI 讨论查看已有结果，不必重新生成。'
          : state.outcomeUnknown ? '请求结果暂未确认，请先进入 AI 讨论核对已有记录，避免重复生成。'
            : 'AI 建议未能生成。市场参考已保留，可进入 AI 讨论重试。'
      return false
    } finally { state.busy = false }
  }
  return { state, selectGenre, generate }
}

// Entry navigation has no backend writes and cannot inherit recommendation context.
export function enterBlankTopicDiscussion(topics) {
  if (topics.sending) return false
  topics.leaveSection()
  topics.activeDiscussion = null
  topics.selectedEvidence = []
  topics.discussionSubject = null
      topics.discussionRecommendation = null
  topics.clearSendFailure()
  return true
}
