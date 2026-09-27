import assert from 'node:assert/strict'
import test from 'node:test'
import { createProjectOverviewContext } from '../../src/application/projects/projectOverviewContext.js'

function fixture(preparation) {
  return { projects: { preparation: preparation || (async id => ({ lifecycle: 'active', nextAction: 'continue_writing', authoritativeChapterNumber: 6, targetPath: `/projects/${id}/write/chapters/6` })) },
    planning: { get: async id => ({ projectId: id, futurePlan: { activeStoryBlockId: 'block', storyBlocks: [{ id: 'block', title: '当前块' }] } }) },
    manuscripts: { index: async id => ({ projectId: id, volumes: [{ chapters: [{ number: 2 }, { number: 5 }] }] }) } }
}
test('overview uses authoritative next action and finalized directory, not inferred chapter increment', async () => {
  const context = createProjectOverviewContext(fixture())
  await context.load('project-a')
  assert.match(context.state.value.action.targetPath, /6/)
  assert.equal(context.state.value.action.chapterNumber, 6)
  assert.equal(context.state.value.block.title, '当前块')
  assert.deepEqual(context.state.value.chapters.map(item => item.number), [5, 2])
})
test('late overview context cannot leak into another project', async () => {
  let resolve
  const api = fixture(id => id === 'a' ? new Promise(done => { resolve = done }) : Promise.resolve({ lifecycle: 'archived' }))
  const context = createProjectOverviewContext(api)
  const first = context.load('a')
  await context.load('b')
  resolve({ lifecycle: 'active', nextAction: 'continue_writing', authoritativeChapterNumber: 2, targetPath: '/projects/a/write/chapters/2' })
  await first
  assert.equal(context.state.value.projectId, 'b')
  assert.equal(context.state.value.action.state, 'archived')
})
test('failed next action or foreign project target never creates a guessed continue link', async () => {
  for (const preparation of [async () => { throw Error('offline') }, async () => ({ lifecycle: 'active', nextAction: 'continue_writing', authoritativeChapterNumber: 2, targetPath: '/projects/other/write/chapters/2' })]) {
    const context = createProjectOverviewContext(fixture(preparation))
    await context.load('a')
    assert.equal(context.state.value.action.state, 'unavailable')
    assert.equal(context.state.value.chapters.length, 2)
  }
})
