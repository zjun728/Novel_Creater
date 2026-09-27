// UI availability hint only; the server rechecks progress under the project lock.
export function planningExpansionAvailability(state, content) {
  const status = state?.canonProjectionStatus
  const result = { initial: false, nextBlock: false, nextVolume: false }
  if (!status?.synchronized || status.canonRevision !== status.projectionRevision) return result
  result.initial = !state.head?.revision && !content?.storyBlocks?.length && status.canonRevision === 0
  const active = content?.storyBlocks?.find(b => b.id === content.activeStoryBlockRef && b.lifecycle === 'active')
  if (!active || !state.futurePlan || status.canonRevision < 1) return result
  const completed = new Set((state.actualProgress || [])
    .filter(row => row.subjectKey === '__global__' && row.entityId === null
      && row.value?.status === 'completed'
      && row.fieldPath === `plot.progress.${row.value.targetType}.${row.value.targetId}`)
    .map(row => `${row.value.targetType}:${row.value.targetId}`))
  const stages = active.stages?.filter(s => s.lifecycle === 'active') || []
  const finished = completed.has(`story_block:${active.id}`) || (stages.length > 0 && stages.every(s =>
    completed.has(`stage:${s.id}`) || (s.sceneTasks?.filter(t => t.lifecycle === 'active').length > 0
      && s.sceneTasks.filter(t => t.lifecycle === 'active').every(t => completed.has(`scene_task:${t.id}`)))))
  result.nextBlock = finished
  result.nextVolume = finished && !content.storyBlocks.some(b => b.lifecycle === 'active'
    && b.volumeRef === active.volumeRef && b.order > active.order)
  return result
}
