import { shallowRef } from 'vue'

export const CONTINUITY_KINDS = Object.freeze({ facts: '已发生事实', state: '当前状态', memory: '重要记忆', arcs: '人物弧光', clues: '线索与伏笔', progress: '实际故事进度' })
export const ENTITY_TYPES = Object.freeze({ person: '人物', organization: '势力', place: '地点', item: '物品' })
const COPY = Object.freeze({ projection_out_of_sync: '正文事实正在同步，请稍后重新读取。', snapshot_changed: '已有新的定稿事实，请刷新后继续查看。', project_missing: '项目不存在。', entity_missing: '这项设定不存在或已不属于当前项目。' })

export function createContinuityController({ api }) {
  const state = shallowRef({ status: 'idle', data: null, message: '' })
  let generation = 0
  let abort = null
  let address = ''
  async function load(projectId, filters = {}) {
    const token = ++generation
    abort?.abort()
    abort = new AbortController()
    const key = JSON.stringify([projectId, filters])
    const previous = address === key ? state.value.data : null
    address = key
    state.value = { status: 'loading', data: previous, message: '' }
    try {
      const result = await api.continuity.records(projectId, filters, { signal: abort.signal })
      if (token !== generation) return
      if (result?.projectId !== projectId || result?.kind !== filters.kind || !Array.isArray(result.items)
        || !Number.isSafeInteger(result.revision) || result.revision < 0
        || (filters.revision !== undefined && result.revision !== filters.revision)
        || (filters.entity_id && result.entity?.id !== filters.entity_id)
        || (filters.field_path && result.items.some(item => item?.field !== filters.field_path || (filters.entity_id ? item.entityId !== filters.entity_id : item.entityId !== null)))
        || (filters.global_only && result.items.some(item => item?.entityId !== null))
        || (result.nextOffset !== null && (!Number.isSafeInteger(result.nextOffset) || result.nextOffset <= (filters.offset || 0)))) {
        throw new Error('Invalid continuity response')
      }
      state.value = { status: 'ready', data: result, message: '' }
    } catch (error) {
      if (token !== generation) return
      state.value = { status: 'error', data: null, message: COPY[error?.code] || '暂时无法读取，请重试。已定稿内容不会因此改变。' }
    }
  }
  function dispose() { generation += 1; abort?.abort(); state.value = { status: 'idle', data: null, message: '' } }
  return { state, load, dispose }
}

const LABELS = Object.freeze({ title: '名称', summary: '说明', description: '描述', status: '状态', goal: '目标', belief: '信念', relationship: '关系', ability: '能力', location: '位置', value: '内容', reason: '原因', outcome: '结果', chapterNumber: '发生章节', targetType: '规划层级', detail: '详情', name: '名称', alive: '是否存活', content: '内容', item: '事项', target: '目标', finding: '发现', type: '类别', amount: '数量', currency: '单位', deadline: '期限', unit: '单位', price: '价格', customer: '相关人物', quantity: '数量', event: '事件' })
const FIELDS = Object.freeze({ status: '人物状态', assets: '持有与财物', investigation: '调查进展', debts: '债务与约定', skills: '能力与技艺', system: '规则与事件', orders: '交易与委托' })
export function recordLabel(field) { return FIELDS[field] || (field?.startsWith('plot.progress.') ? '故事进度' : field?.startsWith('plot.') ? '情节与线索' : field?.startsWith('arc.') ? '人物变化' : '事实记录') }
const WORDS = Object.freeze({ started: '已开始', advanced: '已推进', completed: '已完成', story_block: '故事块', stage: '阶段', scene_task: '场景任务', true: '是', false: '否' })

// Present author content while keeping identifiers/unknown technical fields out
// of the primary surface. This never infers entity identity from text.
export function authorValue(value, depth = 0) {
  if (depth > 5 || value == null) return []
  if (typeof value === 'boolean' || typeof value === 'number') return [WORDS[String(value)] || String(value)]
  if (typeof value === 'string') return [WORDS[value] || value]
  if (Array.isArray(value)) return value.flatMap(item => authorValue(item, depth + 1))
  if (typeof value !== 'object') return []
  return Object.entries(value).flatMap(([key, item]) => {
    if (/(?:^id$|Ids?$|Ref$|Hash$|revision|fieldPath|subjectKey)/i.test(key)) return []
    return authorValue(item, depth + 1).map(text => `${LABELS[key] || '补充内容'}：${text}`)
  })
}
