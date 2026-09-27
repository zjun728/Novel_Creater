import { shallowRef } from 'vue'

export const BIBLE_DESIGN_FIELDS = Object.freeze({ premiseAndPromise: '作品承诺', worldRules: '世界规则', powerOrProgressionSystem: '力量与成长体系', protagonist: '主角设计', coreCast: '核心人物', factions: '势力设计', longTermConflicts: '长期冲突', relationshipDynamics: '关系动力', toneAndNarrativeBoundaries: '叙事边界', continuityGuardrails: '连续性约束', openDesignQuestions: '待解设计问题' })
export const PLOT_TYPES = Object.freeze({ main: '主线', character: '人物线', relationship: '关系线', conflict: '冲突线', mystery: '悬念线', other: '其他情节线' })

export function bibleDesignSections(content) {
  return Object.entries(BIBLE_DESIGN_FIELDS).flatMap(([key, title]) => {
    const value = content?.[key]
    const items = (Array.isArray(value) ? value.map(item => item?.text) : [value]).filter(item => typeof item === 'string' && item.trim())
    return items.length ? [{ key, title, items }] : []
  })
}
export function activeDesignNodes(nodes) { return Array.isArray(nodes) ? nodes.filter(node => node?.lifecycle === 'active') : [] }

export function createFutureDesignController({ api }) {
  const state = shallowRef({ status: 'idle', data: null, message: '' })
  let generation = 0
  let abort
  function clear() { generation++; abort?.abort(); state.value = { status: 'idle', data: null, message: '' } }
  async function load(projectId, revision, entityId = null) {
    const token = ++generation
    abort?.abort(); abort = new AbortController()
    state.value = { status: 'loading', data: null, message: '' }
    try {
      const data = await api.continuity.futureDesign(projectId, { revision, ...(entityId ? { entity_id: entityId } : {}) }, { signal: abort.signal })
      if (generation !== token) return
      if (data?.projectId !== projectId || data.revision !== revision || data.association !== 'explicit'
        || data.entityId !== entityId || !Array.isArray(data.linkedPlots)
        || data.linkedPlots.some(plot => !entityId || plot?.characterDesign?.entityId !== entityId || plot.lifecycle !== 'active')
        || !['bible', 'planning'].every(key => data[key] === null || (data[key] && typeof data[key].content === 'object' && data[key].content !== null && !Array.isArray(data[key].content)))) throw new Error('Invalid future design')
      state.value = { status: 'ready', data, message: '' }
    } catch (error) {
      if (generation !== token) return
      state.value = { status: 'error', data: null, message: error?.code === 'snapshot_changed' ? '正文事实已有更新，请重新读取记录后查看未来设计。' : '未来设计暂时无法读取，请重试。' }
    }
  }
  return { state, load, clear, dispose: clear }
}
