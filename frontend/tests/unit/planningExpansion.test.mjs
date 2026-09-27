import assert from 'node:assert/strict'
import test from 'node:test'
import { planningExpansionAvailability } from '../../src/application/planning/planningExpansion.js'

const block = { id: 'b', lifecycle: 'active', volumeRef: 'v', order: 1,
  stages: [{ id: 's', lifecycle: 'active', sceneTasks: [{ id: 't', lifecycle: 'active' }] }] }
const content = { activeStoryBlockRef: 'b', storyBlocks: [block] }
const progress = (type, id) => ({ entityId: null, subjectKey: '__global__', fieldPath: `plot.progress.${type}.${id}`,
  value: { status: 'completed', targetType: type, targetId: id } })
const state = items => ({ head: { revision: 1 }, futurePlan: {}, canonProjectionStatus: {
  synchronized: true, canonRevision: 1, projectionRevision: 1 }, actualProgress: items })

test('first planning only before initial plan and canon', () => {
  assert.equal(planningExpansionAvailability({ head: { revision: 0 }, canonProjectionStatus: {
    synchronized: true, canonRevision: 0, projectionRevision: 0 } }, null).initial, true)
  assert.equal(planningExpansionAvailability(state([]), content).initial, false)
})
test('continuation requires completed block or all active tasks', () => {
  assert.equal(planningExpansionAvailability(state([]), content).nextBlock, false)
  for (const item of [progress('story_block', 'b'), progress('stage', 's'), progress('scene_task', 't')]) {
    assert.deepEqual(planningExpansionAvailability(state([item]), content), { initial: false, nextBlock: true, nextVolume: true })
  }
})
test('unresolved current volume blocks prevent skipping to next volume', () => {
  const availability = planningExpansionAvailability(state([progress('story_block', 'b')]), {
    ...content, storyBlocks: [block, { ...block, id: 'later', order: 2 }] })
  assert.equal(availability.nextBlock, true)
  assert.equal(availability.nextVolume, false)
})
test('unsynchronized and wrong-target progress never unlock continuation', () => {
  assert.equal(planningExpansionAvailability(state([progress('story_block', 'other')]), content).nextBlock, false)
  const pending = state([progress('story_block', 'b')]); pending.canonProjectionStatus.synchronized = false
  assert.equal(planningExpansionAvailability(pending, content).nextBlock, false)
})
