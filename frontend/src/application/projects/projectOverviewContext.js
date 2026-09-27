import { shallowRef } from 'vue'
import { mapWorkbenchNextAction } from './projectNextAction.js'

export function createProjectOverviewContext(api) {
  const state = shallowRef({ projectId: '', status: 'idle' })
  let generation = 0
  function reset() { generation += 1; state.value = { projectId: '', status: 'idle' } }
  async function load(projectId) {
    const ticket = ++generation
    state.value = { projectId, status: 'loading' }
    const [preparation, planning, manuscript] = await Promise.allSettled([
      api.projects.preparation(projectId), api.planning.get(projectId), api.manuscripts.index(projectId),
    ])
    if (ticket !== generation) return
    let action = preparation.status === 'fulfilled' ? mapWorkbenchNextAction(preparation.value, projectId) : { state: 'unavailable', label: '重新读取创作状态' }
    if (action.state === 'available' && !action.targetPath.startsWith(`/projects/${encodeURIComponent(projectId)}/`)) action = { state: 'unavailable', label: '重新读取创作状态' }
    const plan = planning.status === 'fulfilled' && planning.value?.projectId === projectId ? planning.value.futurePlan : null
    const block = plan?.storyBlocks?.find(item => item.id === plan.activeStoryBlockId) || null
    const directory = manuscript.status === 'fulfilled' && manuscript.value?.projectId === projectId ? manuscript.value : null
    const chapters = (directory?.volumes || []).flatMap(volume => volume.chapters || []).sort((a, b) => b.number - a.number).slice(0, 4)
    state.value = { projectId, status: 'ready', action, block, chapters,
      planningUnavailable: planning.status === 'rejected', manuscriptUnavailable: !directory }
  }
  return { state, load, reset }
}
