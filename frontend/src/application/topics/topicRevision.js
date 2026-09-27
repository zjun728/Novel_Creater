import { ref, computed } from 'vue'
import { parseCandidatePayload, parseDirectionPayload, CANDIDATE_FIELDS, DIRECTION_FIELDS } from './topicContracts.js'

export const TOPIC_FIELD_LABELS = Object.freeze({ title: '暂定名称', genre: '题材', logline: '一句话创意', targetAudience: '目标读者', protagonist: '主角', desire: '核心欲望', coreConflict: '核心冲突', worldPressure: '世界压力', openingHook: '开篇钩子', differentiation: '差异化', storyPromise: '故事承诺', longFormPotential: '长篇发展空间', marketBasis: '市场依据', genreOpportunity: '题材机会', readerPromise: '读者承诺', risks: '风险', evidenceSummary: '证据摘要' })

function commandKey() {
  const bytes = new Uint8Array(32)
  globalThis.crypto.getRandomValues(bytes)
  return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
}

export function createTopicRevision({ api, keyFactory = commandKey }) {
  const draft = ref(null)
  const busy = ref(false)
  const message = ref('')
  const receipt = ref(null)
  let source = null
  let initial = ''
  let pending = null
  const dirty = computed(() => draft.value !== null && JSON.stringify(draft.value) !== initial)
  function begin(kind, detail, version) {
    if (busy.value) return false
    if (!['candidate', 'direction'].includes(kind) || !detail?.id || !version?.discussionId || !version?.basis?.message?.id) {
      message.value = '缺少这份内容的讨论来源，暂时无法建立修订。'
      return false
    }
    source = { kind, id: detail.id, expectedVersion: detail.currentVersion, discussionId: version.discussionId,
      messageId: version.basis.message.id, evidence: (version.basis.evidence || []).map(({ snapshotId, contentHash }) => ({ snapshotId, contentHash })) }
    draft.value = Object.fromEntries((kind === 'candidate' ? CANDIDATE_FIELDS : DIRECTION_FIELDS).map(key => [key, version.payload[key]]))
    initial = JSON.stringify(draft.value)
    pending = null
    receipt.value = null
    message.value = ''
    return true
  }
  function cancel() { if (busy.value) return false; draft.value = null; source = null; pending = null; return true }
  async function save({ copy = false } = {}) {
    if (!source || !draft.value || busy.value) return null
    let payload
    try {
      const trimmed = Object.fromEntries(Object.entries(draft.value).map(([key, value]) => [key, String(value).trim()]))
      if (Object.values(trimmed).some(value => Array.from(value).length > 2000)) throw new Error('Text too long')
      payload = source.kind === 'candidate' ? parseCandidatePayload(trimmed) : parseDirectionPayload(trimmed)
    } catch { message.value = '请补齐所有内容，并将每项控制在 2000 字以内。'; return null }
    const data = { messageId: source.messageId, payload, evidence: source.evidence,
      ...(!copy ? { [`${source.kind}Id`]: source.id, expectedVersion: source.expectedVersion } : {}) }
    const fingerprint = JSON.stringify(data)
    if (!pending || pending.fingerprint !== fingerprint) pending = { fingerprint, key: keyFactory() }
    busy.value = true
    message.value = ''
    try {
      const result = await api[source.kind === 'candidate' ? 'saveCandidate' : 'saveDirection'](source.discussionId, { ...data, idempotencyKey: pending.key })
      if (typeof result?.[`${source.kind}Id`] !== 'string'
        || result.version !== (copy ? 1 : source.expectedVersion + 1)
        || (!copy && result[`${source.kind}Id`] !== source.id)) throw new Error('Invalid save receipt')
      receipt.value = result
      draft.value = null
      source = null
      pending = null
      message.value = copy ? '已另存为独立候选。' : '新版本已保存，原版本保持不变。'
      return result
    } catch (error) {
      message.value = error?.code === 'TOPIC_VERSION_CONFLICT'
        ? (source.kind === 'candidate'
          ? '已有更新版本。你的修改仍保留，请复制内容后读取最新版本，或另存为独立候选。'
          : '已有更新版本。你的修改仍保留，请复制内容后读取最新版本再修订。')
        : '保存未确认成功，修改已保留。重试相同内容会核对同一次保存。'
      return null
    } finally { busy.value = false }
  }
  return { draft, busy, message, receipt, dirty, begin, cancel, save }
}
