import { ref } from 'vue'
import { mapWorkbenchNextAction } from '../projects/projectNextAction.js'

export function createPlanningContinuation({ projectId, loadPreparation, navigate }) {
  const pending = ref(false), message = ref('')
  let generation = 0
  function reset() { generation += 1; pending.value = false; message.value = '' }
  async function proceed() {
    if (pending.value) return false
    const target = String(projectId()), ticket = ++generation
    const current = () => ticket === generation && target === String(projectId())
    pending.value = true
    message.value = '正在查询权威下一步…'
    try {
      const preparation = await loadPreparation(target)
      if (!current()) return false
      const action = mapWorkbenchNextAction(preparation, target)
      if (action.state !== 'available') {
        message.value = action.description || (action.state === 'archived' ? '项目已归档，保持只读。' : '暂时无法确定下一步，请重新查询创作状态。')
        return false
      }
      if (!action.targetPath.startsWith(`/projects/${encodeURIComponent(target)}/`)) {
        message.value = '下一步与当前项目不匹配，请重新查询创作状态。'
        return false
      }
      message.value = action.description
      await navigate(action.targetPath)
      return true
    } catch {
      if (current()) message.value = '下一步暂时无法读取。已确认规划保持有效，请重试查询，无需重复确认。'
      return false
    } finally { if (current()) pending.value = false }
  }
  return { pending, message, reset, proceed }
}
