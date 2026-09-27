import { ref } from 'vue'

// This reader never loads/replaces the planning store or its local draft.
export function createPlanningContinuationCheck({ projectId, load }) {
  const result = ref(null)
  const loading = ref(false)
  const error = ref('')
  let generation = 0
  let scope = ''
  async function reload() {
    const id = String(projectId() || '')
    const ticket = ++generation
    if (id !== scope) { scope = id; result.value = null }
    error.value = ''
    if (!id) { loading.value = false; result.value = null; return null }
    loading.value = true
    try {
      const value = await load(id)
      if (ticket !== generation || id !== String(projectId() || '')) return null
      if (value?.projectId !== id || !Array.isArray(value.actions)) throw new Error('invalid check result')
      result.value = value
      return value
    } catch {
      if (ticket === generation && id === String(projectId() || '')) {
        result.value = null
        error.value = '暂时无法检查后续安排，请重试；已有规划和本地修改保持。'
      }
      return null
    } finally {
      if (ticket === generation) loading.value = false
    }
  }
  function reset() { generation++; scope = ''; result.value = null; loading.value = false; error.value = '' }
  return { result, loading, error, reload, reset }
}
